"""Bounded joint donor search using imported fragment boundaries only."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import time

try:
    from .mrna_fragments import prepare_assembly, project_fragments
    from .sequence_engine import reverse_complement, active_enzymes
except ImportError:
    from mrna_fragments import prepare_assembly, project_fragments
    from sequence_engine import reverse_complement, active_enzymes

_COMPLEMENT = str.maketrans('ACGT', 'TGCA')


def merged_regions(regions):
    result = []
    for start, end in sorted(tuple(region) for region in regions):
        if result and start <= result[-1][1]+1:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def donor_sites(record, translate):
    """Map mutable whole CDS codons onto canonical physical donor DNA.

    Fixed bases encode adapters, exogenous DNA and partial boundary codons.
    Per-construct preserved CDS regions are checked separately during search.
    Reverse-complement donors share a key but retain their use orientation.
    """
    prepared = prepare_assembly(record['assembly'])
    original = prepared['sequence']
    a,b = prepared['cds_start']-1,prepared['cds_end']
    features = {f['fragment_index']:f for f in prepared['_result']['features'] if f.get('source')=='fragment'}
    sites = []
    for index,(source,edge) in enumerate(zip(record['assembly']['fragments'],prepared['_result']['fragments'])):
        feature=features[index];dna=source['sequence'];tokens=[('base',base) for base in dna]
        mapping={};codons=[];sign=(1 if prepared['frame']>0 else -1)*edge['orientation']
        for pos in range(0,len(original),3):
            aa=translate(original[pos:pos+3])
            if aa=='*':  # Keep supplied termination signals unchanged.
                continue
            assembled=[a+i if prepared['frame']>0 else b-1-i for i in range(pos,pos+3)]
            if not all(feature['start']+4<=i<feature['end'] for i in assembled):
                continue
            physical=[edge['target_start']+i-feature['start']-4 for i in assembled]
            if edge['orientation']<0:physical=[len(dna)-1-i for i in physical]
            for rank,p in enumerate(sorted(physical)):
                tokens[p]=('codon',aa,sign,rank)
            mapping.update(zip(physical,range(pos,pos+3)))
            codons.append((aa,physical))
        reverse_tokens=[('base',t[1].translate(_COMPLEMENT)) if t[0]=='base'
                        else ('codon',t[1],-t[2],2-t[3]) for t in reversed(tokens)]
        flipped=json.dumps(reverse_tokens)<json.dumps(tokens)
        if flipped:
            tokens=reverse_tokens;mapping={len(dna)-1-p:i for p,i in mapping.items()}
            codons=[(aa,[len(dna)-1-p for p in positions]) for aa,positions in codons]
            dna=reverse_complement(dna);sign=-sign
        positions=sorted(set(mapping.values()))
        regions=merged_regions([[i+1,i+3] for i in positions if i%3==0])
        sites.append({'fragment_index':index,'fragment_name':source['name'],
            'template':json.dumps([record['assembly']['enzyme'],tokens]),'original':dna,
            'mapping':mapping,'codons':codons,'sign':sign,'reverse_complement':flipped,'regions':regions})
    return sites


def donor_sequence(site, cds):
    dna=list(site['original'])
    for position,index in site['mapping'].items():
        base=cds[index];dna[position]=base if site['sign']>0 else base.translate(_COMPLEMENT)
    return ''.join(dna)


def apply_donor(site, donor, cds):
    output=list(cds)
    for position,index in site['mapping'].items():
        base=donor[position];output[index]=base if site['sign']>0 else base.translate(_COMPLEMENT)
    return ''.join(output)


def fragment_library(records, sequences):
    """Only validated, full physical donors; reverse complements deduplicate."""
    library={}
    for index,(record,sequence) in enumerate(zip(records,sequences)):
        if sequence is None:continue
        prepared=prepare_assembly(record['assembly'])
        coordinates={f['fragment_index']:{'start':f['start']+1,'end':f['end']+4} for f in prepared['_result']['features'] if f.get('source')=='fragment'}
        for fragment_index,fragment in enumerate(project_fragments(record['assembly'],sequence)['fragments']):
            dna=fragment['sequence'];reverse=reverse_complement(dna);canonical=min(dna,reverse)
            key=hashlib.sha256(canonical.encode()).hexdigest()
            entry=library.setdefault(key,{'id':'fragment-'+key[:16],'name':fragment['name'],
                'sequence':canonical,'length':len(canonical),'sha256':key,'usages':[]})
            entry['usages'].append({'input_index':index,'input_name':record['name'],
                'group':record['group'],'fragment_index':fragment_index,'fragment_name':fragment['name'],
                'reverse_complement':dna!=canonical,'left_overhang':fragment['left_overhang'],
                'right_overhang':fragment['right_overhang'],
                'assembled_start':coordinates[fragment_index]['start'],'assembled_end':coordinates[fragment_index]['end'],
                'assembled_length':len(prepared['assembled_sequence']),
                'assembly_orientation':fragment['orientation']*(-1 if dna!=canonical else 1)})
    entries=list(library.values())
    for entry in entries:entry['shared']=len({u['input_index'] for u in entry['usages']})>1
    return sorted(entries,key=lambda e:(not e['shared'],-len(e['usages']),e['name'],e['sha256']))


def match_batch(batch, *, solve=None, translate=None, metric=None, consensus=None,
                max_solves=128, seconds=240):
    """Greedy shared-donor search, ranking feasible trials by worst then mean score.

    Finite proposals and a search budget deliberately do not claim a global optimum.
    All accepted proposals pass each construct's complete optimiser constraints.
    """
    if solve is None:
        import msgspec
        import numpy as np
        import random
        from mrnarchitect.sequence import Sequence
        from mrnarchitect.sequence_metrics import compute_cai,compute_tai
        from mrnarchitect.organism import load_codon_usage_table_from_database
        from mrnarchitect.constants import AMINO_ACID_TO_CODONS_MAP
        try:
            from .mrna_optimization import optimize_cds
        except ImportError:
            from mrna_optimization import optimize_cds
        translate=lambda dna:str(Sequence(dna).amino_acid_sequence)
        metric=lambda dna,p:float((compute_tai if p['objective']=='tai' else compute_cai)(Sequence(dna),p['organism']))
        def solve(dna,params,preserved,seed):
            np.random.seed(seed);random.seed(seed)
            result=optimize_cds(dna,params,preserved)
            if result.status!='success':raise ValueError(result.error.message)
            return {'sequence':result.solution.sequence,'report':msgspec.to_builtins(result)}
        def consensus(site,parameters):
            dna=list(site['original'])
            tables=[load_codon_usage_table_from_database(p['organism']) for p in parameters]
            for aa,positions in site['codons']:
                choices=AMINO_ACID_TO_CODONS_MAP[aa]
                codon=max(sorted(choices),key=lambda c:sum(math.log(max(float(t.weight(c)),1e-12)) for t in tables))
                for p,base in zip(positions,codon):dna[p]=base if site['sign']>0 else base.translate(_COMPLEMENT)
            return ''.join(dna)
    records=deepcopy(batch['records'])
    if len(records)<2 or any(not r.get('assembly') for r in records):
        raise ValueError('Match fragments requires at least two imported fragment assemblies.')
    source_indices=batch.get('_source_indices',list(range(len(records))))
    started=time.monotonic();deadline=started+seconds;solves=0;attempted=0;cache={};exhausted=False
    params=[];sites=[];proteins=[];preserved=[]
    for i,record in enumerate(records):
        p=deepcopy(record.get('parameters') or batch['parameters'])
        p['avoid_restriction_sites']=list(dict.fromkeys(p['avoid_restriction_sites']+list(active_enzymes(record['assembly']['enzyme']))))
        params.append(p);sites.append(donor_sites(record,translate));proteins.append(translate(record['sequence']))
        prepared=prepare_assembly(record['assembly'])
        stops=[[i+1,i+3] for i in range(0,len(record['sequence']),3) if translate(record['sequence'][i:i+3])=='*']
        preserved.append(merged_regions([*record['preserve_regions'],*prepared['preserve_regions'],*stops]))
    immutable=deepcopy(preserved)
    current=[None]*len(records);reports=[None]*len(records);proposals=[[] for _ in records];errors=[]

    def checked(index,sequence,locks,seed):
        nonlocal solves,attempted,exhausted
        attempted+=1
        original=records[index]['sequence'];locks=merged_regions(locks)
        key=(index,sequence,tuple(map(tuple,locks)),seed)
        if key in cache:return cache[key]
        if solves>=max_solves or time.monotonic()>=deadline:
            exhausted=True;raise ValueError('Fragment matching search budget reached.')
        solves+=1
        result=solve(sequence,params[index],locks,seed);designed=result['sequence']
        if len(designed)!=len(original) or set(designed)-set('ACGT') or translate(designed)!=proteins[index]:
            raise ValueError('Shared fragment optimisation changed the encoded protein or CDS length.')
        if any(designed[a-1:b]!=sequence[a-1:b] for a,b in locks):
            raise ValueError('Shared fragment optimisation changed a locked region.')
        if any(designed[a-1:b]!=original[a-1:b] for a,b in immutable[index]):
            raise ValueError('Shared fragment optimisation changed an original protected region.')
        project_fragments(records[index]['assembly'],designed)
        if not math.isfinite(metric(designed,params[index])):raise ValueError('Codon objective score is unavailable.')
        result['report']={**result['report'],'matching_seed':seed}
        cache[key]=result;return result

    def rank(sequences,indices):
        values=[metric(sequences[i],params[i]) for i in indices]
        return (min(values),sum(values)/len(values),-sum(sum(a!=b for a,b in zip(records[i]['sequence'],sequences[i])) for i in indices))

    # Give every construct one attempt before sampling extra independent proposals.
    for number in range(batch['candidates']):
        for index,record in enumerate(records):
            if number and solves>=max_solves//2:break
            try:
                output=checked(index,record['sequence'],preserved[index],batch['seed']+source_indices[index]+number*1000)
                proposals[index].append(output['sequence'])
                if current[index] is None or rank({index:output['sequence']},[index])>rank(current,[index]):
                    current[index]=output['sequence'];reports[index]=output['report']
            except ValueError as error:
                if number==0:errors.append({'name':record['name'],'candidate':1,'error':str(error)})
    independent=list(current)
    grouped=defaultdict(list)
    for index,donors in enumerate(sites):
        if current[index] is not None:
            for site in donors:grouped[site['template']].append((index,site))
    groups=[members for members in grouped.values() if len({i for i,_ in members})>1]
    groups.sort(key=lambda members:(-(len(members)-1)*len(members[0][1]['original']),members[0][1]['template']))
    def unique_count(sequences):
        values=set()
        for i,donors in enumerate(sites):
            if sequences[i] is None:continue
            for site in donors:
                dna=donor_sequence(site,sequences[i]);values.add(min(dna,reverse_complement(dna)))
        return len(values)
    decisions=[]
    for members in groups:
        indices=sorted({i for i,_ in members});first=members[0][1]
        pool={donor_sequence(site,sequence) for i,site in members for sequence in [records[i]['sequence'],*proposals[i],current[i]]}
        if consensus:pool.add(consensus(first,[params[i] for i in indices]))
        def inserted(donor):
            trial=dict(enumerate(current))
            for i,site in members:trial[i]=apply_donor(site,donor,trial[i])
            return trial
        pool=sorted(pool,key=lambda donor:(rank(inserted(donor),indices),donor),reverse=True)
        # Also retain the supplied shared design as a feasibility fallback.
        originals={site['original'] for _,site in members}
        candidates=pool[:max(2,min(6,batch['candidates']*2))]
        if len(originals)==1 and next(iter(originals)) not in candidates:candidates.append(next(iter(originals)))
        best=None;best_rank=None;failure='No tested shared donor satisfies every construct.';evaluated=0
        shared_locks={i:merged_regions([*preserved[i],*(region for j,site in members if j==i for region in site['regions'])]) for i in indices}
        for donor in candidates:
            if exhausted:break
            trial=inserted(donor);trial_reports={};evaluated+=1
            try:
                for i in indices:
                    if trial[i]!=current[i]:
                        output=checked(i,trial[i],shared_locks[i],batch['seed']+source_indices[i])
                        trial[i]=output['sequence'];trial_reports[i]=output['report']
                if any(donor_sequence(site,trial[i])!=donor for i,site in members):
                    raise ValueError('A tested donor could not be shared at every mapped boundary.')
                count=unique_count(trial)
                if count>unique_count(current):raise ValueError('This proposal increases the total number of unique donor designs.')
                value=(-count,*rank(trial,indices))
                if best is None or value>best_rank:best=(trial,trial_reports,donor);best_rank=value
            except ValueError as error:failure=str(error)
        accepted=best is not None
        if accepted:
            trial,trial_reports,donor=best
            for i in indices:
                current[i]=trial[i];reports[i]=trial_reports.get(i,reports[i]);preserved[i]=shared_locks[i]
        decisions.append({'fragment_names':list(dict.fromkeys(site['fragment_name'] for _,site in members)),
            'inputs':[records[i]['name'] for i in indices],'length':len(first['original']),
            'accepted':accepted,'evaluated_proposals':evaluated,
            'worst_codon_score':best_rank[1] if accepted else None,
            'mean_codon_score':best_rank[2] if accepted else None,
            'reason':None if accepted else failure})
    library=fragment_library(records,current);before=fragment_library(records,independent)
    report={'method':'Bounded greedy search over compatible imported donors; maximise shared reuse, then weakest construct codon score, then mean score. This is the best tested feasible design, not a guaranteed global optimum.',
        'scope':'Imported fragment boundaries only. Protein sequences, original protected regions, overhangs and exogenous donor DNA are unchanged.',
        'independent_unique_fragments':len(before),'matched_unique_fragments':len(library),
        'fragments_saved':len(before)-len(library),'shared_fragment_count':sum(e['shared'] for e in library),
        'candidate_groups':len(groups),'accepted_groups':sum(d['accepted'] for d in decisions),
        'optimiser_calls':solves,'cached_or_attempted_calls':attempted,'search_limit_reached':exhausted,
        'seed':batch['seed'],'max_optimiser_calls':max_solves,'planning_budget_seconds':seconds,
        'elapsed_seconds':round(time.monotonic()-started,3),'decisions':decisions,'library':library}
    failed_names={records[i]['name'] for i,sequence in enumerate(current) if sequence is None}
    return {'sequences':current,'optimization_reports':reports,'report':report,'errors':[e for e in errors if e['name'] in failed_names]}
