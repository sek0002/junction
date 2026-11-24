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
try:
    from .mrna_fragments import project_fragments
    from .sequence_engine import active_enzymes
    from .mrna_optimization import mutable_regions, optimize_cds
except ImportError:
    from mrna_fragments import project_fragments
    from sequence_engine import active_enzymes
    from mrna_optimization import mutable_regions, optimize_cds


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


def homopolymer_metrics(sequence):
    """Junction definition: bases in maximal CDS runs of at least two identical bases."""
    import itertools
    runs=[(base,len(list(items))) for base,items in itertools.groupby(sequence)]
    nt=sum(length for _,length in runs if length>=2)
    return {'homopolymer_nt':nt,'homopolymer_ratio':nt/len(sequence),'homopolymer_longest':max((length for _,length in runs),default=0)}


def design_quality(sequence, parameters):
    """Explicit local proxy, not the undocumented Figure 1c manufacturing formula."""
    import msgspec
    from dnachisel import DnaOptimizationProblem
    from mrnarchitect.optimize.engine import build_constraints_and_objectives
    from mrnarchitect.optimize.models import OptimizationConfig
    metrics=homopolymer_metrics(sequence)
    config=dict(parameters);config['gc_window_size']=min(config['gc_window_size'],len(sequence))
    config=msgspec.convert(config,type=OptimizationConfig)
    hard,objectives=build_constraints_and_objectives(sequence,config)
    allowed={'EnforceGCContent','AvoidPattern','AvoidHairpins','UniquifyAllKmers'}
    checks=[c for c in hard+objectives if type(c).__name__ in allowed]
    affected=bytearray(len(sequence));report=[]
    if checks:
        problem=DnaOptimizationProblem(sequence,constraints=checks)
        for evaluation in problem.constraints_evaluations():
            locations=[]
            if not evaluation.passes:
                spans=[(span.start,span.end) for span in evaluation.locations] if evaluation.locations else [(0,len(sequence))]
                for start,end in spans:
                    start=max(0,int(start));end=min(len(sequence),int(end))
                    if start<end:affected[start:end]=b'\x01'*(end-start);locations.append([start+1,end])
            report.append({'check':str(evaluation.specification),'passed':bool(evaluation.passes),'native_score':float(evaluation.score),'locations':locations})
    metrics['manufacturability']=100*(1-sum(affected)/len(sequence)) if checks else None
    return {'metrics':metrics,'definition':'Junction v1: homopolymer nt counts bases in maximal CDS runs >=2; manufacturability is 100*(1 - union of DNA Chisel violation locations / CDS length), for enabled GC, homopolymer, repeat, hairpin and motif checks. This is not the unpublished Figure 1c formula.','affected_nt':sum(affected),'checks':report}

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
    from importlib.metadata import version
    versions={'DNAChisel':version('dnachisel'),'mRNArchitect':'unknown','ViennaRNA':RNA.__version__,'CSC':'Wu 2019 / 293T_ORFome'}
    for line in (source/'pyproject.toml').read_text().splitlines():
        if line.startswith('version = '): versions['mRNArchitect']=line.split('"')[1];break
    degscore_ready=(Path(config['degscore'])/'DegScore.py').is_file()
    if data['action']=='capabilities':
        from mrnarchitect.constants.sequences import EGFP, LUCIFERASE
        presets=json.loads((Path(__file__).parent/'data/mrna/elements.json').read_text())
        return {'ready':True,'versions':versions,'models':{'mRNArchitect':True,'dnachisel':True,'viennarna':True,'degscore':degscore_ready,'csc':Path(config['csc']).is_file(),'ribonn':bool(config.get('ribonn_command'))},'message':'Local mRNArchitect '+versions['mRNArchitect'],'elements':presets, 'examples':{'eGFP':EGFP,'Luciferase':LUCIFERASE}}
    if data['action']=='match':
        try:from .mrna_matching import match_batch
        except ImportError:from mrna_matching import match_batch
        return match_batch(data['batch'])
    if data['action']=='quality':return design_quality(data['sequence'],data['parameters'])
    if data['action']=='stability':
        if not degscore_ready:return {'available':False,'scores':None,'message':'DegScore is not connected.'}
        sys.path.insert(0,config['degscore'])
        with contextlib.redirect_stdout(io.StringIO()):
            from DegScore import DegScore
        model=DegScore(data['sequence'].replace('T','U'),structure=data['structure'])
        values=[float(x) for x in model.degscore_by_position]
        if not all(math.isfinite(x) for x in values):raise ValueError('DegScore returned a non-finite position score.')
        return {'available':True,'scores':values,'model':'DegScore 2.1','total':float(model.degscore)}
    batch=data['batch'];record=data['record'];params=dict(record.get('parameters') or batch['parameters']);organism=params['organism']
    if record.get('assembly'):
        params['avoid_restriction_sites']=list(dict.fromkeys(params['avoid_restriction_sites']+list(active_enzymes(record['assembly']['enzyme']))))
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
        deg=None;half=None;stability_profile=None
        if degclass:
            try:
                model=degclass(foldseq.replace('T','U'),structure=structure);deg=float(model.degscore);half=float(model.est_half_life)
                if not math.isfinite(half) or half<=0:half=None
                stability_profile=[float(x) for x in model.degscore_by_position]
                if not all(math.isfinite(x) for x in stability_profile):stability_profile=None
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
        try:quality=design_quality(cds,params)
        except (ValueError,IndexError,AssertionError) as error:
            quality={'metrics':{**homopolymer_metrics(cds),'manufacturability':None},'error':str(error)}
            warnings.append('The manufacturing constraint-coverage score could not be calculated.')
        metrics.update(quality['metrics'])
        candidate_id=f"{data['index']}-{number}"
        fragment_output=project_fragments(record['assembly'],cds) if record.get('assembly') else None
        rows.append({'id':candidate_id,'name':record['name']+(' / input' if number==0 else f' / {strategy} {number}'),
            'input_name':record['name'],'seed':(report or {}).get('matching_seed',batch['seed']+data['index']),'group':record['group'],'strategy':strategy,'cds':cds,'transcript':transcript,'protein':str(Sequence(cds).amino_acid_sequence),
            'fold_sequence':foldseq,'fold_scope':batch['fold_scope'],'temperature':batch['temperature'],'structure':structure,'coordinates':coords,'pairs':pairs,
            'stability_profile':stability_profile,'gc_profile':profile,'gc_hotspots':hotspots,'gc_window':window,'metrics':metrics,'warnings':warnings,'parameters':params,
            'model_versions':dict(versions),'sha256':hashlib.sha256(transcript.encode()).hexdigest(),'optimization':report,'design_quality':quality,'tissue_predictions':tissue_predictions,
            'fragment_output':fragment_output,'assembly':record.get('assembly'),
            'regions':{'utr5':[1,len(five)],'cds':[len(five)+1,len(five)+len(cds)],'utr3':[len(five)+len(cds)+1,len(five)+len(cds)+len(three)],'poly_a':batch['poly_a']}})
    score(sequence,'input',0)
    if 'matched_sequence' in data:
        designed=data['matched_sequence']
        if designed is not None:
            if str(Sequence(designed).amino_acid_sequence)!=protein:raise ValueError('Matched optimisation did not preserve the encoded protein.')
            if any(designed[a-1:b]!=sequence[a-1:b] for a,b in record['preserve_regions']):raise ValueError('Matched optimisation changed an original protected region.')
            score(designed,'Matched '+params['objective'].upper(),1,data.get('matched_report'))
            rows[-1]['fragment_matching']=True
    elif batch['mode']=='design':
        seen={sequence}
        for number in range(1,batch['candidates']+1):
            try:result=optimize_cds(sequence,params,record['preserve_regions'])
            except ValueError as error:
                errors.append({'name':record['name'],'candidate':number,'error':str(error)});continue
            if result.status!='success':errors.append({'name':record['name'],'candidate':number,'error':result.error.message,'summary':result.error.summary});continue
            designed=result.solution.sequence
            if str(Sequence(designed).amino_acid_sequence)!=protein:raise ValueError('Optimisation did not preserve the encoded protein.')
            report=msgspec.to_builtins(result)
            if params['enable_uridine_depletion'] and record['preserve_regions']:
                report['uridine_depletion']={'exempt_regions':record['preserve_regions'],
                    'applied_regions':mutable_regions(len(sequence),record['preserve_regions'])}
            try:score(designed,params['objective'].upper(),number,report)
            except ValueError as error:
                errors.append({'name':record['name'],'candidate':number,'error':str(error)});continue
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
