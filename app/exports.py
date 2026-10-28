"""Sequence interchange and printable laboratory planning workbooks.

Coordinates in the public feature dictionaries are zero-based, half-open.
Calculations use 660 g/mol/bp for double-stranded DNA. A requested stock
concentration is a planning target; it never substitutes for a recorded stock.
"""

from __future__ import annotations

import io
import math
import re
import textwrap
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.datavalidation import DataValidation


from .plate_labels import label_workbook_plates

DNA_LETTERS = set("ACGTRYSWKMBDHVN")
_RE_SITE = re.compile(r"[^A-Za-z0-9_.-]+")


def _sequence(value: Any) -> str:
    result = re.sub(r"\s+", "", str(value or "")).upper()
    if not result or set(result) - DNA_LETTERS:
        raise ValueError("Sequence must contain DNA IUPAC bases only.")
    return result


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _available_mass(value: Any) -> float | None:
    if value == 0 and not isinstance(value, bool):
        return 0.0
    return _number(value)


def _safe_cell(value: Any) -> Any:
    """Keep user-supplied strings literal when written to Excel."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _gb_escape(value: Any) -> str:
    return str(value).replace('"', '""').replace("\n", " ").replace("\r", " ")


def _feature_location(feature: dict[str, Any], length: int) -> str:
    # Exact imported location strings preserve joins, fuzzy positions and order.
    if feature.get("raw_location"):
        raw = str(feature["raw_location"])
        if not re.fullmatch(r"[A-Za-z0-9_.:<>,()^]+", raw):
            raise ValueError("Invalid GenBank feature location.")
        return raw
    segments = feature.get("segments") or [feature]
    locations = []
    for segment in segments:
        start, end = int(segment["start"]), int(segment["end"])
        if not 0 <= start < end <= length:
            raise ValueError("Feature coordinates are outside the sequence.")
        location = f"{start + 1}..{end}" if end - start > 1 else str(start + 1)
        if int(segment.get("strand", feature.get("strand", 1)) or 1) == -1:
            location = f"complement({location})"
        locations.append(location)
    return locations[0] if len(locations) == 1 else "join(" + ",".join(locations) + ")"


def genbank_bytes(
    name: str,
    sequence: str,
    features: list[dict[str, Any]] | None = None,
    circular: bool = True,
    notes: str | list[str] | None = None,
) -> bytes:
    """Write one DNA record, including imported feature qualifiers and joins."""
    seq = _sequence(sequence)
    identifier = (_RE_SITE.sub("_", str(name)).strip("_") or "assembly")[:32]
    date = datetime.now(timezone.utc).strftime("%d-%b-%Y").upper()
    topology = "circular" if circular else "linear"
    lines = [
        f"LOCUS       {identifier:<32} {len(seq):>11} bp    DNA     {topology:<8} SYN {date}",
        f"DEFINITION  {_gb_escape(name)}.",
        f"ACCESSION   {identifier}",
        f"VERSION     {identifier}",
        "KEYWORDS    .",
        "SOURCE      synthetic DNA construct",
        "  ORGANISM  synthetic DNA construct",
        "            other sequences; artificial sequences.",
    ]
    for note in ([notes] if isinstance(notes, str) else notes or []):
        lines.extend(textwrap.wrap(str(note), 67, initial_indent="COMMENT     ", subsequent_indent="            ", break_long_words=False))
    lines.append("FEATURES             Location/Qualifiers")
    if not any(feature.get("type") == "source" for feature in features or []):
        lines.extend([f"     source          1..{len(seq)}", '                     /organism="synthetic DNA construct"', '                     /mol_type="other DNA"'])
    for feature in features or []:
        feature_type = re.sub(r"[^A-Za-z0-9_'*-]", "_", str(feature.get("type") or "misc_feature"))[:15]
        location = _feature_location(feature, len(seq))
        # Location wrapping is at commas so a round trip rejoins it exactly.
        if len(location) <= 58:
            lines.append(f"     {feature_type:<15} {location}")
        else:
            chunks = textwrap.wrap(location, 58, break_long_words=True, break_on_hyphens=False)
            lines.append(f"     {feature_type:<15} {chunks[0]}")
            lines.extend("                     " + chunk for chunk in chunks[1:])
        qualifiers = dict(feature.get("qualifiers") or {})
        if feature.get("label") and "label" not in qualifiers:
            qualifiers["label"] = [feature["label"]]
        for key, values in qualifiers.items():
            key = re.sub(r"[^A-Za-z0-9_]", "_", str(key))
            for value in values if isinstance(values, list) else [values]:
                if value is None or value is True:
                    lines.append(f"                     /{key}")
                else:
                    # Keep qualifiers on one line to preserve sequence-valued qualifiers.
                    lines.append(f'                     /{key}="{_gb_escape(value)}"')
    lines.append("ORIGIN")
    for i in range(0, len(seq), 60):
        chunk = seq[i:i + 60].lower()
        lines.append(f"{i + 1:>9} " + " ".join(chunk[j:j + 10] for j in range(0, len(chunk), 10)))
    lines.extend(["//", ""])
    return "\n".join(lines).encode("utf-8")


def _location_segments(location: str) -> list[dict[str, int]]:
    """Read common INSDC locations, including nested complement(join(...))."""
    location = re.sub(r"\s", "", location)
    def walk(value: str, strand: int = 1) -> list[dict[str, int]]:
        if value.startswith("complement(") and value.endswith(")"):
            return walk(value[11:-1], -strand)
        for operator in ("join", "order"):
            if value.startswith(operator + "(") and value.endswith(")"):
                inside, chunks, depth, start = value[len(operator) + 1:-1], [], 0, 0
                for index, char in enumerate(inside):
                    depth += (char == "(") - (char == ")")
                    if char == "," and depth == 0:
                        chunks.append(inside[start:index])
                        start = index + 1
                chunks.append(inside[start:])
                return [segment for chunk in chunks for segment in walk(chunk, strand)]
        # Remote-accession locations are preserved verbatim, but cannot be drawn
        # as a local segment without fetching their external sequence.
        if ":" in value:
            return []
        match = re.fullmatch(r"[<>]?(\d+)(?:\.\.[<>]?(\d+)|\^(\d+))?", value)
        if not match:
            return []
        first = int(match.group(1))
        last = int(match.group(2) or match.group(3) or first)
        return [{"start": first - 1, "end": last, "strand": strand}]
    return walk(location)


def parse_genbank(text: str) -> list[dict[str, Any]]:
    """Parse multi-record GenBank text without requiring Biopython.

    Original locations and qualifiers are retained for lossless feature export.
    Segment bounds are supplied for local interactive rendering.
    """
    records = []
    for block in re.split(r"^//\s*$", text.replace("\r\n", "\n"), flags=re.M):
        if not block.strip():
            continue
        lines = block.splitlines()
        locus_line = next((line for line in lines if line.startswith("LOCUS")), None)
        if not locus_line:
            raise ValueError("GenBank record is missing a LOCUS line.")
        origin = next((i for i, line in enumerate(lines) if line.startswith("ORIGIN")), None)
        if origin is None:
            raise ValueError("GenBank record is missing its ORIGIN sequence.")
        seq = _sequence("".join(re.sub(r"[\s\d]", "", line) for line in lines[origin + 1:]))
        name = locus_line.split()[1]
        features, current, collecting = [], None, False
        for line in lines[:origin]:
            if line.startswith("FEATURES"):
                collecting = True
                continue
            if not collecting:
                continue
            if line.startswith("     ") and len(line) > 20 and line[5:21].strip():
                if current:
                    features.append(current)
                current = {"type": line[5:21].strip(), "raw_location": line[21:].strip(), "qualifier_lines": []}
            elif current and line.startswith("                     "):
                value = line[21:].strip()
                if current["qualifier_lines"] or value.startswith("/"):
                    current["qualifier_lines"].append(value)
                else:
                    current["raw_location"] += value
        if current:
            features.append(current)
        parsed_features = []
        for feature in features:
            qualifiers, key, value, quoted = {}, None, "", False
            def commit() -> None:
                if key is None:
                    return
                item = value
                if item.startswith('"') and item.endswith('"'):
                    item = item[1:-1].replace('""', '"')
                qualifiers.setdefault(key, []).append(item if item != "" else True)
            for line in feature.pop("qualifier_lines"):
                if line.startswith("/") and not quoted:
                    commit()
                    match = re.match(r"/([^=\s]+)(?:=(.*))?$", line)
                    if not match:
                        continue
                    key, value = match.group(1), match.group(2) or ""
                else:
                    # Sequence-like translation qualifiers should not acquire spaces.
                    value += ("" if key in {"translation", "transcription"} else " ") + line
                quoted = value.startswith('"') and (len(value.replace('""', "")) - len(value.replace('""', "").replace('"', ""))) % 2 == 1
            commit()
            segments = _location_segments(feature["raw_location"])
            feature.update({
                "qualifiers": qualifiers,
                "label": str((qualifiers.get("label") or qualifiers.get("gene") or qualifiers.get("product") or qualifiers.get("note") or [feature["type"]])[0]),
                "segments": segments,
                "start": min((item["start"] for item in segments), default=0),
                "end": max((item["end"] for item in segments), default=0),
                "strand": segments[0]["strand"] if segments and all(item["strand"] == segments[0]["strand"] for item in segments) else 0,
            })
            parsed_features.append(feature)
        records.append({"name": name, "sequence": seq, "circular": bool(re.search(r"\bcircular\b", locus_line, re.I)), "features": parsed_features})
    if not records:
        raise ValueError("No GenBank records found.")
    return records


def parse_sequence_file(text: str, filename: str = "") -> list[dict[str, Any]]:
    """Read GenBank, multi-record FASTA, or a plain DNA sequence."""
    text = text.lstrip("\ufeff").strip()
    if re.search(r"^LOCUS\s", text, re.M):
        return parse_genbank(text)
    if text.startswith(">"):
        records = []
        for item in text.split(">")[1:]:
            lines = item.splitlines()
            records.append({"name": lines[0].strip() or "sequence", "sequence": _sequence("".join(lines[1:])), "circular": False, "features": []})
        return records
    return [{"name": filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "sequence", "sequence": _sequence(text), "circular": False, "features": []}]


def _construct_length(fragment: dict[str, Any]) -> int:
    physical = _number(fragment.get("physical_length"))
    if physical:
        return int(physical)
    seq = fragment.get("construct_sequence") or fragment.get("sequence") or ""
    return len(re.sub(r"\s", "", str(seq))) if seq else int(_number(fragment.get("length_bp") or fragment.get("length")) or 0)


def resuspension_plan(fragments: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Plan solvent volumes without treating planned concentrations as measured.

    Inventory rows are inserts relative to the explicit backbone reference.
    Unlike a selected assembly, an inventory has no implied first backbone.
    """
    settings = settings or {}
    no_backbone = bool(settings.get("no_backbone"))
    mode = settings.get("resuspension_mode", "fixed_stock")
    matched = mode == "one_ul"
    constrained = mode == "constrained"
    input_volume = _number(settings.get("input_volume_ul")) or 1.0
    reference_bp = _number(settings.get("backbone_length_bp"))
    backbone_mass = _number(settings.get("backbone_ng")) or 50.0
    ratio = _number(settings.get("insert_ratio")) or (1.0 if matched or constrained else 2.0)
    target_stock = _number(settings.get("target_stock_ng_ul")) or 20.0
    backbone_fmol = backbone_mass * 1_000_000 / (reference_bp * 660) if reference_bp else None
    if constrained or no_backbone:
        backbone_fmol = (_number(settings.get("backbone_pmol")) or .05) * 1000
    preferred = _number(settings.get("preferred_resuspension_ul")) or 50.0
    max_resuspension = _number(settings.get("max_resuspension_ul")) or 99.99
    min_input = _number(settings.get("min_input_volume_ul")) or 1.0
    max_input = _number(settings.get("max_input_volume_ul")) or 5.0
    rows = []
    for fragment in fragments:
        bp = _construct_length(fragment)
        available = _available_mass(fragment.get("yield_ng"))
        warnings = []
        if constrained and not no_backbone and (fragment.get('role')=='backbone' or fragment.get('is_backbone')):
            target_fmol=backbone_fmol if bp else None
            target_ng=target_fmol*bp*660/1_000_000 if target_fmol is not None else None
            stock=_number(settings.get('backbone_stock_ng_ul')) or _number(fragment.get('stock_ng_ul'))
            volume=target_ng/stock if target_ng is not None and stock else 1.0 if stock is None else None
            rows.append({'id':fragment.get('id'),'name':fragment.get('name',''),
                'plate_id':fragment.get('plate_id'),'well':fragment.get('well'),
                'physical_length':bp or None,'yield_ng':available,'target_ng_ul':stock,
                'target_fmol':target_fmol,'target_ng':target_ng,'resuspension_ul':None,
                'input_volume_ul':volume,'proposed_input_volume_ul':None,
                'minimum_resuspension_ul':None,'maximum_resuspension_ul':None,
                'manual_stock':True,'feasible':True if volume is not None else None,
                'feasibility':'manual_stock' if stock else 'default_volume',
                'stock_basis':'Manual backbone stock' if stock else 'Default backbone volume: 1 µL',
                'warnings':[]})
            continue
        if not bp:
            warnings.append("Input construct length missing")
        if available is None:
            warnings.append("Available mass unknown; resuspension volume cannot be calculated")
        if not fragment.get('_prepared_nested') and (not fragment.get("plate_id") or not fragment.get("well")):
            warnings.append("Plate identifier or well missing")
        feasible, feasibility = None, "missing_data"
        minimum_resuspension = maximum_resuspension = None
        planned_volume = None
        target_ng = None
        if constrained:
            row_ratio = 1.0 if fragment.get('role')=='backbone' or fragment.get('is_backbone') else ratio
            target_fmol = backbone_fmol*row_ratio if bp and (no_backbone or reference_bp and reference_bp>0) else None
            target_ng = target_fmol * bp * 660 / 1_000_000 if target_fmol is not None else None
            concentration = None
            if not no_backbone and not reference_bp:
                warnings.append("Backbone reference length missing")
            if target_ng is not None and available is not None:
                minimum_resuspension = available / target_ng * min_input
                maximum_resuspension = min(available / target_ng * max_input, max_resuspension)
                if available < target_ng:
                    feasible, feasibility = False, "insufficient_mass"
                    warnings.append("Insufficient available mass for one reaction")
                elif minimum_resuspension > max_resuspension:
                    feasible, feasibility = False, "resuspension_limit"
                    warnings.append(f"No feasible plan: at least {minimum_resuspension:g} µL resuspension is needed for a {min_input:g} µL aliquot; planned cap is {max_resuspension:g} µL")
                elif min_input > max_input:
                    feasible, feasibility = False, "invalid_input_limits"
                    warnings.append("Minimum input volume exceeds maximum input volume")
                else:
                    rounded_min = math.ceil(minimum_resuspension * 100 - 1e-9) / 100
                    rounded_max = math.floor(maximum_resuspension * 100 + 1e-9) / 100
                    if rounded_min > rounded_max:
                        feasible, feasibility = False, "resuspension_precision"
                        warnings.append("No feasible resuspension volume at 0.01 µL precision within the input-volume limits")
                    else:
                        feasible, feasibility = True, "feasible"
                        planned_volume = max(rounded_min, min(round(preferred, 2), rounded_max))
                        concentration = available / planned_volume
                        input_volume = target_ng / concentration
            else:
                warnings.append("Missing length or available mass prevents a constrained resuspension plan")
        elif matched:
            if not no_backbone and not reference_bp:
                warnings.append("Backbone reference length missing; molar-matched concentration cannot be calculated")
            row_ratio = 1.0 if fragment.get("role") == "backbone" or fragment.get("is_backbone") else ratio
            target_fmol = backbone_fmol * row_ratio if backbone_fmol is not None and bp else None
            concentration = target_fmol * bp * 660 / 1_000_000 / input_volume if target_fmol is not None else None
            target_ng = concentration * input_volume if concentration is not None else None
        else:
            concentration = target_stock
            target_fmol = concentration * input_volume * 1_000_000 / (bp * 660) if bp else None
        if fragment.get('_planner_stock_fixed'):
            concentration=_number(fragment.get('stock_ng_ul'))
            planned_volume=_number(fragment.get('resuspension_ul'))
            actual_input=target_ng/concentration if target_ng is not None and concentration else None
            warnings=[message for message in warnings if message=='Plate identifier or well missing']
            feasible=actual_input is not None
            feasibility='instance_stock' if feasible else 'missing_stock'
            if actual_input is None:
                warnings.append('Stock concentration missing')
            elif not min_input-1e-9<=actual_input<=max_input+1e-9:
                feasible,feasibility=False,'input_volume_limit'
                warnings.append(f'Stock requires {actual_input:g} µL; allowed input is {min_input:g}–{max_input:g} µL')
            if available is not None and target_ng is not None and available<target_ng:
                feasible,feasibility=False,'insufficient_mass'
                warnings.append('Insufficient available mass for one reaction')
            if planned_volume is not None and planned_volume>max_resuspension:
                warnings.append('Resuspension exceeds the current cap')
                if settings.get('planner_stock_mode')=='custom':
                    feasible,feasibility=False,'resuspension_limit'
            input_volume=actual_input
        rows.append({
            "id": fragment.get("id"), "name": fragment.get("name", ""),
            "plate_id": fragment.get("plate_id"), "well": fragment.get("well"),
            "physical_length": bp or None, "yield_ng": available,
            "target_ng_ul": concentration, "target_fmol": target_fmol,
            "target_ng": target_ng,
            "resuspension_ul": planned_volume if constrained else available / concentration if available is not None and concentration else None,
            "input_volume_ul": input_volume if fragment.get('_planner_stock_fixed') or not constrained or feasible else None,
            "stock_basis":fragment.get('concentration_basis'),
            "manual_stock":bool(fragment.get('_prepared_nested')),
            "yield_locked":fragment.get('yield_locked',True),
            "proposed_input_volume_ul": input_volume if not constrained or feasible else None,
            "minimum_resuspension_ul": minimum_resuspension, "maximum_resuspension_ul": maximum_resuspension,
            "feasible": feasible, "feasibility": feasibility, "warnings": warnings,
        })
    return rows


