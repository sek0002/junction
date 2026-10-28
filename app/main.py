from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo
import hashlib
import csv
import io
import json
import sqlite3
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, Query
from fastapi.responses import FileResponse, Response, JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from . import database as store
from .version import VERSION
from .auth import AuthMiddleware, router as auth_router, user_id, check_plasmid_write
from .workspace import router as workspace_router, begin_comparison, finish_comparison
from .workbenches import router as workbench_router
from .worksheets import router as worksheet_router
from .design import router as design_router
from .imports import import_plate, parse_plate, dna
from .sequence_engine import assemble, digest_fragment, find_backbone_slots, restriction_sites, active_enzymes, fragment_orientations
from .exports import genbank_bytes, parse_sequence_file, make_workbook, calculate_volumes, reaction_summary, resuspension_plan, build_list_workbook
from .nested import prepare_nested, annotate_nested
from .comparison import compare_record, parse_comparison_file, MODES
from .backbone_examples import seed_backbone_examples
from .inventory import InventoryRules, get_rules, save_rules, inventory_records, linked_update, reset_records, apply_rules_to_records
from .bench_exports import FORMATS, guide_bytes, assembly_sections, build_sections, inventory_sections
from .plates import fragment_site_info
from .comparison_export import comparison_workbook
from .plate_exports import export_bytes as plate_export_bytes, MIME as PLATE_EXPORT_MIME
from .assembly_matrix import matrix_data, META_HEADERS
from .plate_labels import plate_aliases
from .build_genbank import build_genbank_zip
from .fragment_search import match_fragment

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 10 * 1024 * 1024


def seed_manifest_path():
    path = store.db_path().with_suffix('.sources.json')
    return path if path.exists() else ROOT/'data'/'golden_gate.sources.json'


def seed_source_files():
    manifest_path = seed_manifest_path()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf8'))
        if not isinstance(manifest, dict):
            raise ValueError('Database source manifest must be an object.')
        source_root = manifest_path.parent.resolve()
        sources = {}
        extensions = {'plate_files': {'.csv', '.tsv', '.xlsx'}, 'genbank_files': {'.gb', '.gbk'}}
        for key in ('plate_files', 'genbank_files'):
            entries = manifest.get(key, [])
            if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
                raise ValueError(f'Database source manifest {key} must be a list of paths.')
            sources[key] = []
            for entry in entries:
                path = (source_root / entry).resolve()
                if Path(entry).is_absolute() or not path.is_relative_to(source_root):
                    raise ValueError('Database source files must stay within the database directory.')
                if path.suffix.lower() not in extensions[key]:
                    raise ValueError(f'Unsupported database source file: {entry}')
                if not path.is_file():
                    raise ValueError(f'Database source file not found: {entry}')
                sources[key].append(path)
        plate_files, genbank_files = sources['plate_files'], sources['genbank_files']
    else:
        plate_files = sorted((ROOT/'examples').glob('platemap_*.csv'))
        genbank_files = sorted((ROOT/'examples').glob('*.gb'))
    return plate_files, genbank_files


def precalculated_seed_files():
    path=seed_manifest_path()
    if not path.exists():return set()
    manifest=json.loads(path.read_text(encoding='utf8'));entries=manifest.get('precalculated_plate_files',[])
    if not isinstance(entries,list) or any(not isinstance(entry,str) for entry in entries):
        raise ValueError('Database source manifest precalculated_plate_files must be a list of paths.')
    if set(entries)-set(manifest.get('plate_files',[])):
        raise ValueError('Precalculated plate files must be listed in plate_files.')
    return {(path.parent/entry).resolve() for entry in entries}


def retire_seed_plates():
    """Archive withdrawn default maps once when upgrading an existing database."""
    path=seed_manifest_path()
    manifest=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    plates=manifest.get('retired_plate_ids',[])
    if not isinstance(plates,list) or any(not isinstance(p,str) or not p for p in plates):
        raise ValueError('Database source manifest retired_plate_ids must be a list of plate IDs.')
    with store.connection() as db:
        for plate in plates:
            key='retired_seed_plate:'+plate
            if db.execute('SELECT 1 FROM settings WHERE key=?',(key,)).fetchone():continue
            db.execute('UPDATE plates SET archived_at=COALESCE(archived_at,CURRENT_TIMESTAMP) WHERE plate_id=?',(plate,))
            db.execute('INSERT INTO settings(key,value) VALUES(?,?)',(key,'true'))


def seed_examples():
    store.initialize()
    plate_files, genbank_files = seed_source_files()
    retire_seed_plates()
    precalculated=precalculated_seed_files()
    for path in plate_files:
        import_plate(path.read_bytes(), path.name,precalculated=path.resolve() in precalculated)
    for path in genbank_files:
        content = path.read_bytes()
        if store.import_exists(content,'genbank'):
            continue
        records = parse_sequence_file(content.decode('utf8'),path.name)
        with store.connection() as db:
            source_id = db.execute('INSERT INTO imports(filename,digest,kind,row_count) VALUES(?,?,?,?)',
                (path.name,hashlib.sha256(content).hexdigest(),'genbank',len(records))).lastrowid
        for record in records:
            store.save_plasmid(record['name'],record['sequence'],record.get('features'),
                notes='Previous design reference; not inferred from delivered plate maps.',source_id=source_id,
                circular=record.get('circular',True))
    seed_backbone_examples()


@asynccontextmanager
async def lifespan(app):
    seed_examples()
    yield


app = FastAPI(title='Junction — Golden Gate workbench',version=VERSION,lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(workbench_router)
app.include_router(worksheet_router)
app.include_router(design_router)
app.mount('/static',StaticFiles(directory=ROOT/'app'/'static'),name='static')


@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    if request.url.path.startswith('/api/auth/'):
        return JSONResponse({'detail':[{key:value for key,value in error.items() if key not in ('input','ctx')} for error in exc.errors()]},status_code=422)
    return await request_validation_exception_handler(request,exc)



@app.get('/',include_in_schema=False)
def home():
    html = (ROOT/'app'/'static'/'index.html').read_text(encoding='utf8')
    return HTMLResponse(html.replace('__JUNCTION_VERSION__', VERSION),headers={'Cache-Control':'no-cache'})


@app.get('/manifest.webmanifest',include_in_schema=False)
def web_manifest():
    return FileResponse(ROOT/'app'/'static'/'manifest.webmanifest',media_type='application/manifest+json',headers={'Cache-Control':'no-cache'})


@app.get('/service-worker.js',include_in_schema=False)
def service_worker():
    return FileResponse(ROOT/'app'/'static'/'service-worker.js',media_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})


@app.get('/api/health')
def health():
    return {'status':'ok','database':'SQLite','fragments':len(store.fragments()),'plasmids':len(store.plasmids())}


@app.get('/api/summary')
def summary():
    fragments = store.fragments()
    return {'fragments':len(fragments),'plates':len({p['plate_id'] for p in fragments}),
        'plasmids':len(store.plasmids()),'known_stocks':sum(p['stock_ng_ul'] is not None for p in fragments),
        'plate_ids':sorted({p['plate_id'] for p in fragments}),
        'plate_labels':plate_aliases(p['plate_id'] for p in store.plate_records(include_archived=True))}


