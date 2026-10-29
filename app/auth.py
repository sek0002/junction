"""PIN accounts and revocable, persistent server-side login sessions."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from . import database as store

COOKIE='junction_session'
SESSION_SECONDS=7*24*60*60
STATIC=Path(__file__).parent/'static'
router=APIRouter()
_user=ContextVar('junction_user',default=None)
PERMISSIONS=('can_upload','can_edit','can_archive','can_manage_rules')


def user_id():
    user=_user.get()
    if not user:raise HTTPException(401,'Sign in to Junction.')
    return user['id']


def permitted(user,right):
    return bool(user and (user['is_admin'] or user.get(right)))


def check_plasmid_write(db,name,sequence):
    """Adding a duplicate can update metadata or restore an archived record."""
    user=_user.get()
    if not user:return  # Internal seeding and database fixtures have no HTTP actor.
    old=db.execute('SELECT archived_at FROM plasmids WHERE name=? AND sequence=?',(name,sequence)).fetchone()
    if old:
        if not permitted(user,'can_edit'):raise HTTPException(403,'Editing an existing plasmid requires Edit library permission.')
        if old['archived_at'] and not permitted(user,'can_archive'):raise HTTPException(403,'Restoring an archived plasmid requires Archive permission.')


def hash_pin(pin):
    salt=secrets.token_hex(16)
    digest=hashlib.scrypt(pin.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    return 'scrypt$'+salt+'$'+digest


def verify_pin(pin,encoded):
    _,salt,expected=encoded.split('$')
    actual=hashlib.scrypt(pin.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    return hmac.compare_digest(actual,expected)


DUMMY_HASH=hash_pin('000000')


def initial_pin_path():
    return store.db_path().with_suffix('.initial-admin-pin')


def new_initial_pin():
    pin=os.environ.get('GOLDEN_GATE_INITIAL_ADMIN_PIN')
    if pin is None:pin=f'{secrets.randbelow(10**12):012d}'
    if not (6<=len(pin)<=12 and pin.isascii() and pin.isdigit()):
        raise ValueError('GOLDEN_GATE_INITIAL_ADMIN_PIN must contain 6–12 digits.')
    path=initial_pin_path();temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.initial-admin-',delete=False) as stream:
            temporary=Path(stream.name);os.chmod(temporary,0o600);stream.write(pin+'\n')
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return pin


def discard_initial_pin():
    try:initial_pin_path().unlink(missing_ok=True)
    except OSError:pass


def initialize():
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS auth_users(
            id INTEGER PRIMARY KEY,username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            pin_hash TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS auth_sessions(
            token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES auth_users(id),
            expires_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
        CREATE TABLE IF NOT EXISTS auth_attempts(
            key TEXT PRIMARY KEY,failures INTEGER NOT NULL,window_start INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS activity_log(
            id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT NOT NULL,
            action TEXT NOT NULL,target TEXT NOT NULL,status INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE INDEX IF NOT EXISTS activity_user ON activity_log(user_id,id);
        CREATE TABLE IF NOT EXISTS user_workspaces(
            user_id INTEGER PRIMARY KEY REFERENCES auth_users(id),data TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS comparison_runs(
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES auth_users(id),
            filename TEXT NOT NULL,source TEXT NOT NULL,enzyme TEXT NOT NULL,
            result TEXT,error TEXT,removed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS comparison_owner ON comparison_runs(user_id,removed_at,id);
        CREATE TABLE IF NOT EXISTS saved_workbenches(
            id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES auth_users(id),
            name TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',payload TEXT NOT NULL,metadata TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE INDEX IF NOT EXISTS workbench_owner ON saved_workbenches(user_id,updated_at);
        CREATE TABLE IF NOT EXISTS saved_worksheets(
            id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES auth_users(id),
            workbench_id TEXT,scope TEXT NOT NULL,name TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL,metadata TEXT NOT NULL,archived_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE TABLE IF NOT EXISTS worksheet_drafts(
            user_id INTEGER NOT NULL REFERENCES auth_users(id),workbench_key TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL,payload TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,workbench_key,scope));
        CREATE INDEX IF NOT EXISTS worksheet_owner ON saved_worksheets(user_id,workbench_id,scope,archived_at);
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(auth_users)')}
        for field in PERMISSIONS:
            if field not in columns:db.execute(f'ALTER TABLE auth_users ADD COLUMN {field} INTEGER NOT NULL DEFAULT 1')
        if 'deleted_at' not in columns:db.execute('ALTER TABLE auth_users ADD COLUMN deleted_at TEXT')
        if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM settings WHERE key='auth_bootstrapped'").fetchone():
            if not db.execute("SELECT 1 FROM auth_users WHERE username='admin'").fetchone():
                db.execute('INSERT INTO auth_users(username,pin_hash,is_admin) VALUES(?,?,1)',('admin',hash_pin(new_initial_pin())))
            db.execute("INSERT INTO settings(key,value) VALUES('auth_bootstrapped','true')")
        if 'user_id' not in {r['name'] for r in db.execute('PRAGMA table_info(build_list)')}:
            db.execute('ALTER TABLE build_list ADD COLUMN user_id INTEGER REFERENCES auth_users(id)')
        owner=db.execute('SELECT id FROM auth_users WHERE is_admin=1 ORDER BY id LIMIT 1').fetchone()
        if owner:db.execute('UPDATE build_list SET user_id=? WHERE user_id IS NULL',(owner['id'],))
        db.execute('CREATE INDEX IF NOT EXISTS build_list_owner ON build_list(user_id,removed_at,id)')
        db.execute('DELETE FROM auth_sessions WHERE expires_at<=?',(int(time.time()),))


def public_user(row):
    return {'id':row['id'],'username':row['username'],'is_admin':bool(row['is_admin']),'active':bool(row['active']),
        'deleted_at':row['deleted_at'],**{key:bool(row[key]) for key in PERMISSIONS}}


def session_user(token):
    if not token or len(token)>200:return None
    with store.connection() as db:
        row=db.execute('SELECT u.*,s.expires_at FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1 AND u.deleted_at IS NULL',
            (hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    return public_user(row) | {'expires_at':row['expires_at']} if row else None


def write_permission(path,method,preview=False):
    if method in ('GET','HEAD','OPTIONS'):return None
    if path.startswith(('/api/auth/','/api/workspace','/api/build-list','/api/workbenches','/api/worksheets')):return None
    if path=='/api/uploads/custom/parse' or path=='/api/uploads/plate' and preview:return None
    if path in ('/api/uploads/plate','/api/uploads/plasmid','/api/uploads/custom','/api/assemblies'):return 'can_upload'
    if path in ('/api/inventory/rules','/api/inventory/rules/reset'):return 'can_manage_rules'
    if path in ('/api/bin/archive','/api/bin/restore'):return 'can_archive'
    if path in ('/api/inventory/reset','/api/inventory/apply-rules') or (method=='PATCH' and path.startswith(('/api/fragments/','/api/plasmids/'))):return 'can_edit'
    if path in ('/api/design/preview','/api/design/export','/api/assemblies/preview','/api/assemblies/genbank','/api/assemblies/worksheet','/api/inventory/worksheet','/api/inventory/resuspension','/api/compare','/api/compare/export'):return None
    return 'admin'


def audit(user,action,target,status):
    with store.connection() as db:
        db.execute('INSERT INTO activity_log(user_id,username,action,target,status) VALUES(?,?,?,?,?)',
            (user.get('id'),user.get('username','anonymous'),action,str(target)[:240],status))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        path=request.url.path
        # SameSite cookies plus origin checks protect cookie-authenticated writes.
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if (origin and origin!=str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site')=='cross-site':
                return JSONResponse({'detail':'Cross-origin requests are not allowed.'},status_code=403)
        public=(path.startswith('/static/') and path!='/static/index.html') or path in ('/login','/manifest.webmanifest','/service-worker.js','/api/auth/login')
        user=None if public and path!='/login' else await run_in_threadpool(session_user,request.cookies.get(COOKIE))
        request.state.user=user
        if not public and not user:
            if path.startswith('/api/') or path=='/openapi.json':
                return JSONResponse({'detail':'Sign in to Junction.'},status_code=401,headers={'Cache-Control':'no-store'})
            return RedirectResponse('/login',status_code=303,headers={'Cache-Control':'no-store'})
        expected=request.headers.get('x-junction-user')
        if user and expected and expected!=str(user['id']):
            return JSONResponse({'detail':'Account changed. Reload Junction.'},status_code=409,headers={'X-Junction-Account-Changed':'1','Cache-Control':'no-store'})
        right=write_permission(path,request.method,request.query_params.get('preview','').lower() in ('true','1'))
        if user and right and not permitted(user,right):
            await run_in_threadpool(audit,user,request.method,path,403)
            return JSONResponse({'detail':'Your account does not have permission for this library change.'},status_code=403,headers={'Cache-Control':'no-store'})
        token=_user.set(user)
        try:response=await call_next(request)
        finally:_user.reset(token)
        actor=getattr(request.state,'audit_user',None) or user
        # Record actions and downloads, without request bodies, PINs or DNA.
        track=request.method not in ('GET','HEAD','OPTIONS') or path.endswith(('/genbank','/worksheet','/well-list','/export'))
        if actor and track and path.startswith('/api/') and path!='/api/workspace':
            await run_in_threadpool(audit,actor,request.method,path+getattr(request.state,'audit_detail',''),response.status_code)
        if path.startswith('/api/') or path in ('/','/login','/static/index.html','/docs','/redoc','/openapi.json'):
            response.headers['Cache-Control']='no-store'
            response.headers['Vary']='Cookie'
        return response


class Login(BaseModel):
    username:str=Field(min_length=1,max_length=64)
    pin:str=Field(pattern=r'^[0-9]{6,12}$',repr=False)

    @field_validator('username')
    @classmethod
    def username_format(cls,value):
        value=value.strip()
        if not value or any(not (c.isascii() and (c.isalnum() or c in '_.-')) for c in value):
            raise ValueError('Use letters, numbers, dots, hyphens or underscores for usernames.')
        return value.lower()


class NewUser(Login):
    is_admin:bool=False
    can_upload:bool=True
    can_edit:bool=True
    can_archive:bool=True
    can_manage_rules:bool=True


class UserPatch(BaseModel):
    pin:str | None=Field(None,pattern=r'^[0-9]{6,12}$',repr=False)
    active:bool | None=None
    is_admin:bool | None=None
    can_upload:bool | None=None
    can_edit:bool | None=None
    can_archive:bool | None=None
    can_manage_rules:bool | None=None


class ChangePin(BaseModel):
    current_pin:str=Field(pattern=r'^[0-9]{6,12}$',repr=False)
    new_pin:str=Field(pattern=r'^[0-9]{6,12}$',repr=False)


def admin_only(request):
    if not request.state.user['is_admin']:raise HTTPException(403,'Admin access required.')


def attempt_keys(request,username):
    ip=request.client.host if request.client else 'local'
    return [('user:'+username,5),('ip:'+hashlib.sha256(ip.encode()).hexdigest(),20)]


def check_attempts(db,keys,now):
    for key,limit in keys:
        row=db.execute('SELECT * FROM auth_attempts WHERE key=?',(key,)).fetchone()
        if row and now-row['window_start']<900 and row['failures']>=limit:
            raise HTTPException(429,'Too many attempts. Try again in 15 minutes.',headers={'Retry-After':'900'})


def failed_attempt(db,keys,now):
    for key,_ in keys:
        db.execute('INSERT INTO auth_attempts(key,failures,window_start) VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=CASE WHEN ?-window_start>=900 THEN 1 ELSE failures+1 END,window_start=CASE WHEN ?-window_start>=900 THEN ? ELSE window_start END',(key,now,now,now,now))


@router.get('/login',include_in_schema=False)
def login_page(request:Request):
    if request.state.user:return RedirectResponse('/',status_code=303)
    return FileResponse(STATIC/'login.html')


@router.post('/api/auth/login')
def login(payload:Login,request:Request):
    now=int(time.time());keys=attempt_keys(request,payload.username)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        check_attempts(db,keys,now)
        row=db.execute('SELECT * FROM auth_users WHERE username=?',(payload.username,)).fetchone()
        valid=verify_pin(payload.pin,row['pin_hash'] if row else DUMMY_HASH)
        request.state.audit_user={'id':row['id'] if row else None,'username':payload.username}
        if not valid or not row or not row['active'] or row['deleted_at']:
            failed_attempt(db,keys,now)
            # Commit failures before returning an error so limits survive restarts.
            response=JSONResponse({'detail':'Username or PIN is incorrect.'},status_code=401)
        else:
            db.execute('DELETE FROM auth_attempts WHERE key=?',(keys[0][0],))
            old=request.cookies.get(COOKIE)
            if old:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(old.encode()).hexdigest(),))
            token=secrets.token_urlsafe(32);expires=now+SESSION_SECONDS
            db.execute('INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],expires))
            response=JSONResponse({'user':public_user(row),'expires_at':expires})
            response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
    return response


@router.get('/api/auth/session')
def session(request:Request):
    user=dict(request.state.user);expires=user.pop('expires_at')
    return {'user':user,'expires_at':expires}


@router.post('/api/auth/logout')
def logout(request:Request):
    with store.connection() as db:
        db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest(),))
    response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');return response


@router.post('/api/auth/pin')
def change_pin(payload:ChangePin,request:Request):
    now=int(time.time());keys=attempt_keys(request,request.state.user['username'])
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');check_attempts(db,keys,now)
        row=db.execute('SELECT * FROM auth_users WHERE id=?',(request.state.user['id'],)).fetchone()
        if not verify_pin(payload.current_pin,row['pin_hash']):
            failed_attempt(db,keys,now)
            return JSONResponse({'detail':'Current PIN is incorrect.'},status_code=400)
        db.execute('UPDATE auth_users SET pin_hash=? WHERE id=?',(hash_pin(payload.new_pin),row['id']))
        db.execute('DELETE FROM auth_sessions WHERE user_id=?',(row['id'],))
        db.execute('DELETE FROM auth_attempts WHERE key=?',(keys[0][0],))
    if row['username']=='admin':discard_initial_pin()
    response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');return response


@router.get('/api/auth/users')
def users(request:Request,include_deleted:bool=False):
    admin_only(request)
    with store.connection() as db:return [public_user(row) for row in db.execute('SELECT * FROM auth_users'+('' if include_deleted else ' WHERE deleted_at IS NULL')+' ORDER BY username')]


@router.post('/api/auth/users',status_code=201)
def create_user(payload:NewUser,request:Request):
    admin_only(request)
    with store.connection() as db:
        try:
            fields=','.join(PERMISSIONS)
            identifier=db.execute(f'INSERT INTO auth_users(username,pin_hash,is_admin,{fields}) VALUES(?,?,?,?,?,?,?)',
                (payload.username,hash_pin(payload.pin),payload.is_admin,*[getattr(payload,key) for key in PERMISSIONS])).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409,'Username already exists.') from None
        request.state.audit_detail=' · '+payload.username
        return public_user(db.execute('SELECT * FROM auth_users WHERE id=?',(identifier,)).fetchone())


@router.patch('/api/auth/users/{user_id}')
def update_user(user_id:int,payload:UserPatch,request:Request):
    admin_only(request)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM auth_users WHERE id=?',(user_id,)).fetchone()
        if not row or row['deleted_at']:raise HTTPException(404,'User not found.')
        if (payload.active is False or payload.is_admin is False) and row['is_admin'] and row['active'] and db.execute('SELECT COUNT(*) FROM auth_users WHERE is_admin=1 AND active=1 AND deleted_at IS NULL').fetchone()[0]<=1:
            raise HTTPException(422,'Keep at least one active admin.')
        if payload.pin is not None:
            db.execute('UPDATE auth_users SET pin_hash=? WHERE id=?',(hash_pin(payload.pin),user_id))
            db.execute('DELETE FROM auth_attempts WHERE key=?',('user:'+row['username'],))
        if payload.active is not None:db.execute('UPDATE auth_users SET active=? WHERE id=?',(payload.active,user_id))
        for field in ('is_admin',*PERMISSIONS):
            if getattr(payload,field) is not None:db.execute(f'UPDATE auth_users SET {field}=? WHERE id=?',(getattr(payload,field),user_id))
        if payload.pin is not None or payload.active is False:db.execute('DELETE FROM auth_sessions WHERE user_id=?',(user_id,))
        if payload.pin is not None and row['username']=='admin':discard_initial_pin()
        return public_user(db.execute('SELECT * FROM auth_users WHERE id=?',(user_id,)).fetchone())


@router.delete('/api/auth/users/{target_id}')
def delete_user(target_id:int,request:Request):
    admin_only(request)
    if target_id==request.state.user['id']:raise HTTPException(422,'You cannot delete your own account.')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM auth_users WHERE id=? AND deleted_at IS NULL',(target_id,)).fetchone()
        if not row:raise HTTPException(404,'User not found.')
        if row['is_admin'] and row['active'] and db.execute('SELECT COUNT(*) FROM auth_users WHERE is_admin=1 AND active=1 AND deleted_at IS NULL').fetchone()[0]<=1:
            raise HTTPException(422,'Keep at least one active admin.')
        db.execute('UPDATE auth_users SET active=0,deleted_at=CURRENT_TIMESTAMP WHERE id=?',(target_id,))
        db.execute('DELETE FROM auth_sessions WHERE user_id=?',(target_id,))
    return {'deleted':target_id}


@router.post('/api/auth/users/{target_id}/restore')
def restore_user(target_id:int,request:Request):
    admin_only(request)
    with store.connection() as db:
        changed=db.execute('UPDATE auth_users SET deleted_at=NULL,active=0 WHERE id=? AND deleted_at IS NOT NULL',(target_id,))
        if not changed.rowcount:raise HTTPException(404,'Deleted user not found.')
    return {'restored':target_id}


@router.get('/api/auth/activity')
def activity(request:Request,user_id:int | None=None,before:int | None=None):
    admin_only(request)
    where=[];params=[]
    if user_id is not None:where.append('user_id=?');params.append(user_id)
    if before is not None:where.append('id<?');params.append(before)
    with store.connection() as db:
        rows=[dict(row) for row in db.execute('SELECT * FROM activity_log'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY id DESC LIMIT 101',params)]
    return {'items':rows[:100],'next':rows[99]['id'] if len(rows)>100 else None}
