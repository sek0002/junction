"""Private working state. The shared sequence library is never copied or filtered."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import database as store
from .auth import user_id
from .comparison_metrics import refresh_comparison_percentages
from .coding_analysis import refresh_coding_results
from .exports import parse_sequence_file

router=APIRouter()


WORKSHEET_KEYS = {
    'build': {'draft', 'activeBuildId', 'plannerOverrides', 'backboneStocks', 'subtab'},
    'design': {'design'}, 'compare': {'compareView'}, 'mrna': {'mrna'},
}
SHELL_KEYS = {'workbench_id', 'worksheet_ids', 'plasmidViews', 'uploadRuleOverrides', 'plannerOverrides'}


class Workspace(BaseModel):
    data:dict=Field(default_factory=dict)
    context_version:int | None=Field(default=None,ge=0)
    partial:bool=False


def projected_workspace(db,keys,*,shell=False):
    """Read only the requested JSON properties from an existing workspace."""
    fields=[f"json_quote(json_extract(data, '$.{key}')) AS {key}" for key in sorted(keys)]
    if shell:
        fields.extend(["json_extract(data,'$.draft.enzyme') AS enzyme",
                       "json_extract(data,'$.draft.name') AS assembly_name"])
    row=db.execute('SELECT context_version,'+', '.join(fields)+
                   ' FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone()
    result={'context_version':row['context_version'] if row else 0,
            'data':{key:json.loads(row[key]) for key in keys if row and row[key]!='null'}}
    if shell and row:
        result.update(enzyme=row['enzyme'],assembly_name=row['assembly_name'])
    return result


@router.get('/api/workspace')
def workspace(scope:Literal['shell','build','design','compare','mrna'] | None=None):
    with store.connection() as db:
        if scope is not None:
            return projected_workspace(db,SHELL_KEYS if scope=='shell' else WORKSHEET_KEYS[scope],shell=scope=='shell')
        row=db.execute('SELECT data,updated_at,context_version FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone()
    return {'data':json.loads(row['data']) if row else {},'updated_at':row['updated_at'] if row else None,'context_version':row['context_version'] if row else 0}


def write_workspace(db,payload):
    if payload.partial and payload.context_version is None:
        raise HTTPException(422,'A partial workspace save needs an instance version.')
    incoming=payload.data
    current=db.execute('SELECT data,context_version FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone()
    saved=json.loads(current['data']) if current else {}
    if payload.context_version is None and ('worksheet_ids' in payload.data or 'workbench_id' in payload.data):
        def context(data):
            return (data.get('workbench_id') or None,{key:value for key,value in data.get('worksheet_ids',{}).items() if value})
        if context(payload.data)!=context(saved):
            raise HTTPException(409,'Worksheet or Workbench changed. Reload Junction before saving; the stale save was not applied.')
    if payload.context_version is not None:
        if payload.context_version != (current['context_version'] if current else 0):
            raise HTTPException(409,'Worksheet or Workbench changed while this page was open. Reload Junction before saving; the stale save was not applied.')
        # Only explicit worksheet/workbench actions may change these pointers.
        incoming=(saved | payload.data) if payload.partial else dict(payload.data)
        for key in ('workbench_id','worksheet_ids'):
            incoming.pop(key,None)
            if key in saved:incoming[key]=saved[key]
    try:encoded=json.dumps(incoming,allow_nan=False)
    except (ValueError,TypeError):raise HTTPException(422,'Workspace must contain valid JSON values.') from None
    db.execute('INSERT INTO user_workspaces(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP',(user_id(),encoded))
    return incoming


@router.put('/api/workspace')
def save_workspace(payload:Workspace):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        write_workspace(db,payload)
        from .worksheets import autosave
        autosave(db,changed=payload.data if payload.partial else None)
    return {'saved':True}


@router.get('/api/workspace/comparisons')
def comparisons():
    with store.connection() as db:
        rows=db.execute('SELECT * FROM comparison_runs WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),)).fetchall()
    return {'items':[dict(row,result=restored_comparison(row)) for row in rows]}


def restored_comparison(row):
    if not row['result']:
        return None
    result=refresh_comparison_percentages(json.loads(row['result']))
    records=result.get('records') or [result]
    if any('query_features' not in record for record in records):
        try:
            source_records=parse_sequence_file(row['source'],row['filename'])
        except (ValueError,IndexError):
            source_records=[]
        by_name={record['name']:record.get('features',[]) for record in source_records}
        for record in records:
            record.setdefault('query_features',by_name.get(record.get('query_name'),[]))
    return refresh_coding_results(result)


@router.delete('/api/workspace/comparisons')
def clear_comparisons():
    with store.connection() as db:
        db.execute('UPDATE comparison_runs SET removed_at=CURRENT_TIMESTAMP WHERE user_id=? AND removed_at IS NULL',(user_id(),))
        from .worksheets import preserve
        preserve(db,'compare')
    return {'cleared':True}


@router.delete('/api/workspace/comparisons/{run_id}')
def remove_comparison(run_id:int):
    with store.connection() as db:
        changed=db.execute('UPDATE comparison_runs SET removed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND removed_at IS NULL',(run_id,user_id()))
        if not changed.rowcount:raise HTTPException(404,'Comparison not found.')
        from .worksheets import preserve
        preserve(db,'compare')
    return {'removed':run_id}


def begin_comparison(filename,content,enzyme,run_id=None):
    with store.connection() as db:
        if run_id is not None:
            row=db.execute('SELECT id FROM comparison_runs WHERE id=? AND user_id=? AND removed_at IS NULL',(run_id,user_id())).fetchone()
            if not row:raise HTTPException(404,'Comparison not found.')
            db.execute('UPDATE comparison_runs SET filename=?,source=? WHERE id=? AND user_id=?',
                (filename,content.decode('utf-8-sig',errors='replace'),run_id,user_id()))
            from .worksheets import preserve
            preserve(db,'compare')
            return run_id
        identifier=db.execute('INSERT INTO comparison_runs(user_id,filename,source,enzyme) VALUES(?,?,?,?)',
            (user_id(),filename,content.decode('utf-8-sig',errors='replace'),enzyme)).lastrowid
        from .worksheets import preserve
        preserve(db,'compare')
        return identifier


def finish_comparison(run_id,enzyme,result=None,error=None):
    with store.connection() as db:
        db.execute('UPDATE comparison_runs SET enzyme=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND removed_at IS NULL',
            (enzyme,json.dumps(result) if result is not None else None,error,run_id,user_id()))
        from .worksheets import preserve
        preserve(db,'compare')
