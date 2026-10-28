"""Export strand representation without changing design inputs or assembly choices."""
from copy import deepcopy

from .design_engine import scan_type_ii
from .sequence_engine import reverse_complement as rc


def reverse_features(features, length):
    result = []
    for original in features:
        feature = deepcopy(original)
        segments = feature.get('segments') or [dict(start=feature['start'],end=feature['end'],strand=feature.get('strand',1))]
        mapped = [dict(part, start=length-part['end'],end=length-part['start'],
                       strand=-int(part.get('strand',feature.get('strand',1)) or 0)) for part in segments]
        feature.update(start=length-feature['end'],end=length-feature['start'],strand=-int(feature.get('strand',1) or 0))
        feature.pop('raw_location',None)
        if 'segments' in feature:
            feature['segments'] = mapped
        if feature.get('source') in ('fragment','retained_backbone'):
            feature['reverse_complement'] = not feature.get('reverse_complement',False)
        if feature.get('source') == 'fusion':
            label = feature.get('label','')
            if len(label)>4 and set(label[:4])<=set('ACGT'):
                label = rc(label[:4])+label[4:]
                if ' fusion: ' in label and ' → ' in label:
                    prefix,chain = label.split(' fusion: ',1)
                    left,right = chain.split(' → ',1)
                    label = prefix+' fusion: '+right+' → '+left
                feature['label'] = label
        result.append(feature)
    return sorted(result,key=lambda feature:(feature['start'],feature['end']))


def output_view(result, reverse=False):
    output = deepcopy(result)
    orientation = 'Reverse complement' if reverse else 'Forward'
    output.update(reverse_output=reverse,output_orientation=orientation)
    for row in output['generated']:
        row['output_orientation'] = orientation
        if not reverse:
            continue
        for key in ('sequence','full_sequence','target','target_sequence','retained_sequence','unpadded_full_sequence','synthesis_padding'):
            if key in row:
                row[key] = rc(row[key])
        for left,right in [('left_overhang','right_overhang'),('five_prime_sequence','three_prime_sequence'),('left_re_site','right_re_site')]:
            row[left],row[right] = rc(row[right]),rc(row[left])
        row['left_adapter_enzyme'],row['right_adapter_enzyme'] = row['right_adapter_enzyme'],row['left_adapter_enzyme']
        row['sites'] = scan_type_ii(row['full_sequence'])
        if row.get('padding_length'):
            row['padding_end'] = '5′'
    for row in output.get('constant_overhangs',[]):
        row['output_orientation'] = orientation
        if reverse:
            row['left_overhang'],row['right_overhang'] = rc(row['right_overhang']),rc(row['left_overhang'])
    for product in [*output.get('assemblies',[]), *([output['assembly']] if output.get('assembly') else [])]:
        product['output_orientation'] = orientation
        if reverse:
            product['sequence'] = rc(product['sequence'])
            product['features'] = reverse_features(product['features'],product['length'])
    return output
