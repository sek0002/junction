"""Resolve named CDS exclusions and verify the finished, linear coding sequence."""
from functools import lru_cache
import re


@lru_cache(maxsize=1)
def enzyme_catalog():
    from Bio.Restriction.Restriction_Dictionary import rest_dict
    return {name.casefold(): (name, entry['site']) for name, entry in rest_dict.items()}


def supported_names():
    return sorted(name for name, motif in enzyme_catalog().values()
                  if re.fullmatch('[ACGTRYSWKMBDHVN]+', motif))


def canonical_names(names):
    if not names:
        return []
    catalog = enzyme_catalog()
    resolved = []
    for name in names:
        entry = catalog.get(name.strip().casefold())
        if entry is None:
            raise ValueError(f'Unknown restriction enzyme "{name}". Check the enzyme name.')
        canonical, motif = entry
        if not re.fullmatch('[ACGTRYSWKMBDHVN]+', motif):
            raise ValueError(f'{canonical} has a recognition pattern unsupported by the optimiser.')
        if canonical not in resolved:
            resolved.append(canonical)
    return resolved


@lru_cache(maxsize=256)
def recognition_pattern(name):
    from Bio.Data.IUPACData import ambiguous_dna_values
    from Bio.Seq import reverse_complement
    motif = enzyme_catalog()[name.casefold()][1]
    strands = dict.fromkeys((motif, reverse_complement(motif)))
    return re.compile('|'.join(''.join('[' + ambiguous_dna_values[base] + ']' for base in strand)
                               for strand in strands))


def check_cds_exclusions(cds, parameters):
    names = list(parameters['avoid_restriction_sites'])
    if parameters['avoid_manufacture_restriction_sites']:
        from mrnarchitect.optimize.models import MANUFACTURE_RESTRICTION_SITES
        names.extend(site.name for site in MANUFACTURE_RESTRICTION_SITES)
    for name in canonical_names(names):
        hit = recognition_pattern(name).search(cds)
        if hit:
            raise ValueError(f'Excluded {name} recognition site remains at CDS bases '
                             f'{hit.start()+1}–{hit.end()}.')
