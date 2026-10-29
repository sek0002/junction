"""Local SQLite inventory. Imports retain supplied sequence and physical DNA length."""
import contextlib
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_FRAGMENTS="fragments.archived_at IS NULL AND NOT EXISTS (SELECT 1 FROM plates WHERE plates.plate_id=fragments.plate_id AND plates.archived_at IS NOT NULL)"


def db_path():
    return Path(os.environ.get('GOLDEN_GATE_DB', ROOT / 'data' / 'golden_gate.sqlite3'))


@contextlib.contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS build_list(
          id INTEGER PRIMARY KEY, request TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP, removed_at TEXT);
        CREATE TABLE IF NOT EXISTS imports(
          id INTEGER PRIMARY KEY, filename TEXT NOT NULL, digest TEXT NOT NULL,
          kind TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(digest,kind));
        CREATE TABLE IF NOT EXISTS plates(
          plate_id TEXT PRIMARY KEY, archived_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS fragments(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, plate_id TEXT NOT NULL DEFAULT '',
          well TEXT NOT NULL DEFAULT '', sequence TEXT NOT NULL,
          construct_sequence TEXT NOT NULL DEFAULT '', yield_ng REAL,
          stock_ng_ul REAL, resuspension_ul REAL, concentration_basis TEXT DEFAULT 'unknown',
          notes TEXT NOT NULL DEFAULT '', source_id INTEGER REFERENCES imports(id),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(plate_id,well));
        CREATE TABLE IF NOT EXISTS plasmids(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, sequence TEXT NOT NULL,
          circular INTEGER NOT NULL DEFAULT 1, features TEXT NOT NULL DEFAULT '[]',
          recipe TEXT NOT NULL DEFAULT '{}', notes TEXT DEFAULT '',
          stock_ng_ul REAL, plate_id TEXT DEFAULT '', well TEXT DEFAULT '',
          source_id INTEGER REFERENCES imports(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(name,sequence));
        ''')
        # Preserve legacy rows and IDs while allowing stocks without physical wells.
        schema=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fragments'").fetchone()['sql']
        migrated=re.sub(r',\s*UNIQUE\s*\(\s*plate_id\s*,\s*well\s*\)', '', schema, flags=re.I)
        if migrated!=schema:
            indexes=[row['sql'] for row in db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='fragments' AND sql IS NOT NULL")]
            db.execute(migrated.replace('CREATE TABLE fragments','CREATE TABLE fragments_migration',1))
            db.execute('INSERT INTO fragments_migration SELECT * FROM fragments')
            db.execute('DROP TABLE fragments')
            db.execute('ALTER TABLE fragments_migration RENAME TO fragments')
            for statement in indexes:db.execute(statement)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS fragments_physical_well ON fragments(plate_id,well) WHERE plate_id!='' AND well!=''")
        db.execute("INSERT OR IGNORE INTO plates(plate_id) SELECT DISTINCT plate_id FROM fragments WHERE plate_id!='' AND well!=''")
        db.execute('CREATE TABLE IF NOT EXISTS custom_import_results(digest TEXT PRIMARY KEY,result TEXT NOT NULL)')
        columns={row['name'] for row in db.execute('PRAGMA table_info(fragments)')}
        if 'default_yield_ng' not in columns:
            db.execute('ALTER TABLE fragments ADD COLUMN default_yield_ng REAL')
            db.execute('UPDATE fragments SET default_yield_ng=yield_ng')
        if 'stock_saved' not in columns:
            db.execute('ALTER TABLE fragments ADD COLUMN stock_saved INTEGER NOT NULL DEFAULT 0')
            db.execute('UPDATE fragments SET stock_saved=1 WHERE stock_ng_ul IS NOT NULL OR resuspension_ul IS NOT NULL')
        if 'yield_locked' not in columns:
            db.execute('ALTER TABLE fragments ADD COLUMN yield_locked INTEGER NOT NULL DEFAULT 1')
        if 'stock_rules' not in columns:
            db.execute('ALTER TABLE fragments ADD COLUMN stock_rules TEXT')
        if 'custom_metadata' not in columns:db.execute("ALTER TABLE fragments ADD COLUMN custom_metadata TEXT NOT NULL DEFAULT '{}'")
        if 'location' not in columns:db.execute("ALTER TABLE fragments ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        for column,kind in [('default_stock_ng_ul','REAL'),('default_resuspension_ul','REAL'),('default_concentration_basis','TEXT')]:
            if column not in columns:db.execute(f'ALTER TABLE fragments ADD COLUMN {column} {kind}')
        db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        for table in ('fragments','plasmids'):
            if 'archived_at' not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN archived_at TEXT')

    from .auth import initialize as initialize_auth
    initialize_auth()


def fragment_dict(row):
    result = dict(row)
    result['yield_locked'] = bool(result['yield_locked'])
    result['stock_rules'] = json.loads(result['stock_rules']) if result.get('stock_rules') else None
    result['custom_metadata'] = json.loads(result.get('custom_metadata') or '{}')
    result['length'] = len(result['sequence'])
    result['physical_length'] = len(result['construct_sequence'] or result['sequence'])
    return result


def fragments():
    with connection() as db:
        return [fragment_dict(r) for r in db.execute('SELECT * FROM fragments WHERE '+ACTIVE_FRAGMENTS+' ORDER BY plate_id,id')]


def get_fragment(fragment_id):
    with connection() as db:
        row = db.execute('SELECT * FROM fragments WHERE id=? AND '+ACTIVE_FRAGMENTS, (fragment_id,)).fetchone()
        return fragment_dict(row) if row else None


def plasmid_dict(row):
    result = dict(row)
    result['features'] = json.loads(result['features'])
    result['recipe'] = json.loads(result['recipe'])
    result['circular'] = bool(result['circular'])
    result['length'] = len(result['sequence'])
    return result


def plasmids():
    with connection() as db:
        return [plasmid_dict(r) for r in db.execute('SELECT * FROM plasmids WHERE archived_at IS NULL ORDER BY id DESC')]


def get_plasmid(plasmid_id):
    with connection() as db:
        row = db.execute('SELECT * FROM plasmids WHERE id=? AND archived_at IS NULL', (plasmid_id,)).fetchone()
        return plasmid_dict(row) if row else None


def save_plasmid(name, sequence, features=None, recipe=None, notes='', source_id=None, circular=True,
                backbone_enzymes=None, topology_override=False, merge_annotations=False):
    if backbone_enzymes is not None and (not circular or not backbone_enzymes):
        raise ValueError('A backbone template requires a circular sequence and a usable Golden Gate cassette.')
    with connection() as db:
        from .auth import check_plasmid_write
        check_plasmid_write(db,name,sequence)
        inserted=db.execute('''INSERT OR IGNORE INTO plasmids
            (name,sequence,features,recipe,notes,source_id,circular) VALUES(?,?,?,?,?,?,?)''',
            (name, sequence, json.dumps(features or []), json.dumps(recipe or {}), notes, source_id, int(circular)))
        if not inserted.rowcount:check_plasmid_write(db,name,sequence)
        saved=db.execute('SELECT id,recipe,features FROM plasmids WHERE name=? AND sequence=?', (name,sequence)).fetchone()
        if merge_annotations and features:
            # An annotated re-upload enriches the same record without losing its
            # assembly metadata or letting a later FASTA upload clear features.
            def identity(feature):
                parts=feature.get('segments') or [feature]
                bounds=tuple((p.get('start'),p.get('end'),p.get('strand',feature.get('strand',1))) for p in parts)
                return feature.get('type'),feature.get('label'),bounds,feature.get('raw_location') if not bounds or all(p[0] is None or p[1] is None or p[1]<=p[0] for p in bounds) else None
            merged={identity(f):f for f in json.loads(saved['features'])}
            for feature in features:merged[identity(feature)]=feature
            db.execute('UPDATE plasmids SET features=? WHERE id=?',(json.dumps(list(merged.values())),saved['id']))
        db.execute('UPDATE plasmids SET archived_at=NULL WHERE id=?',(saved['id'],))
        if backbone_enzymes is not None or topology_override:
            # Promote an already saved exact product without duplicating it or losing its metadata.
            metadata=json.loads(saved['recipe']) | (recipe or {})
            if backbone_enzymes is not None:
                metadata.update(backbone_template=True,backbone_enzymes=list(backbone_enzymes))
            elif not circular:
                metadata.pop('backbone_template',None)
                metadata.pop('backbone_enzymes',None)
            db.execute('UPDATE plasmids SET recipe=?,circular=? WHERE id=?',
                (json.dumps(metadata),int(circular),saved['id']))
        return saved['id']


def update_plasmid_settings(plasmid_id, circular, backbone_enzymes=None, name=None):
    with connection() as db:
        saved=db.execute('SELECT recipe FROM plasmids WHERE id=?',(plasmid_id,)).fetchone()
        if saved is None:
            raise ValueError('Plasmid not found.')
        metadata=json.loads(saved['recipe'])
        if backbone_enzymes:
            if not circular:
                raise ValueError('A backbone template must be circular.')
            metadata.update(backbone_template=True,backbone_enzymes=list(backbone_enzymes))
        else:
            metadata.pop('backbone_template',None)
            metadata.pop('backbone_enzymes',None)
        if name is not None:
            if 'name' in metadata:metadata['name']=name
            db.execute('UPDATE plasmids SET circular=?,recipe=?,name=? WHERE id=?',
                (int(circular),json.dumps(metadata),name,plasmid_id))
        else:
            db.execute('UPDATE plasmids SET circular=?,recipe=? WHERE id=?',
                (int(circular),json.dumps(metadata),plasmid_id))


def rename_plasmid(plasmid_id, name):
    with connection() as db:
        saved=db.execute('SELECT recipe FROM plasmids WHERE id=? AND archived_at IS NULL',(plasmid_id,)).fetchone()
        if saved is None:raise ValueError('Plasmid not found.')
        metadata=json.loads(saved['recipe'])
        if 'name' in metadata:metadata['name']=name
        db.execute('UPDATE plasmids SET name=?,recipe=? WHERE id=?',(name,json.dumps(metadata),plasmid_id))


def bin_items():
    rows=[]
    with connection() as db:
        for table,kind in (('fragments','fragment'),('plasmids','plasmid')):
            for row in db.execute(f'SELECT id,name,length(sequence) AS length,plate_id,well,archived_at FROM {table} WHERE archived_at IS NOT NULL'+ (" AND NOT EXISTS (SELECT 1 FROM plates WHERE plates.plate_id=fragments.plate_id AND plates.archived_at IS NOT NULL)" if table=='fragments' else '')):
                rows.append(dict(row) | {'kind':kind})
        for row in db.execute('SELECT plate_id,archived_at FROM plates WHERE archived_at IS NOT NULL'):
            rows.append({'id':row['plate_id'],'name':row['plate_id'],'plate_id':row['plate_id'],'kind':'plate','well':'','archived_at':row['archived_at']})
    return sorted(rows,key=lambda row:(row['archived_at'],row['kind'],str(row['id'])),reverse=True)


def move_to_bin(fragment_ids,plasmid_ids,restore=False,plate_ids=None):
    groups=(('fragments','id',set(fragment_ids)),('plasmids','id',set(plasmid_ids)),('plates','plate_id',set(plate_ids or [])))
    with connection() as db:
        for table,key,ids in groups:
            found={row[key] for row in db.execute(f'SELECT {key} FROM {table}')}
            if ids-found:
                raise ValueError(f'Unknown {table} IDs: '+', '.join(map(str,sorted(ids-found))))
        count=0
        for table,key,ids in groups:
            if not ids:
                continue
            marks=','.join('?' for _ in ids)
            value='NULL' if restore else 'CURRENT_TIMESTAMP'
            condition='IS NOT NULL' if restore else 'IS NULL'
            count+=db.execute(f'UPDATE {table} SET archived_at={value} WHERE archived_at {condition} AND {key} IN ({marks})',list(ids)).rowcount
        return count


def import_exists(content, kind):
    digest = hashlib.sha256(content).hexdigest()
    with connection() as db:
        row = db.execute('SELECT * FROM imports WHERE digest=? AND kind=?',(digest,kind)).fetchone()
        return dict(row) if row else None


def plate_records(include_archived=False):
    from .plates import detect_layout
    with connection() as db:
        plates=[dict(row) for row in db.execute('SELECT * FROM plates'+('' if include_archived else ' WHERE archived_at IS NULL')+' ORDER BY plate_id')]
        entries=[dict(row) for row in db.execute('SELECT fragments.plate_id,well,fragments.archived_at,imports.filename FROM fragments LEFT JOIN imports ON imports.id=fragments.source_id')]
    for plate in plates:
        parts=[row for row in entries if row['plate_id']==plate['plate_id']]
        plate.update(detect_layout([row['well'] for row in parts]))
        plate['occupied_wells']=len(parts)
        plate['active_wells']=0 if plate['archived_at'] else sum(not row['archived_at'] for row in parts)
        plate['filenames']=sorted({row['filename'] for row in parts if row['filename']})
    return plates


def plate_fragments(plate_id):
    with connection() as db:
        return [fragment_dict(row) for row in db.execute('SELECT * FROM fragments WHERE plate_id=? ORDER BY id',(plate_id,))]
