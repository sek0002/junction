"""Name, fusion-label and exact DNA searches, independent of assembly orientation."""
from difflib import SequenceMatcher
import re

from .sequence_engine import reverse_complement


def match_fragment(fragment, query, variants):
    query = query.strip().casefold()
    if not query:
        return {'search_score': 1, 'search_match': None}
    name = fragment['name'].casefold()
    candidates = []
    if query in name:
        candidates.append((1 if query == name else .97, {'kind': 'name'}))
    elif len(query) >= 4:
        score = SequenceMatcher(None, query, name).ratio()
        if score >= .65:
            candidates.append((min(score, .96), {'kind': 'name'}))
    sequence = re.sub(r'\s+', '', query).upper()
    if re.fullmatch('[ACGT]{4,}', sequence):
        # Fusion labels outrank incidental four-base words within a long donor.
        if len(sequence) == 4:
            forward = variants[0] if variants else {}
            for side in ('left', 'right'):
                label = forward.get(side + '_overhang')
                if not label:
                    continue
                for reverse, word in ((False, sequence), (True, reverse_complement(sequence))):
                    if label == word:
                        candidates.append((.99 if not reverse else .985,
                            dict(kind='overhang', reverse_complement=reverse,
                                 side=side, matched_sequence=label)))
        for field in ('sequence', 'construct_sequence'):
            original = (fragment.get(field) or '').upper()
            for reverse, word in ((False, sequence), (True, reverse_complement(sequence))):
                start = original.find(word)
                if start >= 0:
                    candidates.append((.95 if not reverse else .94,
                        dict(kind='sequence', reverse_complement=reverse,
                             start=start, end=start+len(word), source=field)))
    if not candidates:
        return None
    score, match = max(candidates, key=lambda item: item[0])
    return {'search_score': score, 'search_match': match}
