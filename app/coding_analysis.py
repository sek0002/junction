"""Genetic-code-aware coding consequences on the actual aligned nucleotides."""
from collections import Counter
from itertools import groupby

try:
    from Bio.Data import CodonTable
    from Bio.Seq import Seq
    from Bio.SeqFeature import CompoundLocation, ExactPosition, Location, SimpleLocation
except ImportError:
    # Translation is optional at runtime. Older service environments may not
    # have installed the new requirement yet; the workbench must still load.
    BIO_AVAILABLE = False
else:
    BIO_AVAILABLE = True

REPORT_VERSION = 1
MIN_ORF_AA = 30
MAX_REGIONS = 100
MAX_EFFECTS = 10000
COMPLEMENT = str.maketrans('ACGTRYSWKMBDHVN', 'TGCAYRSWMKVHDBN')


def _qualifier(feature, name, default=None):
    value = (feature.get('qualifiers') or {}).get(name, default)
    return value[0] if isinstance(value, list) and value else value


def _spans(positions):
    values = sorted(set(position for position in positions if position is not None))
    spans = []
    for _, group in groupby(enumerate(values), lambda item: item[1]-item[0]):
        block = [item[1] for item in group]
        spans.append([block[0], block[-1]+1])
    return spans


def _feature_positions(feature, length, circular):
    if '_positions' in feature:
        return feature['_positions'], feature['strand'], True
    if feature.get('raw_location'):
        location = Location.fromstring(feature['raw_location'], length, circular=circular)
    else:
        segments = feature.get('segments') or [feature]
        parts = [SimpleLocation(int(part['start']), int(part['end']), strand=int(part.get('strand', feature.get('strand', 1)))) for part in segments]
        # The app's segment dictionaries are in genomic order. GenBank raw
        # locations above retain their exact biological join/complement order.
        if all(part.strand == -1 for part in parts):
            parts.reverse()
        location = parts[0] if len(parts) == 1 else CompoundLocation(parts)
    if location.strand not in (1, -1) or any(part.ref for part in location.parts):
        raise ValueError('A local CDS on one defined strand is required.')
    if getattr(location,'operator',None)=='order':
        raise ValueError('CDS order locations require manual review before joining coding bases.')
    positions = list(location)
    if not positions or any(position < 0 or position >= length for position in positions):
        raise ValueError('CDS coordinates fall outside the sequence.')
    if len(positions)>length*2:
        raise ValueError('CDS location repeats more than two sequence lengths.')
    first = location.parts[0]
    boundary = first.start if location.strand == 1 else first.end
    return positions, location.strand, isinstance(boundary, ExactPosition)


def _predict_orfs(sequence, circular):
    """Bounded ATG-to-stop ORFs on six frames, explicitly prediction-only."""
    length = len(sequence)
    features, frames = [], []
    for strand, oriented in ((1, sequence), (-1, str(Seq(sequence).reverse_complement()))):
        search = oriented+oriented if circular else oriented
        for frame in range(3):
            start = None
            lengths = []
            for position in range(frame, len(search)-2, 3):
                codon = search[position:position+3]
                if start is None and position < length and codon == 'ATG':
                    start = position
                if start is not None and position+3-start > length:
                    start = None
                if codon not in ('TAA', 'TAG', 'TGA') or start is None:
                    continue
                amino_acids = (position-start)//3
                if amino_acids >= MIN_ORF_AA:
                    positions = [p % length if strand == 1 else length-1-p % length for p in range(start, position+3)]
                    features.append({'type':'CDS', 'label':f'ORF {strand*(frame+1):+d} / {positions[0]+1}',
                                     'strand':strand, '_positions':positions, '_predicted':True})
                    lengths.append(amino_acids)
                start = None
            frames.append({'frame':strand*(frame+1), 'orf_count':len(lengths), 'longest_aa':max(lengths, default=0)})
    features.sort(key=lambda feature:len(feature['_positions']), reverse=True)
    return features, frames


def _alignment_index(ar, aq, rotation, orientation):
    reference_columns, query_columns = {}, {}
    ref_positions, query_positions = [], []
    reference_position = query_position = 0
    query_length = len(aq.replace('-', ''))
    for column, (a, b) in enumerate(zip(ar, aq)):
        ref = reference_position if a != '-' else None
        original = None
        if b != '-':
            oriented = (query_position+rotation) % query_length
            original = query_length-1-oriented if orientation == -1 else oriented
            query_columns[original] = column
            query_position += 1
        if a != '-':
            reference_columns[reference_position] = column
            reference_position += 1
        ref_positions.append(ref)
        query_positions.append(original)
    return reference_columns, query_columns, ref_positions, query_positions


