"""Scarless donor design against fixed Golden Gate assembly context.

All coordinates are zero based and end exclusive. A split coordinate names
the first base of its four-base overlap. Requested boundaries may move within
the requested window; the concatenated input DNA is never domesticated.
"""
import re
from itertools import product
from math import prod

from .sequence_engine import (ENZYMES, active_enzymes, assemble, digest_fragment,
                              normalize, prepare_backbone, reverse_complement)

from .design_orientation import orient_fragments, annotate_orientations

TYPE_II = {name: motifs[0] for name, motifs in ENZYMES.items()} | {
    'EcoRI': 'GAATTC', 'BamHI': 'GGATCC', 'XbaI': 'TCTAGA',
    'NotI': 'GCGGCCGC', 'XhoI': 'CTCGAG', 'PstI': 'CTGCAG',
    'EcoRV': 'GATATC', 'KpnI': 'GGTACC', 'NheI': 'GCTAGC',
    'SpeI': 'ACTAGT', 'SalI': 'GTCGAC', 'SapI': 'GCTCTTC',
}


def insert_dna(text):
    # FASTA headers are metadata; every other non-DNA character is an error.
    return normalize(''.join(line for line in text.splitlines() if not line.startswith('>')))


def scan_type_ii(sequence, circular=False):
    sequence = normalize(sequence)
    search = sequence + (sequence[:7] if circular else '')
    result = []
    for name, motif in TYPE_II.items():
        for strand, word in ((1, motif), (-1, reverse_complement(motif))):
            if strand == -1 and word == motif:
                continue
            for match in re.finditer('(?=' + word + ')', search):
                start = match.start()
                if start < len(sequence) and (circular or start + len(word) <= len(sequence)):
                    result.append(dict(enzyme=name, start=start, end=start + len(word),
                                       strand=strand, motif=word))
    return sorted(result, key=lambda site: (site['start'], site['enzyme']))


def fusion_key(label):
    return min(label, reverse_complement(label))


def donor_sequence(left, target, right, enzyme, avoid, right_enzyme=None):
    right_enzyme = right_enzyme or enzyme
    forward, reverse = ENZYMES[enzyme][0], ENZYMES[right_enzyme][1]
    adapters = {enzyme,right_enzyme}
    digest_enzyme = enzyme if len(adapters)==1 else 'BsmBI + BsaI'
    # Six external bases protect the terminal recognition sites. Search the
    # one-base spacers to avoid accidental sites at adapter boundaries.
    for a in 'ACGT':
        for b in 'ACGT':
            sequence = 'GCGTAC' + forward + a + left + target + right + b + reverse + 'GTACGC'
            digest = digest_fragment(sequence, digest_enzyme)
            if digest['valid'] and not any(site['enzyme'] in avoid - adapters for site in scan_type_ii(sequence)):
                return sequence
    raise ValueError(f'No {enzyme} adapter spacers avoid internal or boundary restriction sites.')