@app.get('/api/library/metrics')
def library_metrics(enzyme:Literal['BsaI','BsmBI','BsmBI + BsaI']='BsaI'):
    from .sequence_engine import reverse_complement as revcomp
    from . import worksheets
    fragments=store.fragments();backbones=[p for p in store.plasmids() if p['circular'] and
        (p['recipe'].get('example_backbone') or p['recipe'].get('backbone_template')) and not p['recipe'].get('legacy_example')]
    junctions={}
    selected_enzyme=enzyme
    def add(overhang,enzyme,name,kind,errors=()):
        value=(overhang or '').upper()
        if len(value)!=4 or set(value)-set('ACGT'):return
        canonical=min(value,revcomp(value));item=junctions.setdefault(canonical,{'overhang':canonical,'reverse_complement':revcomp(canonical),'enzymes':set(),'fragments':set(),'backbones':set(),'problems':set()})
        item['enzymes'].add(enzyme);item[kind].add(name)
        item['problems'].update((kind,name,error) for error in errors)
    for fragment in fragments:
        for enzyme in ('BsaI','BsmBI','BsmBI + BsaI'):
            digest=digest_fragment(fragment['sequence'],enzyme)
            for side in ('left','right'):add(digest.get(side+'_overhang'),digest.get(side+'_adapter_enzyme',enzyme),fragment['name'],'fragments',digest.get('errors',[]) if enzyme==selected_enzyme else ())
            for nested in digest.get('nested_cassettes',[]):
                for side in ('left','right'):add(nested.get(side+'_overhang'),nested.get(side+'_boundary_enzyme',enzyme),fragment['name'],'fragments')
    for backbone in backbones:
        for enzyme in ('BsaI','BsmBI','BsmBI + BsaI'):
            for slot in find_backbone_slots(backbone['sequence'],enzyme):
                for side in ('left','right'):add(slot.get(side+'_overhang'),slot.get(side+'_boundary_enzyme',slot.get('enzyme',enzyme)),backbone['name'],'backbones',slot.get('errors',[]) if enzyme==selected_enzyme else ())
    with store.connection() as db:
        workspace=worksheets.wb.working(db);records=worksheets.registry(db,live=False)
    designs={d.get('id') for d in workspace.get('design',{}).get('designs',[])}
    for record in records:
        if record['scope']=='design':designs.update(d.get('id') for d in record['snapshot']['workspace'].get('design',{}).get('designs',[]))
    rows=[]
    for _,item in sorted(junctions.items()):
        row={key:sorted(value) if isinstance(value,set) else value for key,value in item.items() if key!='problems'}
        row['problems']=[{'source_type':kind,'source':name,'message':error} for kind,name,error in sorted(item['problems'])]
        rows.append(row)
    return {'backbones':len(backbones),'designs':len(designs-{None}),'qc_enzyme':selected_enzyme,'junctions':rows}


@app.get('/api/fragments')
def fragments(q: str=Query('',max_length=5000), enzyme:Literal['BsaI','BsmBI','BsmBI + BsaI']='BsaI', plate:str='', left:str='', right:str='', limit:int=Query(200,ge=1,le=1000)):
    result=[]
    for fragment in store.fragments():
        if plate and fragment['plate_id']!=plate:
            continue
        variants=fragment_orientations(fragment['sequence'],enzyme)
        parsed=next((d for d in variants if (not left or d.get('left_overhang')==left.upper()) and (not right or d.get('right_overhang')==right.upper())),None)
        if parsed is None:continue
        match=match_fragment(fragment,q,variants)
        if match is None:continue
        result.append({k:v for k,v in fragment.items() if k not in ('sequence','construct_sequence')} | {'digest':parsed,'forward_digest':variants[0],'reverse_complement':parsed['reverse_complement'],'orientation':parsed['orientation'],'sites':restriction_sites(fragment['sequence'])} | match)
    result.sort(key=lambda x:(-x['search_score'],x['name']))
    return result[:limit]


@app.get('/api/fragments/{fragment_id}')
def fragment(fragment_id:int,enzyme:Literal['BsaI','BsmBI','BsmBI + BsaI']='BsaI'):
    result=store.get_fragment(fragment_id)
    if result is None:
        raise HTTPException(404,'Fragment not found.')
    parsed=fragment_orientations(result['sequence'],enzyme)[0]
    return result | {'digest':parsed,'forward_digest':parsed,'reverse_complement':False,'orientation':1,'sites':restriction_sites(result['sequence'])}


class StockUpdate(BaseModel):
    yield_locked:bool | None=None
    yield_ng: float | None = Field(None,gt=0,lt=1e12)
    stock_ng_ul: float | None = Field(None,gt=0,lt=1e8)
    resuspension_ul: float | None = Field(None,gt=0,lt=1e8)
    derive:Literal['yield_ng','stock_ng_ul','resuspension_ul'] | None=None
    notes:str=Field('',max_length=2000)


@app.patch('/api/fragments/{fragment_id}')
def update_stock(fragment_id:int,payload:StockUpdate):
    part=store.get_fragment(fragment_id)
    if part is None:
        raise HTTPException(404,'Fragment not found.')
    updates=payload.model_dump(exclude_unset=True,exclude={'derive'})
    if updates.get('yield_locked') is None:
        updates.pop('yield_locked',None)
    try:
        updates=linked_update(part,updates,payload.derive)
    except ValueError as exc:
        raise HTTPException(422,str(exc))
    if updates:
        with store.connection() as db:
            db.execute('UPDATE fragments SET '+','.join(key+'=?' for key in updates)+' WHERE id=?',[*updates.values(),fragment_id])

    saved=store.get_fragment(fragment_id)
    return saved | {'inventory':inventory_records([saved])[0]}


@app.get('/api/inventory/rules')
def inventory_rules():
    return {'rules':get_rules(),'defaults':InventoryRules().model_dump()}


@app.put('/api/inventory/rules')
def update_inventory_rules(payload:InventoryRules):
    return {'rules':save_rules(payload.model_dump())}


@app.post('/api/inventory/rules/reset')
def reset_inventory_rules():
    return {'rules':save_rules({})}


@app.get('/api/inventory/records')
def inventory_values():
    return {'rows':inventory_records(),'rules':get_rules()}


class InventoryReset(BaseModel):
    fragment_ids:list[int] | None=Field(None,max_length=5000)


@app.post('/api/inventory/reset')
def reset_inventory(payload:InventoryReset):
    try:
        return {'count':reset_records(payload.fragment_ids)}
    except ValueError as exc:
        raise HTTPException(404,str(exc))


class InventoryApplyRules(BaseModel):
    fragment_ids:list[int]=Field(min_length=1,max_length=5000)
    rules:InventoryRules


@app.post('/api/inventory/apply-rules')
def apply_inventory_rules(payload:InventoryApplyRules):
    try:
        return {'count':apply_rules_to_records(payload.fragment_ids,payload.rules.model_dump())}
    except LookupError as exc:
        raise HTTPException(404,str(exc))
    except ValueError as exc:
        raise HTTPException(422,{'message':'Rules cannot be applied. No rows changed.','errors':exc.args[0]})


class BinSelection(BaseModel):
    fragment_ids:list[int]=Field(default_factory=list,max_length=5000)
    plasmid_ids:list[int]=Field(default_factory=list,max_length=5000)
    plate_ids:list[str]=Field(default_factory=list,max_length=5000)


@app.get('/api/bin')
def bin_contents():
    return {'rows':store.bin_items()}


@app.post('/api/bin/archive')
def archive_items(payload:BinSelection):
    try:
        return {'count':store.move_to_bin(payload.fragment_ids,payload.plasmid_ids,plate_ids=payload.plate_ids)}
    except ValueError as exc:
        raise HTTPException(404,str(exc))


@app.post('/api/bin/restore')
def restore_items(payload:BinSelection):
    try:
        return {'count':store.move_to_bin(payload.fragment_ids,payload.plasmid_ids,restore=True,plate_ids=payload.plate_ids)}
    except ValueError as exc:
        raise HTTPException(404,str(exc))


@app.get('/api/plates')
def plate_maps():
    return store.plate_records()


def plate_record(plate_id):
    record=next((row for row in store.plate_records(include_archived=True) if row['plate_id']==plate_id),None)
    if record is None:raise HTTPException(404,'Plate map not found.')
    return record


