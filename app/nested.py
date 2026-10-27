"""Explicit cassette replacements inside linear Golden Gate donors.

Derived sequence and physical reaction inputs are kept separate: simultaneous
reactions use original molecules; staged reactions use a newly prepared parent.
"""
from collections import defaultdict
from .sequence_engine import (assemble, digest_fragment, active_enzymes,
                              restriction_sites, normalize, _collision_messages, reverse_complement)


def prepare_nested(parts, selections, enzyme, lookup):
    parents={part['id']:part for part in parts}
    grouped=defaultdict(list)
    records=[]
    for selection in selections:
        parent=parents.get(selection['parent_fragment_id'])
        if parent is None:
            raise ValueError('Nested parent must be selected in the main assembly.')
        digest=digest_fragment(parent['sequence'],enzyme)
        cassette=next((c for c in digest.get('nested_cassettes',[]) if c['id']==selection['cassette_id']),None)
        if cassette is None:
            raise ValueError(f"{parent['name']}: nested cassette is unavailable for the selected outer adapters.")
        if any(r['cassette']['id']==cassette['id'] for r in grouped[parent['id']]):
            raise ValueError('A nested cassette can only be selected once.')
        children=[]
        for child_id in selection['fragment_ids']:
            child=lookup(child_id)
            if child is None:
                raise ValueError(f'Nested fragment {child_id} is unavailable.')
            children.append(child)
        if not children:
            raise ValueError('Select at least one donor for each nested cassette.')
        if len({c['id'] for c in children})!=len(children) or any(c['id']==parent['id'] for c in children):
            raise ValueError('A nested chain cannot reuse a donor or include its parent.')
        cut=enzyme if selection['mode']=='together' else cassette['enzyme']
        chain=assemble(children,cut,circular=False,left_overhang=cassette['left_overhang'],right_overhang=cassette['right_overhang'])
        errors=list(chain['errors'])
        if chain['left_overhang']!=cassette['left_overhang']:
            message=f"5′ junction requires {cassette['left_overhang']}; found {chain['left_overhang'] or 'no overhang'}."
            errors.append(message)
            chain['fragment_checks'][0]['errors'].append(message)
            chain['fragment_checks'][0]['valid']=False
        if chain['right_overhang']!=cassette['right_overhang']:
            message=f"3′ junction requires {cassette['right_overhang']}; found {chain['right_overhang'] or 'no overhang'}."
            errors.append(message)
            chain['fragment_checks'][-1]['errors'].append(message)
            chain['fragment_checks'][-1]['valid']=False
        if selection['mode']=='together' and not set(active_enzymes(cassette['enzyme'])).issubset(active_enzymes(enzyme)):
            errors.append(f"Together requires {cassette['enzyme']} in the main enzyme selection. Choose dual cutting or Separate first.")
        record={**selection,'parent_name':parent['name'],'cassette':cassette,
                'enzyme':cut,'children':children,'chain':chain,'errors':errors,
                'warnings':list(chain['warnings']),'applied':False}
        grouped[parent['id']].append(record)
        records.append(record)
    derived=[]
    physical=[]
    stages=[]
    for parent in parts:
        groups=sorted(grouped.get(parent['id'],[]),key=lambda r:r['cassette']['replacement_start'])
        if not groups:
            derived.append(parent)
            physical.append(parent)
            continue
        parent_errors=[]
        modes={r['mode'] for r in groups}
        if len(modes)>1:
            parent_errors.append('Use the same reaction mode for all cassettes within one parent.')
        if any(a['cassette']['replacement_end']>b['cassette']['replacement_start'] for a,b in zip(groups,groups[1:])):
            parent_errors.append('Selected nested cassettes overlap.')
        staged=modes=={'separate'}
        if staged:
            stage_enzymes={r['cassette']['enzyme'] for r in groups}
            stocks={r.get('prepared_stock_ng_ul') for r in groups}
            if len(stage_enzymes)>1:
                parent_errors.append('Cassettes prepared together in one parent must use the same enzyme selection.')
            if len(stocks)>1:
                parent_errors.append('Use one prepared-parent stock concentration for all cassettes in this parent.')
            cut=groups[0]['cassette']['enzyme']
            allowed={position for r in groups for position in (r['cassette']['reverse_start'],r['cassette']['forward_start'])}
            other=[s for s in restriction_sites(parent['sequence']) if s['enzyme'] in active_enzymes(cut) and s['start'] not in allowed]
            if other:
                parent_errors.append('Separate first would also cut the parent outside the selected cassette(s): '+', '.join(f"{s['enzyme']} at bp {s['start']+1}" for s in other)+'. Fill every opening or use Together.')
        labels=[]
        for r in groups:
            labels.extend(chain_labels(r['chain'],r['parent_name']))
        parent_errors.extend(_collision_messages(labels))
        donors=[child for r in groups for child in r['children']]
        if len({c['id'] for c in donors})!=len(donors):
            parent_errors.append('A physical donor is selected more than once for this parent reaction.')
        for r in groups:
            r['errors'].extend(parent_errors)
        raw=normalize(parent['sequence'])
        offset=0
        all_valid=all(not r['errors'] for r in groups)
        for r in groups:
            r['raw_start']=r['cassette']['replacement_start']+offset
            if all_valid:
                a,b=r['raw_start'],r['cassette']['replacement_end']+offset
                raw=raw[:a]+r['chain']['sequence']+raw[b:]
                offset+=r['chain']['length']-(b-a)
                r['applied']=True
        if staged and all_valid:
            retained=[site for site in restriction_sites(raw) if site['enzyme'] in active_enzymes(groups[0]['cassette']['enzyme'])]
            if retained:
                for record in groups:
                    record['errors'].append('The prepared parent retains an active stage enzyme site, including at a new junction; it would be cut again.')
        prepared=parent | {'sequence':raw}
        derived.append(prepared)
        if staged:
            stock=groups[0].get('prepared_stock_ng_ul')
            physical.append(prepared | {'id':'prepared:'+str(parent['id']),'source_fragment_id':parent['id'],'name':parent['name']+' (prepared)',
                'physical_length':len(raw),'construct_sequence':raw,'yield_ng':None,
                'stock_ng_ul':stock,'resuspension_ul':None,'plate_id':'','well':'',
                '_prepared_nested':True,'_planner_stock_fixed':True,
                'concentration_basis':'Prepared parent · manual stock'})
            stages.append({'parent':parent,'enzyme':groups[0]['cassette']['enzyme'],
                           'children':donors,'records':groups})
        else:
            physical.extend([parent,*donors])
    return derived,physical,records,stages


