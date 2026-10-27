"""Exact-sequence Golden Gate validation and assembly.

Coordinates are zero-based, end-exclusive. Fusion labels are always reported
on the submitted 5'-to-3' strand; adjacent labels must therefore be identical,
not reverse complements. Donor orientation is resolved before comparing labels;
reversed donors contribute the reverse complement of the full retained payload.
No bases are redesigned or silently removed from a payload. This module has no third-party dependencies.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


ENZYMES = {
    "BsaI": ("GGTCTC", "GAGACC"),
    "BsmBI": ("CGTCTC", "GAGACG"),
    "BbsI": ("GAAGAC", "GTCTTC"),
    "HindIII": ("AAGCTT", "AAGCTT"),
}
DUAL_ENZYME = "BsmBI + BsaI"
_COMPLEMENT = str.maketrans("ACGT", "TGCA")


def normalize(sequence: str) -> str:
    """Uppercase DNA and remove whitespace, preserving all other characters."""
    return re.sub(r"\s+", "", str(sequence or "")).upper()


def reverse_complement(sequence: str) -> str:
    return normalize(sequence).translate(_COMPLEMENT)[::-1]


def _enzyme(enzyme: str) -> str:
    key = str(enzyme or "").lower().replace("-", "").replace(" ", "")
    aliases = {"bsai": "BsaI", "bsmbi": "BsmBI", "bsmbiv2": "BsmBI", "esp3i": "BsmBI",
               "bsmbi+bsai": DUAL_ENZYME, "bsai+bsmbi": DUAL_ENZYME}
    if key not in aliases:
        raise ValueError("Golden Gate digestion supports BsaI, BsmBI (Esp3I), and BsmBI + BsaI.")
    return aliases[key]


def active_enzymes(enzyme: str) -> tuple[str, ...]:
    selected = _enzyme(enzyme)
    return ("BsmBI", "BsaI") if selected == DUAL_ENZYME else (selected,)


def _dna_errors(sequence: str) -> list[str]:
    if not sequence:
        return ["The DNA sequence is empty."]
    invalid = sorted(set(sequence) - set("ACGT"))
    if invalid:
        return ["DNA must contain only A, C, G, and T; found: " + ", ".join(invalid) + "."]
    return []


def _unique(messages: list[str]) -> list[str]:
    return list(dict.fromkeys(messages))


def restriction_sites(sequence: str, circular: bool = False) -> list[dict[str, Any]]:
    """Find both orientations of four enzymes, including overlapping sites.

    A circular-origin-spanning site has ``end > len(sequence)``. HindIII is
    palindromic and is counted once, with strand +1.
    """
    sequence = normalize(sequence)
    length = len(sequence)
    search = sequence + (sequence[:5] if circular and length >= 6 else "")
    sites = []
    for enzyme, motifs in ENZYMES.items():
        for strand, motif in ((1, motifs[0]), (-1, motifs[1])):
            if strand == -1 and motifs[0] == motifs[1]:
                continue
            for match in re.finditer("(?=" + motif + ")", search):
                start = match.start()
                if start < length and (circular or start + len(motif) <= length):
                    sites.append({"enzyme": enzyme, "motif": motif, "start": start,
                                  "end": start + len(motif), "strand": strand,
                                  "wraps_origin": start + len(motif) > length})
    return sorted(sites, key=lambda item: (item["start"], item["enzyme"], -item["strand"]))


def _selected(sequence: str, enzyme: str, circular: bool = False) -> list[dict[str, Any]]:
    return [site for site in restriction_sites(sequence, circular) if site["enzyme"] in active_enzymes(enzyme)]


def _empty_digest(sequence: str, errors: list[str], sites: list | None = None) -> dict[str, Any]:
    return {"left_overhang": "", "right_overhang": "", "target": "", "sequence": "",
            "input_sequence": sequence, "errors": errors, "warnings": [], "sites": sites or [],
            "valid": False}


def nested_cassettes(sequence: str, target_start: int, target_end: int) -> list[dict[str, Any]]:
    """Find internal outward-facing cassettes, without wrapping a linear donor."""
    sequence=normalize(sequence)
    sites=[site for site in restriction_sites(sequence) if site['enzyme'] in ('BsmBI','BsaI')
        and target_start<=site['start'] and site['end']<=target_end]
    cassettes=[]
    for reverse,forward in zip(sites,sites[1:]):
        if reverse['strand']!=-1 or forward['strand']!=1:
            continue
        start,end=reverse['start']-5,forward['start']+11
        if start<target_start or end>target_end:
            continue
        enzyme=reverse['enzyme'] if reverse['enzyme']==forward['enzyme'] else DUAL_ENZYME
        kind='Dual cut' if enzyme==DUAL_ENZYME else enzyme
        left,right=sequence[start:start+4],sequence[end-4:end]
        cassettes.append({'id':f"nested_{reverse['start']}_{forward['start']}",
            'enzyme':enzyme,'cut_type':kind,'label':f'{kind} · {left} → {right}',
            'left_overhang':left,'right_overhang':right,
            'left_boundary_enzyme':reverse['enzyme'],'right_boundary_enzyme':forward['enzyme'],
            'replacement_start':start,'replacement_end':end,
            'reverse_start':reverse['start'],'forward_start':forward['start']})
    return cassettes


def digest_fragment(sequence: str, enzyme: str) -> dict[str, Any]:
    """Extract an inward-facing donor's four-base fusion labels and payload.

    The first forward and last reverse selected-enzyme recognition sites are
    treated as outer adapters. Material outside them (for example synthesis
    buffers) is discarded. Additional selected-enzyme sites retained in the
    donor are errors; sites only in discarded buffers are warnings.
    """
    enzyme = _enzyme(enzyme)
    sequence = normalize(sequence)
    errors = _dna_errors(sequence)
    all_sites = restriction_sites(sequence)
    sites = [site for site in all_sites if site["enzyme"] in active_enzymes(enzyme)]
    if errors:
        return _empty_digest(sequence, errors, sites)
    forward = [site for site in sites if site["strand"] == 1]
    reverse = [site for site in sites if site["strand"] == -1]
    if not forward or not reverse:
        return _empty_digest(sequence, [f"Donor requires an outer forward {enzyme} site and an outer reverse {enzyme} site."], sites)
    f, r = forward[0]["start"], reverse[-1]["start"]
    left_start, target_start, right_start = f + 7, f + 11, r - 5
    right_end = r - 1
    if left_start < 0 or right_end > len(sequence) or target_start > right_start:
        return _empty_digest(sequence, [f"The outer {enzyme} adapters do not face inward around a complete payload and two four-base overhangs."], sites)
    left, target, right = sequence[left_start:target_start], sequence[target_start:right_start], sequence[right_start:right_end]
    if len(left) != 4 or len(right) != 4:
        return _empty_digest(sequence, ["Incomplete four-base fusion overhang at a donor boundary."], sites)
    retained = left + target + right
    retained_sites = _selected(retained, enzyme)
    for site in retained_sites:
        errors.append(f"Internal {site['enzyme']} site at donor base {left_start + site['start'] + 1} ({site['motif']}); digestion cuts the retained fragment.")
    warnings = []
    for site in sites:
        if site["start"] == f:
            site["role"] = "outer_left"
        elif site["start"] == r:
            site["role"] = "outer_right"
        elif left_start <= site["start"] and site["end"] <= right_end:
            site["role"] = "internal"
        elif site["start"] < r + 6 and site["end"] > f:
            site["role"] = "adapter_boundary"
            errors.append(f"Additional {site['enzyme']} recognition site at donor base {site['start'] + 1} overlaps the retained-fragment/adapter boundary; digestion may disrupt the expected donor ends.")
        else:
            site["role"] = "discarded_flank"
        if site["role"] == "discarded_flank":
            warnings.append(f"Additional {site['enzyme']} site at base {site['start'] + 1} lies in a discarded flank.")
    if not target:
        warnings.append("The donor payload is empty; only fusion labels remain.")
    for label, overhang in (("left", left), ("right", right)):
        if overhang == reverse_complement(overhang):
            warnings.append(f"The {label} overhang {overhang} is palindromic and can self-ligate.")
    return {"left_overhang": left, "right_overhang": right, "target": target,
            "sequence": retained, "input_sequence": sequence, "errors": _unique(errors),
            "warnings": _unique(warnings), "sites": sites, "all_sites": all_sites,
            "left_site_start": f, "right_site_start": r,
            "target_start": target_start, "target_end": right_start,
            "nested_cassettes": nested_cassettes(sequence,target_start,right_start),
            "valid": not errors, "enzyme": enzyme,
            "left_adapter_enzyme":forward[0]['enzyme'], "right_adapter_enzyme":reverse[-1]['enzyme']}



def fragment_orientations(sequence: str, enzyme: str) -> list[dict[str, Any]]:
    """Digest both whole-molecule orientations, keeping physical source coordinates."""
    sequence=normalize(sequence)
    forward=digest_fragment(sequence,enzyme)
    reverse=digest_fragment(reverse_complement(sequence),enzyme)
    source={'source_input_length':len(sequence),
            'source_left_overhang_start':forward.get('left_site_start',-7)+7,
            'source_right_overhang_end':forward.get('right_site_start',1)-1}
    return [digest | source | {'orientation':strand,'reverse_complement':strand==-1}
            for strand,digest in ((1,forward),(-1,reverse))]


def _oriented_chain(options, circular, left=None, right=None):
    """Resolve an ordered chain in O(n): fewest flips, then earliest forward.

    Complete closures take priority in automatic/circular mode. While a build is
    incomplete, retain a compatible prefix and let normal QC flag the open end.
    No match ever equates complementary labels without reversing the payload.
    """
    def solve(close,terminal):
        best=None
        for first in options[0] if options else []:
            if left and first['left_overhang']!=left:continue
            if len(first.get('left_overhang',''))!=4:continue
            initial=(int(first.get('reverse_complement',False)),(int(first.get('reverse_complement',False)),))
            states={first['right_overhang']:(initial,[first])}
            for variants in options[1:]:
                following={}
                for variant in variants:
                    prior=states.get(variant['left_overhang'])
                    if prior is None or len(variant.get('right_overhang',''))!=4:continue
                    cost,path=prior;flip=int(variant.get('reverse_complement',False))
                    candidate=((cost[0]+flip,cost[1]+(flip,)),path+[variant])
                    end=variant['right_overhang']
                    if end not in following or candidate[0]<following[end][0]:following[end]=candidate
                states=following
            for end,candidate in states.items():
                if close and end!=first['left_overhang']:continue
                if terminal and right and end!=right:continue
                if best is None or candidate[0]<best[0]:best=candidate
        return best[1] if best else None
    if circular is not False:
        closed=solve(True,True)
        if closed:return closed
    complete=solve(False,True)
    if complete:return complete
    prefix=solve(False,False)
    return prefix or [variants[0] for variants in options]

def _circular_slice(sequence: str, start: int, end: int) -> str:
    """Slice along the forward strand around a circular molecule."""
    length = len(sequence)
    if not length:
        return ""
    start %= length
    distance = (end - start) % length
    return (sequence + sequence)[start:start + distance]


def _cyclic_overhang(sequence: str, start: int) -> str:
    return "".join(sequence[(start + offset) % len(sequence)] for offset in range(4))


def find_backbone_slots(sequence: str, enzyme: str) -> list[dict[str, Any]]:
    """Find outward reverse→forward cassettes on a circular backbone.

    The labels describe the donor required to replace each cassette. With
    more than two active selected-enzyme sites, each slot reports the other
    cuts that remain in its retained vector.
    """
    enzyme = _enzyme(enzyme)
    sequence = normalize(sequence)
    if _dna_errors(sequence):
        return []
    sites = _selected(sequence, enzyme, circular=True)
    if len(sites) < 2:
        return []
    slots = []
    for index, reverse in enumerate(sites):
        forward = sites[(index + 1) % len(sites)]
        if reverse["strand"] != -1 or forward["strand"] != 1:
            continue
        r, f = reverse["start"], forward["start"]
        left = _cyclic_overhang(sequence, r - 5)
        right = _cyclic_overhang(sequence, f + 7)
        retained = _circular_slice(sequence, f + 7, r - 1)
        errors = []
        if len(retained) < 8:
            errors.append("Cassette cut positions overlap; no complete retained backbone is available.")
        retained_sites = _selected(retained, enzyme)
        if retained_sites:
            errors.append(f"The backbone has {len(sites)} active {enzyme} sites; selecting this cassette leaves {len(retained_sites)} additional cut site(s) in the retained vector.")
        cassette_enzyme = reverse['enzyme'] if reverse['enzyme'] == forward['enzyme'] else DUAL_ENZYME
        cassette_type = 'Dual cut' if cassette_enzyme == DUAL_ENZYME else cassette_enzyme
        slots.append({"id": f"slot_{len(slots) + 1}",
                      "label": f"{cassette_type} cassette {len(slots) + 1}: {left} → {right}",
                      "enzyme": cassette_enzyme, "cut_type": cassette_type,
                      "left_boundary_enzyme": reverse['enzyme'], "right_boundary_enzyme": forward['enzyme'],
                      "reverse_start": r, "forward_start": f,
                      "left_overhang": left, "right_overhang": right,
                      "errors": errors, "warnings": [], "total_sites": len(sites),
                      "retained_site_count": len(retained_sites),
                      "structurally_valid": len(retained) >= 8,
                      "cassette_wraps_origin": f < r})
    return slots


def prepare_backbone(sequence: str, enzyme: str, slot_id: str | None = None) -> dict[str, Any]:
    """Return the retained vector as a right-label→left-label graph edge."""
    enzyme = _enzyme(enzyme)
    sequence = normalize(sequence)
    errors = _dna_errors(sequence)
    sites = _selected(sequence, enzyme, circular=True)
    if errors:
        return _empty_digest(sequence, errors, sites)
    slots = find_backbone_slots(sequence, enzyme)
    if not slots:
        return _empty_digest(sequence, [f"No outward reverse/forward {enzyme} cassette was found on the circular backbone."], sites)
    if slot_id is None and len(slots) > 1:
        result = _empty_digest(sequence, [f"Found {len(slots)} {enzyme} cassettes; select a cassette explicitly. Other selected-enzyme cuts must also be resolved."], sites)
        result["slots"] = slots
        return result
    slot = next((item for item in slots if slot_id is None or item["id"] == str(slot_id)), None)
    if slot is None:
        result = _empty_digest(sequence, [f"Unknown backbone cassette: {slot_id}."], sites)
        result["slots"] = slots
        return result
    f, r = slot["forward_start"], slot["reverse_start"]
    retained = _circular_slice(sequence, f + 7, r - 1)
    if len(retained) < 8:
        return _empty_digest(sequence, slot["errors"] or ["Backbone cut positions overlap."], sites)
    left, right = slot["right_overhang"], slot["left_overhang"]
    target = retained[4:-4]
    return {"left_overhang": left, "right_overhang": right, "target": target,
            "sequence": retained, "input_sequence": sequence, "errors": slot["errors"],
            "warnings": slot["warnings"], "sites": sites, "valid": not slot["errors"],
            "enzyme": enzyme, "slot": slot, "slots": slots,
            "retained_start": (f + 7) % len(sequence),
            "retained_end": (r - 1) % len(sequence)}


def _collision_messages(labels: list[tuple[str, str]]) -> list[str]:
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for label, location in labels:
        if len(label) == 4:
            groups[min(label, reverse_complement(label))].append((label, location))
    errors = []
    for group in groups.values():
        if len(group) > 1:
            descriptions = "; ".join(f"{label} at {location}" for label, location in group)
            errors.append("Overhang collision (identical or reverse-complement fusion labels): " + descriptions + ". This permits competing ligation paths.")
    return errors


def _retained_cassette_info(sequence: str, active_enzyme: str,
                           circular: bool) -> tuple[list[dict[str, Any]], list[str]]:
    """Describe later-round cuts without invalidating this enzyme's assembly.

    An outward reverse→forward pair is a candidate replacement cassette.
    Presence and distinct fusion labels alone do not establish donor
    compatibility, and extra unpaired sites are always reported.
    """
    if _enzyme(active_enzyme) == DUAL_ENZYME:
        return [], []
    enzyme = "BsmBI" if active_enzyme == "BsaI" else "BsaI"
    sites = _selected(sequence, enzyme, circular=circular)
    if not sites:
        return [], []
    cassettes, paired = [], set()
    count = len(sites) if circular and len(sites) > 1 else max(0, len(sites) - 1)
    for index in range(count):
        reverse, forward = sites[index], sites[(index + 1) % len(sites)]
        if reverse["strand"] != -1 or forward["strand"] != 1:
            continue
        r, f = reverse["start"], forward["start"]
        if circular:
            left, right = _cyclic_overhang(sequence, r - 5), _cyclic_overhang(sequence, f + 7)
        else:
            left, right = sequence[max(0, r - 5):max(0, r - 1)], sequence[f + 7:f + 11]
        if len(left) != 4 or len(right) != 4:
            continue
        paired.update({index, (index + 1) % len(sites)})
        cassettes.append({"enzyme": enzyme, "id": f"{enzyme}_cassette_{len(cassettes) + 1}",
                          "label": f"{enzyme} cassette {len(cassettes) + 1}",
                          "reverse_start": r, "forward_start": f,
                          "left_overhang": left, "right_overhang": right,
                          "wraps_origin": circular and f < r,
                          "donor_compatibility_checked": False})
    unpaired = [site for index, site in enumerate(sites) if index not in paired]
    warnings = []
    if cassettes:
        warnings.append(f"Retained {enzyme}: {len(sites)} recognition site(s), including {len(cassettes)} outward-facing replacement cassette(s). A later {enzyme} reaction cuts every retained site; compatible donor(s) are required for every opened cassette. Donor compatibility has not been checked.")
        labels = []
        for index, cassette in enumerate(cassettes, start=1):
            warnings.append(f"{enzyme} cassette {index} fusion labels: {cassette['left_overhang']} / {cassette['right_overhang']}.")
            labels.extend([(cassette["left_overhang"], f"cassette {index} left end"),
                           (cassette["right_overhang"], f"cassette {index} right end")])
        for message in _collision_messages(labels):
            warnings.append(f"Second-round {enzyme} " + message[0].lower() + message[1:])
        for label, location in labels:
            if label == reverse_complement(label):
                warnings.append(f"Second-round {enzyme} {location} uses palindromic overhang {label}, allowing self-ligation.")
    else:
        warnings.append(f"Retained {enzyme}: {len(sites)} recognition site(s), with no complete outward-facing replacement cassette. A later {enzyme} reaction cuts these sites.")
    if unpaired:
        positions = ", ".join(str(site["start"] + 1) for site in unpaired)
        direction = " They face the same direction." if len(unpaired) > 1 and len({site["strand"] for site in unpaired}) == 1 else ""
        warnings.append(f"Additional {enzyme} cut site(s) at base(s) {positions} are outside the detected replacement cassette pairs.{direction} These cuts can fragment the plasmid in a later {enzyme} reaction.")
    return cassettes, _unique(warnings)


def _with_fragment_checks(result):
    """Attribute digest, junction and retained-site errors without changing validity."""
    edges=result['fragments']
    checks=[{'id':edge['id'],'name':edge['name'],'is_backbone':edge['is_backbone'],
        'left_overhang':edge['left_overhang'],'right_overhang':edge['right_overhang'],
        'errors':list(edge['errors']),'warnings':list(edge['warnings']),
        'orientation':edge.get('orientation',1),'reverse_complement':edge.get('reverse_complement',False)} for edge in edges]
    count=len(edges) if result['circular'] else max(0,len(edges)-1)
    for index in range(count):
        next_index=(index+1)%len(edges)
        left,right=edges[index],edges[next_index]
        if not left['right_overhang'] or not right['left_overhang']:
            message=f"Cannot verify {left['name']} → {right['name']}: missing fusion overhang."
        elif left['right_overhang']!=right['left_overhang']:
            message=f"Incompatible junction {left['name']} → {right['name']}: {left['right_overhang']} does not match {right['left_overhang']}."
        else:
            continue
        for affected in {index,next_index}:checks[affected]['errors'].append(message)
    if len(edges)==1 and edges[0]['is_backbone']:
        checks[0]['errors'].append('Select at least one donor fragment for the backbone cassette.')
    labels=[(j['overhang'],f"{j['from']} → {j['to']}") for j in result['junctions'] if j['compatible']]
    if edges and not result['circular']:
        labels=[(edges[0]['left_overhang'],'left terminus')]+labels+[(edges[-1]['right_overhang'],'right terminus')]
    groups=defaultdict(list)
    for label,location in labels:
        if len(label)==4:groups[min(label,reverse_complement(label))].append((label,location))
    for key,group in groups.items():
        if len(group)<2:continue
        message=_collision_messages(group)[0]
        for check in checks:
            if any(len(label)==4 and min(label,reverse_complement(label))==key for label in (check['left_overhang'],check['right_overhang'])):
                check['errors'].append(message)
    length=result['length']
    for site in result['restriction_sites']:
        if site['enzyme'] not in active_enzymes(result['enzyme']):continue
        spans=[(site['start'],min(site['end'],length))]
        if site['end']>length:spans.append((0,site['end']-length))
        for feature in result['features']:
            index=feature.get('fragment_index')
            if index is not None and any(start<feature['end'] and end>feature['start'] for start,end in spans):
                checks[index]['errors'].append(f"Retained {site['enzyme']} site at assembly bp {site['start']+1}; the assembled product would be cut again.")
    for check in checks:
        check['errors']=_unique(check['errors'])
        check['warnings']=_unique(check['warnings'])
        check['valid']=not check['errors']
    result['fragment_checks']=checks
    return result


def assemble(fragment_dicts: list[dict[str, Any]], enzyme: str,
             backbone: dict[str, Any] | None = None, slot_id: str | None = None,
             circular: bool | None = True, left_overhang: str | None = None,
             right_overhang: str | None = None) -> dict[str, Any]:
    """Digest and join ordered donors, optionally into a retained backbone.

    With a backbone, the returned sequence begins at the backbone's retained
    downstream fusion label, followed by the retained vector and the donors.
    Invalid junctions retain both unmatched labels in the displayed schematic
    sequence; ``valid`` is false and no physical ligation is implied.

    ``circular=None`` infers topology from valid donor digests, all ordered
    junctions, and matching terminal fusion labels. An open chain is then a
    linear product, without an artificial failed closure junction. Explicit
    ``True`` and ``False`` retain their requested topology and validation.
    """
    enzyme = _enzyme(enzyme)
    options, errors, warnings = [], [], []
    inputs = ([dict(backbone, _is_backbone=True)] if backbone else []) + [dict(item, _is_backbone=False) for item in fragment_dicts]
    for index,item in enumerate(inputs):
        name=str(item.get('name') or item.get('id') or f'Fragment {index+1}')
        variants=([prepare_backbone(item.get('sequence',''),enzyme,slot_id) | {'orientation':1,'reverse_complement':False}]
                  if item['_is_backbone'] else fragment_orientations(item.get('sequence',''),enzyme))
        options.append([digest | {'name':name,'id':item.get('id'),'is_backbone':item['_is_backbone']} for digest in variants])
    edges=_oriented_chain(options,circular,left_overhang,right_overhang)
    for edge in edges:
        errors.extend(f"{edge['name']}: {message}" for message in edge['errors'])
        warnings.extend(f"{edge['name']}: {message}" for message in edge['warnings'])
    if not edges:
        errors.append("Select at least one fragment or a backbone and donor fragments.")
    if backbone and not fragment_dicts:
        errors.append("Select at least one donor fragment for the backbone cassette.")
    circular_detected = bool(edges) and all(edge["valid"] for edge in edges) and all(
        edge["right_overhang"] == edges[(index + 1) % len(edges)]["left_overhang"]
        for index, edge in enumerate(edges)
    )
    topology_auto_detected = circular is None
    circular = circular_detected if topology_auto_detected else circular
    topology = {"circular": circular, "topology": "circular" if circular else "linear",
                "circular_detected": circular_detected,
                "topology_auto_detected": topology_auto_detected}
    if any(not edge["left_overhang"] or not edge["right_overhang"] for edge in edges):
        return _with_fragment_checks({"sequence": "", "length": 0, "gc": 0.0, "features": [], "junctions": [],
                "errors": _unique(errors), "warnings": _unique(warnings), "restriction_sites": [],
                "retained_cassettes": [],
                "valid": False, "left_overhang": "", "right_overhang": "", "fragments": edges,
                **topology, "enzyme": enzyme})
    pieces, features, positions, cursor = [], [], [], 0
    for index, edge in enumerate(edges):
        block = edge["left_overhang"] + edge["target"]
        positions.append(cursor)
        pieces.append(block)
        features.append({"start": cursor, "end": cursor + len(block), "label": edge["name"],
                         "type": "misc_feature", "strand": edge.get("orientation",1), "fragment_id": edge["id"],
                         "reverse_complement":edge.get("reverse_complement",False),
                         "qualifiers":{"note":["Reverse complement of the supplied fragment."]} if edge.get("reverse_complement") else {},
                         "is_backbone": edge["is_backbone"], "fragment_index":index, "source": "retained_backbone" if edge["is_backbone"] else "fragment"})
        cursor += len(block)
        following = edges[(index + 1) % len(edges)] if circular or index + 1 < len(edges) else None
        if following is None or edge["right_overhang"] != following["left_overhang"]:
            pieces.append(edge["right_overhang"])
            cursor += 4
    sequence = "".join(pieces)
    junctions, labels = [], []
    junction_count = len(edges) if circular else max(0, len(edges) - 1)
    for index in range(junction_count):
        left, right = edges[index], edges[(index + 1) % len(edges)]
        compatible = left["right_overhang"] == right["left_overhang"]
        position = positions[(index + 1) % len(edges)]
        junction = {"from": left["name"], "to": right["name"],
                    "left_fragment": left["name"], "right_fragment": right["name"],
                    "left_overhang": left["right_overhang"], "right_overhang": right["left_overhang"],
                    "overhang": left["right_overhang"] if compatible else None,
                    "compatible": compatible, "position": position,
                    "circular_closure": circular and index == len(edges) - 1}
        junctions.append(junction)
        if compatible:
            location = f"{left['name']} → {right['name']}"
            labels.append((left["right_overhang"], location))
            features.append({"start": position, "end": position + 4, "label": f"{left['right_overhang']} fusion: {location}", "type": "misc_feature", "strand": 1, "source": "fusion"})
        else:
            errors.append(f"Incompatible junction {left['name']} → {right['name']}: {left['right_overhang']} does not match {right['left_overhang']}.")
    if edges and not circular:
        labels = [(edges[0]["left_overhang"], "left terminus")] + labels + [(edges[-1]["right_overhang"], "right terminus")]
    errors.extend(_collision_messages(labels))
    all_sites = restriction_sites(sequence, circular=circular)
    selected_sites = [site for site in all_sites if site["enzyme"] in active_enzymes(enzyme)]
    if selected_sites:
        positions_text = ", ".join(str(site["start"] + 1) for site in selected_sites)
        errors.append(f"The assembled product retains {len(selected_sites)} {enzyme} site(s), starting at base(s) {positions_text}; it would be cut again in the assembly reaction.")
    retained_cassettes, later_warnings = _retained_cassette_info(sequence, enzyme, circular)
    warnings.extend(later_warnings)
    if any(not item["compatible"] for item in junctions):
        warnings.append("The displayed sequence is a schematic concatenation retaining unmatched labels; failed junctions do not predict a physical ligation product.")
    return _with_fragment_checks({"sequence": sequence, "length": len(sequence),
            "gc": 100.0 * (sequence.count("G") + sequence.count("C")) / len(sequence) if sequence else 0.0,
            "features": sorted(features, key=lambda feature: (feature["start"], feature["end"])),
            "junctions": junctions, "errors": _unique(errors), "warnings": _unique(warnings),
            "restriction_sites": all_sites, "valid": not errors,
            "retained_cassettes": retained_cassettes,
            "left_overhang": edges[0]["left_overhang"] if edges else "",
            "right_overhang": edges[-1]["right_overhang"] if edges else "",
            "fragments": edges, **topology, "enzyme": enzyme})
