"""Transparent comparison percentages with optional A/T-run deletion exclusion."""
import re

MIN_AT_DELETION_BP = 20
AT_DELETION_POLICY = 'Pure A or pure T deletions of at least 20 bases'


def adjusted_percentages(aligned_reference, aligned_query, circular=False):
    reference = aligned_reference.replace('-', '')
    positions = []
    reference_position = 0
    for base in aligned_reference:
        positions.append(reference_position)
        reference_position += base != '-'
    pure_deletions = []
    for gap in re.finditer(r'-+', aligned_query):
        deleted = aligned_reference[gap.start():gap.end()]
        if deleted and set(deleted) in ({'A'}, {'T'}):
            start = positions[gap.start()]
            pure_deletions.append((gap.start(), gap.end(), start, start + len(deleted), deleted[0]))
    excluded = {item[:4] for item in pure_deletions if item[1] - item[0] >= MIN_AT_DELETION_BP}
    # A deleted run can straddle the origin of a circular reference.
    if circular and len(pure_deletions) > 1:
        first, last = pure_deletions[0], pure_deletions[-1]
        if (first[0] == 0 and last[1] == len(aligned_query) and first[4] == last[4]
                and first[1] - first[0] + last[1] - last[0] >= MIN_AT_DELETION_BP):
            excluded.update((first[:4], last[:4]))
    excluded_spans = [[item[2], item[3]] for item in sorted(excluded)]

    excluded = sum(end - start for start, end in excluded_spans)
    matches = sum(a == b and a != '-' for a, b in zip(aligned_reference, aligned_query))
    paired = sum(a != '-' and b != '-' for a, b in zip(aligned_reference, aligned_query))
    query_length = len(aligned_query.replace('-', ''))
    columns = len(aligned_reference) - excluded
    retained_reference = len(reference) - excluded
    return {
        'adjusted_identity': matches / columns if columns else 0.,
        'adjusted_reference_coverage': paired / retained_reference if retained_reference else 0.,
        'adjusted_query_coverage': paired / query_length if query_length else 0.,
        'excluded_at_deletion_bp': excluded,
        'excluded_at_deletion_events': len(excluded_spans),
        'excluded_at_deletion_spans': excluded_spans,
        'at_deletion_policy': AT_DELETION_POLICY,
    }


def annotate_percentages(match, aligned_reference, aligned_query, circular=False):
    match.update(adjusted_percentages(aligned_reference, aligned_query, circular))
    excluded = {tuple(span) for span in match['excluded_at_deletion_spans']}
    for change in match.get('changes') or []:
        change['excluded_from_adjusted_percentages'] = (
            change.get('type') == 'deletion'
            and (change.get('reference_start'), change.get('reference_end')) in excluded
        )
    return match


def match_rank(match):
    return (match.get('exact', False), match.get('adjusted_identity', match.get('identity', 0)),
            match.get('identity', 0), match.get('score', 0))


def _fragment_alignment(record, hit):
    """Recover old saved fragment alignments from their observed bases and edits."""
    query = record.get('query_sequence', '')
    if not query or not hit.get('query_spans'):
        return None
    observed = ''.join(query[start:end] for start, end in hit['query_spans'])
    reference_parts, query_parts = [], []
    position = 0
    for change in hit.get('changes') or []:
        start, end = change.get('query_start'), change.get('query_end')
        if not isinstance(start, int) or not isinstance(end, int) or not position <= start <= end <= len(observed):
            return None
        if observed[start:end] != change.get('query_bases', ''):
            return None
        reference_parts.extend([observed[position:start], change.get('reference_bases', '') or '-' * (end-start)])
        query_parts.extend([observed[position:start], change.get('query_bases', '') or '-' * len(change.get('reference_bases', ''))])
        position = end
    reference_parts.append(observed[position:])
    query_parts.append(observed[position:])
    ar, aq = ''.join(reference_parts), ''.join(query_parts)
    if len(ar) != len(aq) or len(ar.replace('-', '')) != hit.get('reference_length'):
        return None
    return ar, aq


def refresh_comparison_percentages(result):
    """Upgrade saved result views without modifying the original saved sequences."""
    if not result:
        return result
    for record in result.get('records') or [result]:
        matches = record.get('matches') or []
        for match in matches:
            ar, aq = match.get('aligned_reference'), match.get('aligned_query')
            if isinstance(ar, str) and isinstance(aq, str) and len(ar) == len(aq):
                annotate_percentages(match, ar, aq, match.get('circular', True))
        matches.sort(key=match_rank, reverse=True)
        for hit in record.get('fragment_matches') or []:
            alignment = _fragment_alignment(record, hit)
            if alignment:
                annotate_percentages(hit, *alignment)
    return result
