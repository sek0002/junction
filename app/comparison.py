"""Read-only comparison orchestration and bounded fragment occurrence matching."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from hashlib import sha256
import re

from .exports import parse_sequence_file

from .alignment import _align, _anchors, _rc, _summarize, infer_database_candidates, rank_candidates
from .sequence_engine import digest_fragment, restriction_sites

MODES=('BsaI','BsmBI','BsmBI + BsaI')


def parse_comparison_file(text,filename):
    """Keep malformed records isolated without weakening the import parser."""
    text=text.lstrip('\ufeff').strip()
    genbank=bool(re.search(r'^LOCUS\s',text,re.M))
    blocks=([b for b in re.split(r'^//\s*$',text.replace('\r\n','\n'),flags=re.M) if b.strip()] if genbank else
        [b for b in re.split(r'(?m)(?=^>)',text) if b.strip()] if text.startswith('>') else [text])
    if len(blocks)>100:raise ValueError('A file may contain at most 100 sequence records.')
    records=[]
    for i,block in enumerate(blocks):
        locus=re.search(r'^LOCUS\s+(\S+)',block,re.M)
        name=locus.group(1) if locus else block.splitlines()[0].lstrip('>').strip() if block.startswith('>') else filename
        try:
            if not block.strip() or block.startswith('>') and not ''.join(block.splitlines()[1:]).strip():
                raise ValueError('The sequence is empty.')
            records.extend(parse_sequence_file(block,filename))
        except (ValueError,IndexError) as error:
            if len(blocks)==1:raise ValueError(str(error)) from error
            records.append({'name':name or 'Record '+str(i+1),'error':str(error)})
    return records


def _spans(start,length,total):
    start%=total
    return [[start,min(start+length,total)]]+([[0,start+length-total]] if start+length>total else [])


def fragment_matches(query,fragments,enzymes,circular=True,max_approximate=60):
    """Locate full inputs/payloads, then align a bounded anchor-guided shortlist.

    Shared and short matches are evidence of sequence presence, not unique source
    attribution. Approximate matching is heuristic and never proves absence.
    """
    total=len(query);extended=query+query if circular else query
    exact=[];approximate=[];indexes={};truncated=False
    for part in fragments:
        variants={}
        raw=part['sequence'].upper()
        if len(raw)>=8:variants[raw]={'representation':'Full input','enzymes':[]}
        for enzyme in enzymes:
            digest=digest_fragment(raw,enzyme)
            retained=digest.get('sequence','')
            if digest.get('valid') and len(retained)>=8:
                variant=variants.setdefault(retained,{'representation':'Digested payload','enzymes':[]})
                variant['enzymes'].append(enzyme)
        best=None
        for reference,meta in variants.items():
            for strand,oriented in (('+',reference),('-',_rc(reference))):
                if len(oriented)<=total:
                    positions=[];at=extended.find(oriented)
                    while at>=0 and at<total:
                        positions.append(at)
                        if len(positions)>=8:break
                        at=extended.find(oriented,at+1)
                    if positions:
                        hit={'id':part['id'],'name':part['name'],'plate_id':part.get('plate_id',''),'well':part.get('well',''),
                            **meta,'strand':strand,'reference_length':len(reference),'identity':1.,'coverage':1.,'exact':True,
                            'short_match':len(reference)<30,'query_spans':_spans(positions[0],len(reference),total),
                            'occurrences':[_spans(p,len(reference),total) for p in positions], 'occurrences_capped':len(positions)==8,
                            'changes':[],'status':'Exact'}
                        if best is None or hit['reference_length']>best['reference_length']:best=hit
                        continue
                if len(reference)<30:continue
                k=min(13,max(7,len(reference)//5))
                if k not in indexes:
                    index=defaultdict(list)
                    for i in range(len(extended)-k+1):
                        word=extended[i:i+k]
                        if len(index[word])<9:index[word].append(i)
                    indexes[k]=index
                votes=Counter();supported=0;sampled=0
                step=max(1,len(reference)//80)
                for i in range(0,len(oriented)-k+1,step):
                    sampled+=1;positions=indexes[k].get(oriented[i:i+k],[])
                    if not positions or len(positions)>8:continue
                    supported+=1
                    for pos in positions:
                        offset=(pos-i)%total if circular else pos-i
                        votes[round(offset/8)*8]+=1
                support=supported/max(1,sampled)
                if supported>=3 and support>=.25:
                    approximate.append((support,part,oriented,meta,strand,votes.most_common(2)))
        if best:exact.append(best)
    exact_ids={hit['id'] for hit in exact}
    approximate=[row for row in approximate if row[1]['id'] not in exact_ids]
    approximate.sort(key=lambda row:row[0],reverse=True)
    truncated=len(approximate)>max_approximate
    near={}
    for support,part,reference,meta,strand,offsets in approximate[:max_approximate]:
        for offset,_ in offsets:
            padding=16;start=offset-padding
            if circular:
                start%=total;window=(query+query+query)[start:start+min(total,len(reference)+padding*2)]
            else:
                start=max(0,start);window=query[start:start+len(reference)+padding*2]
            seeds=_anchors(reference,window)
            if not seeds and len(reference)*len(window)<=1000000:
                seeds=[(b.a,b.b,b.size) for b in SequenceMatcher(None,reference,window,autojunk=False).get_matching_blocks() if b.size]
            if not seeds:continue
            left=max(0,seeds[0][1]-seeds[0][0])
            last=seeds[-1];right=min(len(window),last[1]+len(reference)-last[0])
            observed=window[left:right]
            if not observed:continue
            ar,aq=_align(reference,observed)
            same=sum(a==b and a!='-' for a,b in zip(ar,aq));covered=sum(a!='-' and b!='-' for a,b in zip(ar,aq))
            identity=same/max(1,len(ar));coverage=covered/len(reference)
            if identity<.65 or coverage<.6 or same<30:continue
            changes,_=_summarize(ar,aq,0,'+',len(observed))
            for change in changes:
                n=change['query_end']-change['query_start']
                position=start+left+change['query_start']
                point=position%total if circular else min(total,max(0,position))
                change['original_query_spans']=_spans(position,n,total) if n else [[point,point]]
            hit={'id':part['id'],'name':part['name'],'plate_id':part.get('plate_id',''),'well':part.get('well',''),
                **meta,'strand':strand,'reference_length':len(reference),'identity':identity,'coverage':coverage,'exact':not changes,
                'query_spans':_spans(start+left,len(observed),total),'occurrences':[], 'short_match':False,
                'changes':changes,'status':'Partial' if coverage<.95 else 'Near match'}
            current=near.get(part['id'])
            if current is None or (identity,coverage,len(reference))>(current['identity'],current['coverage'],current['reference_length']):near[part['id']]=hit
    hits=exact+list(near.values());hits.sort(key=lambda hit:(hit['query_spans'][0][0],-hit['reference_length'],hit['name']))
    return {'matches':hits,'metadata':{'fragments_checked':len(fragments),'matched_fragments':len(hits),
        'approximate_variants_checked':min(len(approximate),max_approximate),'approximate_search_capped':truncated,
        'limitations':'Exact full-input/payload search plus bounded anchor-guided approximate matching. Short/shared matches do not establish unique fragment origin. Unreported fragments are not proven absent.'}}


def _minimal_rotation(sequence):
    """Lexicographically minimal circular origin in linear time (Booth)."""
    doubled=sequence+sequence;n=len(sequence);i,j,k=0,1,0
    while i<n and j<n and k<n:
        a,b=doubled[i+k],doubled[j+k]
        if a==b:k+=1;continue
        if a>b:
            i=i+k+1
            if i<=j:i=j+1
        else:
            j=j+k+1
            if j<=i:j=i+1
        k=0
    start=min(i,j)
    return doubled[start:start+n]


def _reference_key(candidate):
    sequence=candidate['sequence'].upper();circular=bool(candidate.get('circular',True))
    if circular:sequence=min(_minimal_rotation(sequence),_minimal_rotation(_rc(sequence)))
    return sha256(sequence.encode()).hexdigest(),circular


def compare_record(record,fragments,references,enzyme='auto',infer=True):
    query=record['sequence'];modes=MODES if enzyme=='auto' else (enzyme,)
    candidates=[dict(item) for item in references];metadata={};inferred=[]
    if infer:
        for mode in modes:
            generated=infer_database_candidates(query,fragments,enzyme=mode,max_candidates=64,max_parts=20,backbones=references)
            metadata[mode]=generated['metadata']
            inferred.extend(dict(p,assembly_enzymes=[mode],source='inferred from plate fragments') for p in generated['candidates'])
        candidates.extend(inferred)
    combined={}
    for candidate in candidates:
        key=_reference_key(candidate)
        paths=[]
        if candidate.get('parts'):
            paths=[{field:candidate[field] for field in ('name','source','parts','fragment_ids','part_orientations','backbone_id','slot_id','assembly_enzymes') if field in candidate}]
        if key not in combined:
            combined[key]=dict(candidate,aliases=[{'name':candidate['name'],'source':candidate['source']}],assembly_enzymes=list(candidate.get('assembly_enzymes',[])),assembly_paths=paths)
        else:
            match=combined[key];match['aliases'].append({'name':candidate['name'],'source':candidate['source']})
            match['assembly_enzymes']=list(dict.fromkeys(match['assembly_enzymes']+candidate.get('assembly_enzymes',[])))
            match['assembly_paths'].extend(paths)
            if not match.get('parts') and candidate.get('parts'):match['parts']=candidate['parts']
    ranked=rank_candidates(query,combined.values(),limit=5) if combined else []
    # A high-identity circular reference can establish circular context for FASTA.
    circular=bool(record.get('circular') or ranked and ranked[0].get('circular') and ranked[0]['identity']>=.95)
    fragments_result=fragment_matches(query,fragments,modes,circular=circular)
    counts=Counter(site['enzyme'] for site in restriction_sites(query,circular=circular) if site['enzyme'] in ('BsaI','BsmBI'))
    compatible=ranked[0].get('assembly_enzymes',[]) if ranked and ranked[0]['identity']>=.95 else []
    return {'query_name':record['name'],'query_length':len(query),'query_sequence':query,'query_circular':circular,'matches':ranked,
        'candidate_count':len(combined),'inferred_count':len(inferred),'search':{'modes':metadata,'routes_explored':sum(v.get('routes_explored',0) for v in metadata.values()),'complete_search':all(v['complete_search'] for v in metadata.values()) if metadata else None},
        'enzyme_detection':{'mode':enzyme,'tested':list(modes),'site_counts':dict(counts),'compatible_assembly_modes':compatible,
            'resolved_enzyme':compatible[0] if len(compatible)==1 else None,
            'basis':'Auto tests all assembly modes. Retained recognition sites alone do not identify the assembly enzyme.'},
        'fragment_matches':fragments_result['matches'],'fragment_search':fragments_result['metadata'],
        'source_counts':dict(Counter(p['source'] for p in references)),
        'note':'Closest alignments within saved plasmids, valid build-list/recipe assemblies, and a bounded search of oriented fragments and retained backbone cassettes. Fragment matches can overlap and do not establish a unique assembly.'}
