"""Page-scoped private worksheets inside a named workbench."""
import hashlib
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import database as store
from .auth import user_id
from . import workbenches as wb

router=APIRouter(prefix='/api/worksheets')
Scope=Literal['build','design','compare']
KEYS={'build':{'draft','activeBuildId','plannerOverrides','backboneStocks','subtab'},
      'design':{'design'},'compare':{'compareView'}}
FORMAT='junction-worksheet'


class Save(wb.Save):
    scope:Scope


class New(BaseModel):
    scope:Scope
    discard_unsaved:bool=False


def parent(db):return wb.working(db).get('workbench_id')


def current(db,scope):
    identifier=wb.working(db).get('worksheet_ids',{}).get(scope)
    return db.execute('SELECT * FROM saved_worksheets WHERE id=? AND user_id=? AND scope=? AND archived_at IS NULL',(identifier,user_id(),scope)).fetchone() if identifier else None


def owned(db,identifier):
    row=db.execute('SELECT * FROM saved_worksheets WHERE id=? AND user_id=? AND archived_at IS NULL',(identifier,user_id())).fetchone()
    if not row:raise HTTPException(404,'Worksheet not found.')
    return row


def summary(row):return wb.summary(row)|{'scope':row['scope']}


def subset(data,scope):
    workspace={key:value for key,value in data['workspace'].items() if key in KEYS[scope]}
    workspace['view']=scope
    # One Design worksheet is one design. Legacy designs are migrated separately.
    if scope=='design' and workspace.get('design'):
        design=workspace['design'];active=next((item for item in design.get('designs',[]) if item.get('id')==design.get('activeId')),None)
        if active:workspace['design']={'designs':[active],'activeId':active['id']}
    result={'workspace':workspace,'builds':data['builds'] if scope=='build' else [],
        'comparisons':data['comparisons'] if scope=='compare' else [],'inventory':data['inventory']}
    fragments,plasmids=wb.references(result)
    result['inventory']={kind:[item for item in data['inventory'][kind] if item['id'] in ids] for kind,ids in [('fragments',fragments),('plasmids',plasmids)]}
    return wb.checked(result)


def save_record(db,name,notes,scope,data,identifier=None,automatic=False):
    name=name.strip()
    if not name:raise HTTPException(422,'Enter a worksheet name.')
    if identifier and owned(db,identifier)['scope']!=scope:raise HTTPException(422,'Worksheet type does not match.')
    meta=wb.metadata(db,data,scope=scope,automatic=automatic)
    if identifier:
        db.execute("UPDATE saved_worksheets SET name=?,notes=?,payload=?,metadata=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND user_id=?",(name,notes,wb.encode(data),wb.encode(meta),identifier,user_id()))
    else:
        identifier=str(uuid4())
        db.execute('INSERT INTO saved_worksheets(id,user_id,workbench_id,scope,name,notes,payload,metadata) VALUES(?,?,?,?,?,?,?,?)',(identifier,user_id(),parent(db),scope,name,notes,wb.encode(data),wb.encode(meta)))
    return owned(db,identifier)


def set_current(db,scope,identifier):
    workspace=wb.working(db);workspace.setdefault('worksheet_ids',{})[scope]=identifier;wb.set_working(db,workspace)


def capture(db,scope):return subset(wb.capture(db,include_worksheets=False,scope=scope),scope)


def registry(db,live=True):
    rows=db.execute('SELECT * FROM saved_worksheets WHERE user_id=? AND workbench_id IS ? AND archived_at IS NULL ORDER BY created_at,id',(user_id(),parent(db))).fetchall()
    active=wb.working(db).get('worksheet_ids',{})
    return [{'id':row['id'],'scope':row['scope'],'name':row['name'],'notes':row['notes'],
        'snapshot':capture(db,row['scope']) if live and active.get(row['scope'])==row['id'] else json.loads(row['payload'])} for row in rows]


def restore_registry(db,data,workbench_id):
    db.execute('UPDATE saved_worksheets SET archived_at=CURRENT_TIMESTAMP WHERE user_id=? AND workbench_id IS ? AND archived_at IS NULL',(user_id(),workbench_id))
    mapping={}
    for item in data.get('worksheets',[]):
        identifier=str(uuid4());mapping[item['id']]=identifier;payload=wb.checked(item['snapshot'])
        db.execute('INSERT INTO saved_worksheets(id,user_id,workbench_id,scope,name,notes,payload,metadata) VALUES(?,?,?,?,?,?,?,?)',
            (identifier,user_id(),workbench_id,item['scope'],item['name'],item['notes'],wb.encode(payload),wb.encode(wb.metadata(db,payload,scope=item['scope']))))
    return {scope:mapping[old] for scope,old in data.get('worksheet_active',{}).items() if old in mapping}


