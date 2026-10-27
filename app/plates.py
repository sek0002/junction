"""Plate geometry derived from validated well coordinates."""
import re

from .sequence_engine import digest_fragment, normalize, restriction_sites


def fragment_site_info(sequence, construct_sequence=''):
    """Describe detected sites without applying an assembly enzyme or QC verdict.

    Internal coordinates follow sequence_engine (zero-based, end-exclusive).
    Four-base labels use the submitted 5′→3′ strand, including reverse sites.
    Construct coordinates are supplied only when the insert maps uniquely.
    """
    sequence=normalize(sequence);construct=normalize(construct_sequence)
    offset=construct.find(sequence) if sequence and construct else 0
    if offset<0 or (construct and construct.find(sequence,offset+1)>=0):offset=None
    sites=restriction_sites(sequence)
    gg=[site for site in sites if site['enzyme'] in ('BsaI','BsmBI')]
    # All Golden Gate sites participate in boundary detection. This retains the
    # outer adapters when another enzyme forms a nested cassette inside them.
    cut=digest_fragment(sequence,'BsmBI + BsaI') if gg else {}
    ends=[]
    if cut.get('left_overhang') and cut.get('right_overhang'):
        for label,start,value in (('5′',cut['left_site_start']+7,cut['left_overhang']),
                                  ('3′',cut['right_site_start']-5,cut['right_overhang'])):
            ends.append({'label':label,'overhang':value,'start':start,'end':start+4,
                         'construct_start':start+offset if offset is not None else None,
                         'construct_end':start+offset+4 if offset is not None else None})
    for site in sites:
        if site['enzyme']=='HindIII':start=site['start']+1
        else:
            spacer=2 if site['enzyme']=='BbsI' else 1
            start=site['end']+spacer if site['strand']==1 else site['start']-spacer-4
        end=start+4;complete=0<=start and end<=len(sequence)
        site.update(overhang=sequence[start:end] if complete else '',
                    overhang_start=start if complete else None,overhang_end=end if complete else None,
                    construct_start=site['start']+offset if offset is not None else None,
                    construct_end=site['end']+offset if offset is not None else None,
                    construct_overhang_start=start+offset if complete and offset is not None else None,
                    construct_overhang_end=end+offset if complete and offset is not None else None)
        if site['enzyme'] in ('BsaI','BsmBI') and ends:
            site['location']='5′ adapter' if site['start']==cut['left_site_start'] else '3′ adapter' if site['start']==cut['right_site_start'] else 'Internal' if cut['target_start']<=site['start']<cut['target_end'] else 'Flank'
        else:site['location']=''
    enzymes=list(dict.fromkeys(site['enzyme'] for site in sites))
    adapters=list(dict.fromkeys(cut.get(key) for key in ('left_adapter_enzyme','right_adapter_enzyme') if cut.get(key)))
    return {'sites':sites,'detected_enzymes':enzymes,'fusion_ends':ends,
            'adapter_enzyme':' + '.join(adapters),'construct_offset':offset,
            'digest':{'left_overhang':cut.get('left_overhang',''),'right_overhang':cut.get('right_overhang','')}}


def detect_layout(wells):
    positions=[];unplaced=[]
    for well in wells:
        match=re.fullmatch(r'([A-P])(0?[1-9]|1[0-9]|2[0-4])',well.upper())
        if match:positions.append((ord(match[1])-ord('A'),int(match[2])))
        else:unplaced.append(well)
    large=any(row>=8 or column>12 for row,column in positions)
    return {'format':384 if large else 96,'row_count':16 if large else 8,'column_count':24 if large else 12,
        'layout_basis':'Extended wells' if large else 'Wells fit 96; sparse 384 maps may also fit', 'unplaced':unplaced}
