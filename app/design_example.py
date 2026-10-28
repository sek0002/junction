"""Reference-only GenBank review, including exact highlighted design regions."""
from copy import deepcopy


def example_features(result):
    features = deepcopy(result['assembly']['features'])
    length = result['assembly']['length']
    by_id = {feature.get('fragment_id'): feature for feature in features if feature.get('source') == 'fragment'}
    for run in result['runs']:
        first = next((row for row in result['generated'] if row['run'] == run['index']), None)
        if not first or first['id'] not in by_id:
            continue
        offset = by_id[first['id']]['start'] + 4 - first['target_start']
        for section in run['sections']:
            start = (offset + section['start']) % length
            count = min(section['end'] - section['start'], length)
            segments = [dict(start=start, end=min(length,start+count), strand=1)]
            if start + count > length:
                segments.append(dict(start=0,end=start+count-length,strand=1))
            mode = section.get('mode','constant').title()
            features.append(dict(label=section['name'],type='misc_feature',source='design_region',
                start=segments[0]['start'],end=segments[0]['end'],strand=1,segments=segments,
                qualifiers={'note':[f'{mode} region; reference design example.'],
                            'ApEinfo_fwdcolor':['#8263AF' if mode=='Dynamic' else '#31856D']}))
    return features
