"""Named row variants share one fixed, native-overlap fragment design."""
from copy import deepcopy

from .design_engine import donor_sequence, insert_dna, scan_type_ii
from .design_orientation import annotate_orientations
from .sequence_engine import ENZYMES, active_enzymes, assemble, digest_fragment


def dynamic_regions(entries):
    return {f"{entry['id']}:{section['start']}:{section['end']}": section
            for entry in entries if entry['kind'] == 'placeholder'
            for section in entry.get('sections', []) if section.get('mode') == 'dynamic'}


def check_rows(entries, rows, enzyme, avoid_sites=()):
    regions = dynamic_regions(entries)
    errors, statuses, seen = [], [], set()
    blocked = set(active_enzymes(enzyme)) | set(avoid_sites)
    if not regions:
        errors.append('Define a Dynamic region before using table rows.')
    if not rows:
        errors.append('Add or paste at least one named table row.')
    for index, row in enumerate(rows, 1):
        row_errors = []
        name = row['name'].strip()
        if not name:
            row_errors.append('Enter a row name.')
        if name.casefold() in seen:
            row_errors.append('Row names must be unique.')
        seen.add(name.casefold())
        if set(row['dynamic_inputs']) != set(regions):
            row_errors.append('Fill each current Dynamic region; remove cells for deleted regions.')
        for key, sequence in row['dynamic_inputs'].items():
            title = regions.get(key, {}).get('name', key)
            if sum(line.lstrip().startswith('>') for line in sequence.splitlines()) > 1:
                row_errors.append(f'{title}: use one sequence per cell.')
            sequence = insert_dna(sequence)
            if not sequence or set(sequence) - set('ACGT'):
                row_errors.append(f'{title}: enter A/C/G/T DNA.')
            for site in scan_type_ii(sequence):
                if site['enzyme'] in blocked:
                    row_errors.append(f"{title}: {site['enzyme']} site at input base {site['start'] + 1}.")
        errors.extend(f"Row {index} ({name or 'unnamed'}): {message}" for message in row_errors)
        statuses.append(dict(name=name, valid=not row_errors, errors=row_errors))
    return errors, statuses


