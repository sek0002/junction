"""Circular plasmid comparison and bounded fragment-graph candidate discovery.

All positions are zero-based, end-exclusive. Query coordinates in changes/blocks
refer to the oriented, left-rotated query shown in the alignment. The original
upload is recoverable from ``orientation`` and ``rotation``; each change also
includes original-query spans. Alignment uses exact k-mer circular anchors and
SequenceMatcher anchors, with optimal edit alignment inside small changed gaps.
It is an alignment heuristic, not a sequencing consensus or variant caller.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from bisect import bisect_left
from difflib import SequenceMatcher
from hashlib import sha256
from typing import Any, Iterable

_COMPLEMENT = str.maketrans("ACGTRYSWKMBDHVN", "TGCAYRSWMKVHDBN")
_MOTIFS = {"bsai": ("GGTCTC", "GAGACC"), "bsmbi": ("CGTCTC", "GAGACG"),
           "bbsi": ("GAAGAC", "GTCTTC")}


def _clean(sequence: str) -> str:
    value = "".join(str(sequence or "").split()).upper()
    if any(base not in "ACGTRYSWKMBDHVN" for base in value):
        raise ValueError("DNA sequences may only contain IUPAC DNA bases and whitespace")
    return value


def _rc(sequence: str) -> str:
    return sequence.translate(_COMPLEMENT)[::-1]


def _kmers(sequence: str, k: int = 17, circular: bool = False) -> set[str]:
    if len(sequence) < k:
        return {sequence} if sequence else set()
    extended = sequence + sequence[:k - 1] if circular else sequence
    return {extended[i:i + k] for i in range(len(extended) - k + 1)}


def _rotations(reference: str, query: str, limit: int = 3) -> list[int]:
    """Vote for query rotations with unique exact 17-mer circular anchors."""
    if not query:
        return [0]
    k = min(17, max(4, min(len(reference), len(query)) // 8))
    if min(len(reference), len(query)) < k:
        return list(range(len(query)))[:32]
    ref_index: dict[str, list[int]] = defaultdict(list)
    ext_ref = reference + reference[:k - 1]
    for i in range(len(reference)):
        ref_index[ext_ref[i:i + k]].append(i)
    votes: Counter[int] = Counter()
    ext_query = query + query[:k - 1]
    # Sample at most ~1,500 query anchors. Limit repeated reference hits.
    step = max(1, len(query) // 1500)
    for j in range(0, len(query), step):
        hits = ref_index.get(ext_query[j:j + k], ())
        if len(hits) > 4:
            continue
        for i in hits:
            votes[(j - i) % len(query)] += 1
    ranked = [offset for offset, _ in votes.most_common(limit)]
    return list(dict.fromkeys(ranked + [0]))


def _edit_gap(reference: str, query: str) -> tuple[str, str]:
    """Optimal unit edit alignment for a small unmatched gap."""
    prefix = 0
    while prefix < min(len(reference), len(query)) and reference[prefix] == query[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(reference), len(query)) - prefix and reference[-suffix - 1] == query[-suffix - 1]:
        suffix += 1
    if prefix or suffix:
        tail_r = reference[len(reference) - suffix:] if suffix else ""
        tail_q = query[len(query) - suffix:] if suffix else ""
        middle_r = reference[prefix:len(reference) - suffix if suffix else len(reference)]
        middle_q = query[prefix:len(query) - suffix if suffix else len(query)]
        ar, aq = _edit_gap(middle_r, middle_q)
        return reference[:prefix] + ar + tail_r, query[:prefix] + aq + tail_q
    n, m = len(reference), len(query)
    if not n:
        return "-" * m, query
    if not m:
        return reference, "-" * n
    # Large unrelated regions are represented as replacement blocks rather than
    # allocating an unbounded quadratic matrix.
    if n * m > 160000:
        shared = min(n, m)
        return reference[:shared] + reference[shared:] + "-" * (m - shared), query[:shared] + "-" * (n - shared) + query[shared:]
    matrix = [list(range(m + 1))]
    for i, a in enumerate(reference, 1):
        row = [i] + [0] * m
        previous = matrix[-1]
        for j, b in enumerate(query, 1):
            row[j] = min(previous[j - 1] + (a != b), previous[j] + 1, row[j - 1] + 1)
        matrix.append(row)
    ar, aq = [], []
    i, j = n, m
    while i or j:
        if i and j and matrix[i][j] == matrix[i - 1][j - 1] + (reference[i - 1] != query[j - 1]):
            ar.append(reference[i - 1]); aq.append(query[j - 1]); i -= 1; j -= 1
        elif i and matrix[i][j] == matrix[i - 1][j] + 1:
            ar.append(reference[i - 1]); aq.append("-"); i -= 1
        else:
            ar.append("-"); aq.append(query[j - 1]); j -= 1
    return "".join(reversed(ar)), "".join(reversed(aq))


def _anchors(reference: str, query: str, k: int = 17) -> list[tuple[int, int, int]]:
    """Find a monotonic chain of unique exact seeds, in O(n log n)."""
    if min(len(reference), len(query)) < k:
        return []
    query_index = {}
    repeated = set()
    for j in range(len(query) - k + 1):
        token = query[j:j + k]
        if token in query_index:
            repeated.add(token)
        else:
            query_index[token] = j
    pairs = []
    # Dense-enough sampling preserves anchors adjacent to small variants while
    # avoiding quadratic DNA alphabet matching on complete plasmids.
    for i in range(0, len(reference) - k + 1, 8):
        token = reference[i:i + k]
        if token in query_index and token not in repeated:
            pairs.append((i, query_index[token]))
    if not pairs:
        return []
    tails, tail_indices, previous = [], [], [-1] * len(pairs)
    for index, (_, qpos) in enumerate(pairs):
        at = bisect_left(tails, qpos)
        if at:
            previous[index] = tail_indices[at - 1]
        if at == len(tails):
            tails.append(qpos); tail_indices.append(index)
        else:
            tails[at] = qpos; tail_indices[at] = index
    chain = []
    index = tail_indices[-1]
    while index >= 0:
        chain.append(pairs[index]); index = previous[index]
    chain.reverse()
    merged = []
    for i, j in chain:
        if merged and i - j == merged[-1][0] - merged[-1][1] and i <= merged[-1][0] + merged[-1][2]:
            a, b, size = merged[-1]
            merged[-1] = (a, b, max(size, i + k - a))
        elif not merged or (i >= merged[-1][0] + merged[-1][2] and j >= merged[-1][1] + merged[-1][2]):
            merged.append((i, j, k))
    return merged


def _align(reference: str, query: str) -> tuple[str, str]:
    seeds = _anchors(reference, query)
    if not seeds:
        if len(reference) * len(query) > 1000000:
            # With no unique long anchors, quadratic DNA matching is both
            # expensive and ambiguous. Prefix/suffix trimming still resolves
            # a simple mutation in a long repeated region deterministically.
            return _edit_gap(reference, query)
        matcher = SequenceMatcher(None, reference, query, autojunk=False)
        seeds = [(b.a, b.b, b.size) for b in matcher.get_matching_blocks() if b.size]
    ar, aq = [], []
    ri = qi = 0
    for i, j, size in seeds + [(len(reference), len(query), 0)]:
        if i > ri or j > qi:
            left, right = _edit_gap(reference[ri:i], query[qi:j])
            ar.append(left); aq.append(right)
        ar.append(reference[i:i + size]); aq.append(query[j:j + size])
        ri, qi = i + size, j + size
    return "".join(ar), "".join(aq)


def _original_spans(start: int, end: int, rotation: int, length: int, orientation: str) -> list[list[int]]:
    if length == 0:
        return [[0, 0]]
    if start == end:
        point = (start + rotation) % length
        return [[point, point]] if orientation == "+" else [[length - point, length - point]]
    start_rot = (start + rotation) % length
    remaining = end - start
    spans = []
    while remaining:
        take = min(remaining, length - start_rot)
        spans.append([start_rot, start_rot + take])
        remaining -= take
        start_rot = 0
    if orientation == "-":
        spans = [[length - b, length - a] for a, b in spans]
    return spans


def _summarize(ar: str, aq: str, rotation: int, orientation: str, query_length: int) -> tuple[list[dict], list[dict]]:
    changes: list[dict] = []
    ref_pos = query_pos = 0
    current: dict | None = None
    for a, b in zip(ar, aq):
        kind = "insertion" if a == "-" else "deletion" if b == "-" else "substitution" if a != b else None
        if current and kind != current["type"]:
            current["original_query_spans"] = _original_spans(current["query_start"], current["query_end"], rotation, query_length, orientation)
            changes.append(current); current = None
        if kind and current is None:
            current = {"type": kind, "reference_start": ref_pos, "reference_end": ref_pos,
                       "query_start": query_pos, "query_end": query_pos,
                       "reference_bases": "", "query_bases": ""}
        if current:
            current["reference_bases"] += "" if a == "-" else a
            current["query_bases"] += "" if b == "-" else b
            current["reference_end"] += a != "-"
            current["query_end"] += b != "-"
        ref_pos += a != "-"; query_pos += b != "-"
    if current:
        current["original_query_spans"] = _original_spans(current["query_start"], current["query_end"], rotation, query_length, orientation)
        changes.append(current)
    blocks = []
    ref_pos = query_pos = 0
    for start in range(0, len(ar), 100):
        left, right = ar[start:start + 100], aq[start:start + 100]
        nr, nq = len(left.replace("-", "")), len(right.replace("-", ""))
        blocks.append({"reference_start": ref_pos, "reference_end": ref_pos + nr,
                       "query_start": query_pos, "query_end": query_pos + nq,
                       "reference": left, "query": right,
                       "match": "".join("|" if a == b else " " if "-" in (a, b) else "*" for a, b in zip(left, right))})
        ref_pos += nr; query_pos += nq
    return changes, blocks


def _alignment_coverage(reference: str, query: str) -> dict[str, Any]:
    """Coverage counts paired bases, including substitutions, but excluding gaps."""
    paired = sum(a != '-' and b != '-' for a, b in zip(reference, query))
    nr, nq = len(reference.replace('-', '')), len(query.replace('-', ''))
    return {'aligned_bp': paired, 'reference_coverage': paired / nr if nr else 0.,
            'query_coverage': paired / nq if nq else 0.}


def compare_sequences(reference: str, query: str, circular: bool = True) -> dict[str, Any]:
    """Align uploaded DNA to a reference, accounting for strand and circle origin.

    ``rotation`` is the number of bases left-rotated in the oriented query.
    Identity is identical columns / all alignment columns (gaps included).
    ``score`` is the number of identical columns minus mismatched/gapped columns.
    """
    reference, query = _clean(reference), _clean(query)
    if not reference or not query:
        raise ValueError("Both reference and query sequences must be nonempty")
    trials: list[tuple[int, str, int, str, str]] = []
    for orientation, oriented in (("+", query), ("-", _rc(query))):
        if circular and len(reference) == len(oriented):
            at = (oriented + oriented).find(reference)
            if 0 <= at < len(oriented):
                ar, aq = reference, reference
                changes, blocks = _summarize(ar, aq, at, orientation, len(query))
                return {**_alignment_coverage(ar, aq), "score": len(reference), "identity": 1.0, "orientation": orientation,
                        "rotation": at, "reference_length": len(reference), "query_length": len(query),
                        "changes": changes, "blocks": blocks, "aligned_reference": ar, "aligned_query": aq,
                        "exact": True, "coordinate_system": "zero-based, end-exclusive; query coordinates after orientation and rotation",
                        "method": "exact circular sequence match"}
        offsets = _rotations(reference, oriented) if circular else [0]
        # Rank rotation hypotheses cheaply before expensive SequenceMatcher alignment.
        for rotation in offsets:
            rotated = oriented[rotation:] + oriented[:rotation]
            matches = sum(size for _, _, size in _anchors(reference, rotated))
            if not matches and min(len(reference), len(rotated)) < 100:
                matches = sum(b.size for b in SequenceMatcher(None, reference, rotated, autojunk=False).get_matching_blocks())
            trials.append((matches, orientation, rotation, rotated, ""))
    trials.sort(key=lambda item: (-item[0], item[1] != "+", item[2]))
    best = None
    for _, orientation, rotation, rotated, _ in trials[:2]:
        pending = [(rotation, rotated)]
        tried = set()
        while pending and len(tried) < 3:
            rotation, rotated = pending.pop(0)
            if rotation in tried:
                continue
            tried.add(rotation)
            ar, aq = _align(reference, rotated)
            matches = sum(a == b for a, b in zip(ar, aq))
            edits = len(ar) - matches
            key = (matches - edits, matches / max(1, len(ar)))
            if best is None or key > best[0]:
                best = (key, orientation, rotation, ar, aq)
            # Indels shift the strongest rotation vote. A reference prefix can
            # then appear as a deletion at one end and an insertion at the other.
            # Move that identical sequence across the circular seam and realign.
            if circular:
                deleted = len(aq) - len(aq.lstrip('-'))
                inserted = len(ar) - len(ar.lstrip('-'))
                if deleted and ar[-deleted:] == '-' * deleted and ar[:deleted] == aq[-deleted:]:
                    pending.append(((rotation-deleted) % len(query), rotated[-deleted:]+rotated[:-deleted]))
                if inserted and aq[-inserted:] == '-' * inserted and aq[:inserted] == ar[-inserted:]:
                    pending.append(((rotation+inserted) % len(query), rotated[inserted:]+rotated[:inserted]))
    assert best is not None
    (score, identity), orientation, rotation, ar, aq = best
    changes, blocks = _summarize(ar, aq, rotation, orientation, len(query))
    return {**_alignment_coverage(ar, aq), "score": score, "identity": identity, "orientation": orientation, "rotation": rotation,
            "reference_length": len(reference), "query_length": len(query), "changes": changes,
            "blocks": blocks, "aligned_reference": ar, "aligned_query": aq, "exact": not changes,
            "low_identity": identity < 0.8,
            "coordinate_system": "zero-based, end-exclusive; query coordinates after orientation and rotation",
            "method": "circular k-mer anchors; monotonic unique-seed chain and local optimal edit alignment",
            "limitations": "Heuristic alignment; repeat-associated indel placement may be ambiguous. No sequencing quality scores are used."}


def rank_candidates(query: str, candidates: Iterable[dict], limit: int = 5) -> list[dict]:
    """Rank a bounded shortlist with complete circular alignments.

    Input candidates require sequence and may contain id, name, features, parts.
    The k-mer prefilter keeps detailed alignment bounded to max(8, 2*limit).
    """
    query = _clean(query)
    if not query:
        raise ValueError("Query sequence must be nonempty")
    limit = max(1, min(int(limit), 20))
    qkmers = _kmers(query, circular=True) | _kmers(_rc(query), circular=True)
    shortlist = []
    for candidate in candidates:
        sequence = _clean(candidate.get("sequence", ""))
        if not sequence:
            continue
        kmers = _kmers(sequence, circular=True)
        coverage = len(kmers & qkmers) / max(1, len(kmers))
        length_similarity = min(len(sequence), len(query)) / max(len(sequence), len(query))
        shortlist.append((coverage * 0.8 + length_similarity * 0.2, candidate, sequence))
    shortlist.sort(key=lambda x: x[0], reverse=True)
    results = []
    for _, candidate, sequence in shortlist[:max(8, limit * 2)]:
        result = compare_sequences(sequence, query, circular=candidate.get("circular", True))
        result.update({"id": candidate.get("id"), "name": candidate.get("name", "Unnamed candidate"),
                       "candidate_id": candidate.get("id"), "candidate_name": candidate.get("name", "Unnamed candidate"),
                       "features": candidate.get("features", []), "parts": candidate.get("parts", []),
                       "sequence": sequence, "source": candidate.get("source", "reference"),
                       "inferred": bool(candidate.get("inferred", False)), "circular":candidate.get("circular",True),
                       "assembly_enzymes":candidate.get("assembly_enzymes",[]), "aliases":candidate.get("aliases",[])})
        result['assembly_paths'] = candidate.get('assembly_paths', [])
        results.append(result)
    results.sort(key=lambda x: (x["exact"], x["identity"], x["score"]), reverse=True)
    return results[:limit]


def _digest_for_graph(fragment: dict, enzyme: str) -> dict | None:
    """Read pre-digested metadata or an unambiguous inward adapter pair."""
    if fragment.get("left_overhang") and fragment.get("right_overhang"):
        target = fragment.get("target_sequence")
        if target is None:
            target = fragment.get("target")
        if target is not None:
            return {"left": _clean(fragment["left_overhang"]), "right": _clean(fragment["right_overhang"]), "core": _clean(target)}
    sequence = _clean(fragment.get("sequence", ""))
    if enzyme.lower().replace("-", "").replace(" ", "") in {"bsai", "bsmbi", "esp3i", "bsmbi+bsai", "bsai+bsmbi"}:
        from .sequence_engine import digest_fragment
        digest = digest_fragment(sequence, enzyme)
        if digest.get("errors"):
            return None
        return {"left": digest["left_overhang"], "right": digest["right_overhang"], "core": digest["target"]}
    motifs = _MOTIFS.get(enzyme.lower().replace("-", ""))
    if not motifs:
        raise ValueError("Supported enzymes: BsaI, BsmBI, BbsI")
    forward, reverse = motifs
    sites_f = [i for i in range(len(sequence) - 5) if sequence[i:i + 6] == forward]
    sites_r = [i for i in range(len(sequence) - 5) if sequence[i:i + 6] == reverse]
    # Only fragments with exactly their outer pair are safe for this assembly.
    if len(sites_f) != 1 or len(sites_r) != 1:
        return None
    left, right = sites_f[0], sites_r[0]
    spacer = 2 if enzyme.lower() == "bbsi" else 1
    left_start = left + 6 + spacer
    right_start = right - spacer - 4
    if left_start + 4 > right_start or right_start < 0:
        return None
    return {"left": sequence[left_start:left_start + 4],
            "right": sequence[right_start:right_start + 4],
            "core": sequence[left_start + 4:right_start]}


def infer_database_candidates(query: str, fragments: Iterable[dict], enzyme: str = "BsaI", max_candidates: int = 64, max_parts: int = 16,
                              backbones: Iterable[dict] = ()) -> dict:
    """Discover closed circles in a bounded, sequence-guided overhang graph.

    No exhaustive Cartesian expansion is performed. Every returned candidate is
    a closed route with exact overhang matches and no reused database fragment,
    in either orientation, with at most one retained backbone cassette.
    ``complete_search`` is false when any beam/path/candidate limit was reached;
    this search cannot prove that an unreturned circle does not exist.
    """
    query = _clean(query)
    if not query:
        raise ValueError("Query sequence must be nonempty")
    max_candidates = max(1, min(int(max_candidates), 256))
    max_parts = max(1, min(int(max_parts), 32))
    qkmers = _kmers(query, circular=True) | _kmers(_rc(query), circular=True)
    nodes, excluded = [], []
    def add_nodes(parsed, source, key, is_backbone=False, slot_id=None):
        for orientation in (1, -1):
            ends = parsed if orientation == 1 else {'left': _rc(parsed['right']), 'right': _rc(parsed['left']), 'core': _rc(parsed['core'])}
            content = ends['left'] + ends['core']
            words = _kmers(content)
            support = len(words & qkmers) / max(1, len(words))
            nodes.append({**ends, 'fragment': source, 'key': key, 'orientation': orientation,
                          'is_backbone': is_backbone, 'slot_id': slot_id, 'support': support, 'content': content})
    for index, fragment in enumerate(fragments):
        try:
            parsed = _digest_for_graph(fragment, enzyme)
        except ValueError:
            parsed = None
        if not parsed:
            excluded.append(fragment.get("id", index)); continue
        add_nodes(parsed, fragment, 'fragment:' + str(fragment.get('id', index)))
    from .sequence_engine import find_backbone_slots, prepare_backbone
    for index, backbone in enumerate(backbones):
        if not backbone.get('circular', True):
            continue
        for slot in find_backbone_slots(backbone['sequence'], enzyme):
            digest = prepare_backbone(backbone['sequence'], enzyme, slot['id'])
            if not digest['valid']:
                continue
            add_nodes({'left': digest['left_overhang'], 'right': digest['right_overhang'], 'core': digest['target']},
                      backbone, 'backbone:' + str(backbone.get('id', index)), True, slot['id'])
    by_left: dict[str, list[int]] = defaultdict(list)
    for i, node in enumerate(nodes):
        by_left[node["left"]].append(i)
    for value in by_left.values():
        value.sort(key=lambda i: nodes[i]["support"], reverse=True)
    # Start from strong unique sequence evidence. Rotations of the same circle
    # are deduplicated by their fragment-key cycle.
    starts = sorted(range(len(nodes)), key=lambda i: nodes[i]["support"], reverse=True)[:min(24, len(nodes))]
    beam_width = max(64, max_candidates * 4)
    beam = [((i,), nodes[i]["support"] * len(nodes[i]["content"]), len(nodes[i]["content"])) for i in starts]
    candidates, seen_cycles = [], set()
    rejected_circles = 0
    capped = len(nodes) > len(starts)
    explored = 0
    for depth in range(max_parts):
        next_beam = []
        for path, support_sum, length in beam:
            explored += 1
            last, first = nodes[path[-1]], nodes[path[0]]
            if last["right"] == first["left"]:
                if len(path) == 1 and first['is_backbone']:
                    continue
                keys = tuple((nodes[i]['key'], nodes[i]['slot_id'] or '', nodes[i]['orientation']) for i in path)
                reverse_keys = tuple((key, slot, -orientation) for key, slot, orientation in reversed(keys))
                canonical = min(cycle[i:] + cycle[:i] for cycle in (keys, reverse_keys) for i in range(len(keys)))
                if canonical not in seen_cycles:
                    seen_cycles.add(canonical)
                    sequence = "".join(nodes[i]["content"] for i in path)
                    # Revalidate the complete product: an exact graph route can
                    # still create a restriction site across a ligation seam.
                    enzyme_key = enzyme.lower().replace("-", "").replace(" ", "")
                    motif_pair = _MOTIFS['bsai'] + _MOTIFS['bsmbi'] if enzyme_key in ('bsmbi+bsai','bsai+bsmbi') else _MOTIFS.get(enzyme_key, ())
                    circular_sequence = sequence + sequence[:5]
                    if any(motif in circular_sequence for motif in motif_pair):
                        rejected_circles += 1
                        continue
                    parts = [nodes[i]["fragment"].get("name", nodes[i]["key"]) for i in path]
                    features, offset = [], 0
                    for i in path:
                        node = nodes[i]
                        features.append({"type": "misc_feature", "start": offset, "end": offset + len(node["content"]), "label": node["fragment"].get("name", node["key"]),
                                         "strand": node['orientation'], 'is_backbone': node['is_backbone']})
                        offset += len(node["content"])
                    candidate_id = "inferred_" + sha256((enzyme + repr(canonical)).encode()).hexdigest()[:12]
                    candidates.append({"id": candidate_id, "name": "Inferred: " + " → ".join(parts), "sequence": sequence,
                                       "parts": parts, "fragment_ids": [nodes[i]["fragment"].get("id") for i in path if not nodes[i]['is_backbone']],
                                       'part_orientations': [nodes[i]['orientation'] for i in path],
                                       'backbone_id': next((nodes[i]['fragment'].get('id') for i in path if nodes[i]['is_backbone']), None),
                                       'slot_id': next((nodes[i]['slot_id'] for i in path if nodes[i]['is_backbone']), None),
                                       "features": features, "circular": True, "inferred": True,
                                       "query_support": support_sum / max(1, length)})
            if len(path) >= max_parts:
                if any(nodes[i]['key'] not in {nodes[j]['key'] for j in path} for i in by_left.get(last["right"], [])):
                    capped = True
                continue
            for nxt in by_left.get(last["right"], []):
                node = nodes[nxt]
                if node['key'] in {nodes[i]['key'] for i in path}:
                    continue
                if node['is_backbone'] and any(nodes[i]['is_backbone'] for i in path):
                    continue
                label_class = min(node["left"], _rc(node["left"]))
                used_labels = {min(nodes[i]["left"], _rc(nodes[i]["left"])) for i in path}
                if label_class in used_labels:
                    # Duplicate or reverse-complement fusion labels permit
                    # competing ligations and are not unambiguous assemblies.
                    continue
                new_length = length + len(node["content"])
                # Large insertions/deletions are supported, but runaway graph
                # routes far beyond the query length are not useful candidates.
                if new_length > max(len(query) * 1.6, len(query) + 3000):
                    capped = True; continue
                next_beam.append((path + (nxt,), support_sum + node["support"] * len(node["content"]), new_length))
        # Keep looking through longer routes even after finding many short
        # circles. Otherwise unrelated early closures can hide an exact build.
        if len(candidates) > max_candidates * 4:
            candidates.sort(key=lambda item: item['query_support'] * .8 + min(len(item['sequence']), len(query)) / max(len(item['sequence']), len(query)) * .2, reverse=True)
            candidates = candidates[:max_candidates * 4]
            capped = True
        next_beam.sort(key=lambda item: item[1] / max(1, item[2]) * 0.85 + min(item[2], len(query)) / max(item[2], len(query)) * 0.15, reverse=True)
        if len(next_beam) > beam_width:
            capped = True
        beam = next_beam[:beam_width]
        if not beam:
            break
    candidates.sort(key=lambda item: item["query_support"] * 0.8 + min(len(item["sequence"]), len(query)) / max(len(item["sequence"]), len(query)) * 0.2, reverse=True)
    if len(candidates) > max_candidates:
        capped = True
    return {"candidates": candidates[:max_candidates], "metadata": {
        "method": "bounded sequence-guided beam search of oriented fragments and retained backbone cassettes", "enzyme": enzyme,
        "fragments_considered": len({node['key'] for node in nodes if not node['is_backbone']}),
        'oriented_edges': len(nodes), 'backbone_cassettes_considered': len({(node['key'], node['slot_id']) for node in nodes if node['is_backbone']}),
        "fragments_excluded": excluded, "routes_explored": explored,
        "circles_rejected_for_junction_sites": rejected_circles,
        "max_candidates": max_candidates, "max_parts": max_parts, "complete_search": not capped,
        "limitations": "Search is bounded and heuristic; no absence or unique closest-match claim is implied. Fragments with internal active-enzyme sites and backbones with unresolved additional active-enzyme cuts are excluded. Each route uses at most one backbone cassette."}}
