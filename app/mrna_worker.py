"""JSON-only scientific adapter. BASE code remains in its private installation."""
import contextlib
import csv
import hashlib
import io
import json
import math
import random
import shlex
import subprocess
import sys
from pathlib import Path


def gc_profile(sequence, window, minimum, maximum):
    window=min(window,len(sequence)); prefix=[0]
    for base in sequence: prefix.append(prefix[-1]+(base in 'GC'))
    profile=[]; hotspots=[]
    for start in range(len(sequence)-window+1):
        gc=(prefix[start+window]-prefix[start])/window
        profile.append([start+1,round(gc,5)])
        if gc<minimum or gc>maximum:
            kind='high' if gc>maximum else 'low'
            if hotspots and hotspots[-1]['kind']==kind and start+1<=hotspots[-1]['end']:
                hotspots[-1]['end']=start+window
                hotspots[-1]['peak']=max(hotspots[-1]['peak'],gc) if kind=='high' else min(hotspots[-1]['peak'],gc)
            else: hotspots.append({'start':start+1,'end':start+window,'kind':kind,'peak':gc})
    return profile,hotspots,window


def translation(config, sequence, five, three, organism):
    command=config.get('ribonn_command')
    if not command:return None,'RiboNN trained runtime is not connected.'
    request={'organism':organism,'utr5_sequence':five,'cds_sequence':sequence,'utr3_sequence':three}
    try:
        result=subprocess.run(shlex.split(command),input=json.dumps(request),capture_output=True,text=True,timeout=240,check=True)
        value=json.loads(result.stdout)
        score=value['translation']; model=value['model']
        if not isinstance(model,str) or not model or not math.isfinite(score):raise ValueError('Invalid model output')
        details=value.get('tissue_predictions',{})
        details={str(k):float(v) for k,v in details.items() if isinstance(v,(int,float)) and math.isfinite(v)} if isinstance(details,dict) else {}
        return {'score':float(score),'model':model,'tissue_predictions':details},None
    except (ValueError,KeyError,TypeError,subprocess.SubprocessError,OSError):
        return None,'The connected RiboNN predictor failed for this sequence.'


