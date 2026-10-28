"""Private named sandboxes and portable, data-only .junc bundles."""
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from . import database as store
from .auth import user_id
from .version import VERSION

router=APIRouter(prefix='/api/workbenches')
FORMAT='junction-workbench'
MAX_BYTES=25*1024*1024


class Name(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    notes:str=Field(default='',max_length=4000)


class Save(Name):
    id:str | None=Field(default=None,max_length=36)


class New(BaseModel):
    discard_unsaved:bool=False


class Fragment(BaseModel):
    id:int=Field(gt=0)
    name:str=Field(min_length=1,max_length=1000)
    sequence:str=Field(min_length=1,max_length=5000000,pattern='^[ACGTRYSWKMBDHVNacgtryswkmbdhvn]+$')
    construct_sequence:str=Field(default='',max_length=5000000,pattern='^[ACGTRYSWKMBDHVNacgtryswkmbdhvn]*$')
    plate_id:str=Field(default='',max_length=1000)
    well:str=Field(default='',max_length=100)
    yield_ng:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    stock_ng_ul:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    resuspension_ul:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    default_yield_ng:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    stock_saved:bool=False
    yield_locked:bool=True
    concentration_basis:str=Field(default='unknown',max_length=200)
    default_stock_ng_ul:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    default_resuspension_ul:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    default_concentration_basis:str | None=Field(default=None,max_length=200)
    stock_rules:dict | None=None
    notes:str=Field(default='',max_length=20000)


class Plasmid(BaseModel):
    id:int=Field(gt=0)
    name:str=Field(min_length=1,max_length=1000)
    sequence:str=Field(min_length=1,max_length=5000000,pattern='^[ACGTRYSWKMBDHVNacgtryswkmbdhvn]+$')
    circular:bool=True
    features:list[dict]=Field(default_factory=list,max_length=10000)
    notes:str=Field(default='',max_length=20000)
    stock_ng_ul:float | None=Field(default=None,ge=0,allow_inf_nan=False)
    plate_id:str=Field(default='',max_length=1000)
    well:str=Field(default='',max_length=100)
    backbone_template:bool=False


class Inventory(BaseModel):
    fragments:list[Fragment]=Field(default_factory=list,max_length=5000)
    plasmids:list[Plasmid]=Field(default_factory=list,max_length=500)


class Build(BaseModel):
    id:int=Field(gt=0)
    request:dict


class Comparison(BaseModel):
    id:int=Field(gt=0)
    filename:str=Field(min_length=1,max_length=1000)
    source:str=Field(max_length=10000000)
    enzyme:str=Field(max_length=100)
    result:dict | None=None
    error:str | None=Field(default=None,max_length=10000)


class Worksheet(BaseModel):
    id:str=Field(min_length=1,max_length=100)
    scope:Literal['build','design','compare']
    name:str=Field(min_length=1,max_length=100)
    notes:str=Field(default='',max_length=4000)
    snapshot:dict


class Snapshot(BaseModel):
    workspace:dict=Field(default_factory=dict)
    builds:list[Build]=Field(default_factory=list,max_length=50)
    comparisons:list[Comparison]=Field(default_factory=list,max_length=200)
    inventory:Inventory=Field(default_factory=Inventory)
    worksheets:list[Worksheet]=Field(default_factory=list,max_length=100)
    worksheet_active:dict[str,str]=Field(default_factory=dict,max_length=3)


def encode(value):
    try:return json.dumps(value,allow_nan=False,sort_keys=True,separators=(',',':'))
    except (ValueError,TypeError,RecursionError):raise HTTPException(422,'Workbench must contain finite JSON data.') from None


def checked(value,nested=False):
    """Validate structure and reference closure before any database writes."""
    from .main import AssemblyRequest
    from .design import DesignRequest
    try:
        data=Snapshot.model_validate(value).model_dump()
        if nested and (data['worksheets'] or data['worksheet_active']):raise ValueError('Worksheets cannot contain nested worksheets.')
        if len({item['id'] for item in data['worksheets']})!=len(data['worksheets']):raise ValueError('Duplicate worksheet IDs.')
        for item in data['worksheets']:item['snapshot']=checked(item['snapshot'],nested=True)
        if any(scope not in ('build','design','compare') for scope in data['worksheet_active']):raise ValueError('Unknown worksheet type.')
        workspace=data['workspace']
        for key in ('design','backboneStocks','plannerStocks','compareView','preferences','plannerOverrides','worksheet_ids'):
            if key in workspace and not isinstance(workspace[key],dict):raise ValueError(key+' must be an object.')
        if isinstance(workspace.get('compareView'),dict) and 'jobs' in workspace['compareView'] and not isinstance(workspace['compareView']['jobs'],dict):raise ValueError('Comparison view jobs must be an object.')
        if workspace.get('draft'):workspace['draft']=AssemblyRequest.model_validate(workspace['draft']).model_dump()
        for item in data['builds']:item['request']=AssemblyRequest.model_validate(item['request']).model_dump()
        designs=(workspace.get('design') or {}).get('designs',[])
        if not isinstance(designs,list) or len(designs)>20:raise ValueError('Use at most 20 designs.')
        for design in designs:
            parsed=DesignRequest.model_validate(design)
            design['backbone_id']=parsed.backbone_id
            for entry,validated in zip(design['entries'],parsed.entries):entry['fragment_id']=validated.fragment_id
        for kind in ('builds','comparisons'):
            if len({item['id'] for item in data[kind]})!=len(data[kind]):raise ValueError('Duplicate item IDs.')
        for kind in ('fragments','plasmids'):
            items=data['inventory'][kind]
            if len({item['id'] for item in items})!=len(items):raise ValueError('Duplicate inventory IDs.')
        fragments,plasmids=references(data)
        if fragments-{p['id'] for p in data['inventory']['fragments']} or plasmids-{p['id'] for p in data['inventory']['plasmids']}:
            raise ValueError('The file is missing referenced fragments or plasmids.')
        encoded=encode(data)
        if len(encoded.encode())>MAX_BYTES:raise HTTPException(413,'Workbench exceeds 25 MiB.')
        # The live sandbox has the same limit as /api/workspace.
        if len(encode(workspace).encode())>2*1024*1024:raise HTTPException(413,'Workbench settings exceed 2 MiB.')
        return data
    except (ValidationError,ValueError,TypeError,AttributeError,KeyError,RecursionError) as error:
        raise HTTPException(422,'Invalid workbench data: '+str(error)[:300]) from None


def references(data):
    fragments=set();plasmids=set()
    def assembly(item):
        if not item:return
        fragments.update(item.get('fragment_ids',[]))
        if item.get('starter_fragment_id'):fragments.add(item['starter_fragment_id'])
        if item.get('backbone_id'):plasmids.add(item['backbone_id'])
        for nested in item.get('nested_assemblies',[]):
            fragments.add(nested['parent_fragment_id']);fragments.update(nested.get('fragment_ids',[]))
    assembly(data['workspace'].get('draft'))
    for item in data['builds']:assembly(item['request'])
    for design in (data['workspace'].get('design') or {}).get('designs',[]):
        if design.get('backbone_id'):plasmids.add(design['backbone_id'])
        for entry in design.get('entries',[]):
            if entry.get('kind')=='fragment' and entry.get('fragment_id'):fragments.add(entry['fragment_id'])
    return fragments,plasmids


def working(db):
    row=db.execute('SELECT data FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone()
    return json.loads(row['data']) if row else {}


def capture(db,include_worksheets=True,scope=None):
    workspace=working(db);workspace.pop('workbench_id',None);active={key:value for key,value in workspace.pop('worksheet_ids',{}).items() if key in ('build','design','compare') and isinstance(value,str) and value}
    if scope:
        from .worksheets import KEYS
        workspace={key:value for key,value in workspace.items() if key in KEYS[scope]}
        if scope=='design' and workspace.get('design'):
            designs=workspace['design'];selected=next((item for item in designs.get('designs',[]) if item.get('id')==designs.get('activeId')),None)
            if selected:workspace['design']={'designs':[selected],'activeId':selected['id']}
    builds=[dict(row,request=json.loads(row['request'])) for row in db.execute('SELECT id,request FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),))]
    comparisons=[dict(row,result=json.loads(row['result']) if row['result'] else None) for row in db.execute('SELECT id,filename,source,enzyme,result,error FROM comparison_runs WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),))]
    data={'workspace':workspace,'builds':builds if scope in (None,'build') else [],'comparisons':comparisons if scope in (None,'compare') else [],'inventory':{'fragments':[],'plasmids':[]}}
    fragments,plasmids=references(data)
    for kind,ids in [('fragments',fragments),('plasmids',plasmids)]:
        for identifier in sorted(ids):
            row=db.execute(f'SELECT * FROM {kind} WHERE id=?',(identifier,)).fetchone()
            if not row:raise HTTPException(422,f'Referenced {kind[:-1]} {identifier} is unavailable.')
            record=store.fragment_dict(row) if kind=='fragments' else store.plasmid_dict(row)
            if kind=='plasmids':record['backbone_template']=bool(record['recipe'].get('backbone_template'))
            data['inventory'][kind].append(record)
    if include_worksheets:
        from .worksheets import registry
        data['worksheets']=registry(db);data['worksheet_active']=active
    return checked(data)


def metadata(db,data,**extra):
    creator=db.execute('SELECT username FROM auth_users WHERE id=?',(user_id(),)).fetchone()['username']
    return {'app_version':VERSION,'created_by':creator,'builds':len(data['builds']),
        'designs':len((data['workspace'].get('design') or {}).get('designs',[])),
        'comparisons':len(data['comparisons']),'fragments':len(data['inventory']['fragments']),
        'plasmids':len(data['inventory']['plasmids']),'worksheets':len(data.get('worksheets',[])),**extra}


def owned(db,identifier):
    row=db.execute('SELECT * FROM saved_workbenches WHERE id=? AND user_id=?',(identifier,user_id())).fetchone()
    if not row:raise HTTPException(404,'Workbench not found.')
    return row


def summary(row):
    return {key:row[key] for key in ('id','name','notes','created_at','updated_at')}|{'metadata':json.loads(row['metadata'])}


def save_record(db,name,notes,data,identifier=None,**extra):
    name=name.strip()
    if not name:raise HTTPException(422,'Enter a workbench name.')
    if identifier:
        previous=json.loads(owned(db,identifier)['metadata'])
        extra={**{key:previous[key] for key in ('origin','imported_from','automatic') if key in previous},**extra}
    payload=encode(data);meta=encode(metadata(db,data,**extra))
    if identifier:
        owned(db,identifier)
        db.execute("UPDATE saved_workbenches SET name=?,notes=?,payload=?,metadata=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND user_id=?",(name,notes,payload,meta,identifier,user_id()))
    else:
        identifier=str(uuid4())
        db.execute('INSERT INTO saved_workbenches(id,user_id,name,notes,payload,metadata) VALUES(?,?,?,?,?,?)',(identifier,user_id(),name,notes,payload,meta))
    return owned(db,identifier)


def set_working(db,data):
    db.execute('INSERT INTO user_workspaces(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP',(user_id(),encode(data)))


def current_record(db):
    identifier=working(db).get('workbench_id')
    return db.execute('SELECT * FROM saved_workbenches WHERE id=? AND user_id=?',(identifier,user_id())).fetchone() if identifier else None


@router.get('')
def list_workbenches():
    with store.connection() as db:
        rows=db.execute('SELECT * FROM saved_workbenches WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user_id(),)).fetchall()
        current=current_record(db)
    return {'items':[summary(row) for row in rows],'current':summary(current) if current else None}


@router.post('')
def save_workbench(payload:Save):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');data=capture(db)
        row=save_record(db,payload.name,payload.notes,data,payload.id)
        from .worksheets import reparent_on_save
        active=reparent_on_save(db,data,row['id'])
        set_working(db,data['workspace']|{'workbench_id':row['id'],'worksheet_ids':active})
    return summary(row)


def bundle(row):
    data=json.loads(row['payload'])
    return {'format':FORMAT,'format_version':1,'workbench':summary(row),'snapshot':data,
        'sha256':hashlib.sha256(encode(data).encode()).hexdigest()}


def download(value,name):
    filename=re.sub(r'[^A-Za-z0-9_.-]+','_',name).strip('._')[:80] or 'Workbench'
    date=datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return Response(encode(value).encode(),media_type='application/vnd.junction.workbench+json',
        headers={'Content-Disposition':f'attachment; filename="{filename}_{date}.junc"'})


@router.post('/export-current')
def export_current():
    with store.connection() as db:
        data=capture(db);current=current_record(db)
        description=summary(current) if current else {'id':str(uuid4()),'name':'Workbench','notes':'','created_at':datetime.now(timezone.utc).isoformat(),'updated_at':datetime.now(timezone.utc).isoformat(),'metadata':metadata(db,data)}
        description['metadata']=metadata(db,data)
    return download({'format':FORMAT,'format_version':1,'workbench':description,'snapshot':data,'sha256':hashlib.sha256(encode(data).encode()).hexdigest()},description['name'])


@router.get('/{identifier}/export')
def export_saved(identifier:str,scope:Literal['build','design','compare'] | None=None):
    with store.connection() as db:row=owned(db,identifier)
    if scope:
        from .worksheets import subset,bundle as worksheet_bundle
        data=subset(json.loads(row['payload']),scope)
        return download(worksheet_bundle(data,scope,row['name']+' · '+scope.title(),row['notes']),row['name']+'_'+scope)
    return download(bundle(row),row['name'])


@router.post('/import')
async def import_workbench(file:UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.junc'):raise HTTPException(422,'Choose a .junc file.')
    content=await file.read(MAX_BYTES+1)
    if len(content)>MAX_BYTES:raise HTTPException(413,'Workbench exceeds 25 MiB.')
    try:
        value=json.loads(content.decode('utf-8-sig'))
        if not isinstance(value,dict) or value.get('format')!=FORMAT or value.get('format_version')!=1:raise ValueError('Unsupported .junc format or version.')
        original=value['snapshot'];data=checked(original)
        if value.get('sha256')!=hashlib.sha256(encode(original).encode()).hexdigest():raise ValueError('The .junc file checksum does not match.')
        title=Name.model_validate(value['workbench'])
    except (UnicodeError,ValueError,TypeError,KeyError,RecursionError) as error:
        raise HTTPException(422,'Invalid .junc file: '+str(error)[:200]) from None
    with store.connection() as db:
        source=value['workbench'];source_meta=source.get('metadata') if isinstance(source.get('metadata'),dict) else {}
        origin={key:str(source.get(key,''))[:200] for key in ('id','name','created_at','updated_at')}
        origin.update({key:str(source_meta.get(key,''))[:200] for key in ('app_version','created_by')})
        row=save_record(db,title.name,title.notes,data,imported_from=origin['id'],origin=origin)
    return summary(row)


def resolve_inventory(db,data,identifier):
    """Match content and physical identity, never trust another server's row IDs."""
    user=dict(db.execute('SELECT * FROM auth_users WHERE id=?',(user_id(),)).fetchone())
    can_upload=bool(user['is_admin'] or user['can_upload']);maps={}
    for kind in ('fragments','plasmids'):
        mapping={};maps[kind]=mapping
        for item in data['inventory'][kind]:
            sequence=item['sequence'].upper();name=item['name'];plate=item.get('plate_id','');well=item.get('well','')
            condition=' AND '+store.ACTIVE_FRAGMENTS if kind=='fragments' else ' AND archived_at IS NULL'
            row=db.execute(f'SELECT * FROM {kind} WHERE name=? AND upper(sequence)=? AND plate_id=? AND well=?'+condition,(name,sequence,plate,well)).fetchone()
            if row and kind=='fragments' and (row['construct_sequence'] or '').upper()!=item['construct_sequence'].upper():row=None
            if row and kind=='plasmids' and bool(row['circular'])!=item['circular']:row=None
            if row:mapping[item['id']]=row['id'];continue
            if not can_upload:raise HTTPException(403,'Upload permission is required to load missing fragments or plasmids from this workbench.')
            if kind=='fragments':
                # Preserve occupied wells. A conflicting plate is visibly namespaced.
                if db.execute('SELECT 1 FROM fragments WHERE plate_id=? AND well=?',(plate,well)).fetchone() or db.execute('SELECT 1 FROM plates WHERE plate_id=? AND archived_at IS NOT NULL',(plate,)).fetchone():
                    plate='JUNC-'+identifier[:8]+'-'+(plate or str(item['id']))
                existing=db.execute('SELECT * FROM fragments WHERE plate_id=? AND well=? AND name=? AND upper(sequence)=? AND '+store.ACTIVE_FRAGMENTS,(plate,well,name,sequence)).fetchone()
                if existing and (existing['construct_sequence'] or '').upper()==item['construct_sequence'].upper():mapping[item['id']]=existing['id'];continue
                if db.execute('SELECT 1 FROM fragments WHERE plate_id=? AND well=?',(plate,well)).fetchone():plate+='-'+uuid4().hex[:8]
                values={key:value for key,value in item.items() if key not in ('id',)}
                values.update(sequence=sequence,plate_id=plate)
                if values.get('stock_rules') is not None:values['stock_rules']=encode(values['stock_rules'])
                columns=list(values)
                row_id=db.execute('INSERT INTO fragments('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',list(values.values())).lastrowid
                if plate:db.execute('INSERT OR IGNORE INTO plates(plate_id) VALUES(?)',(plate,))
            else:
                # An existing plasmid with different location/archived status is not overwritten.
                if db.execute('SELECT 1 FROM plasmids WHERE name=? AND upper(sequence)=?',(name,sequence)).fetchone():name+=' (JUNC '+uuid4().hex[:8]+')'
                recipe={'backbone_template':True} if item['backbone_template'] else {}
                row_id=db.execute('INSERT INTO plasmids(name,sequence,circular,features,notes,stock_ng_ul,plate_id,well,recipe) VALUES(?,?,?,?,?,?,?,?,?)',
                    (name,sequence,item['circular'],encode(item['features']),item['notes'],item['stock_ng_ul'],plate,well,encode(recipe))).lastrowid
            mapping[item['id']]=row_id
    return maps['fragments'],maps['plasmids']


def remap_settings(settings,fragments):
    if not isinstance(settings,dict):return
    if isinstance(settings.get('fragment_stock_overrides'),dict):
        settings['fragment_stock_overrides']={str(fragments[int(key)]):value for key,value in settings['fragment_stock_overrides'].items() if str(key).isdigit() and int(key) in fragments}


def remap_assembly(item,fragments,plasmids):
    if not item:return
    item['fragment_ids']=[fragments[value] for value in item.get('fragment_ids',[])]
    if item.get('starter_fragment_id'):item['starter_fragment_id']=fragments[item['starter_fragment_id']]
    if item.get('backbone_id'):item['backbone_id']=plasmids[item['backbone_id']]
    for nested in item.get('nested_assemblies',[]):
        nested['parent_fragment_id']=fragments[nested['parent_fragment_id']]
        nested['fragment_ids']=[fragments[value] for value in nested.get('fragment_ids',[])]
    remap_settings(item.get('settings'),fragments)


@router.post('/{identifier}/open')
def open_workbench(identifier:str):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');target=owned(db,identifier);data=checked(json.loads(target['payload']))
        current=current_record(db)
        if current and current['id']==identifier:return {'opened':identifier,'view':'build'}
        before=capture(db)
        if current:save_record(db,current['name'],current['notes'],before,current['id'])
        elif before['workspace'] or before['builds'] or before['comparisons']:
            save_record(db,'Before '+target['name'][:80],'Automatic recovery snapshot before opening a workbench.',before,automatic=True)
        fragments,plasmids=resolve_inventory(db,data,identifier)
        workspace=data['workspace'];remap_assembly(workspace.get('draft'),fragments,plasmids)
        for design in (workspace.get('design') or {}).get('designs',[]):
            if design.get('backbone_id'):design['backbone_id']=plasmids[design['backbone_id']]
            for entry in design.get('entries',[]):
                if entry.get('kind')=='fragment' and entry.get('fragment_id'):entry['fragment_id']=fragments[entry['fragment_id']]
        if isinstance(workspace.get('plannerStocks'),dict):workspace['plannerStocks']={str(fragments[int(key)]):value for key,value in workspace['plannerStocks'].items() if str(key).isdigit() and int(key) in fragments}
        stocks={}
        for key,value in workspace.get('backboneStocks',{}).items():
            kind,_,old=key.partition(':');mapping=plasmids if kind=='plasmid' else fragments
            if old.isdigit() and int(old) in mapping:stocks[kind+':'+str(mapping[int(old)])]=value
        workspace['backboneStocks']=stocks
        db.execute('UPDATE build_list SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        build_ids={}
        for item in data['builds']:
            remap_assembly(item['request'],fragments,plasmids)
            build_ids[item['id']]=db.execute('INSERT INTO build_list(request,user_id) VALUES(?,?)',(encode(item['request']),user_id())).lastrowid
        workspace['activeBuildId']=build_ids.get(workspace.get('activeBuildId'))
        db.execute('UPDATE comparison_runs SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        comparison_ids={}
        for item in data['comparisons']:
            comparison_ids[item['id']]=db.execute('INSERT INTO comparison_runs(user_id,filename,source,enzyme,result,error) VALUES(?,?,?,?,?,?)',
                (user_id(),item['filename'],item['source'],item['enzyme'],encode(item['result']) if item['result'] is not None else None,item['error'])).lastrowid
        view=workspace.get('compareView')
        if isinstance(view,dict) and isinstance(view.get('jobs'),dict):view['jobs']={str(comparison_ids[int(key)]):value for key,value in view['jobs'].items() if str(key).isdigit() and int(key) in comparison_ids}
        from .worksheets import restore_registry
        workspace['worksheet_ids']=restore_registry(db,data,identifier)
        workspace['workbench_id']=identifier;set_working(db,workspace)
    view=workspace.get('view')
    return {'opened':identifier,'view':view if view in ('build','design','library','uploads','compare') else 'build'}


@router.post('/new')
def new_workbench(payload:New):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');current=current_record(db)
        if current:save_record(db,current['name'],current['notes'],capture(db),current['id'])
        elif not payload.discard_unsaved:raise HTTPException(409,'Save this workbench or choose Start without saving.')
        else:
            # Retain individually saved worksheets in the recoverable archive,
            # while giving the next unnamed workbench an empty worksheet list.
            db.execute('UPDATE saved_worksheets SET archived_at=CURRENT_TIMESTAMP WHERE user_id=? AND workbench_id IS NULL AND archived_at IS NULL',(user_id(),))
        db.execute('UPDATE build_list SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        db.execute('UPDATE comparison_runs SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        set_working(db,{})
    return {'created':True,'autosaved':current['id'] if current else None}
