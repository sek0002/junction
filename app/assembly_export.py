"""Immutable worksheet/plate export bundles, accessed by unguessable QR links."""
import hashlib
import io
import json
import re
import secrets
from html import escape
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from . import database as store
from .auth import user_id
from .version import VERSION
from .bench_exports import FORMATS, guide_bytes
from .assembly_plates import layout, assignments, csv_bytes, qr_png, plate_png, pdf_bytes, TRANSFER_HEADERS, ASSIGNMENT_HEADERS

router=APIRouter()


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS assembly_export_snapshots(
        id TEXT PRIMARY KEY,token_hash TEXT NOT NULL UNIQUE,user_id INTEGER NOT NULL,
        metadata TEXT NOT NULL,bundle BLOB NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))''')


def saved_export(format, sections, factory, request, day, identifier, filename):
    filename=re.sub(r'[^A-Za-z0-9_.-]+','_',filename)
    token=secrets.token_urlsafe(24)
    # base_url respects the deployment's configured trusted proxy forwarding.
    url=str(request.url_for('assembly_export_page',token=token))
    data=layout(sections,day,identifier,url)
    metadata=dict(date=day,identifier=identifier,worksheet=filename,format=format,plates=[p['id'] for p in data['plates']],download_url=url,app_version=VERSION)
    from .workbenches import working
    with store.connection() as db:
        workspace=working(db)
        metadata.update(workbench_id=workspace.get('workbench_id'),worksheet_id=workspace.get('worksheet_ids',{}).get('build'))
        worksheet=db.execute('SELECT name FROM saved_worksheets WHERE id=? AND user_id=?',(metadata['worksheet_id'],user_id())).fetchone()
        metadata['worksheet_name']=worksheet['name'] if worksheet else 'Unsaved assembly worksheet'
    content=guide_bytes(format,sections,factory,plate_data=data)
    out=io.BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as archive:
        archive.writestr(filename,content)
        archive.writestr('plate-maps.pdf',pdf_bytes(data))
        archive.writestr('well-transfers.csv',csv_bytes(TRANSFER_HEADERS,data['transfers']))
        archive.writestr('plate-assignments.csv',csv_bytes(ASSIGNMENT_HEADERS,assignments(data)))
        archive.writestr('download-qr.png',qr_png(url))
        archive.writestr('manifest.json',json.dumps(metadata,ensure_ascii=False,indent=2))
        for plate in data['plates']:archive.writestr(plate['id']+'.png',plate_png(data,plate))
    with store.connection() as db:
        initialize(db)
        db.execute('INSERT INTO assembly_export_snapshots(id,token_hash,user_id,metadata,bundle) VALUES(?,?,?,?,?)',
                   (identifier,hashlib.sha256(token.encode()).hexdigest(),user_id(),json.dumps(metadata),out.getvalue()))
    return Response(content,media_type=FORMATS[format],headers={'Content-Disposition':f'attachment; filename="{filename}"','X-Junction-Export-URL':url,'Cache-Control':'no-store'})


@router.get('/api/build-list/exports')
def list_exports():
    with store.connection() as db:
        initialize(db)
        rows=db.execute('SELECT metadata,created_at FROM assembly_export_snapshots WHERE user_id=? ORDER BY created_at DESC,id DESC',(user_id(),)).fetchall()
    return {'items':[json.loads(row['metadata'])|{'created_at':row['created_at']} for row in rows]}


def snapshot(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{32}',token):raise HTTPException(404,'Export not found.')
    with store.connection() as db:
        initialize(db)
        row=db.execute('SELECT metadata,bundle FROM assembly_export_snapshots WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:raise HTTPException(404,'Export not found.')
    return json.loads(row['metadata']),bytes(row['bundle'])


def private_headers():
    return {'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}


@router.get('/exports/{token}',name='assembly_export_page',include_in_schema=False)
def export_page(token:str):
    metadata,bundle=snapshot(token)
    with ZipFile(io.BytesIO(bundle)) as archive:files=[name for name in archive.namelist() if name!='manifest.json']
    links=''.join(f'<li><a href="{escape(token)}/files/{escape(name,quote=True)}">{escape(name)}</a></li>' for name in files)
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Junction export</title><style>body{font:16px system-ui;max-width:760px;margin:40px auto;padding:20px;color:#1d443b;background:#f5f8f5}a{color:#226649;overflow-wrap:anywhere}li{padding:8px}h1{font-size:26px}</style><h1>Junction export</h1>'
    html+=f'<p>{escape(metadata["date"])} · {escape(metadata["identifier"])}</p><p><a href="{escape(token)}/bundle.zip">Download all</a></p><ul>{links}</ul></html>'
    return HTMLResponse(html,headers=private_headers())


@router.get('/exports/{token}/bundle.zip',include_in_schema=False)
def export_bundle(token:str):
    metadata,bundle=snapshot(token)
    return Response(bundle,media_type='application/zip',headers=private_headers()|{'Content-Disposition':f'attachment; filename="Build_list_{metadata["date"]}_{metadata["identifier"]}.zip"'})


@router.get('/exports/{token}/files/{filename}',include_in_schema=False)
def export_file(token:str,filename:str):
    metadata,bundle=snapshot(token)
    with ZipFile(io.BytesIO(bundle)) as archive:
        if filename not in archive.namelist():raise HTTPException(404,'Export file not found.')
        content=archive.read(filename)
    media={'pdf':'application/pdf','csv':'text/csv; charset=utf-8','png':'image/png','xlsx':FORMATS['xlsx'],'json':'application/json'}.get(filename.rsplit('.',1)[-1],'application/octet-stream')
    return Response(content,media_type=media,headers=private_headers()|{'Content-Disposition':f'attachment; filename="{filename}"'})
