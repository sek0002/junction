"""Export-only 3-prime synthesis padding; never alter retained target DNA."""
from hashlib import sha256
import random
import re

from .design_engine import TYPE_II, scan_type_ii
from .sequence_engine import reverse_complement

MIN_LENGTH = 300
MOTIFS = tuple(sorted({word for motif in TYPE_II.values()
                       for word in (motif, reverse_complement(motif))}))
_SITE = re.compile('(?=(' + '|'.join(MOTIFS) + '))')
_RUN = re.compile(r'(?=(A{5}|C{5}|G{5}|T{5}))')
CONTEXT = max(map(len, MOTIFS)) - 1


def padding_is_clean(sequence, padding):
    """Check only new sites/runs, including those straddling the junction."""
    context = sequence[-CONTEXT:]
    combined = context + padding
    boundary = len(context)
    return not any(match.start() + len(match.group(1)) > boundary
                   for pattern in (_SITE, _RUN) for match in pattern.finditer(combined))


def gc_windows_ok(padding):
    # Short tails use the nearest possible integer to 50% GC overall.
    # Longer tails also keep every 50-base padding window at 40–60% GC.
    if len(padding) < 50:
        return True
    count = sum(base in 'GC' for base in padding[:50])
    if not 20 <= count <= 30:
        return False
    for left, right in zip(padding, padding[50:]):
        count += (right in 'GC') - (left in 'GC')
        if not 20 <= count <= 30:
            return False
    return True


def synthesis_padding(sequence):
    """Return a stable pseudorandom tail so preview and every export agree."""
    if not sequence or re.fullmatch('[ACGT]+', sequence) is None:
        raise ValueError('Synthesis padding requires a nonempty A/C/G/T fragment.')
    length = max(0, MIN_LENGTH - len(sequence))
    if not length:
        return ''
    rng = random.Random(sha256(('junction-twist-v1:' + sequence).encode()).digest())
    for _ in range(2048):
        gc_count = rng.choice((length // 2, (length + 1) // 2))
        bases = [rng.choice('GC') for _ in range(gc_count)]
        bases += [rng.choice('AT') for _ in range(length - gc_count)]
        rng.shuffle(bases)
        padding = ''.join(bases)
        if padding_is_clean(sequence, padding) and gc_windows_ok(padding):
            return padding
    raise ValueError('Could not generate clean 3′ synthesis padding. Check the fragment end.')


def apply_synthesis_padding(result):
    """Decorate full donor records after assembly has already been validated."""
    updates = []
    for row in result['generated']:
        original = row.get('unpadded_full_sequence', row['full_sequence'])
        padding = synthesis_padding(original)
        full = original + padding
        updates.append(dict(unpadded_full_sequence=original, unpadded_length=len(original),
                            synthesis_padding=padding, padding_length=len(padding),
                            full_sequence=full, sequence=full, length=len(full),
                            gc=100 * sum(base in 'GC' for base in full) / len(full),
                            sites=scan_type_ii(full)))
    for row, update in zip(result['generated'], updates):
        row.update(update)
    result['make_twist_compatible'] = True
    return result
