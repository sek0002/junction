"""Explain designed junctions and exact/RC reuse without treating library reuse as ligation failure."""
from collections import defaultdict
import re

from .design_engine import fusion_key
from .plate_labels import plate_aliases
from .sequence_engine import active_enzymes, prepare_backbone, restriction_sites, reverse_complement


def valid_label(value):return bool(re.fullmatch('[ACGT]{4}',value or ''))


def database_index(fragments,plasmids,keys,selected_fragments,backbone_id,enzyme):
    index=defaultdict(dict);active=set(active_enzymes(enzyme))
    aliases=plate_aliases(record.get('plate_id','') for record in [*fragments,*plasmids] if not record.get('archived_at'))
    for kind,records in [('fragment',fragments),('plasmid',plasmids)]:
        for record in records:
            if record.get('archived_at'):continue
            sequence=record['sequence'].upper();length=len(sequence)
            circular=kind=='plasmid' and bool(record.get('circular'))
            for site in restriction_sites(sequence,circular):
                if site['enzyme'] not in ('BsaI','BsmBI'):continue
                start=site['end']+1 if site['strand']==1 else site['start']-5
                if circular and length>=4:
                    label=''.join(sequence[(start+i)%length] for i in range(4))
                elif 0<=start and start+4<=length:label=sequence[start:start+4]
                else:continue
                if not valid_label(label) or fusion_key(label) not in keys:continue
                key=fusion_key(label);identity=(kind,record['id']);group=index[key]
                if identity not in group:
                    recipe=record.get('recipe') or {}
                    group[identity]=dict(id=record['id'],kind='backbone' if kind=='plasmid' and (recipe.get('example_backbone') or recipe.get('backbone_template')) else kind,
                        name=record['name'],plate_id=record.get('plate_id',''),well=record.get('well',''),location=record.get('location',''),
                        display_plate=aliases.get(record.get('plate_id',''),''),
                        linked_stock=bool((record.get('custom_metadata') or {}).get('linked_fragment_id')),
                        in_assembly=record['id'] in selected_fragments if kind=='fragment' else record['id']==backbone_id,sites=[])
                group[identity]['sites'].append(dict(enzyme=site['enzyme'],overhang=label,site_start=site['start'],site_end=site['end'],
                    overhang_start=start%length if circular else start,overhang_end=(start%length if circular else start)+4,
                    wraps_origin=circular and (start<0 or start+4>length or site['end']>length),active_enzyme=site['enzyme'] in active))
    return index


