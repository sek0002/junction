"""Authenticated design previews and downloads; shared inventory is read only."""
import csv
import io
import re
from datetime import datetime
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from . import database as store
from .design_engine import TYPE_II, design
from .exports import genbank_bytes
from .sequence_engine import find_backbone_slots, fragment_orientations

router = APIRouter(prefix='/api/design')
Enzyme = Literal['BsaI', 'BsmBI', 'BsmBI + BsaI']


class Variant(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sequence: str = Field(min_length=1, max_length=100000)


class Section(BaseModel):
    mode: Literal['constant', 'dynamic'] = 'constant'
    variants: list[Variant] = Field(default_factory=list, max_length=8)
    name: str = Field(min_length=1, max_length=100)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Entry(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal['fragment', 'placeholder']
    name: str = Field(default='Insert', max_length=100)
    fragment_id: int | None = Field(default=None, gt=0)
    reverse: bool = False
    sequence: str = Field(default='', max_length=100000)
    sections: list[Section] = Field(default_factory=list, max_length=100)


class DesignRequest(BaseModel):
    name: str = Field(default='New design', min_length=1, max_length=100)
    enzyme: Enzyme = 'BsaI'
    adapter_enzyme: Literal['BsaI', 'BsmBI'] = 'BsaI'
    backbone_id: int | None = Field(default=None, gt=0)
    slot_id: str | None = Field(default=None, max_length=100)
    entries: list[Entry] = Field(default_factory=list, max_length=100)
    left_overhang: str = Field(default='', pattern='^(?:[ACGT]{4})?$')
    right_overhang: str = Field(default='', pattern='^(?:[ACGT]{4})?$')
    window: int = Field(default=20, ge=0, le=100)
    avoid_sites: list[str] = Field(default_factory=list, max_length=16)
    excluded_overhangs: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode='after')
    def bounded(self):
        if sum(len(entry.sequence) + sum(len(v.sequence) for s in entry.sections for v in s.variants) for entry in self.entries) > 150000:
            raise ValueError('Use at most 150,000 insert bases per design.')
        if sum(len(entry.sections) for entry in self.entries) > 100:
            raise ValueError('Use at most 100 highlighted sections per design.')
        for entry in self.entries:
            if any(section.variants and section.mode != 'dynamic' for section in entry.sections):
                raise ValueError('Pasted variants belong to Dynamic regions.')
            sections = sorted(entry.sections,key=lambda section:section.start)
            if any(left.end > right.start for left,right in zip(sections,sections[1:])):
                raise ValueError('Highlighted regions must not overlap.')
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError('Each design entry needs a unique identifier.')
        if any(enzyme not in TYPE_II for enzyme in self.avoid_sites):
            raise ValueError('Unknown restriction enzyme in exclusions.')
        if any(not re.fullmatch('[ACGT]{4}', label) for label in self.excluded_overhangs):
            raise ValueError('Excluded overhangs must each contain four A/C/G/T bases.')
        return self


@router.get('/references')
def references(enzyme: Enzyme = 'BsaI'):
    backbones = []
    for plasmid in store.plasmids():
        if not plasmid['circular'] or not (plasmid['recipe'].get('backbone_template') or plasmid['recipe'].get('example_backbone')):
            continue
        all_slots = {key: find_backbone_slots(plasmid['sequence'], key)
                     for key in ('BsaI', 'BsmBI', 'BsmBI + BsaI')}
        backbones.append(dict(id=plasmid['id'], name=plasmid['name'], length=plasmid['length'],
                              slots=all_slots[enzyme], all_slots=all_slots))
    fragments = []
    for fragment in store.fragments():
        variants = fragment_orientations(fragment['sequence'], enzyme)
        fragments.append(dict(id=fragment['id'], name=fragment['name'], length=fragment['length'],
                              plate_id=fragment['plate_id'], well=fragment['well'],
                              variants=[{key: digest.get(key) for key in ('left_overhang', 'right_overhang', 'valid', 'errors', 'reverse_complement')}
                                        for digest in variants]))
    return dict(backbones=backbones, fragments=fragments, enzymes=list(TYPE_II))


def preview_design(payload, generate=True):
    backbone = store.get_plasmid(payload.backbone_id) if payload.backbone_id else None
    if payload.backbone_id and (not backbone or not backbone['circular'] or not (backbone['recipe'].get('backbone_template') or backbone['recipe'].get('example_backbone'))):
        raise HTTPException(422, 'Select an available circular backbone template.')
    entries = []
    for entry in payload.entries:
        row = entry.model_dump()
        if entry.kind == 'fragment':
            fragment = store.get_fragment(entry.fragment_id) if entry.fragment_id else None
            if not fragment:
                raise HTTPException(422, 'A selected fragment is archived or unavailable.')
            row.update(name=fragment['name'], sequence=fragment['sequence'])
        entries.append(row)
    result = design(entries, payload.enzyme, backbone, payload.slot_id,
                    payload.left_overhang, payload.right_overhang, payload.window,
                    payload.avoid_sites, payload.excluded_overhangs, generate, payload.adapter_enzyme)
    result['name'] = payload.name
    return result


@router.post('/preview')
def preview(payload: DesignRequest, generate: bool = False):
    return preview_design(payload, generate)


@router.post('/export')
def export(payload: DesignRequest, format: Literal['csv', 'fasta', 'gb'] = 'csv'):
    result = preview_design(payload)
    if not result['valid']:
        raise HTTPException(422, dict(message='Resolve design errors before exporting.', errors=result['errors']))
    if format != 'gb' and not result['generated']:
        raise HTTPException(422, 'No new fragments to export. Choose GenBank for the assembled sequence.')
    if format == 'gb':
        content = b''.join(genbank_bytes((f'{index:02d}_' + payload.name + '_' + item['name']) if len(result['assemblies']) > 1 else payload.name,
                                        item['sequence'], item['features'], circular=item['circular'])
                           for index,item in enumerate(result['assemblies'],1))
        mime = 'text/plain'
    elif format == 'fasta':
        content = ''.join('>' + re.sub(r'[\r\n>]', '_', row['name']) + '\n' + '\n'.join(row['sequence'][i:i+80] for i in range(0, len(row['sequence']), 80)) + '\n' for row in result['generated']).encode()
        mime = 'text/plain'
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Name', 'Sequence', 'Length nt', 'GC %', '5\u2032 overhang', '3\u2032 overhang', 'Adapter enzyme', 'Region', 'Insert start (1-based)', 'Insert end'])
        for row in result['generated']:
            name = row['name']
            if name.startswith(('=', '+', '-', '@')):
                name = "'" + name
            writer.writerow([name, row['sequence'], row['length'], round(row['gc'], 2), row['left_overhang'], row['right_overhang'], row['adapter_enzyme'], row['region_mode'], row['source_start'] + 1, row['source_end']])
        content, mime = output.getvalue().encode('utf-8-sig'), 'text/csv'
    day = datetime.now(ZoneInfo('Australia/Melbourne')).date().isoformat()
    filename = f'Design_{day}_{uuid4().hex[:12]}.{format}'
    return Response(content, media_type=mime, headers={'Content-Disposition': f'attachment; filename="{filename}"'})