@app.get('/api/plates/export')
def export_plate_map(plate_id:str):
    plate=plate_record(plate_id)
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['Name','Plate ID','Well','Sequence','Construct sequence','Yield ng','Stock ng/ul','Resuspension ul','Notes','Archived'])
    for part in sorted(store.plate_fragments(plate_id),key=lambda p:(p['well'][0],int(p['well'][1:]))):
        writer.writerow([part.get(key,'') for key in ('name','plate_id','well','sequence','construct_sequence','yield_ng','stock_ng_ul','resuspension_ul','notes')]+[bool(plate['archived_at'] or part['archived_at'])])
    safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in plate_id)[:100] or 'Plate'
    return download(output.getvalue().encode('utf-8-sig'),safe+'.csv','text/csv')


@app.get('/api/plates/detail')
def plate_map_details(plate_id:str):
    record=plate_record(plate_id);parts=store.plate_fragments(plate_id)
    planned={p['id']:p for p in inventory_records(parts)}
    rows=[{k:v for k,v in part.items() if k not in ('sequence','construct_sequence')} |
        {'inventory':planned[part['id']]} | fragment_site_info(part['sequence'],part['construct_sequence'])
        for part in parts]
    return record | {'fragments':rows,'display_id':plate_aliases(p['plate_id'] for p in store.plate_records(include_archived=True))[plate_id]}


@app.get('/api/plates/well-list')
def export_plate_well_list(plate_id:str,format:Literal['pdf','csv','xlsx']='pdf',layout:Literal['auto','96','384']='auto'):
    plate=plate_map_details(plate_id)
    chosen=plate['format'] if layout=='auto' else int(layout)
    if chosen<plate['format']:raise HTTPException(422,'The selected layout cannot contain all occupied wells.')
    safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in plate['display_id'])[:100] or 'Plate'
    extension='csv.zip' if format=='csv' else format
    return download(plate_export_bytes(plate,format,chosen),safe+'-well-list.'+extension,PLATE_EXPORT_MIME[format])


@app.get('/api/plasmids')
def plasmids(enzyme:Literal['BsaI','BsmBI','BsmBI + BsaI']='BsmBI'):
    return [{k:v for k,v in p.items() if k!='sequence'} | {
        'slots':find_backbone_slots(p['sequence'],enzyme) if p['circular'] else [],
        'backbone_options':backbone_template_info(p['sequence'],True)} for p in store.plasmids()]


@app.get('/api/plasmids/{plasmid_id}')
def plasmid(plasmid_id:int):
    result=store.get_plasmid(plasmid_id)
    if not result:
        raise HTTPException(404,'Plasmid not found.')
    return result | {'restriction_sites':restriction_sites(result['sequence'],circular=result['circular']),
        'backbone_options':backbone_template_info(result['sequence'],True)}


class PlasmidUpdate(BaseModel):
    name:str | None=Field(None,min_length=1,max_length=100)

    @field_validator('name',mode='before')
    @classmethod
    def trim_name(cls,value):
        return value.strip() if isinstance(value,str) else value

    circular:bool | None=None
    backbone_template:bool | None=None


@app.patch('/api/plasmids/{plasmid_id}')
def update_plasmid(plasmid_id:int,payload:PlasmidUpdate):
    saved=plasmid(plasmid_id)
    if payload.name is not None and payload.circular is None and payload.backbone_template is None:
        try:store.rename_plasmid(plasmid_id,payload.name)
        except sqlite3.IntegrityError:raise HTTPException(409,'A plasmid with this name and sequence already exists.')
        return plasmid(plasmid_id)
    circular=payload.circular if payload.circular is not None else (True if payload.backbone_template else saved['circular'])
    template=payload.backbone_template if payload.backbone_template is not None else bool(saved['recipe'].get('backbone_template') and circular)
    options=backbone_template_info(saved['sequence'],circular)
    if template and not options['eligible']:
        raise HTTPException(422,'A backbone template must be circular and contain complete BsaI, BsmBI or dual-cut replacement cassettes, with no unpaired active cut sites.')
    try:store.update_plasmid_settings(plasmid_id,circular,options['enzymes'] if template else None,name=payload.name)
    except sqlite3.IntegrityError:raise HTTPException(409,'A plasmid with this name and sequence already exists.')
    return plasmid(plasmid_id)


@app.get('/api/plasmids/{plasmid_id}/genbank')
def plasmid_genbank(plasmid_id:int):
    p=plasmid(plasmid_id)
    return download(genbank_bytes(p['name'],p['sequence'],p['features'],circular=p['circular'],notes=p.get('notes')),p['name']+'.gb','text/plain')


def download(content,filename,media='application/octet-stream'):
    # Avoid user-controlled response header syntax.
    import re
    filename=re.sub(r'[^A-Za-z0-9_.-]+','_',filename)[:120]
    return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="{filename}"'})


class PlannerStockOverride(BaseModel):
    yield_ng:float=Field(gt=0,lt=1e12)
    stock_ng_ul:float=Field(gt=0,lt=1e8)
    resuspension_ul:float=Field(gt=0,lt=1e8)
    yield_locked:bool=True


class ReactionSettings(BaseModel):
    backbone_ng:float=Field(50,gt=0,allow_inf_nan=False)
    backbone_stock_ng_ul:float | None=Field(None,gt=0,allow_inf_nan=False)
    insert_ratio:float=Field(1,gt=0,allow_inf_nan=False)
    resuspension_mode:Literal['constrained','one_ul','fixed_stock']='constrained'
    backbone_pmol:float=Field(0.05,gt=0,allow_inf_nan=False)
    preferred_resuspension_ul:float=Field(50,gt=0,allow_inf_nan=False)
    max_resuspension_ul:float=Field(99.99,gt=0,allow_inf_nan=False)
    min_input_volume_ul:float=Field(1,gt=0,allow_inf_nan=False)
    max_input_volume_ul:float=Field(5,gt=0,allow_inf_nan=False)
    input_volume_ul:float=Field(1,gt=0,allow_inf_nan=False)
    backbone_length_bp:int | None=Field(None,gt=0,le=1000000000)
    target_stock_ng_ul:float=Field(20,gt=0,allow_inf_nan=False)
    reaction_volume_ul:float=Field(20,gt=0,allow_inf_nan=False)
    master_mix_volume_ul:float=Field(4,ge=0,allow_inf_nan=False)
    assume_target_stock:bool=False
    no_backbone:bool=False
    planner_stock_mode:Literal['saved','custom'] | None=None
    fragment_stock_overrides:dict[int,PlannerStockOverride]=Field(default_factory=dict,max_length=1000)


class ResuspensionRequest(ReactionSettings):
    backbone_id:int | None=None
    starter_fragment_id:int | None=None
    plate:str=''
    fragment_ids:list[int] | None=Field(None,max_length=1000)


def planner_parts(parts,settings):
    """Apply stock choices to copies for this plan; never write inventory records."""
    mode=settings.get('planner_stock_mode')
    if mode is None:
        return parts
    records={row['id']:row for row in inventory_records([p for p in parts if p.get('role')!='backbone' and not p.get('is_backbone') and not p.get('_prepared_nested')])} if mode=='saved' else {}
    overrides=settings.get('fragment_stock_overrides') or {}
    prepared=[]
    for part in parts:
        part=dict(part)
        if part.get('role')=='backbone' or part.get('is_backbone') or part.get('_prepared_nested'):
            prepared.append(part)
            continue
        override=overrides.get(part.get('id')) or overrides.get(str(part.get('id')))
        if override:
            part.update(override.model_dump() if isinstance(override,BaseModel) else override)
            part.update(_planner_stock_fixed=True,concentration_basis='Instance override')
        elif mode=='saved':
            record=records[part['id']]
            part.update({key:record[key] for key in ('yield_ng','stock_ng_ul','resuspension_ul','yield_locked')})
            part.update(_planner_stock_fixed=True,concentration_basis=record['concentration_basis'] if record['concentration_basis']=='Custom rule plan (unmeasured)' else 'Saved stock' if record['saved'] else 'Library planned stock (unmeasured)')
        else:
            part.update(stock_ng_ul=None,resuspension_ul=None,concentration_basis='Custom planned stock (unmeasured)')
        prepared.append(part)
    return prepared