def _coding_columns(positions, axis_columns, axis_sequence, direction, length, circular):
    columns = []
    for index, position in enumerate(positions):
        column = axis_columns[position]
        columns.append(column)
        if index+1 == len(positions):
            continue
        following = positions[index+1]
        expected = (position+direction) % length if circular else position+direction
        if following != expected:
            continue
        next_column = axis_columns[following]
        # Actual display direction also depends on query reverse complementation.
        display_step = 1 if direction > 0 else -1
        between = []
        at = (column+display_step) % len(axis_sequence)
        while at != next_column and axis_sequence[at] == '-':
            between.append(at)
            at = (at+display_step) % len(axis_sequence)
        if at == next_column:
            columns.extend(between)
    return columns


def _protein(sequence, table, complete_start):
    coding = sequence[:len(sequence)//3*3]
    protein = str(Seq(coding).translate(table=table.id)) if coding else ''
    if protein and complete_start and coding[:3] in table.start_codons:
        protein = 'M'+protein[1:]
    return protein


def _frame(position, strand, length):
    if position is None:
        return None
    return strand*((position if strand == 1 else length-1-position) % 3+1)


def _effect_type(reference_aa, query_aa, ref_codon, query_codon, ref_index, query_index, complete_start, table):
    if len(ref_codon) != 3 or len(query_codon) != 3 or set(ref_codon+query_codon)-set('ACGT'):
        return 'uncertain'
    if (query_index-ref_index) % 3:
        return 'frameshift_context'
    if reference_aa != '*' and query_aa == '*':
        return 'stop_gained'
    if reference_aa == '*' and query_aa != '*':
        return 'stop_lost'
    if ref_index < 3 and query_index < 3 and complete_start and ref_codon in table.start_codons and query_codon not in table.start_codons:
        return 'start_lost'
    return 'synonymous' if reference_aa == query_aa else 'missense'


def _analyse_region(match, feature, source, index, original_query, alignment_index):
    ar, aq = match['aligned_reference'], match['aligned_query']
    ref_columns, query_columns, ref_positions, query_positions = alignment_index
    query_orientation = -1 if match.get('orientation') == '-' else 1
    length = len(ar.replace('-', '')) if source == 'reference' else len(original_query)
    positions, strand, complete_start = _feature_positions(feature, length, match.get('circular', True))
    offset = int(_qualifier(feature, 'codon_start', 1))-1
    if offset not in (0, 1, 2):
        raise ValueError('codon_start must be 1, 2 or 3.')
    positions = positions[offset:]
    if not positions:
        raise ValueError('CDS has no complete coding bases.')
    table_id = int(_qualifier(feature, 'transl_table', 1))
    table = CodonTable.unambiguous_dna_by_id.get(table_id)
    if table is None:
        raise ValueError(f'Unsupported translation table {table_id}.')
    effective_strand = strand if source == 'reference' else strand*query_orientation
    axis_columns = ref_columns if source == 'reference' else query_columns
    axis_sequence = ar if source == 'reference' else aq
    # Query positions are original-file coordinates, so orient their column
    # lookup before collecting insertions between consecutive coding bases.
    if source == 'query' and query_orientation == -1:
        axis_positions = [length-1-position for position in positions]
        oriented_columns = {length-1-position:column for position, column in axis_columns.items()}
        columns = _coding_columns(axis_positions, oriented_columns, axis_sequence, effective_strand, length, match.get('circular', True))
    else:
        columns = _coding_columns(positions, axis_columns, axis_sequence, effective_strand, length, match.get('circular', True))
    complement = effective_strand == -1
    reference = ''.join(ar[column].translate(COMPLEMENT) if complement else ar[column] for column in columns)
    query = ''.join(aq[column].translate(COMPLEMENT) if complement else aq[column] for column in columns)
    ref_dna, query_dna = reference.replace('-', ''), query.replace('-', '')
    qualifiers = feature.get('qualifiers') or {}
    warnings = []
    manual = any(key in qualifiers for key in ('transl_except', 'exception')) or bool(set(table.stop_codons)&set(table.forward_table))
    if manual:
        warnings.append('Translation exceptions or context-dependent stop codons require manual review.')
    if 'pseudo' in qualifiers or 'pseudogene' in qualifiers:
        warnings.append('Annotated pseudogene. Translation is a sequence comparison only.')
    if len(ref_dna) % 3 or len(query_dna) % 3:
        warnings.append('Incomplete terminal codon.')
    ambiguous = bool(set(ref_dna+query_dna)-set('ACGT'))
    if ambiguous:
        warnings.append('Ambiguous coding bases. Some amino-acid consequences are uncertain.')
    # Dual-coding tables can trigger context-dependent translation warnings.
    ref_protein = '' if manual else _protein(ref_dna, table, complete_start and offset == 0)
    query_protein = '' if manual else _protein(query_dna, table, complete_start and offset == 0)
    supplied_translation = _qualifier(feature,'translation')
    annotation_matches = None
    if supplied_translation and not manual:
        computed = ref_protein if source=='reference' else query_protein
        annotation_matches = ''.join(str(supplied_translation).split()).rstrip('*') == computed.rstrip('*')
        if not annotation_matches:
            warnings.append('The annotated translation differs from the DNA translation in this frame.')
    reference_stops, query_stops = ref_protein[:-1].count('*'), query_protein[:-1].count('*')
    if query_stops:
        warnings.append(f'Query translation contains {query_stops} internal stop codon(s).')
    first_ref = next((ref_positions[c] for c in columns if ref_positions[c] is not None), None)
    first_query = next((query_positions[c] for c in columns if query_positions[c] is not None), None)
    row = {'id':index, 'name':str(feature.get('label') or _qualifier(feature,'gene') or _qualifier(feature,'product') or 'CDS'),
           'basis':'predicted_orf' if feature.get('_predicted') else 'annotated_cds', 'source':source,
           'reference_frame':_frame(first_ref,effective_strand,len(ar.replace('-',''))),
           'query_frame':_frame(first_query,effective_strand*query_orientation,len(original_query)),
           'strand':effective_strand, 'codon_start':offset+1, 'translation_table':table_id,
           'reference_spans':_spans(ref_positions[c] for c in columns), 'query_spans':_spans(query_positions[c] for c in columns),
           'reference_protein':ref_protein, 'query_protein':query_protein,
           'reference_aa_length':len(ref_protein.rstrip('*')), 'query_aa_length':len(query_protein.rstrip('*')),
           'protein_changed':None if manual or ambiguous else ref_protein != query_protein,
           'annotation_translation_matches':annotation_matches, 'reference_internal_stops':reference_stops,
           'query_internal_stops':query_stops, 'warnings':warnings, 'effects':[]}
    reference_index = query_index = 0
    i = 0
    while i < len(columns):
        a, b = reference[i], query[i]
        if a == b:
            reference_index += a != '-'
            query_index += b != '-'
            i += 1
            continue
        kind = 'insertion' if a == '-' else 'deletion' if b == '-' else 'substitution'
        stop = i+1
        if kind != 'substitution':
            while stop < len(columns) and ((reference[stop] == '-') if kind == 'insertion' else (query[stop] == '-')):
                stop += 1
        ref_codon_start, query_codon_start = reference_index//3*3, query_index//3*3
        ref_codon, query_codon = ref_dna[ref_codon_start:ref_codon_start+3], query_dna[query_codon_start:query_codon_start+3]
        ref_aa = ref_protein[reference_index//3:reference_index//3+1] or '?'
        query_aa = query_protein[query_index//3:query_index//3+1] or '?'
        effect_type = 'uncertain' if manual else _effect_type(ref_aa, query_aa, ref_codon, query_codon, reference_index, query_index, complete_start and offset == 0, table)
        if kind != 'substitution' and not manual:
            effect_type = 'frameshift' if (stop-i) % 3 else 'inframe_'+kind
        affected_columns = columns[i:stop]
        row['effects'].append({'type':effect_type, 'nucleotide_type':kind, 'region_id':index, 'region_name':row['name'], 'basis':row['basis'],
            'amino_acid_position':reference_index//3+1, 'query_amino_acid_position':query_index//3+1,
            'reference_codon':ref_codon, 'query_codon':query_codon, 'reference_aa':ref_aa, 'query_aa':query_aa,
            'protein_change':f'{ref_aa}{reference_index//3+1}{query_aa}' if kind == 'substitution' else effect_type.replace('_',' '),
            'reference_spans':_spans(ref_positions[c] for c in affected_columns), 'query_spans':_spans(query_positions[c] for c in affected_columns),
            'alignment_columns':affected_columns, 'frame':row['reference_frame'], 'translation_table':table_id})
        reference_index += sum(base != '-' for base in reference[i:stop])
        query_index += sum(base != '-' for base in query[i:stop])
        i = stop
    row['frameshift'] = any(effect['type']=='frameshift' for effect in row['effects'])
    return row


def annotate_coding(match, query_features=None):
    if not BIO_AVAILABLE:
        match['coding_analysis'] = {
            'version': REPORT_VERSION, 'available': False, 'regions': [],
            'frames': {}, 'predicted': False, 'summary': {},
            'warnings': ['Translation analysis unavailable: Biopython is missing or could not be imported. Install requirements.txt in the service virtual environment, then restart Junction.'],
        }
        return match
    ar, aq = match.get('aligned_reference'), match.get('aligned_query')
    if not isinstance(ar,str) or not isinstance(aq,str) or not ar or len(ar) != len(aq):
        return match
    reference = ar.replace('-', '')
    oriented = aq.replace('-', '')
    rotation = int(match.get('rotation',0)) % len(oriented) if oriented else 0
    unrotated = oriented[-rotation:]+oriented[:-rotation] if rotation else oriented
    original_query = str(Seq(unrotated).reverse_complement()) if match.get('orientation')=='-' else unrotated
    annotations = [(feature,source) for source,features in [('reference',match.get('features') or []),('query',query_features or [])]
                   for feature in features if str(feature.get('type') or '').upper()=='CDS']
    predictions, frames = [], {}
    if not annotations:
        for source, sequence in [('reference',reference),('query',original_query)]:
            features, frame_counts = _predict_orfs(sequence,match.get('circular',True))
            predictions.extend((feature,source) for feature in features)
            frames[source] = frame_counts
    candidates = annotations or predictions
    report = {'version':REPORT_VERSION, 'regions':[], 'frames':frames, 'predicted':not bool(annotations),
              'min_orf_aa':MIN_ORF_AA, 'warnings':[], 'effects_capped':False}
    if len(candidates)>MAX_REGIONS:
        report['warnings'].append(f'Coding-region analysis capped at {MAX_REGIONS} regions.')
    alignment_index = _alignment_index(ar,aq,rotation,-1 if match.get('orientation')=='-' else 1)
    seen, total_effects = set(), 0
    for feature, source in candidates[:MAX_REGIONS]:
        try:
            row = _analyse_region(match,feature,source,len(report['regions']),original_query,alignment_index)
        except (ValueError,TypeError,KeyError,IndexError) as error:
            report['warnings'].append(str(feature.get('label') or 'CDS')+': '+str(error))
            continue
        identity = (tuple(map(tuple,row['reference_spans'])),row['strand'],row['codon_start'],row['translation_table'],row['reference_protein'],row['query_protein'])
        if identity in seen:
            continue
        seen.add(identity)
        available = MAX_EFFECTS-total_effects
        if len(row['effects'])>available:
            row['effects']=row['effects'][:available]
            report['effects_capped']=True
        total_effects += len(row['effects'])
        report['regions'].append(row)
    effects = [effect for row in report['regions'] for effect in row['effects']]
    counts = Counter(effect['type'] for effect in effects)
    report['summary'] = dict(counts)
    report['summary'].update(regions=len(report['regions']),protein_changed=sum(row['protein_changed'] is True for row in report['regions']))
    # Associate coding consequences with the same nucleotide-difference groups
    # reconstructed by the interactive viewer, including reverse-strand CDSs.
    by_column = {}
    change_index, previous = -1, None
    for column,(a,b) in enumerate(zip(ar,aq)):
        kind = 'insertion' if a=='-' else 'deletion' if b=='-' else 'substitution' if a!=b else None
        if kind and kind != previous:
            change_index += 1
        if kind:
            by_column[column]=change_index
        previous=kind
    changes = match.get('changes') or []
    for change in changes:
        change['coding_effects']=[]
    assessed_substitutions = set()
    for effect in effects:
        columns = effect.pop('alignment_columns')
        if effect['nucleotide_type']=='substitution':
            assessed_substitutions.update(columns)
        for index in {by_column[column] for column in columns if column in by_column}:
            if index < len(changes):
                changes[index]['coding_effects'].append(effect)
    report['unassigned_substitution_bp'] = sum(a!=b and a!='-' and b!='-' and i not in assessed_substitutions for i,(a,b) in enumerate(zip(ar,aq)))
    match['coding_analysis']=report
    return match


def refresh_coding_results(result):
    if not result:
        return result
    for record in result.get('records') or [result]:
        if not record.get('matches') and record.get('query_sequence') and (not record.get('query_coding_analysis') or (BIO_AVAILABLE and record['query_coding_analysis'].get('available') is False)):
            record['query_coding_analysis']=query_translation_report(record['query_sequence'],record.get('query_features'),record.get('query_circular',False))
        for match in record.get('matches') or []:
            if match.get('coding_analysis',{}).get('version') != REPORT_VERSION or (BIO_AVAILABLE and match.get('coding_analysis',{}).get('available') is False):
                annotate_coding(match,record.get('query_features'))
    return result


def query_translation_report(sequence, features=None, circular=False):
    """Make frames accessible even when no database alignment was found."""
    match={'aligned_reference':sequence,'aligned_query':sequence,'orientation':'+','rotation':0,'circular':circular,'features':[],'changes':[]}
    report=annotate_coding(match,features)['coding_analysis']
    report['query_only']=True
    report['frames'].pop('reference',None)
    for region in report['regions']:
        region.update(query_only=True,source='query',reference_frame=None,reference_spans=[],reference_protein='',reference_aa_length=None,protein_changed=None)
    return report