def design(entries, enzyme='BsaI', backbone=None, slot_id=None, left_overhang='',
           right_overhang='', window=20, avoid_sites=(), excluded_overhangs=(),
           generate=True, adapter_enzyme='BsaI', left_adapter_enzyme=None, right_adapter_enzyme=None):
    active = set(active_enzymes(enzyme))
    adapter = adapter_enzyme if len(active) > 1 else next(iter(active))
    left_adapter = left_adapter_enzyme or adapter
    right_adapter = right_adapter_enzyme or adapter
    avoid = active | set(avoid_sites)
    errors, warnings, nodes, runs, generated = [], [], [], [], []
    for side, chosen in (('5′',left_adapter),('3′',right_adapter)):
        if chosen not in active:
            errors.append(f'{side} {chosen} adapter is not cut by the selected assembly enzyme. Select {chosen} or the dual-enzyme reaction.')
    excluded = {fusion_key(label) for label in excluded_overhangs}
    reserved = set(excluded)
    bb = prepare_backbone(backbone['sequence'], enzyme, slot_id) if backbone else None
    if bb:
        errors.extend(bb['errors'])
        reserved.update(fusion_key(bb[key]) for key in ('left_overhang', 'right_overhang') if bb[key])
    resolved = orient_fragments(entries, enzyme, bb, left_overhang, right_overhang)
    for index, entry in enumerate(entries):
        node = dict(entry, index=index)
        if entry['kind'] == 'fragment':
            node['digest'] = resolved[index]
            node['reverse'] = bool(node['digest']['reverse_complement'])
            node['oriented_sequence'] = node['digest']['input_sequence']
            errors.extend(f"{entry['name']}: {message}" for message in node['digest']['errors'])
            reserved.update(fusion_key(node['digest'][key]) for key in ('left_overhang', 'right_overhang') if node['digest'][key])
        else:
            node['sequence'] = insert_dna(entry.get('sequence', ''))
            node['sites'] = scan_type_ii(node['sequence'])
            for site in node['sites']:
                if site['enzyme'] in avoid:
                    errors.append(f"{entry['name']}: {site['enzyme']} site at insert base {site['start'] + 1}.")
            if not node['sequence']:
                errors.append(f"{entry['name']}: paste an insert sequence.")
            elif set(node['sequence']) - set('ACGT'):
                errors.append(f"{entry['name']}: only A, C, G and T are supported.")
            for section in entry.get('sections', []):
                if not 0 <= section['start'] < section['end'] <= len(node['sequence']):
                    errors.append(f"{entry['name']}: section {section['name']} is outside the insert.")
                for variant in section.get('variants', []):
                    if not insert_dna(variant['sequence']) or set(insert_dna(variant['sequence'])) - set('ACGT'):
                        errors.append(f"{section['name']} / {variant['name']}: only A, C, G and T are supported.")
                    for site in scan_type_ii(insert_dna(variant['sequence'])):
                        if site['enzyme'] in avoid:
                            errors.append(f"{section['name']} / {variant['name']}: {site['enzyme']} site at variant base {site['start'] + 1}.")
        nodes.append(node)

    for previous, following in zip(nodes, nodes[1:]):
        if previous['kind'] == following['kind'] == 'fragment' and previous['digest']['right_overhang'] != following['digest']['left_overhang']:
            errors.append(f"{previous['name']} → {following['name']}: mismatched overhangs {previous['digest']['right_overhang']} / {following['digest']['left_overhang']}.")
    if bb and nodes:
        if nodes[0]['kind'] == 'fragment' and nodes[0]['digest']['left_overhang'] != bb['right_overhang']:
            errors.append(f"Backbone → {nodes[0]['name']}: expected {bb['right_overhang']} at the first donor.")
        if nodes[-1]['kind'] == 'fragment' and nodes[-1]['digest']['right_overhang'] != bb['left_overhang']:
            errors.append(f"{nodes[-1]['name']} → Backbone: expected {bb['left_overhang']} at the last donor.")
    if not bb and nodes:
        for node,key,expected in [(nodes[0],'left_overhang',left_overhang),(nodes[-1],'right_overhang',right_overhang)]:
            if expected and node['kind']=='fragment' and node['digest'][key]!=expected:
                errors.append(f"{node['name']}: expected fixed {key.replace('_',' ')} {expected}.")
    for node in nodes:
        if node['kind'] == 'fragment':
            for key in ('left_overhang', 'right_overhang'):
                value = node['digest'][key]
                if value and fusion_key(value) in excluded:
                    errors.append(f"{node['name']}: fixed overhang {value} conflicts with an exclusion.")

    # Treat adjacent placeholders as one continuous insert. Their boundary
    # requests remain distinct, but a shared native overlap is counted once.
    i = 0
    while i < len(nodes):
        if nodes[i]['kind'] != 'placeholder':
            i += 1
            continue
        start = i
        while i < len(nodes) and nodes[i]['kind'] == 'placeholder':
            i += 1
        group = nodes[start:i]
        sequence, boundaries, sections = '', [], []
        for node in group:
            offset = len(sequence)
            if offset:
                boundaries.append(offset)
            for section in node.get('sections', []):
                boundaries.extend((offset + section['start'], offset + section['end']))
                sections.append(dict(section, start=offset + section['start'], end=offset + section['end'], key=f"{node['id']}:{section['start']}:{section['end']}"))
            sequence += node['sequence']
        previous = nodes[start - 1]['digest']['right_overhang'] if start else (bb['right_overhang'] if bb else left_overhang)
        following = nodes[i]['digest']['left_overhang'] if i < len(nodes) else (bb['left_overhang'] if bb else right_overhang)
        trim_left, trim_right = 0, 0
        if not previous and len(sequence) >= 4:
            previous, trim_left = sequence[:4], 4
        if not following and len(sequence) >= 4:
            following, trim_right = sequence[-4:], 4
        stop = len(sequence) - trim_right
        core = sequence[trim_left:stop]
        if len(previous) != 4 or len(following) != 4 or not core:
            errors.append(f"{group[0]['name']}: the insert is too short for two four-base ends and a payload.")
        for label in (previous, following):
            if label:
                if fusion_key(label) in excluded:
                    errors.append(f'{group[0]["name"]}: fixed overhang {label} conflicts with an exclusion.')
                reserved.add(fusion_key(label))
                if label == reverse_complement(label):
                    warnings.append(f'Fixed overhang {label} is palindromic.')
        for section in sections:
            if section.get('variants') and (section['start'] < trim_left or section['end'] > stop):
                errors.append(f"{section['name']}: define fixed open ends or select a backbone before replacing terminal dynamic bases.")
        requested = sorted({b - trim_left for b in boundaries if trim_left < b < stop})
        run = dict(index=len(runs), start=start, end=i, ids=[n['id'] for n in group],
                   name=group[0]['name'], sequence=core, left_overhang=previous,
                   right_overhang=following, trim_left=trim_left, sections=sections,
                   requested=requested, positions=[])
        runs.append(run)
        for node in group:
            node['run'] = run['index']

    complete = bool(nodes) and not errors
    result = dict(valid=False, complete=complete, errors=errors, warnings=warnings,
                  entries=nodes, runs=runs, generated=generated, assembly=None,
                  scanned_enzymes=list(TYPE_II), boundary_shifts=[])
    if not nodes:
        errors.append('Add a fragment or placeholder.')
    if not generate or errors:
        return result

    # Enumerate all boundary choices together, so an early greedy choice
    # cannot consume the only available overhang in a later placeholder.
    tasks = []
    for run in runs:
        for wanted in run['requested']:
            candidates = []
            for position in range(max(1, wanted - window), min(len(run['sequence']) - 5, wanted + window) + 1):
                label = run['sequence'][position:position + 4]
                dynamic = [s for s in run['sections'] if s.get('mode') == 'dynamic']
                original = position + run['trim_left']
                wanted_original = wanted + run['trim_left']
                if any(original < s['end'] and original + 4 > s['start'] for s in dynamic):
                    continue
                if any((wanted_original == s['start'] and original + 4 > s['start']) or (wanted_original == s['end'] and original < s['end']) for s in dynamic):
                    continue
                if label == reverse_complement(label) or fusion_key(label) in reserved:
                    continue
                gc = label.count('G') + label.count('C')
                candidates.append((abs(position - wanted), abs(gc - 2), -len(set(label)), position, label))
            tasks.append((run, wanted, sorted(candidates)))
    if len(tasks) > 100:
        errors.append('Use at most 100 split boundaries per design.')
        return result
    attempts = 0
    used = set(reserved)

    def choose(index):
        nonlocal attempts
        if index == len(tasks):
            return True
        run, wanted, candidates = tasks[index]
        for _, _, _, position, label in candidates:
            attempts += 1
            if attempts > 25000:
                return False
            if run['positions'] and position < run['positions'][-1] + 5:
                continue
            key = fusion_key(label)
            if key in used:
                continue
            used.add(key)
            run['positions'].append(position)
            if choose(index + 1):
                return True
            run['positions'].pop()
            used.remove(key)
        return False

    if not choose(0):
        errors.append('No non-conflicting native overhang set was found. Increase the boundary window or move the highlighted sections. Dynamic regions need constant flanks for their four-base junctions; the insert has not been changed.')
        return result
    for run in runs:
        for wanted, actual in zip(run['requested'], run['positions']):
            result['boundary_shifts'].append(dict(run=run['index'], requested=wanted + run['trim_left'],
                                                 actual=actual + run['trim_left'], overhang=run['sequence'][actual:actual + 4]))
        starts = [0] + run['positions']
        stops = [p + 4 for p in run['positions']] + [len(run['sequence'])]
        for number, (start, stop) in enumerate(zip(starts, stops), 1):
            left = run['left_overhang'] if number == 1 else run['sequence'][start:start + 4]
            right = run['right_overhang'] if number == len(starts) else run['sequence'][stop - 4:stop]
            target_start = start if number == 1 else start + 4
            target_end = stop if number == len(starts) else stop - 4
            target = run['sequence'][target_start:target_end]
            center = (target_start + target_end) / 2 + run['trim_left']
            contained_dynamic = [s for s in run['sections'] if s.get('mode') == 'dynamic' and s['start'] >= target_start + run['trim_left'] and s['end'] <= target_end + run['trim_left']]
            section = next(iter(contained_dynamic), None) or next((s for s in run['sections'] if s['start'] <= center < s['end']), None)
            name = f"{section['name'] if section else run['name']}_{number}"
            try:
                sequence = donor_sequence(left, target, right, left_adapter, avoid, right_adapter)
            except ValueError as exc:
                errors.append(f'{name}: {exc}')
                continue
            fragment = dict(id=f"design_{run['index']}_{number}", name=name, sequence=sequence,
                                  left_overhang=left, right_overhang=right, target=target,
                                  length=len(sequence), gc=100 * (sequence.count('G') + sequence.count('C')) / len(sequence),
                                  run=run['index'], source_start=start + run['trim_left'],
                                  source_end=stop + run['trim_left'], adapter_enzyme=left_adapter if left_adapter==right_adapter else 'BsmBI + BsaI',
                                  left_adapter_enzyme=left_adapter, right_adapter_enzyme=right_adapter,
                                  target_start=target_start+run['trim_left'], target_end=target_end+run['trim_left'],
                                  region_mode=section.get('mode','constant') if section else 'constant',
                                  dynamic_regions=[s for s in run['sections'] if s.get('mode')=='dynamic' and s['start']>=target_start+run['trim_left'] and s['end']<=target_end+run['trim_left']],
                                  sites=scan_type_ii(sequence))
            generated.append(fragment)
            for dynamic in contained_dynamic:
                offset = dynamic['start'] - run['trim_left'] - target_start
                for variant_index, variant in enumerate(dynamic.get('variants', []), 1):
                    alternate = insert_dna(variant['sequence'])
                    variant_target = target[:offset] + alternate + target[offset + dynamic['end'] - dynamic['start']:]
                    variant_name = name + '__' + variant['name']
                    try:
                        variant_sequence = donor_sequence(left, variant_target, right, left_adapter, avoid, right_adapter)
                    except ValueError as exc:
                        errors.append(f'{variant_name}: {exc}')
                        continue
                    generated.append(fragment | dict(id=fragment['id'] + f'_v{variant_index}', name=variant_name,
                        variant_of=fragment['id'], variant_name=variant['name'], sequence=variant_sequence,
                        target=variant_target, length=len(variant_sequence),
                        gc=100 * (variant_sequence.count('G') + variant_sequence.count('C')) / len(variant_sequence),
                        sites=scan_type_ii(variant_sequence)))
    if errors:
        return result
    donors, emitted = [], set()
    for node in nodes:
        if node['kind'] == 'fragment':
            donors.append(dict(id=node.get('fragment_id'), name=node['name'], sequence=node['oriented_sequence']))
        elif node['run'] not in emitted:
            emitted.add(node['run'])
            donors.extend(fragment for fragment in generated if fragment['run'] == node['run'] and not fragment.get('variant_of'))
    assembly = annotate_orientations(assemble(donors, enzyme, backbone, slot_id, circular=None), nodes)
    result['assembly'] = assembly
    errors.extend(assembly['errors'])
    warnings.extend(assembly['warnings'])
    blocked = [site for site in scan_type_ii(assembly['sequence'], assembly['circular']) if site['enzyme'] in avoid]
    for site in blocked:
        message = f"Final assembly: {site['enzyme']} site at base {site['start'] + 1}."
        if message not in errors:
            errors.append(message)
    # Scan complete donors for inactive enzymes requested for exclusion, too.
    for fragment in generated:
        if any(site['enzyme'] in avoid - active for site in fragment['sites']):
            errors.append(fragment['name'] + ': an excluded restriction site remains in the donor.')
    result['valid'] = not errors
    result['errors'] = list(dict.fromkeys(errors))
    result['warnings'] = list(dict.fromkeys(warnings))
    result['assembly_sites'] = scan_type_ii(assembly['sequence'], assembly['circular'])
    families = [[donor] + [row for row in generated if row.get('variant_of') == donor.get('id')] for donor in donors]
    count = prod(len(family) for family in families)
    if count > 64 or count * max(1, assembly['length']) > 2000000:
        result['errors'].append('Use at most 64 variant combinations and 2 million assembled bases per design.')
        result['valid'] = False
        result['assemblies'] = []
        return result
    products = []
    total_bases = 0
    for index, combination in enumerate(product(*families)):
        assembled = assembly if index == 0 else assemble(list(combination), enzyme, backbone, slot_id, circular=None)
        annotate_orientations(assembled, nodes)
        total_bases += assembled['length']
        names = [row.get('variant_name', row['name']) for family, row in zip(families, combination) if len(family) > 1]
        product_name = ' / '.join(names) if names else 'Reference'
        for message in assembled['errors']:
            if message not in result['errors']:
                result['errors'].append(product_name + ': ' + message)
        for site in scan_type_ii(assembled['sequence'], assembled['circular']):
            if site['enzyme'] in avoid:
                message = f"{product_name}: {site['enzyme']} site at base {site['start'] + 1}."
                if message not in result['errors']:
                    result['errors'].append(message)
        products.append({key: assembled[key] for key in ('sequence', 'length', 'circular', 'features', 'gc')} | {'name': product_name})
    if total_bases > 2000000:
        result['errors'].append('Variant products exceed 2 million assembled bases. Split the design into smaller batches.')
    result['assemblies'] = products
    result['valid'] = not result['errors']
    return result