def reference_settings(settings, backbone_id=None, starter_fragment_id=None, default_f1=True):
    """Use the selected physical DNA as the molarity reference, never a guessed length."""
    effective=settings.model_dump() if isinstance(settings,ReactionSettings) else dict(settings)
    if effective.get('planner_stock_mode'):
        effective['assume_target_stock']=effective['planner_stock_mode']=='custom'
        if effective['planner_stock_mode']=='saved':
            effective.update({key:value for key,value in get_rules().items() if key not in ('backbone_pmol','insert_ratio')})
    if backbone_id and starter_fragment_id:
        raise HTTPException(422,'Choose either a circular plasmid or a backbone fragment.')
    if effective.get('no_backbone') and (backbone_id or starter_fragment_id):
        raise HTTPException(422,'No backbone cannot be combined with a selected backbone reference.')
    if effective.get('resuspension_mode')=='constrained':
        validate_constrained_settings(effective)
    if effective.get('no_backbone'):
        effective['backbone_length_bp']=None
        effective['backbone_ng']=None
        if effective.get('resuspension_mode')=='constrained':
            validate_constrained_settings(effective)
        reference={'id':None,'type':'none','name':'Fragments','length_bp':None,
            'backbone_ng':None,'backbone_pmol':effective.get('backbone_pmol',0.05),
            'input_volume_ul':effective.get('input_volume_ul',1),'default_reference':False,
            'plate_id':'','well':''}
        effective['backbone_reference']=reference
        return effective,reference
    if backbone_id:
        source=store.get_plasmid(backbone_id)
        if source is None:
            raise HTTPException(404,'Backbone not found.')
        if not source['circular']:
            raise HTTPException(422,'A backbone plasmid must be circular.')
        source_type='plasmid'
        length=len(source['sequence'])
    else:
        source=store.get_fragment(starter_fragment_id) if starter_fragment_id else None
        if starter_fragment_id and source is None:
            raise HTTPException(404,'Backbone fragment not found.')
        if source is None and default_f1:
            defaults=[part for part in store.fragments() if part['name'].strip().casefold()=='f1']
            if len(defaults)!=1:
                raise HTTPException(422,'Select a backbone reference; a unique F1 fragment is not available.')
            source=defaults[0]
        if source is None:
            raise HTTPException(422,'Select a backbone plasmid or a backbone fragment.')
        source_type='fragment'
        length=source['physical_length']
    effective['backbone_length_bp']=length
    if effective.get('resuspension_mode')=='constrained':
        validate_constrained_settings(effective)
        effective['backbone_ng']=effective.get('backbone_pmol',0.05)*length*660/1000
    reference={'id':source['id'],'type':source_type,'name':source['name'],'length_bp':length,
        'backbone_ng':effective.get('backbone_ng',50),'backbone_pmol':effective.get('backbone_pmol',0.05),
        'input_volume_ul':effective.get('input_volume_ul',1),
        'default_reference':not bool(backbone_id or starter_fragment_id),
        'plate_id':source.get('plate_id',''),'well':source.get('well','')}
    effective['backbone_reference']=reference
    return effective,reference


def validate_constrained_settings(settings):
    if settings.get('min_input_volume_ul',1)>settings.get('max_input_volume_ul',5):
        raise HTTPException(422,'Minimum DNA input volume cannot exceed the maximum.')


def mark_inventory_reference(fragments,reference):
    # Roles apply only to this plan; saved inventories and stocks remain unchanged.
    return [part | {'role':'backbone'} if reference['type']=='fragment' and (part.get('id')==reference['id']
        or bool(reference['plate_id'] and reference['well'] and part.get('plate_id')==reference['plate_id'] and part.get('well')==reference['well'])) else part
        for part in fragments]


def inventory_plan(settings,backbone_id=None,starter_fragment_id=None,plate='',fragments=None):
    effective,reference=reference_settings(settings,backbone_id,starter_fragment_id)
    selected=store.fragments() if fragments is None else fragments
    if plate:
        selected=[part for part in selected if part['plate_id']==plate]
    requested=settings.fragment_ids if isinstance(settings,ResuspensionRequest) else None
    if requested is not None:
        selected=[part for part in selected if part['id'] in requested]
    marked=planner_parts(mark_inventory_reference(selected,reference),effective)
    return {'rows':resuspension_plan(marked,effective),'reference':reference,'settings':effective}


class NestedAssembly(BaseModel):
    parent_fragment_id:int
    cassette_id:str=Field(min_length=1,max_length=100)
    fragment_ids:list[int]=Field(min_length=1,max_length=50)
    mode:Literal['together','separate']='together'
    prepared_stock_ng_ul:float | None=Field(None,gt=0,lt=1e8)


class AssemblyRequest(BaseModel):
    name:str=Field('New assembly',min_length=1,max_length=100)
    name_mode:Literal['auto','manual'] | None=None
    enzyme:Literal['BsaI','BsmBI','BsmBI + BsaI']='BsaI'
    fragment_ids:list[int]=Field(default_factory=list,max_length=50)
    backbone_id:int | None=None
    starter_fragment_id:int | None=None
    slot_id:str | int | None=None
    circular:bool | None=None
    save_as_backbone:bool=False
    nested_assemblies:list[NestedAssembly]=Field(default_factory=list,max_length=50)
    settings:ReactionSettings=Field(default_factory=ReactionSettings)


def backbone_template_info(sequence, circular, valid=True):
    sites=restriction_sites(sequence,circular=circular)
    site_counts={enzyme:sum(site['enzyme']==enzyme for site in sites) for enzyme in ('BsmBI','BsaI')}
    cassettes={}
    if circular:
        for enzyme in ('BsaI','BsmBI','BsmBI + BsaI'):
            slots=[slot for slot in find_backbone_slots(sequence,enzyme) if slot['structurally_valid']]
            boundaries={(slot[side+'_boundary_enzyme'],slot[direction+'_start']) for slot in slots
                        for side,direction in (('left','reverse'),('right','forward'))}
            active={(site['enzyme'],site['start']) for site in sites if site['enzyme'] in active_enzymes(enzyme)}
            # Saving a template does not simulate a completed reaction. Multiple
            # complete cassettes are reusable, but every active cut must belong
            # to one; the assembly engine still rejects unresolved retained cuts.
            if slots and active==boundaries:cassettes[enzyme]=slots
    counts={enzyme:len(slots) for enzyme,slots in cassettes.items()}
    return {'eligible':bool(valid and circular and cassettes),'enzymes':list(cassettes),
        'cassettes':cassettes,'cassette_counts':counts,'site_counts':site_counts,
        'requires_multiple_inserts':any(count>1 for count in counts.values())}


def reaction_plan(parts,settings):
    settings=settings.model_dump() if isinstance(settings,ReactionSettings) else settings
    rows=calculate_volumes(parts,settings)
    summary=reaction_summary(rows,settings)
    if any('ASSUMED' in row['concentration_basis'] for row in rows):
        summary['warnings'].append('Volumes use planned stock concentrations, not measured stocks.')
    for row in rows:
        row['ratio']=1 if row['role']=='backbone' else settings['insert_ratio']
    return {'rows':rows,'water_ul':summary['water_volume_ul'],
        'master_mix_ul':summary['master_mix_volume_ul'],
        'reaction_volume_ul':summary['reaction_volume_ul'],'warnings':summary['warnings'],
        'backbone_fmol':next((row['target_fmol'] for row in rows if row['role']=='backbone'),None),
        'input_fmol':rows[0]['target_fmol'] if rows and settings.get('no_backbone') else None,
        'volume_complete':all(row['volume_ul'] is not None for row in rows),
        'molecular_weight_g_mol_per_bp':660}