def calculate_volumes(parts: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Calculate DNA mass and pipetting amounts without inventing stock data.

    An explicit ``assume_target_stock`` setting permits estimates using the
    requested target concentration. Those rows are labeled as assumptions.
    Saved stock concentration is otherwise required for each insert volume.
    """
    settings = settings or {}
    no_backbone = bool(settings.get("no_backbone"))
    matched = settings.get("resuspension_mode") == "one_ul"
    constrained = settings.get("resuspension_mode") == "constrained"
    target_stock = _number(settings.get("target_stock_ng_ul")) or 20.0
    backbone_ng = _number(settings.get("backbone_ng")) or 50.0
    ratio = _number(settings.get("insert_ratio")) or (1.0 if matched or constrained else 2.0)
    input_volume = _number(settings.get("input_volume_ul")) or 1.0
    backbone = {} if no_backbone else next((p for p in parts if p.get("role") == "backbone" or p.get("is_backbone")), parts[0] if parts else {})
    backbone_length = None if no_backbone else _number(settings.get("backbone_length_bp")) or _construct_length(backbone)
    backbone_fmol = backbone_ng * 1_000_000 / (backbone_length * 660) if backbone_length else None
    if constrained or no_backbone:
        backbone_fmol = (_number(settings.get("backbone_pmol")) or .05) * 1000 if no_backbone or backbone_length and backbone_length>0 else None
    rows = []
    for part in parts:
        is_backbone = part is backbone
        length = int(backbone_length or 0) if is_backbone else _construct_length(part)
        saved_stock = _number(part.get("stock_ng_ul"))
        fmol = backbone_fmol * (1 if is_backbone else ratio) if backbone_fmol is not None and length else None
        mass = fmol * length * 660 / 1_000_000 if fmol is not None else None
        planned_stock = mass / input_volume if matched and mass is not None else None if matched else target_stock
        plan = resuspension_plan([dict(part, role="backbone" if is_backbone else "insert")], dict(settings, backbone_length_bp=backbone_length))[0] if constrained and not is_backbone else None
        if constrained and is_backbone:
            planned_stock = None
        if plan:
            planned_stock = plan["target_ng_ul"]
        concentration = _number(settings.get("backbone_stock_ng_ul")) if is_backbone else None
        basis = "user-entered backbone stock" if concentration else str(part.get("concentration_basis") or "recorded stock; basis unspecified")
        concentration = concentration or saved_stock
        warnings = list(plan["warnings"]) if plan else []
        if concentration is None and (settings.get("assume_target_stock") or settings.get('planner_stock_mode')=='custom') and not (constrained and is_backbone) and not part.get('_planner_stock_fixed'):
            concentration = planned_stock
            if concentration is not None:
                basis = "ASSUMED proposed constrained stock; verify actual concentration before pipetting" if constrained else "ASSUMED proposed molar-matched stock; verify actual concentration before pipetting" if matched else "ASSUMED target stock; verify actual concentration before pipetting"
                warnings.append("Stock concentration is an unmeasured planning assumption")
        default_backbone=constrained and is_backbone and concentration is None
        if default_backbone:
            basis='Default backbone volume: 1 µL'
        elif concentration is None:
            basis = "unknown"
            warnings.append("Backbone stock missing" if constrained and is_backbone else "Actual stock concentration missing; volume cannot be calculated")
        volume = 1.0 if default_backbone else mass / concentration if mass is not None and concentration else None
        feasible = plan["feasible"] if plan else (True if constrained and is_backbone and volume is not None else None)
        feasibility = plan["feasibility"] if plan else ("default_volume" if default_backbone else "manual_stock" if constrained and is_backbone else None)
        if constrained and not is_backbone and volume is not None:
            min_input = _number(settings.get("min_input_volume_ul")) or 1.0
            max_input = _number(settings.get("max_input_volume_ul")) or 5.0
            if volume < min_input - 1e-9 or volume > max_input + 1e-9:
                feasible, feasibility = False, "input_volume_limit"
                warnings.append(f"Stock requires {volume:g} µL; allowed input is {min_input:g}–{max_input:g} µL")
        if matched and volume is not None and not math.isclose(volume, input_volume, rel_tol=1e-6, abs_tol=1e-6):
            warnings.append(f"Recorded stock requires {volume:g} µL instead of the planned {input_volume:g} µL; use the recorded-stock volume")
        available = _available_mass(part.get("yield_ng"))
        if not length:
            warnings.append("Input construct length missing")
        if not part.get('_prepared_nested') and not (constrained and is_backbone) and (not part.get("plate_id") or not part.get("well")):
            warnings.append("Plate identifier or well missing")
        if available is None and not (constrained and is_backbone):
            warnings.append("Available mass unknown")
        if volume is not None and volume < 0.5 and not (constrained and is_backbone):
            warnings.append("Pipetting volume below 0.5 µL; prepare a dilution")
        if mass is not None and available is not None and mass > available and not (constrained and is_backbone):
            warnings.append("Required mass exceeds uploaded available mass")
        rows.append({
            "id": part.get("id"), "name": part.get("name", ""), "role": "backbone" if is_backbone else "insert",
            "plate_id": part.get("plate_id"), "well": part.get("well"), "length_bp": length or None,
            "concentration_ng_ul": concentration, "concentration_basis": basis,
            "molarity_nm": concentration * 1_000_000 / (length * 660) if concentration and length else None,
            "target_fmol": fmol, "target_ng": mass, "volume_ul": volume,
            "target_ng_ul": planned_stock, "input_volume_ul": plan["input_volume_ul"] if plan else input_volume,
            "feasible": feasible, "feasibility": feasibility,
            "available_ng": available,
            "resuspension_ul": plan["resuspension_ul"] if plan else available / planned_stock if available is not None and planned_stock else None,
            "recorded_resuspension_ul": _number(part.get("resuspension_ul")), "warnings": warnings,
        })
    return rows


def reaction_summary(rows: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    target = _number(settings.get("reaction_volume_ul")) or 20.0
    master = _number(settings.get("master_mix_volume_ul"))
    if settings.get("master_mix_volume_ul") == 0:
        master = 0.0
    missing = any(row.get("volume_ul") is None for row in rows)
    dna = sum(row.get("volume_ul") or 0 for row in rows) if not missing else None
    water = target - dna - master if dna is not None and master is not None else None
    warnings = []
    if missing:
        warnings.append("Incomplete DNA volumes prevent a complete reaction plan")
    if any(row.get("feasible") is False for row in rows):
        warnings.append("One or more DNA inputs cannot meet the mass, resuspension, or input-volume limits")
    if master is None:
        warnings.append("Master mix / other reagent volume missing")
    if water is not None and water < 0:
        warnings.append("Reaction overfilled: DNA and other reagents exceed target volume")
    if not rows:
        warnings.append("No assembly parts selected")
    return {"dna_volume_ul": dna, "master_mix_volume_ul": master, "water_volume_ul": water, "reaction_volume_ul": target, "warnings": warnings}


def make_workbook(
    fragments: list[dict[str, Any]],
    assembly: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> bytes:
    """Build an editable, printable resuspension and assembly planning workbook."""
    settings = settings or {}
    no_backbone = bool(settings.get("no_backbone"))
    wb = Workbook()
    wb.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True)
    settings_ws = wb.active
    settings_ws.title = "Settings"
    matched = settings.get("resuspension_mode") == "one_ul"
    constrained = settings.get("resuspension_mode") == "constrained"
    mode = "constrained" if constrained else "one_ul" if matched else "fixed_stock"
    input_volume = _number(settings.get("input_volume_ul")) or 1.0
    backbone_pmol = _number(settings.get("backbone_pmol")) or .05
    preferred_resuspension = _number(settings.get("preferred_resuspension_ul")) or 50.0
    max_resuspension = _number(settings.get("max_resuspension_ul")) or 99.99
    min_input = _number(settings.get("min_input_volume_ul")) or 1.0
    max_input = _number(settings.get("max_input_volume_ul")) or 5.0
    target = _number(settings.get("target_stock_ng_ul")) or 20.0
    backbone_mass = _number(settings.get("backbone_ng")) or 50.0
    insert_ratio = _number(settings.get("insert_ratio")) or (1.0 if matched or constrained else 2.0)
    reaction = _number(settings.get("reaction_volume_ul")) or 20.0
    master_mix = _number(settings.get("master_mix_volume_ul"))
    # A real zero master mix is meaningful, but absence is not an assumed zero.
    if settings.get("master_mix_volume_ul") == 0:
        master_mix = 0.0
    parts = list((assembly or {}).get("parts") or [])
    calculated_rows = calculate_volumes(parts, settings)
    backbone_part = {} if no_backbone else next((p for p in parts if p.get("role") == "backbone" or p.get("is_backbone")), parts[0] if parts else {})
    backbone_len = None if no_backbone else _number(settings.get("backbone_length_bp")) or _construct_length(backbone_part) or None
    if constrained:
        backbone_mass = backbone_pmol * 1000 * backbone_len * 660 / 1_000_000 if backbone_len else None
    backbone_stock = _number(settings.get("backbone_stock_ng_ul")) or _number(backbone_part.get("stock_ng_ul"))
    settings_ws.append(["Golden Gate planning settings", "Value", "Units / interpretation"])
    setting_rows = [
        ("Target stock concentration", target, "ng/µL; planned resuspension target, not a measured stock"),
        ("Backbone input mass", f'=IF(B11="constrained",IF(B8="","",B13*1000*B8*B9/1000000),{backbone_mass or 50:g})', "ng per reaction; derived from pmol in constrained mode; overwrite for legacy mass plans"),
        ("Backbone stock concentration", backbone_stock, "ng/µL; enter actual saved/measured concentration"),
        ("Insert : backbone molar ratio", insert_ratio, "per insert molecule, relative to backbone"),
        ("Total reaction volume", reaction, "µL; editable planning target"),
        ("Master mix / other reagents", master_mix, "µL; include all non-DNA additions except water"),
        ("Backbone construct length", backbone_len, "bp; full input molecule including adapters"),
        ("dsDNA molecular-weight factor", 660, "g/mol/bp"),
        ("Allow target-stock estimates", 1 if settings.get("assume_target_stock") else 0, "0 = require actual stock; 1 = allow estimates using target stock. Estimates are labeled ASSUMED."),
        ("Resuspension mode", mode, "constrained = configured molar amount, ratio, aliquot limits and resuspension cap; legacy modes: one_ul, fixed_stock"),
        ("Input volume", input_volume, "µL per fragment when using molar-matched planned stocks"),
        ("Backbone amount", backbone_pmol, "pmol per reaction; 0.05 pmol = 50 fmol"),
        ("Preferred resuspension", preferred_resuspension, "µL; adjusted to the feasible interval, at 0.01 µL precision"),
        ("Resuspension cap", max_resuspension, "µL; configured maximum resuspension volume"),
        ("Minimum DNA input", min_input, "µL per fragment"),
        ("Maximum DNA input", max_input, "µL per fragment"),
        ("No backbone", 1 if no_backbone else 0, "1 = fragment-only assembly; each input uses the specified molar amount without a backbone length reference"),
    ]
    for row in setting_rows:
        settings_ws.append(list(row))
    settings_ws.append(["Calculation guide", None, None])
    guides = [
        "Resuspension volume (µL) = available mass (ng) / target stock (ng/µL).",
        "Molar-matched target stock (ng/µL) = backbone mass × fragment bp ÷ backbone bp × molar ratio ÷ input volume.",
        "Constrained: required ng = input pmol × 1000 × ratio × physical bp × 660 / 1,000,000; solvent volume and aliquots follow Settings.",
        "dsDNA amount (fmol) = mass (ng) × 1,000,000 / [length (bp) × 660].",
        "Stock molarity (nM) = stock (ng/µL) × 1,000,000 / [length (bp) × 660].",
        "Volume to use (µL) = required mass (ng) / actual stock (ng/µL).",
        "Buffer and adapters are included in full construct length for input molarity.",
        "Blank cells mean unknown. A calculated resuspension plan is not a recorded or measured stock.",
        "Yield is the uploaded available mass; confirm remaining material after prior use.",
        "Blue cells are editable inputs. Green cells contain formulas; recalculate in Excel before printing.",
    ]
    for guide in guides:
        settings_ws.append([guide])
        settings_ws.merge_cells(start_row=settings_ws.max_row, start_column=1, end_row=settings_ws.max_row, end_column=3)
    for row in range(2, 19):
        settings_ws.cell(row, 2).fill = PatternFill("solid", fgColor="E8F1FF")
    dv = DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True)
    dv.error = "Enter a positive number or leave blank when unknown."
    dv.errorTitle = "Positive value required"
    dv.showErrorMessage = True
    settings_ws.add_data_validation(dv)
    dv.add("B2:B6")
    dv.add("B8:B9")
    dv.add("B12")
    dv.add("B13:B17")
    planned_dv = DataValidation(type="whole", operator="between", formula1="0", formula2="1")
    planned_dv.error = "Use 0 to require actual stock or 1 to allow planning estimates."
    planned_dv.showErrorMessage = True
    settings_ws.add_data_validation(planned_dv)
    planned_dv.add("B10")
    planned_dv.add("B18")
    mode_dv = DataValidation(type="list", formula1='"constrained,fixed_stock,one_ul"')
    mode_dv.showErrorMessage = True
    settings_ws.add_data_validation(mode_dv)
    mode_dv.add("B11")

    def constrained_stock_formula(mass: str, available: str) -> str:
        low = f'({available}/{mass}*Settings!B16)'
        high = f'MIN({available}/{mass}*Settings!B17,Settings!B15)'
        rounded_low = f'CEILING({low}-0.000000001,0.01)'
        rounded_high = f'FLOOR({high}+0.000000001,0.01)'
        volume = f'MAX({rounded_low},MIN(ROUND(Settings!B14,2),{rounded_high}))'
        missing = f'OR({mass}="",{mass}<=0,{available}="",AND(Settings!B18<>1,OR(Settings!B8="",Settings!B8<=0)),Settings!B16<=0,Settings!B17<Settings!B16,Settings!B15<=0)'
        impossible = f'OR({available}<{mass},{low}>Settings!B15,{rounded_low}>{rounded_high})'
        return f'IF({missing},"",IF({impossible},"",{available}/{volume}))'

    inventory = wb.create_sheet("Resuspension inventory")
    inventory_headers = ["Fragment ID", "Name", "Plate identifier", "Well", "Construct bp", "Available mass ng", "Target stock ng/µL", "Plan: add µL", "Recorded resuspension µL", "Saved stock ng/µL", "Stock nM", "Stock basis", "Notes / warnings"]
    inventory.append(inventory_headers)
    inventory_index = {}
    selected_backbone_key = backbone_part.get("id") or backbone_part.get("name")
    planned_fragments = [dict(fragment, is_backbone=bool(
        fragment.get("is_backbone") or fragment.get("role") == "backbone" or
        selected_backbone_key and (fragment.get("id") or fragment.get("name")) == selected_backbone_key
    )) for fragment in fragments]
    planned_settings = dict(settings, backbone_length_bp=backbone_len)
    plans = resuspension_plan(planned_fragments, planned_settings)
    for fragment, plan in zip(planned_fragments, plans):
        row = inventory.max_row + 1
        bp = _construct_length(fragment)
        yield_ng = _available_mass(fragment.get("yield_ng"))
        stock = _number(fragment.get("stock_ng_ul"))
        resuspension = _number(fragment.get("resuspension_ul"))
        warnings = []
        if yield_ng is None:
            warnings.append("Available mass unknown: no resuspension plan")
        if stock is None:
            warnings.append("Actual stock unknown: pipetting volume unavailable")
        if not fragment.get('_prepared_nested') and (not fragment.get("plate_id") or not fragment.get("well")):
            warnings.append("Plate/well incomplete")
        if not bp:
            warnings.append("Construct length unknown")
        if (matched or constrained) and not backbone_len and not no_backbone:
            warnings.append("Backbone reference length unknown: no molar-matched plan")
        if constrained:
            warnings.extend(plan["warnings"])
        if fragment.get("notes"):
            warnings.append(str(fragment["notes"]))
        ratio_source = "1" if fragment.get("is_backbone") else "Settings!B5"
        constrained_mass = f'(Settings!B13*1000*E{row}*Settings!B9/1000000*{ratio_source})'
        constrained_target = constrained_stock_formula(constrained_mass, f'F{row}')
        target_formula = f'=IF(Settings!B11="constrained",{constrained_target},IF(Settings!B11="one_ul",IF(Settings!B18=1,IF(OR(Settings!B12="",Settings!B12<=0,E{row}=""),"",Settings!B13*1000*E{row}*Settings!B9/1000000*{ratio_source}/Settings!B12),IF(OR(Settings!B3="",Settings!B8="",Settings!B8<=0,Settings!B12="",Settings!B12<=0,E{row}=""),"",Settings!B3*E{row}/Settings!B8*{ratio_source}/Settings!B12)),Settings!B2))'
        if constrained and fragment.get('is_backbone'):
            warnings=list(plan['warnings'])
            target_formula=f'=IF(AND(Settings!B4<>"",Settings!B4>0),Settings!B4,"")'
        inventory.append([
            _safe_cell(fragment.get("id", "")), _safe_cell(fragment.get("name", "")), _safe_cell(fragment.get("plate_id", "")), _safe_cell(fragment.get("well", "")), bp or None,
            yield_ng, target_formula, f'=IF(OR(F{row}="",G{row}="",G{row}<=0),"",F{row}/G{row})', resuspension, stock,
            f'=IF(OR(J{row}="",E{row}=""),"",J{row}*1000000/(E{row}*Settings!B9))',
            _safe_cell(fragment.get("concentration_basis") or ("recorded; basis unspecified" if stock else "unknown")), _safe_cell("; ".join(warnings)),
        ])
        if fragment.get('_planner_stock_fixed'):
            inventory.cell(row,7,f'=IF(J{row}="","",J{row})')
            inventory.cell(row,8,f'=IF(I{row}="","",I{row})')
        if constrained and fragment.get('is_backbone'):
            inventory.cell(row,8,None).value=None
        for key in (fragment.get("id"), fragment.get("name")):
            if key is not None:
                inventory_index[str(key)] = row
        for column in (6, 9, 10):
            inventory.cell(row, column).fill = PatternFill("solid", fgColor="E8F1FF")
        for column in (7, 8, 11):
            inventory.cell(row, column).fill = PatternFill("solid", fgColor="EAF5ED")
        inventory.cell(row, 8).comment = Comment("Planned total solvent volume, assuming the reported mass is fully available. Enter actual stock separately after resuspension.", "Golden Gate planner")

    # A computed snapshot is printable immediately, even in viewers that do not
    # recalculate Excel formulas. The editable inventory remains authoritative.
    plan_ws = wb.create_sheet("Resuspension plan")
    plan_ws.append(["Resuspension plan — export snapshot", mode, "No backbone" if no_backbone else f"Reference: {backbone_len or 'unknown'} bp", f"Each input: {backbone_pmol:g} pmol" if no_backbone else f"Backbone: {backbone_mass:g} ng" if backbone_mass else "Backbone mass unknown", f"Insert ratio: {insert_ratio:g}", f"Input: {min_input:g}–{max_input:g} µL; resuspend ≤{max_resuspension:g} µL" if constrained else f"Input: {input_volume:g} µL" if matched else "Fixed stock; assembly volumes on pipetting sheet"])
    plan_ws.append(["Fragment", "Plate identifier", "Well", "Construct bp", "Available ng", "Target ng/µL", "Add µL", "Use µL", "Target fmol", "Basis / checks"])
    for plan in plans:
        plan_ws.append([
            _safe_cell(plan["name"]), _safe_cell(plan["plate_id"]), _safe_cell(plan["well"]), plan["physical_length"], plan["yield_ng"],
            plan["target_ng_ul"], plan["resuspension_ul"], plan["input_volume_ul"] if plan.get('manual_stock') or (matched or constrained) and plan["target_ng_ul"] is not None else None, plan["target_fmol"] if matched or constrained else None,
            _safe_cell((plan.get('stock_basis') or ("Manual backbone stock" if plan.get("manual_stock") else "Proposed constrained stock; " + plan["feasibility"] if constrained else "Proposed molar-matched stock" if matched else "Proposed fixed stock")) + ("" if plan.get("manual_stock") or plan.get('stock_basis') else "; unmeasured") + ("; " + "; ".join(plan["warnings"]) if plan["warnings"] else "")),
        ])
    _format_sheet(plan_ws, [25, 24, 8, 13, 13, 14, 13, 11, 13, 57], header_row=2, paper="A3")
    for row in plan_ws.iter_rows(min_row=3):
        for cell in row[4:9]:
            cell.number_format = "0.00"

    # Import locally: the export module also serves standalone sequence-file
    # parsing and does not need the assembly engine until a workbook is made.
    from .sequence_engine import digest_fragment, restriction_sites, DUAL_ENZYME

    selection = wb.create_sheet("Fragment selection")
    selection.append(["Fragment picking reference — enzyme inferred from the outermost paired adapters unless explicitly recorded."])
    selection.merge_cells("A1:H1")
    selection.append(["Fusion labels are shown on the submitted 5′→3′ strand; adjacent labels must match. Target length excludes both 4-base fusion labels."])
    selection.merge_cells("A2:H2")
    selection.append(["Fragment", "Plate identifier", "Well", "Cloning enzyme", "Left end", "Right end", "Target bp", "Digestion checks / retained restriction sites"])
    enzyme_names = {"bsai": "BsaI", "bsmbi": "BsmBI", "esp3i": "BsmBI", "bsmbiv2": "BsmBI", "bsmbi+bsai":DUAL_ENZYME, "bsai+bsmbi":DUAL_ENZYME}
    for fragment in fragments:
        seq = re.sub(r"\s", "", str(fragment.get("sequence") or fragment.get("construct_sequence") or "")).upper()
        explicit = enzyme_names.get(re.sub(r"[\s-]", "", str(fragment.get("cloning_enzyme") or fragment.get("enzyme") or "")).lower())
        candidates = {enzyme: digest_fragment(seq, enzyme) for enzyme in ("BsaI", "BsmBI", DUAL_ENZYME)}
        paired = [(enzyme, digest) for enzyme, digest in candidates.items() if digest.get("left_overhang") and digest.get("right_overhang")]
        if (assembly or {}).get('enzyme') == DUAL_ENZYME:
            enzyme, digest = DUAL_ENZYME, candidates[DUAL_ENZYME]
        elif explicit:
            enzyme, digest = explicit, candidates[explicit]
        elif paired:
            enzyme, digest = min(paired, key=lambda item: item[1].get("left_site_start", len(seq)) + len(seq) - item[1].get("right_site_start", 0) - 6)
        else:
            # Keep an unrecognised or unpaired donor visibly unresolved.
            sites = [site for site in restriction_sites(seq) if site["enzyme"] in candidates]
            enzyme = sites[0]["enzyme"] if sites else ""
            digest = candidates[enzyme] if enzyme else {"errors": ["No paired BsaI or BsmBI donor adapters detected."], "warnings": []}
        nested=[g for g in (assembly or {}).get('nested_assemblies',[]) if g['parent_fragment_id']==fragment.get('id')]
        checked=next((c for c in (assembly or {}).get('fragment_checks',[]) if c['id']==fragment.get('id') and not c['is_backbone']),None) if nested else None
        notes = ["ERROR: " + message for message in (checked or digest).get("errors", [])]
        notes.extend("WARNING: " + message for message in (checked or digest).get("warnings", []))
        if nested:
            notes.append('Nested cassette(s): '+', '.join(('Separate first' if g['mode']=='separate' else 'Together')+' / '+g['cassette']['enzyme'] for g in nested))
        target_seq = digest.get("target", "")
        if target_seq:
            retained = restriction_sites(digest.get("sequence") or target_seq)
            counts = {name: sum(site["enzyme"] == name for site in retained) for name in ("BsmBI", "BsaI", "BbsI", "HindIII")}
            additional = [f"{name}: {count}" for name, count in counts.items() if count and name != enzyme]
            if additional:
                notes.append("Retained sites — " + "; ".join(additional))
        if not notes:
            notes.append("Outer adapter checks pass")
        selection.append([
            _safe_cell(fragment.get("name", "")), _safe_cell(fragment.get("plate_id", "")), _safe_cell(fragment.get("well", "")),
            enzyme or "Unresolved", digest.get("left_overhang") or None, digest.get("right_overhang") or None,
            len(target_seq) if digest.get("left_overhang") else None, _safe_cell(" | ".join(notes)),
        ])
    _format_sheet(selection, [25, 24, 8, 13, 11, 11, 11, 63], header_row=3, paper="A4")
    selection.row_dimensions[1].height = 25
    selection.row_dimensions[2].height = 27
    selection.auto_filter.ref = f"A3:H{selection.max_row}"

    if assembly:
        def messages(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                return [value] if value else []
            if isinstance(value, dict):
                return [str(value.get("message") or value.get("detail") or value)]
            return [message for item in value for message in messages(item)]

        errors = messages(assembly.get("errors"))
        design_warnings = messages(assembly.get("warnings"))
        invalid = bool(errors) or assembly.get("valid") is False or str(assembly.get("status", "")).lower() in {"invalid", "failed", "blocked", "error"}
        if invalid and not errors:
            errors = ["Assembly is marked invalid. Review its sequence checks before ordering or assembling."]
        if invalid:
            status = f"BLOCKED — {len(errors)} assembly error(s). Planning worksheet only; resolve all errors before assembly."
        elif design_warnings:
            status = f"REVIEW — {len(design_warnings)} assembly warning(s). Review Assembly checks before use."
        else:
            status = "No blocking assembly checks reported. Verify concentrations and reaction volumes before use."
        checks_ws = wb.create_sheet("Assembly checks", 1)
        checks_ws.append(["Assembly validation", "Result / details"])
        checks_ws.append(["Status", status])
        checks_ws.append(["Assembly", _safe_cell(assembly.get("name") or "Selected assembly")])
        checks_ws.append(["Interpretation", "Sequence validity and pipetting readiness are separate checks. Unknown concentrations stay blank unless target-stock estimates are explicitly enabled."])
        for message in errors:
            checks_ws.append(["ERROR", _safe_cell(message)])
        for message in design_warnings:
            checks_ws.append(["WARNING", _safe_cell(message)])
        for message in reaction_summary(calculated_rows, settings)["warnings"]:
            checks_ws.append(["REACTION", _safe_cell(message)])
        if not errors and not design_warnings:
            checks_ws.append(["DESIGN", "No error or warning messages were supplied for this selected design."])
        _format_sheet(checks_ws, [22, 110], paper="A4")
        checks_ws.auto_filter.ref = None
        checks_ws.row_dimensions[2].height = 44
        for cell in checks_ws[2]:
            cell.fill = PatternFill("solid", fgColor="FDE7E6" if invalid else "FFF2D5" if design_warnings else "EAF5ED")
            cell.font = Font(name="Aptos", size=11, bold=True, color="8C2524" if invalid else "5E4313" if design_warnings else "245B38")
        pipetting = wb.create_sheet("Assembly pipetting")
        pipetting.append([f"Assembly: {assembly.get('name') or 'Selected assembly'}"])
        pipetting.merge_cells("A1:N1")
        pipetting.append([status])
        pipetting.merge_cells("A2:N2")
        headers = ["Order", "Role", "Fragment", "Plate identifier", "Well", "Input bp", "Ratio", "Required fmol", "Required ng", "Actual stock ng/µL", "Use µL", "Available ng", "Source / basis", "Checks"]
        pipetting.append(headers)
        for index, part in enumerate(parts, 1):
            row = pipetting.max_row + 1
            backbone = part is backbone_part
            inventory_row = inventory_index.get(str(part.get("id"))) or inventory_index.get(str(part.get("name")))
            bp = _construct_length(part)
            calculated = calculated_rows[index - 1]
            stock = calculated["concentration_ng_ul"]
            available = _available_mass(part.get("yield_ng"))
            length_value = "=Settings!B8" if backbone else (f"='Resuspension inventory'!E{inventory_row}" if inventory_row else bp or None)
            if backbone:
                stock_source = "Settings!B4"
            elif inventory_row:
                stock_source = f"'Resuspension inventory'!J{inventory_row}"
            else:
                stock_source = None
            constrained_proposal = constrained_stock_formula(f'I{row}', f'L{row}')
            proposed_stock = f'IF(Settings!B11="constrained",{constrained_proposal},IF(Settings!B11="one_ul",IF(OR(I{row}="",Settings!B12="",Settings!B12<=0),"",I{row}/Settings!B12),Settings!B2))'
            proposed_basis = 'IF(Settings!B11="constrained","ASSUMED proposed constrained stock; verify before pipetting",IF(Settings!B11="one_ul","ASSUMED proposed molar-matched stock; verify before pipetting","ASSUMED target stock; verify before pipetting"))'
            if stock_source:
                stock_value = f'=IF(AND({stock_source}<>"",{stock_source}>0),{stock_source},IF(Settings!B10=1,{proposed_stock},""))'
                basis_value = f'=IF(J{row}="","unknown",IF(AND(OR({stock_source}="",{stock_source}<=0),Settings!B10=1),{proposed_basis},"Recorded / entered stock"))'
                if part.get('_planner_stock_fixed'):
                    stock_value=f'=IF({stock_source}="","",{stock_source})'
                    basis_value=_safe_cell(calculated['concentration_basis'])
            elif _number(part.get("stock_ng_ul")):
                stock_value = _number(part.get("stock_ng_ul"))
                basis_value = _safe_cell(calculated["concentration_basis"])
            else:
                stock_value = f'=IF(Settings!B10=1,{proposed_stock},"")'
                basis_value = f'=IF(J{row}="","unknown",{proposed_basis})'
            if part.get('_prepared_nested'):
                stock_value=_number(part.get('stock_ng_ul'))
                basis_value='Prepared parent · manual stock'
            if backbone and constrained:
                stock_value='=IF(AND(Settings!B4<>"",Settings!B4>0),Settings!B4,"")'
                basis_value=f'=IF(J{row}="","Default backbone volume: 1 µL","Manual backbone stock")'
            checks = []
            if not backbone and stock is None and inventory_row is None:
                checks.append("Stock unknown")
            if not (constrained and backbone) and (not part.get("plate_id") or not part.get("well")):
                checks.append("Plate/well incomplete")
            pipetting.append([
                index, "Backbone" if backbone else "Insert", _safe_cell(part.get("name", "")), _safe_cell(part.get("plate_id", "")), _safe_cell(part.get("well", "")), length_value,
                1 if backbone else '=Settings!B5', f'=IF(Settings!B11="constrained",IF(OR(AND(Settings!B18<>1,OR(Settings!B8="",Settings!B8<=0)),F{row}=""),"",Settings!B13*1000*G{row}),IF(Settings!B18=1,IF(F{row}="","",Settings!B13*1000*G{row}),IF(OR(Settings!B3="",Settings!B8="",F{row}=""),"",Settings!B3*1000000/(Settings!B8*Settings!B9)*G{row})))',
                f'=IF(OR(H{row}="",F{row}=""),"",H{row}*F{row}*Settings!B9/1000000)', stock_value,
                f'=IF(OR(J{row}="",J{row}=0,I{row}=""),"",I{row}/J{row})',
                f'=IF(\'Resuspension inventory\'!F{inventory_row}="","",\'Resuspension inventory\'!F{inventory_row})' if inventory_row else available,
                basis_value,
                f'=IF(J{row}="","MISSING STOCK / INFEASIBLE PLAN; ",IF(K{row}<0.5,"<0.5 µL: dilute stock; ",""))&IF(AND(Settings!B11="constrained",K{row}<>"",OR(K{row}<Settings!B16,K{row}>Settings!B17)),"INPUT OUTSIDE LIMITS; ","")&IF(AND(Settings!B11="one_ul",K{row}<>"",ABS(K{row}-Settings!B12)>0.000001),"RECORDED STOCK: use calculated volume; ","")&IF(AND(L{row}<>"",I{row}>L{row}),"INSUFFICIENT MASS; ","")&"{_gb_escape("; ".join(checks)).replace(chr(34), chr(34)*2)}"',
            ])
            if backbone and constrained:
                pipetting.cell(row,11,f'=IF(OR(J{row}="",J{row}<=0),1,IF(I{row}="","",I{row}/J{row}))')
                pipetting.cell(row,14,'=""')
            for column in (7, 8, 9, 11):
                pipetting.cell(row, column).fill = PatternFill("solid", fgColor="EAF5ED")
        last_part = pipetting.max_row
        pipetting.append([])
        total_row = last_part + 2
        total_formula = f'=IF(COUNT(K4:K{last_part})<{len(parts)},"",SUM(K4:K{last_part}))' if parts else '=""'
        pipetting.append(["Total DNA volume µL", None, None, None, None, None, None, None, None, None, total_formula])
        pipetting.append(["Master mix / other reagents µL", None, None, None, None, None, None, None, None, None, '=IF(Settings!B7="","",Settings!B7)'])
        water_row = pipetting.max_row + 1
        pipetting.append(["Water µL", None, None, None, None, None, None, None, None, None, f'=IF(OR(K{total_row}="",Settings!B7=""),"",Settings!B6-K{total_row}-K{total_row + 1})', None, None, f'=IF(K{water_row}="","INCOMPLETE: missing stock or reagent volume",IF(K{water_row}<0,"OVERFILLED: reduce DNA/reagent volume","Volume fits planned reaction"))'])
        pipetting.append(["Final reaction volume µL", None, None, None, None, None, None, None, None, None, "=Settings!B6"])
        if parts and not no_backbone and not any(p.get("role") == "backbone" or p.get("is_backbone") for p in parts):
            pipetting.append(["Role note: first selected part treated as backbone; confirm this selection."])
            pipetting.merge_cells(start_row=pipetting.max_row, start_column=1, end_row=pipetting.max_row, end_column=14)
        _format_sheet(pipetting, [6, 10, 22, 20, 7, 9, 8, 11, 11, 13, 10, 11, 19, 32], header_row=3, paper="A3")
        pipetting.row_dimensions[2].height = 32
        pipetting["A2"].fill = PatternFill("solid", fgColor="FDE7E6" if invalid else "FFF2D5" if design_warnings else "EAF5ED")
        pipetting["A2"].font = Font(name="Aptos", size=11, bold=True, color="8C2524" if invalid else "5E4313" if design_warnings else "245B38")
        for row in range(4, last_part + 1):
            for column in (8, 9, 10, 11, 12):
                pipetting.cell(row, column).number_format = "0.00"

    _format_sheet(settings_ws, [42, 18, 78], paper="A4")
    _format_sheet(inventory, [11, 24, 21, 7, 10, 12, 12, 12, 14, 13, 11, 19, 35], paper="A3")
    for row in inventory.iter_rows(min_row=2):
        for cell in row[5:11]:
            cell.number_format = "0.00"
    for row in range(2, 10):
        settings_ws.cell(row, 2).number_format = "0.00"
    settings_ws["B10"].number_format = "0"
    settings_ws["B12"].number_format = "0.00"
    if assembly:
        nested_workbook_sheets(wb,[assembly])
    output = io.BytesIO()
    _flag_palindromic_overhangs(wb)
    label_workbook_plates(wb)
    wb.save(output)
    return output.getvalue()


def _flag_palindromic_overhangs(workbook):
    """Flag only explicit fusion-label columns, keeping names and DNA unchanged."""
    from copy import copy
    from .sequence_engine import reverse_complement
    columns={'Fragment selection':(3,(5,6)),'Nested assemblies':(1,(5,6))}
    for title,(header_row,indices) in columns.items():
        if title not in workbook.sheetnames:continue
        sheet=workbook[title]
        for index in indices:
            for cells in sheet.iter_rows(min_row=header_row+1,min_col=index,max_col=index):
                cell=cells[0];label=str(cell.value or '').strip().upper()
                if not re.fullmatch('[ACGT]{4}',label) or label!=reverse_complement(label):continue
                cell.fill=PatternFill('solid',fgColor='FFF1A3')
                font=copy(cell.font);font.color='624800';cell.font=font
                cell.comment=Comment('Palindromic overhang; can self-ligate.','Junction')



def _format_sheet(sheet: Any, widths: list[int], header_row: int = 1, paper: str = "A4") -> None:
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3 if paper == "A3" else sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = f"1:{header_row}"
    sheet.print_options.horizontalCentered = True
    sheet.page_margins.left = sheet.page_margins.right = 0.25
    sheet.page_margins.top = sheet.page_margins.bottom = 0.4
    sheet.oddFooter.center.text = "Page &P of &N"
    sheet.oddFooter.right.text = "Golden Gate planner"
    for col, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    for row in sheet.iter_rows():
        for cell in row:
            cell.font = Font(name="Aptos", size=10, color="172B3A")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for cell in sheet[header_row]:
        cell.fill = PatternFill("solid", fgColor="173E4C")
        cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
    sheet.row_dimensions[header_row].height = 34
    for row in range(header_row + 1, sheet.max_row + 1):
        sheet.row_dimensions[row].height = 44 if sheet.title != "Settings" else 30
        if row % 2 == 0:
            for cell in sheet[row]:
                if cell.fill.patternType is None:
                    cell.fill = PatternFill("solid", fgColor="F3F7F8")
    sheet.print_area = f"A1:{get_column_letter(len(widths))}{sheet.max_row}"
    if sheet.title != "Settings":
        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(len(widths))}{sheet.max_row if sheet.title != 'Assembly pipetting' else header_row + len([sheet.cell(r, 1).value for r in range(header_row+1, sheet.max_row+1) if isinstance(sheet.cell(r, 1).value, int)])}"


def nested_workbook_sheets(wb, assemblies):
    """Print nested recipes and their physically separate input reactions."""
    if not any(a.get('nested_assemblies') for a in assemblies):
        return
    summary=wb.create_sheet('Nested assemblies')
    summary.append(['Assembly','Parent','Cassette enzyme','Mode','5′ fusion','3′ fusion','Order','Nested fragment','Plate','Well','Prepared stock ng/µL','Checks'])
    pipetting=wb.create_sheet('Nested reactions')
    pipetting.append(['Assembly','Stage','Enzyme','Fragment / reagent','Plate','Well','Physical bp','Stock ng/µL','Required ng','Required fmol','Use µL','Basis','Checks'])
    resuspend=wb.create_sheet('Nested resuspension')
    resuspend.append(['Assembly','Stage','Fragment','Plate','Well','Physical bp','Yield ng','Resuspend µL','Stock ng/µL','Use µL','Checks'])
    for assembly in assemblies:
        name=assembly.get('name','')
        for group in assembly.get('nested_assemblies',[]):
            for index,child in enumerate(group['children'],1):
                summary.append([_safe_cell(name),_safe_cell(group['parent_name']),group['cassette']['enzyme'],
                    'Separate first' if group['mode']=='separate' else 'Together',group['cassette']['left_overhang'],group['cassette']['right_overhang'],index,
                    _safe_cell(child['name']),_safe_cell(child.get('plate_id','')),_safe_cell(child.get('well','')),group.get('prepared_stock_ng_ul'),
                    _safe_cell('; '.join(group['errors']) or 'Pass')])
        for stage in assembly.get('nested_reactions',[]):
            reaction=stage['reaction']
            for part in reaction['rows']:
                pipetting.append([_safe_cell(name),_safe_cell(stage['name']),stage['enzyme'],_safe_cell(part['name']),_safe_cell(part.get('plate_id','')),_safe_cell(part.get('well','')),
                    part['length_bp'],part['concentration_ng_ul'],part['target_ng'],part['target_fmol'],part['volume_ul'],_safe_cell(part['concentration_basis']),_safe_cell('; '.join(stage['errors']+part['warnings']))])
            for label,volume in [('Other reagents',reaction['master_mix_ul']),('Water',reaction['water_ul']),('Total',reaction['reaction_volume_ul'])]:
                pipetting.append([_safe_cell(name),_safe_cell(stage['name']),stage['enzyme'],label,None,None,None,None,None,None,volume,None,_safe_cell('; '.join(reaction['warnings']))])
            for part in stage['resuspension']['rows']:
                resuspend.append([_safe_cell(name),_safe_cell(stage['name']),_safe_cell(part['name']),_safe_cell(part.get('plate_id','')),_safe_cell(part.get('well','')),part['physical_length'],part['yield_ng'],part['resuspension_ul'],part['target_ng_ul'],part['input_volume_ul'],_safe_cell('; '.join(part['warnings']))])
    for sheet,widths in [(summary,[24,26,17,17,11,11,8,27,24,9,21,65]),(pipetting,[24,30,17,27,24,9,12,15,14,15,12,40,65]),(resuspend,[24,30,27,24,9,12,14,15,15,12,65])]:
        _format_sheet(sheet,widths,paper='A3')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,float):cell.number_format='0.00'


def build_list_workbook(items):
    """Print a separate, current reaction plan for each queued assembly."""
    wb=Workbook()
    overview=wb.active
    overview.title='Build list'
    overview.append(['Assembly','Enzyme','Status','Fragments','Backbone','bp','DNA µL','Other reagents µL','Water µL','Total µL','Checks'])
    pipetting=wb.create_sheet('Pipetting')
    pipetting.append(['Assembly','Enzyme','Order','Role','Fragment / reagent','Plate','Well','Physical bp','Stock ng/µL','Required ng','Required fmol','Use µL','Basis','Checks'])
    resuspension=wb.create_sheet('Resuspension')
    resuspension.append(['Assembly','Fragment','Plate','Well','Physical bp','Yield ng','Target ng/µL','Resuspend µL','Use µL','Checks'])
    settings_ws=wb.create_sheet('Reaction settings')
    settings_ws.append(['Assembly','DNA pmol','Insert ratio','Minimum input µL','Maximum input µL','Resuspend target µL','Resuspend cap µL','Backbone stock ng/µL','Total µL','Other reagents µL'])
    for item in items:
        request=item['request']
        name=request['name']
        plan=item.get('plan')
        settings=request['settings']
        reaction=plan['reaction'] if plan else {}
        checks=([item['error']] if item.get('error') else [])+((plan['errors']+reaction['warnings']) if plan else [])
        backbone=next((p['name'] for p in plan['parts'] if p['role']=='backbone'),'No backbone') if plan else ''
        rows=reaction.get('rows',[])
        overview.append([_safe_cell(name),request['enzyme'],item['status'],len(request['fragment_ids']),_safe_cell(backbone),plan['length'] if plan else None,
            sum(p['volume_ul'] for p in rows) if rows and all(p['volume_ul'] is not None for p in rows) else None,
            reaction.get('master_mix_ul'),reaction.get('water_ul'),reaction.get('reaction_volume_ul'),_safe_cell('; '.join(checks))])
        settings_ws.append([_safe_cell(name)]+[settings.get(key) for key in ('backbone_pmol','insert_ratio','min_input_volume_ul','max_input_volume_ul','preferred_resuspension_ul','max_resuspension_ul','backbone_stock_ng_ul','reaction_volume_ul','master_mix_volume_ul')])
        if not plan:continue
        for index,part in enumerate(rows,1):
            pipetting.append([_safe_cell(name),request['enzyme'],index,part['role'],_safe_cell(part['name']),_safe_cell(part.get('plate_id') or ''),_safe_cell(part.get('well') or ''),part['length_bp'],
                part['concentration_ng_ul'],part['target_ng'],part['target_fmol'],part['volume_ul'],_safe_cell(part['concentration_basis']),_safe_cell('; '.join(plan['errors']+part['warnings']))])
        for label,volume in [('Other reagents',reaction['master_mix_ul']),('Water',reaction['water_ul'])]:
            pipetting.append([_safe_cell(name),request['enzyme'],None,'Reagent',label,None,None,None,None,None,None,volume,None,_safe_cell('; '.join(reaction['warnings']))])
        for part in plan['resuspension']['rows']:
            if part.get('manual_stock'):continue
            resuspension.append([_safe_cell(name),_safe_cell(part['name']),_safe_cell(part.get('plate_id') or ''),_safe_cell(part.get('well') or ''),part['physical_length'],part['yield_ng'],part['target_ng_ul'],part['resuspension_ul'],part['input_volume_ul'],_safe_cell('; '.join(part['warnings']))])
    for sheet,widths in [(overview,[25,10,17,10,22,10,13,17,13,13,65]),(pipetting,[25,10,8,12,28,25,8,12,14,14,14,12,42,65]),(resuspension,[25,28,25,8,13,13,15,15,12,65]),(settings_ws,[25,12,12,15,15,17,17,20,12,18])]:
        _format_sheet(sheet,widths,paper='A3')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,float):cell.number_format='0.00'
    nested_workbook_sheets(wb,[item['plan'] for item in items if item.get('plan')])
    output=io.BytesIO()
    _flag_palindromic_overhangs(wb)
    label_workbook_plates(wb)
    wb.save(output)
    return output.getvalue()
