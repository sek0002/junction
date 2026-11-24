"""Shared plasmid folders and reviewed, atomic saves from the private build list."""
import hashlib
import json
import sqlite3
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from . import database as store
from .auth import user_id, check_plasmid_write
from . import worksheets, workbenches

router=APIRouter(tags=['Plasmid library'])


class FolderName(BaseModel):
    name:str=Field(min_length=1,max_length=100)

    @field_validator('name',mode='before')
    @classmethod
    def strip_name(cls,value):return value.strip() if isinstance(value,str) else value


class FolderAssignment(BaseModel):
    plasmid_ids:list[int]=Field(min_length=1,max_length=5000)
    folder_id:int | None=Field(None,gt=0)


class BulkSave(BaseModel):
    build_ids:list[int]=Field(min_length=1,max_length=50)
    context_version:int=Field(ge=0)
    fingerprint:str=Field(min_length=64,max_length=64)
    folder_id:int | None=Field(None,gt=0)
    folder_name:str | None=Field(None,min_length=1,max_length=100)

    @field_validator('folder_name',mode='before')
    @classmethod
    def strip_name(cls,value):return value.strip() if isinstance(value,str) else value


def folder_exists(db,identifier):
    if identifier is not None and not db.execute('SELECT 1 FROM plasmid_folders WHERE id=?',(identifier,)).fetchone():raise HTTPException(404,'Folder not found.')


@router.get('/api/plasmid-folders')
def folders():
    with store.connection() as db:
        return {'items':[dict(row) for row in db.execute('SELECT f.id,f.name,f.created_at,count(p.id) AS count FROM plasmid_folders f LEFT JOIN plasmids p ON p.folder_id=f.id AND p.archived_at IS NULL GROUP BY f.id ORDER BY f.name_key,f.id')]}


@router.post('/api/plasmid-folders',status_code=201)
def create_folder(payload:FolderName):
    with store.connection() as db:
        try:identifier=db.execute('INSERT INTO plasmid_folders(name,name_key) VALUES(?,?)',(payload.name,payload.name.casefold())).lastrowid
        except sqlite3.IntegrityError:raise HTTPException(409,'A folder with this name already exists.') from None
    return {'id':identifier,'name':payload.name,'count':0}


@router.patch('/api/plasmid-folders/{folder_id}')
def rename_folder(folder_id:int,payload:FolderName):
    with store.connection() as db:
        folder_exists(db,folder_id)
        try:db.execute('UPDATE plasmid_folders SET name=?,name_key=? WHERE id=?',(payload.name,payload.name.casefold(),folder_id))
        except sqlite3.IntegrityError:raise HTTPException(409,'A folder with this name already exists.') from None
    return {'id':folder_id,'name':payload.name}


@router.delete('/api/plasmid-folders/{folder_id}')
def delete_folder(folder_id:int):
    with store.connection() as db:
        folder_exists(db,folder_id)
        count=db.execute('SELECT count(*) FROM plasmids WHERE folder_id=?',(folder_id,)).fetchone()[0]
        db.execute('DELETE FROM plasmid_folders WHERE id=?',(folder_id,))
    return {'removed':folder_id,'unfiled':count}


@router.post('/api/plasmid-folders/assign')
def assign_folder(payload:FolderAssignment):
    identifiers=list(dict.fromkeys(payload.plasmid_ids));marks=','.join('?' for _ in identifiers)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');folder_exists(db,payload.folder_id)
        rows=db.execute(f'SELECT id FROM plasmids WHERE id IN ({marks}) AND archived_at IS NULL',identifiers).fetchall()
        if len(rows)!=len(identifiers):raise HTTPException(404,'A selected plasmid is unavailable.')
        db.execute(f'UPDATE plasmids SET folder_id=? WHERE id IN ({marks})',[payload.folder_id,*identifiers])
    return {'count':len(identifiers),'folder_id':payload.folder_id}


def current_context(db,expected):
    row=db.execute('SELECT context_version FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone();version=row['context_version'] if row else 0
    if version!=expected:raise HTTPException(409,'The worksheet changed. Reload the build list before saving.')
    sheet=worksheets.current(db,'build')
    return version,sheet['name'] if sheet else 'Unsaved assembly'


def build_records(db):
    return db.execute('SELECT id,request FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),)).fetchall()


def fingerprint(rows):return hashlib.sha256(json.dumps([(row['id'],row['request']) for row in rows],separators=(',',':')).encode()).hexdigest()


def prepare(row):
    from .main import AssemblyRequest,build
    request=AssemblyRequest.model_validate(json.loads(row['request']));result,_=build(request)
    if result.get('errors'):raise HTTPException(422,{'message':'Resolve assembly errors before saving.','errors':result['errors']})
    template=result['backbone_template']
    if request.save_as_backbone and not template['eligible']:raise HTTPException(422,'This assembly is not eligible as a backbone template.')
    return request,result


@router.get('/api/build-list/plasmid-preview')
def preview_build_save(context_version:int=Query(ge=0)):
    with store.connection() as db:
        version,name=current_context(db,context_version);rows=build_records(db);items=[]
        for row in rows:
            label=json.loads(row['request']).get('name','Assembly')
            try:
                request,result=prepare(row)
                items.append({'id':row['id'],'name':label,'eligible':True,'length':len(result['sequence']),'circular':result['circular'],'warnings':result.get('warnings',[])})
            except (HTTPException,ValueError) as error:
                detail=error.detail if isinstance(error,HTTPException) else str(error)
                items.append({'id':row['id'],'name':label,'eligible':False,'error':detail})
    return {'items':items,'folder_name':name,'context_version':version,'fingerprint':fingerprint(rows)}


@router.post('/api/build-list/save-plasmids')
def save_build_plasmids(payload:BulkSave):
    selected=set(payload.build_ids)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');_,default_name=current_context(db,payload.context_version);rows=build_records(db)
        if fingerprint(rows)!=payload.fingerprint:raise HTTPException(409,'The build list changed. Review the save list again.')
        if selected-{row['id'] for row in rows}:raise HTTPException(404,'A selected build is unavailable.')
        prepared=[(row,*prepare(row)) for row in rows if row['id'] in selected]
        # Check duplicate/restore permissions for the entire batch before writing any records.
        for row,request,result in prepared:check_plasmid_write(db,request.name,result['sequence'])
        if payload.folder_id is not None:folder_exists(db,payload.folder_id);folder_id=payload.folder_id
        else:folder_id=store.ensure_plasmid_folder(db,payload.folder_name or default_name)
        items=[]
        for row,request,result in prepared:
            existing=db.execute('SELECT id FROM plasmids WHERE name=? AND sequence=?',(request.name,result['sequence'])).fetchone()
            identifier=store.save_plasmid(request.name,result['sequence'],result.get('features'),request.model_dump(),
                notes='Saved from the Assembly build list.',circular=result['circular'],
                backbone_enzymes=result['backbone_template']['enzymes'] if request.save_as_backbone else None,folder_id=folder_id,merge_annotations=True,db=db)
            items.append({'id':identifier,'build_id':row['id'],'name':request.name,'created':existing is None})
        folder=dict(db.execute('SELECT id,name FROM plasmid_folders WHERE id=?',(folder_id,)).fetchone())
    return {'items':items,'folder':folder,'created':sum(item['created'] for item in items),'reused':sum(not item['created'] for item in items)}