def build(payload):
    ids=([payload.starter_fragment_id] if payload.starter_fragment_id else [])+payload.fragment_ids
    if payload.backbone_id and payload.starter_fragment_id:
        raise HTTPException(422,'Choose either a circular plasmid or a backbone fragment.')
    if len(ids)!=len(set(ids)):
        raise HTTPException(422,'A fragment cannot be selected twice in one assembly.')
    ps=[]
    for i in ids:
        p=store.get_fragment(i)
        if not p:raise HTTPException(404,f'Fragment {i} not found.')
        ps.append(p)
    backbone=store.get_plasmid(payload.backbone_id) if payload.backbone_id else None
    if payload.backbone_id and not backbone:raise HTTPException(404,'Backbone not found.')
    if backbone and not backbone['circular']:raise HTTPException(422,'A backbone plasmid must be circular.')
    if not backbone and not ps:
        raise HTTPException(422,'Select at least one fragment or a backbone plasmid.')
    circular=True if payload.circular is None and (backbone or payload.starter_fragment_id) else payload.circular
    try:
        derived,nested_physical,nested,stages=prepare_nested(ps,[group.model_dump() for group in payload.nested_assemblies],payload.enzyme,store.get_fragment)
    except ValueError as error:
        raise HTTPException(422,str(error))
    result=assemble(derived,payload.enzyme,backbone=backbone,slot_id=payload.slot_id,circular=circular)
    annotate_nested(result,nested)
    result['name']=payload.name
    result['backbone_template']=backbone_template_info(result['sequence'],result['circular'],not result['errors'])
    physical=([backbone | {'id':'plasmid:'+str(backbone['id']), 'physical_length':len(backbone['sequence']), 'role':'backbone'}] if backbone else [])+[
        part | {'role':'backbone' if part.get('source_fragment_id',part['id'])==payload.starter_fragment_id else 'insert'} for part in nested_physical]
    result['parts']=[{k:v for k,v in p.items() if k not in ('sequence','construct_sequence','features','recipe')} for p in physical]
    planning_settings=payload.settings.model_dump() | get_rules() | payload.settings.model_dump(exclude_unset=True) | {'no_backbone':not bool(backbone or payload.starter_fragment_id)}
    effective,reference=reference_settings(planning_settings,payload.backbone_id,payload.starter_fragment_id,default_f1=False)
    prepared_reference=next((p for p in physical if p.get('role')=='backbone' and p.get('_prepared_nested')),None)
    if prepared_reference:
        effective.update(backbone_length_bp=prepared_reference['physical_length'],
            backbone_stock_ng_ul=prepared_reference['stock_ng_ul'],
            backbone_ng=effective['backbone_pmol']*prepared_reference['physical_length']*.66)
        reference=reference | {'name':prepared_reference['name'],'length_bp':prepared_reference['physical_length'],'backbone_ng':effective['backbone_ng']}
        effective['backbone_reference']=reference
    physical=planner_parts(physical,effective)
    result['parts']=[{k:v for k,v in p.items() if k not in ('sequence','construct_sequence','features','recipe')} for p in physical]
    result['reaction']=reaction_plan(physical,effective)
    result['resuspension']={'rows':resuspension_plan(physical,effective),'reference':reference,'settings':effective}
    result['nested_reactions']=[]
    for stage in stages:
        # The scaffold is a delivered fragment, so its original stock is planned
        # under fragment rules before assigning the 1x reference role.
        prepared_input=next((row for row in result['reaction']['rows'] if row['id']=='prepared:'+str(stage['parent']['id'])),None)
        stage_pmol=prepared_input['target_fmol']/1000 if prepared_input and prepared_input['target_fmol'] is not None else effective['backbone_pmol']*effective['insert_ratio']
        stage_settings=effective | {'no_backbone':True,'backbone_length_bp':None,'backbone_ng':None,
            'backbone_pmol':stage_pmol}
        scaffold=planner_parts([stage['parent'] | {'role':'insert'}],stage_settings | {'insert_ratio':1})[0]
        scaffold_plan=resuspension_plan([scaffold],stage_settings | {'insert_ratio':1})[0]
        stage_settings.update(no_backbone=False,backbone_length_bp=stage['parent']['physical_length'],
            backbone_ng=stage_settings['backbone_pmol']*stage['parent']['physical_length']*.66,
            backbone_stock_ng_ul=scaffold_plan['target_ng_ul'])
        children=planner_parts([child | {'role':'insert'} for child in stage['children']],stage_settings)
        stage_parts=[scaffold | {'role':'backbone','stock_ng_ul':scaffold_plan['target_ng_ul']},*children]
        stage_reaction=reaction_plan(stage_parts,stage_settings)
        stage_reaction['warnings'].append('Stage amount assumes complete recovery; scale the separate reaction for assembly and purification losses.')
        stage_reaction['rows'][0]['concentration_basis']=scaffold.get('concentration_basis') or 'Planned scaffold stock (unmeasured)'
        stage_reaction['rows'][0]['warnings']=scaffold_plan['warnings']
        stage_reaction['rows'][0]['feasible']=scaffold_plan['feasible']
        result['nested_reactions'].append({'parent_fragment_id':stage['parent']['id'],
            'name':stage['parent']['name']+' · Separate first','enzyme':stage['enzyme'],
            'reaction':stage_reaction,'settings':stage_settings,
            'errors':list(dict.fromkeys(error for group in stage['records'] for error in group['errors'])),
            'resuspension':{'rows':[scaffold_plan,*resuspension_plan(children,stage_settings)]}})
    result['effective_settings']=effective
    result['recipe']=payload.model_dump()
    return result,physical


def build_list_item(row):
    item=dict(row)
    item['request']=json.loads(item['request'])
    try:
        result,_=build(AssemblyRequest.model_validate(item['request']))
        item['plan']={key:result[key] for key in ('name','length','circular','errors','warnings','reaction','resuspension','parts','fragment_checks','nested_assemblies','nested_reactions')}
        reaction=result['reaction']
        ready=not result['errors'] and bool(reaction['rows']) and all(part['feasible'] is True and part['volume_ul'] is not None for part in reaction['rows']) and reaction['water_ul'] is not None and reaction['water_ul']>=0
        ready=ready and all(not stage['errors'] and stage['reaction']['rows'] and all(p['feasible'] is True and p['volume_ul'] is not None for p in stage['reaction']['rows']) and stage['reaction']['water_ul'] is not None and stage['reaction']['water_ul']>=0 for stage in result['nested_reactions'])
        item['status']='Ready' if ready else 'Check links' if result['errors'] else 'Check volumes'
    except (HTTPException,ValueError) as error:
        item['plan']=None
        item['error']=str(error.detail if isinstance(error,HTTPException) else error)
        item['status']='Unavailable'
    return item