def table_design(base, rows, enzyme, backbone=None, slot_id=None, avoid_sites=()):
    result = deepcopy(base)
    row_errors, statuses = check_rows(base['entries'], rows, enzyme, avoid_sites)
    result.update(table_mode=True, table_rows=statuses, constant_overhangs=[], assemblies=[], assembly=None)
    if row_errors or not base['valid']:
        result['errors'] = list(dict.fromkeys(base['errors'] + row_errors))
        result['valid'] = False
        return result
    result['warnings'] = [message for message in base['warnings'] if message.startswith('Fixed overhang ')]
    blocked = set(active_enzymes(enzyme)) | set(avoid_sites)
    original = base['generated']
    constants = [deepcopy(row) | {'row_name': 'Shared'} for row in original if not row['dynamic_regions']]
    generated, products, all_errors = list(constants), [], []
    baseline = {row['id']: row for row in original}
    total_bases = 0
    for number, row in enumerate(rows, 1):
        by_id = {item['id']: item for item in constants}
        row_errors = []
        for fragment in original:
            if not fragment['dynamic_regions']:
                continue
            target = fragment['target']
            for region in sorted(fragment['dynamic_regions'], key=lambda region: region['start'], reverse=True):
                offset = region['start'] - fragment['target_start']
                target = target[:offset] + insert_dna(row['dynamic_inputs'][region['key']]) + target[offset + region['end'] - region['start']:]
            try:
                sequence = donor_sequence(fragment['left_overhang'], target, fragment['right_overhang'],
                                          fragment['left_adapter_enzyme'], blocked, fragment['right_adapter_enzyme'])
            except ValueError as exc:
                row_errors.append(f"{fragment['name']}: {exc}")
                continue
            candidate = deepcopy(fragment) | dict(id=fragment['id'] + f'_row{number}',
                name=row['name'].strip() + '__' + fragment['name'], row_name=row['name'].strip(),
                variant_name=row['name'].strip(), target=target, sequence=sequence,
                length=len(sequence), gc=100 * (sequence.count('G') + sequence.count('C')) / len(sequence),
                sites=scan_type_ii(sequence))
            parsed = digest_fragment(sequence, enzyme)
            if not parsed['valid'] or any(parsed[key] != fragment[key] for key in ('left_overhang', 'right_overhang')):
                row_errors.append(fragment['name'] + ': constant overhangs changed.')
            by_id[fragment['id']] = candidate
            generated.append(candidate)
        if row_errors:
            all_errors.extend(f"{row['name']}: {message}" for message in row_errors)
            statuses[number-1].update(valid=False, errors=row_errors)
            continue
        donors, emitted = [], set()
        for node in base['entries']:
            if node['kind'] == 'fragment':
                donors.append(dict(id=node.get('fragment_id'), name=node['name'], sequence=node['oriented_sequence']))
            elif node['run'] not in emitted:
                emitted.add(node['run'])
                donors.extend(by_id[item['id']] for item in original if item['run'] == node['run'])
        assembled = annotate_orientations(assemble(donors, enzyme, backbone, slot_id, circular=None), base['entries'])
        row_errors.extend(assembled['errors'])
        result['warnings'].extend(f"{row['name']}: {message}" for message in assembled['warnings'])
        for site in scan_type_ii(assembled['sequence'], assembled['circular']):
            if site['enzyme'] in blocked:
                row_errors.append(f"{site['enzyme']} site at assembled base {site['start'] + 1}.")
        total_bases += assembled['length']
        if total_bases > 2000000:
            all_errors.append('Table products exceed two million assembled bases. Export smaller batches.')
            break
        all_errors.extend(f"{row['name']}: {message}" for message in row_errors)
        statuses[number-1].update(valid=not row_errors, errors=row_errors)
        products.append({key: assembled[key] for key in ('sequence', 'length', 'circular', 'features', 'gc')} |
                        dict(name=row['name'].strip(), valid=not row_errors))
        if len(products) == 1:
            result['assembly'] = assembled
            result['assembly_sites'] = scan_type_ii(assembled['sequence'], assembled['circular'])
    result['generated'] = generated
    result['assemblies'] = products
    result['errors'] = list(dict.fromkeys(all_errors))
    result['valid'] = not all_errors and len(products) == len(rows)
    if result['valid']:
        for item in baseline.values():
            if item['dynamic_regions']:
                for region in item['dynamic_regions']:
                    result['constant_overhangs'].append(dict(key=region['key'], name=region['name'],
                        left_overhang=item['left_overhang'], right_overhang=item['right_overhang'], valid=True))
    return result


def sequence_metadata(result, include_re_sites=True):
    """Keep payload, retained insert and synthesis sequence explicit in exports."""
    for row in result['generated']:
        canonical = row['sequence']
        left, right = row['left_overhang'], row['right_overhang']
        prefix = canonical[:17] if include_re_sites else left
        suffix = canonical[-17:] if include_re_sites else right
        full = prefix + row['target'] + suffix
        row.update(target_sequence=row['target'], full_sequence=full, sequence=full,
                   retained_sequence=left + row['target'] + right,
                   five_prime_sequence=prefix, three_prime_sequence=suffix,
                   left_re_site=ENZYMES[row['left_adapter_enzyme']][0] if include_re_sites else '',
                   right_re_site=ENZYMES[row['right_adapter_enzyme']][1] if include_re_sites else '',
                   include_re_sites=include_re_sites, length=len(full), target_length=len(row['target']),
                   gc=100 * (full.count('G') + full.count('C')) / len(full), sites=scan_type_ii(full),
                   row_name=row.get('row_name', row.get('variant_name', 'Reference')))
    return result