def overhang_report(base,enzyme,backbone=None,slot_id=None,excluded=(),fragments=(),plasmids=()):
    rows={};chain=[];locations=defaultdict(list);fixed=set();excluded={fusion_key(label) for label in excluded}
    shifts=base.get('boundary_shifts',[]);runs=base.get('runs',[])
    def run_name(run):
        return ' + '.join(entry['name'] for entry in base.get('entries',[]) if entry.get('run')==run.get('index')) or run.get('name','Insert')
    generated=[row for row in base.get('generated',[]) if not row.get('variant_of')]
    def add(label,kind='existing'):
        if not valid_label(label):return None
        key=fusion_key(label)
        if key not in rows:rows[key]=dict(overhang=label,reverse_complement=reverse_complement(label),kind=kind,uses=[],boundaries=[],assembly_messages=[],assembly_warnings=[])
        return rows[key]
    # Selected native boundaries are distinct from mandatory ends inherited from neighbors.
    for shift in shifts:
        row=add(shift['overhang'],'new')
        if row:
            run=next((run for run in runs if run['index']==shift['run']),{})
            row['boundaries'].append(dict(run=shift['run'],name=run_name(run),requested=shift['requested']+1,actual=shift['actual']+1))
    bb=prepare_backbone(backbone['sequence'],enzyme,slot_id) if backbone else None
    if bb:
        chain.append(dict(name=backbone['name'],left=bb.get('left_overhang',''),right=bb.get('right_overhang',''),kind='backbone'))
        fixed.update(fusion_key(label) for label in (chain[0]['left'],chain[0]['right']) if valid_label(label))
    emitted=set()
    for entry in base.get('entries',[]):
        if entry['kind']=='fragment':
            digest=entry.get('digest',{});node=dict(name=entry['name'],left=digest.get('left_overhang',''),right=digest.get('right_overhang',''),kind='fragment')
            chain.append(node);fixed.update(fusion_key(label) for label in (node['left'],node['right']) if valid_label(label))
        elif entry.get('run') not in emitted:
            emitted.add(entry.get('run'));run=next((run for run in runs if run['index']==entry.get('run')),None)
            if not run:continue
            donors=[row for row in generated if row['run']==run['index']]
            if donors:
                chain.extend(dict(name=row['name'],left=row['left_overhang'],right=row['right_overhang'],kind='generated') for row in donors)
            else:chain.append(dict(name=run['name'],left=run['left_overhang'],right=run['right_overhang'],kind='placeholder'))
            fixed.update(fusion_key(label) for label in (run['left_overhang'],run['right_overhang']) if valid_label(label))
    for node in chain:
        for side,key in [('5′','left'),('3′','right')]:
            row=add(node[key])
            if row:
                use=dict(name=node['name'],side=side,kind=node['kind'])
                if use not in row['uses']:row['uses'].append(use)
    for run in runs:
        selected={shift['requested'] for shift in shifts if shift['run']==run['index']}
        for wanted in run.get('requested',[]):
            position=wanted+run['trim_left']
            if position in selected:continue
            row=add(run['sequence'][wanted:wanted+4],'candidate')
            if row:
                if row['kind']!='new':row['kind']='candidate'
                row['boundaries'].append(dict(run=run['index'],name=run_name(run),requested=position+1,actual=None))
                if fusion_key(row['overhang']) in fixed:row['assembly_messages'].append('Requested boundary reuses an existing assembly overhang or its reverse complement.')
    circular=bool(bb) or bool((base.get('assembly') or {}).get('circular'))
    if chain and valid_label(chain[0]['left']) and chain[0]['left']==chain[-1]['right']:circular=True
    pairs=list(zip(chain,chain[1:]))
    if circular and chain:pairs.append((chain[-1],chain[0]))
    for left,right in pairs:
        name=left['name']+' → '+right['name'];a,b=left['right'],right['left']
        if valid_label(a) and a==b:locations[fusion_key(a)].append(name)
        else:
            message=f"{name}: {a or 'missing'} / {b or 'missing'} do not match."
            for label in (a,b):
                row=add(label)
                if row:row['assembly_messages'].append(message)
    if chain and not circular:
        for label,name in [(chain[0]['left'],'5′ open end'),(chain[-1]['right'],'3′ open end')]:
            if valid_label(label):locations[fusion_key(label)].append(name)
    selected_fragments={entry.get('fragment_id') for entry in base.get('entries',[]) if entry['kind']=='fragment'}
    database=database_index(fragments,plasmids,set(rows),selected_fragments,backbone.get('id') if backbone else None,enzyme)
    for key,row in rows.items():
        if row['kind']=='candidate' and len(row['boundaries'])>1:row['assembly_messages'].append('Requested boundaries share this overhang or its reverse complement.')
        if len(locations[key])>1:row['assembly_messages'].append('Overhang or reverse complement is reused at separate junctions: '+'; '.join(locations[key])+'.')
        if row['kind']=='new' and key in fixed:row['assembly_messages'].append('New junction collides with an existing assembly end or its reverse complement.')
        if key in excluded:row['assembly_messages'].append('Overhang matches an excluded sequence or its reverse complement.')
        if row['overhang']==row['reverse_complement']:row['assembly_warnings'].append('Palindromic overhang can self-ligate.')
        row['assembly_messages']=list(dict.fromkeys(row['assembly_messages']))
        row['assembly_status']='conflict' if row['assembly_messages'] else 'warning' if row['assembly_warnings'] else 'pending' if row['kind']=='candidate' else 'clear'
        row['database_matches']=sorted(database[key].values(),key=lambda match:(match['in_assembly'],match['kind'],match['name'],match['id']))
        for match in row['database_matches']:
            for site in match['sites']:site['reverse_complement']=site['overhang']!=row['overhang']
        row['database_reuse_count']=sum(not match['in_assembly'] for match in row['database_matches'])
    output=sorted(rows.values(),key=lambda row:({'new':0,'candidate':1,'existing':2}[row['kind']],row['overhang']))
    return dict(rows=output,summary=dict(assembly_validated=bool(base.get('valid')),new=sum(row['kind']=='new' for row in output),existing=sum(row['kind']=='existing' for row in output),
        pending=sum(row['kind']=='candidate' for row in output),assembly_conflicts=sum(row['assembly_status']=='conflict' for row in output),
        assembly_warnings=sum(row['assembly_status']=='warning' for row in output),database_reused=sum(row['database_reuse_count']>0 for row in output),
        fragments_scanned=sum(not r.get('archived_at') for r in fragments),plasmids_scanned=sum(not r.get('archived_at') for r in plasmids)),
        scope='Current Design assembly; detected BsaI/BsmBI cut overhangs in the active fragment and plasmid database, including internal sites. Exact and reverse-complement matches; database reuse alone does not block generation.')