def reparent_on_save(db,data,identifier):
    if parent(db)==identifier:return wb.working(db).get('worksheet_ids',{})
    if parent(db) is None:
        db.execute('UPDATE saved_worksheets SET workbench_id=? WHERE user_id=? AND workbench_id IS NULL',(identifier,user_id()))
        return wb.working(db).get('worksheet_ids',{})
    return restore_registry(db,data,identifier)


@router.get('')
def list_worksheets(scope:Scope,archived:bool=False):
    with store.connection() as db:
        rows=db.execute('SELECT * FROM saved_worksheets WHERE user_id=? AND workbench_id IS ? AND scope=? AND (archived_at IS NOT NULL)=? ORDER BY updated_at DESC,id',(user_id(),parent(db),scope,archived)).fetchall()
        active=current(db,scope)
    return {'items':[summary(row) for row in rows],'current':summary(active) if active else None}


@router.post('')
def save_worksheet(payload:Save):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=save_record(db,payload.name,payload.notes,payload.scope,capture(db,payload.scope),payload.id);set_current(db,payload.scope,row['id'])
    return summary(row)


def bundle(data,scope,name='Worksheet',notes=''):
    return {'format':FORMAT,'format_version':1,'scope':scope,'worksheet':{'name':name,'notes':notes},'snapshot':data,'sha256':hashlib.sha256(wb.encode(data).encode()).hexdigest()}


@router.post('/bootstrap')
def bootstrap_legacy_designs():
    """Retain older multi-design sandboxes as individual selectable worksheets."""
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM saved_worksheets WHERE user_id=? AND workbench_id IS ? AND scope='design' AND archived_at IS NULL",(user_id(),parent(db))).fetchone():return {'migrated':0}
        data=wb.capture(db,include_worksheets=False);designs=data['workspace'].get('design',{});count=0;selected=None
        for design in designs.get('designs',[]):
            if not design.get('entries') and design.get('name')=='New design':continue
            copy=json.loads(wb.encode(data));copy['workspace']['design']={'designs':[design],'activeId':design['id']}
            row=save_record(db,design['name'],'','design',subset(copy,'design'));count+=1
            if design['id']==designs.get('activeId'):selected=row['id']
        if selected:set_current(db,'design',selected)
    return {'migrated':count}


@router.post('/export-current')
def export_current(scope:Scope):
    with store.connection() as db:
        data=capture(db,scope);record=current(db,scope)
    return wb.download(bundle(data,scope,record['name'] if record else scope.title()+' worksheet',record['notes'] if record else ''),record['name'] if record else scope.title()+'_worksheet')


@router.get('/{identifier}/export')
def export_saved(identifier:str):
    with store.connection() as db:row=owned(db,identifier)
    return wb.download(bundle(json.loads(row['payload']),row['scope'],row['name'],row['notes']),row['name'])


@router.post('/import')
async def import_worksheet(scope:Scope | None=None,file:UploadFile=File(...)):
    if not (file.filename or '').lower().endswith('.junc'):raise HTTPException(422,'Choose a .junc file.')
    content=await file.read()
    try:
        value=json.loads(content.decode('utf-8-sig'))
        if value.get('format_version')!=1 or value.get('format') not in (FORMAT,wb.FORMAT):raise ValueError('Unsupported .junc format.')
        original=value['snapshot'];data=wb.checked(original)
        if value.get('sha256')!=hashlib.sha256(wb.encode(original).encode()).hexdigest():raise ValueError('Checksum does not match.')
        if value['format']==FORMAT:
            source_scope=value['scope']
            if source_scope not in KEYS or (scope and scope!=source_scope):raise ValueError('Worksheet type does not match the selected page.')
            scope=source_scope;title=wb.Name.model_validate(value['worksheet'])
        else:
            if scope is None:raise ValueError('Choose a worksheet type to extract from this workbench.')
            title=wb.Name.model_validate(value['workbench'])
        data=subset(data,scope)
    except (UnicodeError,ValueError,TypeError,KeyError,AttributeError,RecursionError) as error:raise HTTPException(422,'Invalid worksheet: '+str(error)[:200]) from None
    with store.connection() as db:row=save_record(db,title.name,title.notes,scope,data)
    return summary(row)