def active_build_list():
    with store.connection() as db:
        rows=db.execute('SELECT * FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),)).fetchall()
    return [build_list_item(row) for row in rows]


@app.get('/api/build-list')
def get_build_list():
    with store.connection() as db:
        removed=db.execute('SELECT id FROM build_list WHERE user_id=? AND removed_at IS NOT NULL ORDER BY removed_at DESC,id DESC LIMIT 1',(user_id(),)).fetchone()
    items=active_build_list()
    headers,rows,metadata,plates=matrix_data(build_sections(items))
    return {'items':items,'last_removed_id':removed['id'] if removed else None,
        'export':{'headers':headers,'rows':rows,'metadata_headers':META_HEADERS,'metadata':metadata,'plates':list(plates.values())}}


def checked_build_request(payload):
    result,_=build(payload)
    request=payload.model_dump()
    request['settings']={key:value for key,value in result['effective_settings'].items() if key in ReactionSettings.model_fields and (value is not None or key in ('backbone_stock_ng_ul','backbone_length_bp'))}
    return request


@app.post('/api/build-list')
def add_build_list(payload:AssemblyRequest):
    request=checked_build_request(payload)
    with store.connection() as db:
        if db.execute('SELECT count(*) FROM build_list WHERE user_id=? AND removed_at IS NULL',(user_id(),)).fetchone()[0]>=50:
            raise HTTPException(422,'The build list is full (50 assemblies).')
        existing={json.loads(row['request'])['name'].strip().casefold() for row in db.execute('SELECT request FROM build_list WHERE user_id=? AND removed_at IS NULL',(user_id(),))}
        original=request['name']
        index=2
        while request['name'].strip().casefold() in existing:
            suffix=f' ({index})'
            request['name']=original[:100-len(suffix)]+suffix
            index+=1
        row_id=db.execute('INSERT INTO build_list(request,user_id) VALUES(?,?)',(json.dumps(request),user_id())).lastrowid
        row=db.execute('SELECT * FROM build_list WHERE id=?',(row_id,)).fetchone()
    return build_list_item(row)


@app.put('/api/build-list/{build_id}')
def update_build_list(build_id:int,payload:AssemblyRequest):
    request=checked_build_request(payload)
    with store.connection() as db:
        changed=db.execute('UPDATE build_list SET request=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND removed_at IS NULL',(json.dumps(request),build_id,user_id()))
        if not changed.rowcount:raise HTTPException(404,'Build not found.')
        row=db.execute('SELECT * FROM build_list WHERE id=?',(build_id,)).fetchone()
    return build_list_item(row)


class BuildPlanPatch(BaseModel):
    model_config={'extra':'forbid'}
    backbone_pmol:float=Field(default=None,gt=0,allow_inf_nan=False)
    insert_ratio:float=Field(default=None,gt=0,allow_inf_nan=False)
    reaction_volume_ul:float=Field(default=None,gt=0,allow_inf_nan=False)
    master_mix_volume_ul:float=Field(default=None,ge=0,allow_inf_nan=False)
    backbone_stock_ng_ul:float | None=Field(default=None,gt=0,allow_inf_nan=False)


def patch_build_rows(db,rows,changes):
    for row in rows:
        request=json.loads(row['request'])
        request['settings'].update(changes)
        checked=checked_build_request(AssemblyRequest.model_validate(request))
        db.execute('UPDATE build_list SET request=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (json.dumps(checked),row['id']))
    return [db.execute('SELECT * FROM build_list WHERE id=?',(row['id'],)).fetchone() for row in rows]


@app.patch('/api/build-list/{build_id}/settings')
def patch_build_plan(build_id:int,patch:BuildPlanPatch):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM build_list WHERE id=? AND user_id=? AND removed_at IS NULL',(build_id,user_id())).fetchone()
        if row is None:raise HTTPException(404,'Build not found.')
        updated=patch_build_rows(db,[row],patch.model_dump(exclude_unset=True))[0]
    return build_list_item(updated)


class BackboneStockPatch(BaseModel):
    kind:Literal['plasmid','fragment']
    id:int=Field(gt=0)
    stock_ng_ul:float | None=Field(gt=0,le=1e8,allow_inf_nan=False)


@app.put('/api/build-list/backbone-stocks/apply')
def patch_backbone_stocks(patch:BackboneStockPatch):
    field='backbone_id' if patch.kind=='plasmid' else 'starter_fragment_id'
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=[row for row in db.execute('SELECT * FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),))
            if json.loads(row['request']).get(field)==patch.id]
        updated=patch_build_rows(db,rows,{'backbone_stock_ng_ul':patch.stock_ng_ul})
    return {'items':[build_list_item(row) for row in updated]}


@app.delete('/api/build-list/{build_id}')
def remove_build_list(build_id:int):
    with store.connection() as db:
        changed=db.execute("UPDATE build_list SET removed_at=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=? AND user_id=? AND removed_at IS NULL",(build_id,user_id()))
        if not changed.rowcount:raise HTTPException(404,'Build not found.')
    return {'removed':build_id}


@app.post('/api/build-list/{build_id}/restore')
def restore_build_list(build_id:int):
    with store.connection() as db:
        if db.execute('SELECT count(*) FROM build_list WHERE user_id=? AND removed_at IS NULL',(user_id(),)).fetchone()[0]>=50:
            raise HTTPException(422,'The build list is full (50 assemblies).')
        changed=db.execute('UPDATE build_list SET removed_at=NULL WHERE id=? AND user_id=? AND removed_at IS NOT NULL',(build_id,user_id()))
        if not changed.rowcount:raise HTTPException(404,'Removed build not found.')
        row=db.execute('SELECT * FROM build_list WHERE id=?',(build_id,)).fetchone()
    return build_list_item(row)


@app.get('/api/build-list/worksheet')
def export_build_list(format:Literal['xlsx','pdf','csv']='xlsx',export_date:date | None=None):
    items=active_build_list()
    if not items:raise HTTPException(422,'Add an assembly to the build list first.')
    export_day = export_date or datetime.now(ZoneInfo('Australia/Melbourne')).date()
    identifier = 'BL-' + uuid4().hex
    filename = f'Build_list_{export_day.isoformat()}_{identifier}.{format}'
    return download(guide_bytes(format,build_sections(items),lambda:build_list_workbook(items)), filename, FORMATS[format])


@app.get('/api/build-list/genbank')
def export_build_genbanks(export_date:date | None=None):
    # Rebuild from current inventory instead of exporting stale preview sequences.
    with store.connection() as db:
        rows=db.execute('SELECT id,request FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),)).fetchall()
    if not rows:raise HTTPException(422,'Add an assembly to the build list first.')
    builds=[]
    errors=[]
    for row in rows:
        name=f"Build {row['id']}"
        try:
            data=json.loads(row['request'])
            name=data.get('name',name)
            request=AssemblyRequest.model_validate(data)
            result,_=build(request)
            if result.get('errors'):
                errors.append(name+': '+' '.join(result['errors']))
            else:
                builds.append((row['id'],request,result))
        except (HTTPException,ValueError) as error:
            detail=error.detail if isinstance(error,HTTPException) else str(error)
            errors.append(name+': '+str(detail))
    if errors:raise HTTPException(422,{'message':'Resolve assembly errors before exporting the build list.','errors':errors})
    export_day=export_date or datetime.now(ZoneInfo('Australia/Melbourne')).date()
    filename=f'Build_list_{export_day.isoformat()}_BL-{uuid4().hex}_GenBank.zip'
    return download(build_genbank_zip(builds),filename,'application/zip')


@app.post('/api/assemblies/preview')
def preview(payload:AssemblyRequest):
    return build(payload)[0]


@app.post('/api/assemblies')
def save_assembly(payload:AssemblyRequest):
    result,_=build(payload)
    if result.get('errors'):
        raise HTTPException(422,{'message':'Resolve assembly errors before saving.','errors':result['errors']})
    template=result['backbone_template']
    if payload.save_as_backbone and not template['eligible']:
        raise HTTPException(422,'A backbone template must be circular and contain complete BsaI, BsmBI or dual-cut replacement cassettes, with no unpaired active cut sites.')
    pid=store.save_plasmid(payload.name,result['sequence'],result.get('features'),payload.model_dump(),
        notes='Assembled from the persistent fragment inventory.',circular=result['circular'],
        backbone_enzymes=template['enzymes'] if payload.save_as_backbone else None)
    saved=store.get_plasmid(pid)
    return {'id':pid,'name':payload.name,'length':len(result['sequence']),'circular':result['circular'],
        'backbone_template':bool(saved['recipe'].get('backbone_template')),
        'backbone_enzymes':saved['recipe'].get('backbone_enzymes',[])}


@app.post('/api/assemblies/genbank')
def export_assembly(payload:AssemblyRequest):
    result,_=build(payload)
    if result.get('errors'):raise HTTPException(422,{'message':'Resolve errors before exporting a predicted assembly.','errors':result['errors']})
    return download(genbank_bytes(payload.name,result['sequence'],result.get('features'),result['circular'],notes='Assembly enzyme: '+payload.enzyme),payload.name+'.gb','text/plain')


@app.post('/api/assemblies/worksheet')
def export_worksheet(payload:AssemblyRequest,format:Literal['xlsx','pdf','csv']='xlsx'):
    result,physical=build(payload)
    # Invalid designs remain reviewable on the worksheet, explicitly marked.
    result['parts']=physical
    effective=result['effective_settings']
    return download(guide_bytes(format,assembly_sections(result,effective,payload.enzyme),
        lambda:make_workbook(planner_parts(store.fragments(),effective),result,effective)),payload.name+'_worksheet.'+format,FORMATS[format])


@app.post('/api/inventory/worksheet')
def planner_inventory_worksheet(payload:ResuspensionRequest,format:Literal['xlsx','pdf','csv']='xlsx'):
    effective,reference=reference_settings(payload,payload.backbone_id,payload.starter_fragment_id)
    selected=[part for part in store.fragments() if (not payload.plate or part['plate_id']==payload.plate)
        and (payload.fragment_ids is None or part['id'] in payload.fragment_ids)]
    marked=planner_parts(mark_inventory_reference(selected,reference),effective)
    return download(guide_bytes(format,inventory_sections(marked,effective),lambda:make_workbook(marked,settings=effective)), 'Resuspension.'+format,FORMATS[format])


@app.post('/api/inventory/resuspension')
def inventory_resuspension_post(payload:ResuspensionRequest):
    return inventory_plan(payload,payload.backbone_id,payload.starter_fragment_id,payload.plate)


@app.get('/api/inventory/resuspension')
def inventory_resuspension(backbone_id:int | None=None,starter_fragment_id:int | None=None,no_backbone:bool=False,
        backbone_ng:float=Query(50,gt=0,allow_inf_nan=False),insert_ratio:float=Query(1,gt=0,allow_inf_nan=False),
        input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        resuspension_mode:Literal['constrained','one_ul','fixed_stock']='constrained',
        backbone_pmol:float=Query(0.05,gt=0,allow_inf_nan=False),
        backbone_stock_ng_ul:float | None=Query(None,gt=0,allow_inf_nan=False),
        preferred_resuspension_ul:float=Query(50,gt=0,allow_inf_nan=False),
        max_resuspension_ul:float=Query(99.99,gt=0,allow_inf_nan=False),
        min_input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        max_input_volume_ul:float=Query(5,gt=0,allow_inf_nan=False),
        target_stock_ng_ul:float=Query(20,gt=0,allow_inf_nan=False),plate:str=''):
    settings=ReactionSettings(backbone_ng=backbone_ng,insert_ratio=insert_ratio,input_volume_ul=input_volume_ul,no_backbone=no_backbone,
        resuspension_mode=resuspension_mode,target_stock_ng_ul=target_stock_ng_ul,backbone_pmol=backbone_pmol,backbone_stock_ng_ul=backbone_stock_ng_ul,
        preferred_resuspension_ul=preferred_resuspension_ul,max_resuspension_ul=max_resuspension_ul,
        min_input_volume_ul=min_input_volume_ul,max_input_volume_ul=max_input_volume_ul)
    return inventory_plan(settings,backbone_id,starter_fragment_id,plate)


@app.get('/api/inventory/worksheet')
def inventory_worksheet(backbone_id:int | None=None,starter_fragment_id:int | None=None,no_backbone:bool=False,
        backbone_ng:float=Query(50,gt=0,allow_inf_nan=False),insert_ratio:float=Query(1,gt=0,allow_inf_nan=False),
        input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        resuspension_mode:Literal['constrained','one_ul','fixed_stock']='constrained',
        backbone_pmol:float=Query(0.05,gt=0,allow_inf_nan=False),
        backbone_stock_ng_ul:float | None=Query(None,gt=0,allow_inf_nan=False),
        preferred_resuspension_ul:float=Query(50,gt=0,allow_inf_nan=False),
        max_resuspension_ul:float=Query(99.99,gt=0,allow_inf_nan=False),
        min_input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        max_input_volume_ul:float=Query(5,gt=0,allow_inf_nan=False),
        target_stock_ng_ul:float=Query(20,gt=0,allow_inf_nan=False),plate:str='',
        planner_stock_mode:Literal['saved','custom'] | None=None,format:Literal['xlsx','pdf','csv']='xlsx'):
    settings=ReactionSettings(backbone_ng=backbone_ng,insert_ratio=insert_ratio,input_volume_ul=input_volume_ul,no_backbone=no_backbone,
        resuspension_mode=resuspension_mode,target_stock_ng_ul=target_stock_ng_ul,backbone_pmol=backbone_pmol,backbone_stock_ng_ul=backbone_stock_ng_ul,
        preferred_resuspension_ul=preferred_resuspension_ul,max_resuspension_ul=max_resuspension_ul,
        min_input_volume_ul=min_input_volume_ul,max_input_volume_ul=max_input_volume_ul,planner_stock_mode=planner_stock_mode)
    effective,reference=reference_settings(settings,backbone_id,starter_fragment_id)
    selected=[part for part in store.fragments() if not plate or part['plate_id']==plate]
    marked=planner_parts(mark_inventory_reference(selected,reference),effective)
    return download(guide_bytes(format,inventory_sections(marked,effective),lambda:make_workbook(marked,settings=effective)),
        'Golden_Gate_resuspension_reference.'+format,FORMATS[format])


async def read_upload(file):
    content=await file.read(MAX_UPLOAD+1)
    if len(content)>MAX_UPLOAD:raise HTTPException(413,'File exceeds the 10 MB limit.')
    if not content:raise HTTPException(422,'The uploaded file is empty.')
    return content


@app.post('/api/uploads/plate')
async def upload_plate(file:UploadFile=File(...),preview:bool=False,apply_import_rules:bool=False,
        backbone_id:int | None=None,starter_fragment_id:int | None=None,no_backbone:bool=False,
        backbone_ng:float=Query(50,gt=0,allow_inf_nan=False),insert_ratio:float=Query(1,gt=0,allow_inf_nan=False),
        input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        resuspension_mode:Literal['constrained','one_ul','fixed_stock']='constrained',
        backbone_pmol:float=Query(0.05,gt=0,allow_inf_nan=False),
        backbone_stock_ng_ul:float | None=Query(None,gt=0,allow_inf_nan=False),
        preferred_resuspension_ul:float=Query(50,gt=0,allow_inf_nan=False),
        max_resuspension_ul:float=Query(99.99,gt=0,allow_inf_nan=False),
        min_input_volume_ul:float=Query(1,gt=0,allow_inf_nan=False),
        max_input_volume_ul:float=Query(5,gt=0,allow_inf_nan=False),
        target_stock_ng_ul:float=Query(20,gt=0,allow_inf_nan=False)):
    content=await read_upload(file)
    try:
        incoming=parse_plate(content,file.filename or 'upload.csv')
        settings=ReactionSettings(backbone_ng=backbone_ng,insert_ratio=insert_ratio,input_volume_ul=input_volume_ul,no_backbone=no_backbone,
            resuspension_mode=resuspension_mode,target_stock_ng_ul=target_stock_ng_ul,backbone_pmol=backbone_pmol,backbone_stock_ng_ul=backbone_stock_ng_ul,
        preferred_resuspension_ul=preferred_resuspension_ul,max_resuspension_ul=max_resuspension_ul,
        min_input_volume_ul=min_input_volume_ul,max_input_volume_ul=max_input_volume_ul)
        rules=None
        if apply_import_rules:
            if not no_backbone or backbone_id or starter_fragment_id or resuspension_mode!='constrained':
                raise ValueError('Import rules require a constrained fragment plan without a backbone selection.')
            rules=InventoryRules.model_validate({key:getattr(settings,key) for key in InventoryRules.model_fields}).model_dump()
        # Validate the reference before any database mutation. Only uploaded rows are planned.
        plan=inventory_plan(settings,backbone_id,starter_fragment_id,fragments=incoming)
        result=import_plate(content,file.filename or 'upload.csv',preview=preview,rules=rules)
        return result | {'resuspension':plan}
    except (ValueError,UnicodeError,KeyError) as exc:raise HTTPException(422,str(exc))


@app.post('/api/uploads/plasmid')
async def upload_plasmid(file:UploadFile=File(...),topology:Literal['file','circular','linear']='file',backbone_template:bool=False):
    content=await read_upload(file)
    try:
        records=parse_sequence_file(content.decode('utf-8-sig'),file.filename or 'upload.gb')
        if not records:raise ValueError('No GenBank or FASTA records found.')
        if backbone_template and topology=='linear':
            raise ValueError('A backbone template must be circular.')
        for r in records:
            r['sequence']=dna(r['sequence'])
            if len(r['sequence'])>100000:raise ValueError('Plasmids must be 100,000 nt or shorter.')
            r['circular']=True if backbone_template or topology=='circular' else False if topology=='linear' else r.get('circular',False)
            options=backbone_template_info(r['sequence'],r['circular'])
            if backbone_template and not options['eligible']:
                raise ValueError(f"{r['name']}: no complete BsaI, BsmBI or dual-cut cassette set was found; import as a reference or resolve unpaired cuts first.")
            r['backbone_enzymes']=options['enzymes'] if backbone_template else None
        # Validate every record before importing a multi-record file.
        with store.connection() as db:
            for r in records:check_plasmid_write(db,r['name'],r['sequence'])
        ids=[store.save_plasmid(r['name'],r['sequence'],r.get('features'),notes='Uploaded plasmid reference.',
            circular=r['circular'],backbone_enzymes=r['backbone_enzymes'],topology_override=topology!='file',merge_annotations=True) for r in records]
        return {'count':len(ids),'ids':ids,'names':[r['name'] for r in records]}
    except (ValueError,UnicodeError,KeyError) as exc:raise HTTPException(422,str(exc))


@app.get('/api/uploads')
def upload_history():
    with store.connection() as db:return [dict(r) for r in db.execute('SELECT id,filename,kind,row_count,created_at FROM imports ORDER BY id DESC')]


@app.get('/api/examples')
def examples():
    plates, genbanks = seed_source_files()
    return sorted([{'filename':p.name,'kind':'plate'} for p in plates] +
        [{'filename':p.name,'kind':'GenBank'} for p in genbanks], key=lambda item:item['filename'])


@app.get('/api/examples/{filename}')
def example(filename:str):
    plates, genbanks = seed_source_files()
    path = next((p for p in plates + genbanks if p.name == filename), None)
    if path is None:raise HTTPException(404,'Example not found.')
    return FileResponse(path,filename=path.name)


@app.get('/api/recipes')
def recipes():
    ps=store.fragments()
    names={p['name']:p['id'] for p in ps}
    def lookup(base):
        if base in names:return names[base]
        matches=[p['id'] for p in ps if p['name'].startswith(base+' ')];return matches[0] if len(matches)==1 else None
    templates=[('pIVT_V2',['F1','F2','F4','F10','F11']),
        ('pULT_V2',['F1','F5','F8',"F6 (3'LTR_BsaI-ve)",'F13','F14','F15','F16','F18']),
        ('pHR_V2',['F1','F3',"F6 (3'LTR_BsaI-ve)",'F17 (BsmbI)','F15','F16','F19','F20','F21(mod)','F24','F25','F26']),
        ('pHR_V2 · U6',['F1','F3',"F6 (3'LTR_U6_BsmBI)",'F17 (BsmbI)','F15','F16','F19','F20','F21(mod)','F24','F25','F26']),
        ('AAV6_V2',['F1','F2','F9','F12'])]
    result=[]
    for name,components in templates:
        ids=[lookup(n) for n in components];missing=[n for n,i in zip(components,ids) if i is None]
        result.append({'name':name,'enzyme':'BsaI','starter_fragment_id':ids[0],'fragment_ids':ids[1:],'no_backbone':True,'no_backbone_fragment_ids':ids,'missing':missing,'available':not missing})
    return result


def comparison_references():
    references=[dict(p,source='saved plasmid',assembly_enzymes=[p['recipe']['enzyme']] if p.get('recipe',{}).get('enzyme') in MODES else []) for p in store.plasmids()]
    with store.connection() as db:
        queued=[dict(row) for row in db.execute('SELECT id,request FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),))]
    requests=[('Build list',str(row['id']),json.loads(row['request'])) for row in queued]
    for recipe in recipes():
        if recipe['available']:
            ids=recipe.get('no_backbone_fragment_ids') or [recipe.get('starter_fragment_id'),*recipe.get('fragment_ids',[])]
            requests.append(('Assembly recipe',recipe['name'],{'name':recipe['name'],'enzyme':recipe['enzyme'],'fragment_ids':[i for i in ids if i]}))
    for source,key,request in requests:
        try:
            result,_=build(AssemblyRequest.model_validate(request))
            if result['valid']:
                references.append({'id':source+':'+key,'name':request['name'],'sequence':result['sequence'],'features':result['features'],
                    'parts':[part['name'] for part in result['parts']], 'circular':result['circular'],'source':source,
                    'assembly_enzymes':[request['enzyme']]})
        except (ValueError,HTTPException,KeyError):
            continue
    return references


class ComparisonExportRequest(BaseModel):
    scope:Literal['exact','selected']='exact'
    records:list[dict]=Field(min_length=1,max_length=2000)


@app.post('/api/compare/export')
def export_comparisons(request:ComparisonExportRequest):
    try:
        content=comparison_workbook(request.records,request.scope)
        return download(content,'comparison-'+request.scope+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc))


@app.post('/api/compare')
async def compare(file:UploadFile=File(...),enzyme:Literal['auto','BsaI','BsmBI','BsmBI + BsaI']='auto',infer:bool=True,sandbox_id:int | None=None):
    content=await read_upload(file)
    run_id=begin_comparison(file.filename or 'query.gb',content,enzyme,sandbox_id)
    try:
        records=parse_comparison_file(content.decode('utf-8-sig'),file.filename or 'query.gb')
        if not records:raise ValueError('No sequence records found.')
        if len(records)>100:raise ValueError('A file may contain at most 100 sequence records.')
        references=await run_in_threadpool(comparison_references)
        fragments=store.fragments();results=[]
        for record in records:
            try:
                if record.get('error'):raise ValueError(record['error'])
                record['sequence']=dna(record['sequence'])
                if len(record['sequence'])>30000:raise ValueError('Comparison supports sequences up to 30,000 nt per record.')
                if not record['sequence']:raise ValueError('The sequence is empty.')
                results.append(await run_in_threadpool(compare_record,record,fragments,references,enzyme,infer))
            except (ValueError,KeyError) as exc:
                if len(records)==1:raise
                results.append({'query_name':record.get('name','Sequence'),'error':str(exc)})
        # Preserve the single-record API while supporting multi-record files.
        result=(results[0] if len(results)==1 else {'query_name':file.filename,'record_count':len(results)}) | {'records':results,'record_count':len(results)}
        finish_comparison(run_id,enzyme,result=result)
        return result | {'sandbox_id':run_id}
    except (ValueError,UnicodeError,KeyError) as exc:
        finish_comparison(run_id,enzyme,error=str(exc))
        raise HTTPException(422,str(exc),headers={'X-Junction-Comparison-Id':str(run_id)})
