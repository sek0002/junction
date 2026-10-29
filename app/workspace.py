"""Private working state. The shared sequence library is never copied or filtered."""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import database as store
from .auth import user_id

router=APIRouter()


class Workspace(BaseModel):
    data:dict=Field(default_factory=dict)


@router.get('/api/workspace')
def workspace():
    with store.connection() as db:
        row=db.execute('SELECT data,updated_at FROM user_workspaces WHERE user_id=?',(user_id(),)).fetchone()
    return {'data':json.loads(row['data']) if row else {},'updated_at':row['updated_at'] if row else None}


@router.put('/api/workspace')
def save_workspace(payload:Workspace):
    try:encoded=json.dumps(payload.data,allow_nan=False)
    except (ValueError,TypeError):raise HTTPException(422,'Workspace must contain valid JSON values.') from None
    with store.connection() as db:
        db.execute('INSERT INTO user_workspaces(user_id,data) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP',(user_id(),encoded))
        from .worksheets import autosave
        autosave(db)
    return {'saved':True}


@router.get('/api/workspace/comparisons')
def comparisons():
    with store.connection() as db:
        rows=db.execute('SELECT * FROM comparison_runs WHERE user_id=? AND removed_at IS NULL ORDER BY id',(user_id(),)).fetchall()
    return {'items':[dict(row,result=json.loads(row['result']) if row['result'] else None) for row in rows]}


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