def chain_labels(chain, location):
    if not chain['fragments']:
        return []
    return [(chain['left_overhang'],location+' nested 5′'),
            *[(j['overhang'],location+' nested junction') for j in chain['junctions'] if j['compatible']],
            (chain['right_overhang'],location+' nested 3′')]


def annotate_nested(result, records):
    together=[r for r in records if r['mode']=='together']
    labels=[(j['overhang'],f"{j['from']} → {j['to']}") for j in result['junctions'] if j['compatible']]
    if result['fragments'] and not result['circular']:
        labels=[(result['left_overhang'],'main 5′'),*labels,(result['right_overhang'],'main 3′')]
    for record in together:
        labels.extend(chain_labels(record['chain'],record['parent_name']))
    collisions=_collision_messages(labels) if together else []
    physical_ids=[c['id'] for r in together for c in r['children']]
    main_ids=[p['id'] for p in result['fragments'] if not p['is_backbone']]
    duplicate=bool(len(set(physical_ids+main_ids))!=len(physical_ids+main_ids))
    for record in records:
        if record['mode']=='together':
            record['errors'].extend(collisions)
            if duplicate:
                record['errors'].append('A donor is reused in the main reaction. Each physical donor can have only one position.')
        record['errors']=list(dict.fromkeys(record['errors']))
        record['valid']=not record['errors']
        result['errors'].extend(f"{record['parent_name']} nested: {error}" for error in record['errors'])
        result['warnings'].extend(f"{record['parent_name']} nested: {message}" for message in record['warnings'])
        for check in result['fragment_checks']:
            if check['id']==record['parent_fragment_id'] and not check['is_backbone']:
                check['errors']=list(dict.fromkeys(check['errors']+record['errors']))
                check['warnings']=list(dict.fromkeys(check['warnings']+record['warnings']))
                check['valid']=not check['errors']
        if not record['applied']:
            continue
        parent_feature=next((f for f in result['features'] if f.get('fragment_id')==record['parent_fragment_id'] and f.get('source')=='fragment'),None)
        parent_edge=next((f for f in result['fragments'] if f['id']==record['parent_fragment_id'] and not f['is_backbone']),None)
        if parent_feature is None or parent_edge is None:
            continue
        parent_reversed=parent_edge.get('reverse_complement',False)
        shift=parent_feature['start']+record['raw_start']-parent_edge.get('source_left_overhang_start',parent_edge['left_site_start']+7)
        boundary_features=[{'start':position,'end':position+4,'type':'misc_feature','strand':1,'label':f"{overhang} nested fusion",'source':'fusion'} for position,overhang in ((0,record['cassette']['left_overhang']),(record['chain']['length']-4,record['cassette']['right_overhang']))]
        for feature in record['chain']['features']+boundary_features:
            moved=feature | {'start':feature['start']+shift,'end':feature['end']+shift,
                'parent_fragment_id':record['parent_fragment_id'],'source':'nested_fragment' if feature.get('source')=='fragment' else 'nested_fusion',
                'qualifiers':{'note':[f"Nested in {record['parent_name']}; {record['mode']}; {record['enzyme']}"]}}
            if parent_reversed:
                source_end=parent_edge['source_right_overhang_end']
                moved['start']=parent_feature['start']+source_end-record['raw_start']-feature['end']
                moved['end']=parent_feature['start']+source_end-record['raw_start']-feature['start']
                moved['strand']=-feature.get('strand',1)
                if feature.get('source')=='fusion' and len(feature.get('label','').split(' ')[0])==4:
                    moved['label']=reverse_complement(feature['label'][:4])+feature['label'][4:]
                moved['reverse_complement']=not feature.get('reverse_complement',False) if feature.get('source')=='fragment' else False
            moved.pop('fragment_index',None)
            if 0<=moved['start']<moved['end']<=result['length']:
                result['features'].append(moved)
    result['features'].sort(key=lambda f:(f['start'],f['end']))
    result['errors']=list(dict.fromkeys(result['errors']))
    result['warnings']=list(dict.fromkeys(result['warnings']))
    result['valid']=not result['errors']
    result['nested_assemblies']=[{k:v for k,v in record.items() if k not in ('children','chain')} | {
        'fragment_checks':record['chain']['fragment_checks'],
        'children':[{k:v for k,v in child.items() if k not in ('sequence','construct_sequence')} for child in record['children']],
        'length':record['chain']['length'],'junctions':[
            {'from':record['parent_name']+' cassette 5′','to':record['children'][0]['name'],
             'left_overhang':record['cassette']['left_overhang'],'right_overhang':record['chain']['left_overhang'],
             'overhang':record['cassette']['left_overhang'],'compatible':record['cassette']['left_overhang']==record['chain']['left_overhang']},
            *record['chain']['junctions'],
            {'from':record['children'][-1]['name'],'to':record['parent_name']+' cassette 3′',
             'left_overhang':record['chain']['right_overhang'],'right_overhang':record['cassette']['right_overhang'],
             'overhang':record['cassette']['right_overhang'],'compatible':record['cassette']['right_overhang']==record['chain']['right_overhang']} ]}

        for record in records]