def run(data):
    config=data['config'];source=Path(config['source'])
    sys.path.insert(0,str(source/'src'))
    import RNA
    import msgspec
    import numpy as np
    from mrnarchitect.sequence import Sequence
    from mrnarchitect.sequence_metrics import compute_cai, compute_tai
    import mrnarchitect.organism as organisms
    versions={'mRNArchitect':'unknown','ViennaRNA':RNA.__version__,'CSC':'Wu 2019 / 293T_ORFome'}
    for line in (source/'pyproject.toml').read_text().splitlines():
        if line.startswith('version = '): versions['mRNArchitect']=line.split('"')[1];break
    degscore_ready=(Path(config['degscore'])/'DegScore.py').is_file()
    if data['action']=='capabilities':
        from mrnarchitect.constants.sequences import EGFP, LUCIFERASE
        presets=json.loads((Path(__file__).parent/'data/mrna/elements.json').read_text())
        return {'ready':True,'versions':versions,'models':{'mRNArchitect':True,'viennarna':True,'degscore':degscore_ready,'csc':Path(config['csc']).is_file(),'ribonn':bool(config.get('ribonn_command'))},'message':'Local mRNArchitect '+versions['mRNArchitect'],'elements':presets, 'examples':{'eGFP':EGFP,'Luciferase':LUCIFERASE}}
    batch=data['batch'];record=data['record'];params=record.get('parameters') or batch['parameters'];organism=params['organism']
    np.random.seed(batch['seed']+data['index']);random.seed(batch['seed']+data['index'])
    sequence=record['sequence']
    if record['kind']=='protein':sequence=Sequence.reverse_translate(sequence,organism)
    protein=str(Sequence(sequence).amino_acid_sequence)
    if '*' in protein.rstrip('*'):raise ValueError('The coding sequence contains an internal stop codon.')
    five=''.join((record['five_prime_utr'] if record.get('five_prime_utr') is not None else batch['five_prime_utr']).split()).upper().replace('U','T')
    three=''.join((record['three_prime_utr'] if record.get('three_prime_utr') is not None else batch['three_prime_utr']).split()).upper().replace('U','T')
    csc={}
    if Path(config['csc']).is_file():
        with open(config['csc']) as stream:
            csc={r['codon'].replace('U','T'):float(r['293T_ORFome']) for r in csv.DictReader(stream)}
    degclass=None
    if degscore_ready:
        sys.path.insert(0,config['degscore'])
        with contextlib.redirect_stdout(io.StringIO()):
            from DegScore import DegScore
        degclass=DegScore;versions['DegScore']='2.1'
    rows=[];errors=[]
    def score(cds,strategy,number,report=None):
        transcript=five+cds+three+'A'*batch['poly_a'];foldseq=cds if batch['fold_scope']=='cds' else transcript
        md=RNA.md();md.temperature=batch['temperature']
        folding=RNA.fold_compound(foldseq.replace('T','U'),md)
        structure,mfe=folding.mfe()
        positions=RNA.get_xy_coordinates(structure)
        coords=[[round(positions.get(i).X,3),round(positions.get(i).Y,3)] for i in range(len(structure))]
        paired=RNA.ptable(structure)
        pairs=[[i,int(paired[i])] for i in range(1,len(structure)+1) if paired[i]>i]
        codons=[cds[i:i+3] for i in range(0,len(cds),3) if cds[i:i+3] not in ('TAA','TAG','TGA')]
        warnings=[]
        if not cds.startswith('ATG'):warnings.append('Coding sequence does not begin with AUG.')
        if not cds.endswith(('TAA','TAG','TGA')):warnings.append('Coding sequence has no terminal stop codon.')
        if record['kind']=='protein':warnings.append('Input nucleotide sequence is a reverse-translated baseline, not a supplied wild type.')
        try:cai=compute_cai(Sequence(cds),organism)
        except (ValueError,KeyError,ZeroDivisionError):cai=None;warnings.append('CAI could not be computed for this sequence.')
        try:tai=compute_tai(Sequence(cds),organism)
        except (ValueError,KeyError,ZeroDivisionError):tai=None
        csc_score=sum(csc[c] for c in codons)/len(codons) if codons and csc and all(c in csc for c in codons) else None
        if organism!='homo-sapiens':csc_score=None;warnings.append('Human 293T codon stability coefficients are not applied to mouse.')
        deg=None;half=None
        if degclass:
            try:
                model=degclass(foldseq.replace('T','U'),structure=structure);deg=float(model.degscore);half=float(model.est_half_life)
                if not math.isfinite(half) or half<=0:half=None
            except (ValueError,IndexError,AssertionError):warnings.append('DegScore could not evaluate this fold.')
        te=None;tissue_predictions={}
        if batch.get('predict_translation'):
            pred,error=translation(config,cds,five,three,organism)
            if pred:te=pred['score'];versions['translation']=pred['model'];tissue_predictions=pred['tissue_predictions']
            if error:warnings.append(error)
        profile,hotspots,window=gc_profile(cds,params['gc_window_size'],params['gc_window_min'],params['gc_window_max'])
        metrics={'length':len(cds),'transcript_length':len(transcript),'gc':(cds.count('G')+cds.count('C'))/len(cds),
            'uridine':cds.count('T')/len(cds),'cai':cai,'tai':tai,'mfe':round(mfe,4),'mfe_density':mfe/len(foldseq),
            'paired_ratio':len(pairs)*2/len(foldseq),'degscore':deg,'predicted_half_life':half,'csc':csc_score,'translation':te,
            'hamming_ratio':sum(a!=b for a,b in zip(cds,sequence))/len(sequence),'protein_preserved':str(Sequence(cds).amino_acid_sequence)==protein,
            'rare_codon_ratio':None}
        table=organisms.load_codon_usage_table_from_database(organism)
        metrics['rare_codon_ratio']=sum(table.weight(c)<.1 for c in codons)/len(codons) if codons else None
        candidate_id=f"{data['index']}-{number}"
        rows.append({'id':candidate_id,'name':record['name']+(' / input' if number==0 else f' / {strategy} {number}'),
            'input_name':record['name'],'seed':batch['seed']+data['index'],'group':record['group'],'strategy':strategy,'cds':cds,'transcript':transcript,'protein':str(Sequence(cds).amino_acid_sequence),
            'fold_sequence':foldseq,'fold_scope':batch['fold_scope'],'temperature':batch['temperature'],'structure':structure,'coordinates':coords,'pairs':pairs,
            'gc_profile':profile,'gc_hotspots':hotspots,'gc_window':window,'metrics':metrics,'warnings':warnings,'parameters':params,
            'model_versions':dict(versions),'sha256':hashlib.sha256(transcript.encode()).hexdigest(),'optimization':report,'tissue_predictions':tissue_predictions,
            'regions':{'utr5':[1,len(five)],'cds':[len(five)+1,len(five)+len(cds)],'utr3':[len(five)+len(cds)+1,len(five)+len(cds)+len(three)],'poly_a':batch['poly_a']}})
    score(sequence,'input',0)
    if batch['mode']=='design':
        from mrnarchitect.optimize.engine import optimize
        from mrnarchitect.optimize.models import OptimizationConfig
        constraints=msgspec.convert(params,type=OptimizationConfig)
        configs=[constraints]
        for start,end in record['preserve_regions']:
            configs.append(OptimizationConfig(organism=organism,objective=params['objective'],start=start,end=end,enforce_sequence=True))
        seen={sequence}
        for number in range(1,batch['candidates']+1):
            result=optimize(Sequence(sequence),configs)
            if result.status!='success':errors.append({'name':record['name'],'candidate':number,'error':result.error.message,'summary':result.error.summary});continue
            designed=result.solution.sequence
            if str(Sequence(designed).amino_acid_sequence)!=protein:raise ValueError('Optimisation did not preserve the encoded protein.')
            score(designed,params['objective'].upper(),number,msgspec.to_builtins(result))
            if designed in seen:rows[-1]['warnings'].append('This candidate duplicates the input or an earlier candidate; optimisation does not guarantee distinct designs.')
            seen.add(designed)
    return {'rows':rows,'errors':errors}


if __name__=='__main__':
    try:
        payload=json.load(sys.stdin)
        with contextlib.redirect_stdout(io.StringIO()):result=run(payload)
        print(json.dumps(result,allow_nan=False))
    except Exception as error:
        print(json.dumps({'error':str(error)[:1500]}))
