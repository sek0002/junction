"""CDS detection and reversible mapping between Golden Gate donors and mRNA CDS.

Assembly coordinates are zero-based/end-exclusive internally; the API uses
one-based inclusive CDS coordinates on the assembled forward strand.
"""
from __future__ import annotations

try:
    from .sequence_engine import assemble, normalize, reverse_complement
except ImportError:  # Scientific worker is launched as a standalone script.
    from sequence_engine import assemble, normalize, reverse_complement

STOPS = {'TAA', 'TAG', 'TGA'}


def detect_cds(sequence, frame='auto'):
    """Rank complete ATG-to-stop ORFs, then explicitly labelled partial ORFs."""
    sequence = normalize(sequence)
    frames = (1, 2, 3, -1, -2, -3) if frame == 'auto' else (int(frame),)
    candidates = []
    for reading_frame in frames:
        if reading_frame not in (1, 2, 3, -1, -2, -3):
            raise ValueError('Choose Auto or a reading frame from +1 to +3 / −1 to −3.')
        dna = sequence if reading_frame > 0 else reverse_complement(sequence)
        offset = abs(reading_frame)-1
        segment, starts = offset, []
        def add(start, end, complete):
            if end-start < 3:
                return
            a, b = (start, end) if reading_frame > 0 else (len(dna)-end, len(dna)-start)
            candidates.append({'start': a+1, 'end': b, 'frame': reading_frame,
                'length': end-start, 'complete': complete,
                'start_codon': dna[start:start+3] == 'ATG',
                'stop_codon': dna[end-3:end] in STOPS})
        for pos in range(offset, len(dna)-2, 3):
            codon = dna[pos:pos+3]
            if codon == 'ATG' and not starts:
                starts.append(pos)
            if codon in STOPS:
                add(starts[0] if starts else segment, pos+3, bool(starts))
                segment, starts = pos+3, []
        end = offset + ((len(dna)-offset)//3)*3
        add(starts[0] if starts else segment, end, False)
    candidates.sort(key=lambda c: (not c['complete'], -c['length'], c['frame'] < 0, abs(c['frame']), c['start']))
    return candidates[:60]


def prepare_assembly(snapshot):
    fragments = snapshot['fragments']
    if not fragments or len(fragments) > 32:
        raise ValueError('Choose between 1 and 32 donor fragments.')
    if sum(len(f['sequence']) for f in fragments) > 100000:
        raise ValueError('Use at most 100,000 nt of donor DNA per assembly.')
    result = assemble(fragments, snapshot['enzyme'], circular=False)
    if not result['valid']:
        raise ValueError('Assembly is invalid: '+' '.join(result['errors']))
    dna = result['sequence']
    frame = snapshot.get('frame', 'auto')
    candidates = detect_cds(dna, frame)
    start, end = snapshot.get('cds_start'), snapshot.get('cds_end')
    if (start is None) != (end is None):
        raise ValueError('Specify both CDS start and end, or leave both automatic.')
    if start is None:
        if not candidates:
            raise ValueError('No coding region was found. Specify CDS coordinates and a frame.')
        selected = candidates[0]
        start, end, frame = selected['start'], selected['end'], selected['frame']
    else:
        if not 1 <= start <= end <= len(dna) or (end-start+1) % 3:
            raise ValueError('CDS bounds must lie within the assembly and contain complete codons.')
        if frame == 'auto':
            frame = (start-1) % 3+1
        frame = int(frame)
        offset = start-1 if frame > 0 else len(dna)-end
        if offset % 3 != abs(frame)-1:
            raise ValueError('CDS coordinates do not match the specified reading frame.')
    cds = dna[start-1:end]
    if frame < 0:
        cds = reverse_complement(cds)
    if any(cds[i:i+3] in STOPS for i in range(0, len(cds)-3, 3)):
        raise ValueError('The selected CDS contains an internal stop codon; choose another ORF or edit its bounds.')
    # Every fusion label, including both terminal labels, is immutable. Expand
    # an overlapping label to whole CDS codons to keep optimiser locations aligned.
    spans = [(f['start'], f['start']+4) for f in result['features'] if f.get('source') == 'fragment']
    spans.append((len(dna)-4, len(dna)))
    protected = []
    for a, b in spans:
        a, b = max(a, start-1), min(b, end)
        if a >= b:
            continue
        a, b = (a-(start-1), b-(start-1)) if frame > 0 else (end-b, end-a)
        a, b = (a//3)*3, min(len(cds), ((b+2)//3)*3)
        protected.append([a+1, b])
    protected.sort()
    merged = []
    for a, b in protected:
        if merged and a <= merged[-1][1]+1:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    warning = []
    if not cds.startswith('ATG') or cds[-3:] not in STOPS:
        warning.append('Partial CDS: selected region lacks an ATG start or terminal stop codon. Confirm the frame and bounds.')
    complete = [c for c in candidates if c['complete']]
    if snapshot.get('cds_start') is None and len(complete) > 1:
        warning.append('Multiple complete ORFs were detected; the longest was selected. Confirm the CDS before optimisation.')
    canonical = {**snapshot, 'frame': frame, 'cds_start': start, 'cds_end': end}
    return {'assembly': canonical, 'sequence': cds, 'assembled_sequence': dna,
        'frame': frame, 'cds_start': start, 'cds_end': end, 'candidates': candidates,
        'preserve_regions': merged, 'warnings': result['warnings']+warning,
        'fragment_map': [{'name': f['label'], 'start': f['start']+1, 'end': f['end']+4,
            'orientation': f['strand']} for f in result['features'] if f.get('source') == 'fragment'],
        '_result': result}


def project_fragments(snapshot, cds):
    """Replace CDS only, return donors in their original physical orientation."""
    prepared = prepare_assembly(snapshot)
    original = prepared['sequence']
    if len(cds) != len(original) or set(cds)-set('ACGT'):
        raise ValueError('Optimised CDS length or DNA alphabet changed.')
    for start, end in prepared['preserve_regions']:
        if original[start-1:end] != cds[start-1:end]:
            raise ValueError('Optimisation changed a protected junction codon.')
    a, b = prepared['cds_start']-1, prepared['cds_end']
    inserted = cds if prepared['frame'] > 0 else reverse_complement(cds)
    dna = prepared['assembled_sequence'][:a]+inserted+prepared['assembled_sequence'][b:]
    result = prepared['_result']
    features = {f['fragment_index']: f for f in result['features'] if f.get('source') == 'fragment'}
    exported = []
    for index, (source, edge) in enumerate(zip(snapshot['fragments'], result['fragments'])):
        feature = features[index]
        oriented = edge['input_sequence']
        updated = oriented[:edge['target_start']]+dna[feature['start']+4:feature['end']]+oriented[edge['target_end']:]
        physical = updated if edge['orientation'] > 0 else reverse_complement(updated)
        exported.append({'id': source.get('id'), 'name': source['name'], 'sequence': physical,
            'orientation': edge['orientation'], 'left_overhang': edge['left_overhang'],
            'right_overhang': edge['right_overhang'], 'changed_nt': sum(x != y for x, y in zip(source['sequence'], physical))})
    rebuilt = assemble(exported, snapshot['enzyme'], circular=False)
    if not rebuilt['valid'] or rebuilt['sequence'] != dna:
        raise ValueError('Optimised donor reassembly failed validation: '+' '.join(rebuilt['errors']))
    return {'sequence': dna, 'fragments': exported, 'junctions_preserved': True,
        'frame': prepared['frame'], 'cds_start': a+1, 'cds_end': b}