def replace_page(db,data,scope,identifier=None):
    fragments,plasmids=wb.resolve_inventory(db,data,parent(db) or identifier or uuid4().hex)
    page=data['workspace'];wb.remap_assembly(page.get('draft'),fragments,plasmids)
    for design in (page.get('design') or {}).get('designs',[]):
        if design.get('backbone_id'):design['backbone_id']=plasmids[design['backbone_id']]
        for entry in design.get('entries',[]):
            if entry.get('kind')=='fragment' and entry.get('fragment_id'):entry['fragment_id']=fragments[entry['fragment_id']]
    if scope=='build':
        stocks={}
        for key,value in page.get('backboneStocks',{}).items():
            kind,_,old=key.partition(':');mapping=plasmids if kind=='plasmid' else fragments
            if old.isdigit() and int(old) in mapping:stocks[kind+':'+str(mapping[int(old)])]=value
        page['backboneStocks']=stocks
        db.execute('UPDATE build_list SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        ids={}
        for item in data['builds']:
            wb.remap_assembly(item['request'],fragments,plasmids)
            ids[item['id']]=db.execute('INSERT INTO build_list(request,user_id) VALUES(?,?)',(wb.encode(item['request']),user_id())).lastrowid
        page['activeBuildId']=ids.get(page.get('activeBuildId'))
    if scope=='compare':
        db.execute('UPDATE comparison_runs SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),));ids={}
        for item in data['comparisons']:
            ids[item['id']]=db.execute('INSERT INTO comparison_runs(user_id,filename,source,enzyme,result,error) VALUES(?,?,?,?,?,?)',
                (user_id(),item['filename'],item['source'],item['enzyme'],wb.encode(item['result']) if item['result'] is not None else None,item['error'])).lastrowid
        view=page.get('compareView',{})
        if isinstance(view.get('jobs'),dict):view['jobs']={str(ids[int(key)]):value for key,value in view['jobs'].items() if str(key).isdigit() and int(key) in ids}
    workspace=wb.working(db)
    for key in KEYS[scope]:workspace.pop(key,None)
    workspace.update(page);workspace.setdefault('worksheet_ids',{})[scope]=identifier;wb.set_working(db,workspace)


def preserve(db,scope):
    record=current(db,scope);data=capture(db,scope)
    if record:save_record(db,record['name'],record['notes'],scope,data,record['id'])
    elif data['builds'] or data['comparisons'] or any(key in data['workspace'] for key in KEYS[scope]):
        save_record(db,'Recovered '+scope.title(),'Automatic recovery snapshot.',scope,data,automatic=True)


@router.post('/{identifier}/open')
def open_worksheet(identifier:str):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');target=owned(db,identifier)
        if target['workbench_id']!=parent(db):raise HTTPException(409,'Open the owning workbench first.')
        active=current(db,target['scope'])
        if active and active['id']==identifier:return {'view':target['scope']}
        preserve(db,target['scope']);replace_page(db,wb.checked(json.loads(target['payload'])),target['scope'],identifier)
    return {'view':target['scope']}


@router.post('/new')
def new_worksheet(payload:New):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');record=current(db,payload.scope)
        if record:save_record(db,record['name'],record['notes'],payload.scope,capture(db,payload.scope),record['id'])
        elif not payload.discard_unsaved:raise HTTPException(409,'Save this worksheet or choose Start without saving.')
        replace_page(db,{'workspace':{'view':payload.scope},'inventory':{'fragments':[],'plasmids':[]},'builds':[],'comparisons':[]},payload.scope)
    return {'view':payload.scope,'autosaved':record['id'] if record else None}


@router.delete('/{identifier}')
def archive_worksheet(identifier:str):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');record=owned(db,identifier)
        active=current(db,record['scope'])
        if active and active['id']==identifier:save_record(db,record['name'],record['notes'],record['scope'],capture(db,record['scope']),identifier)
        db.execute('UPDATE saved_worksheets SET archived_at=CURRENT_TIMESTAMP WHERE id=?',(identifier,))
        if current(db,record['scope']) is None:
            data=wb.working(db);data.setdefault('worksheet_ids',{}).pop(record['scope'],None);wb.set_working(db,data)
    return {'archived':identifier}


@router.post('/{identifier}/restore')
def restore_worksheet(identifier:str):
    with store.connection() as db:
        row=db.execute('SELECT * FROM saved_worksheets WHERE id=? AND user_id=?',(identifier,user_id())).fetchone()
        if not row:raise HTTPException(404,'Worksheet not found.')
        db.execute('UPDATE saved_worksheets SET archived_at=NULL WHERE id=?',(identifier,))
    return {'restored':identifier}
