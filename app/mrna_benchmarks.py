"""Private, user-owned sequence references and context-matched scientific scores."""
import hashlib
import json
import threading
from uuid import uuid4

from . import database as store
from .version import VERSION

_LOCK = threading.RLock()
_SCORING_LOCKS = {}


def initialize():
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS mrna_benchmarks(
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES auth_users(id),
          name TEXT NOT NULL, definition TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,name));
        CREATE TABLE IF NOT EXISTS mrna_benchmark_scores(
          benchmark_id TEXT NOT NULL REFERENCES mrna_benchmarks(id) ON DELETE CASCADE,
          context_key TEXT NOT NULL, result TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(benchmark_id,context_key));
        ''')


def register(owner, definition):
    """Import a private reference; called by the authorised local/server importer."""
    from .mrna import Batch, Record, Parameters
    batch = Batch(records=[Record(name=definition['name'], sequence=definition['sequence'])],
        five_prime_utr=definition['five_prime_utr'], three_prime_utr=definition['three_prime_utr'],
        poly_a=definition['poly_a'], parameters=Parameters(organism=definition['organism']))
    reference = {**definition, 'name':batch.records[0].name, 'sequence':batch.records[0].sequence,
        'five_prime_utr':''.join(batch.five_prime_utr.split()).upper().replace('U','T'),
        'three_prime_utr':''.join(batch.three_prime_utr.split()).upper().replace('U','T')}
    transcript = reference['five_prime_utr'] + reference['sequence'] + reference['three_prime_utr'] + 'A'*batch.poly_a
    checksum = hashlib.sha256(transcript.encode()).hexdigest()
    if reference.get('transcript_sha256', checksum) != checksum:
        raise ValueError('Reference transcript checksum does not match its components.')
    reference['transcript_sha256'] = checksum
    encoded = json.dumps(reference, sort_keys=True)
    initialize()
    with store.connection() as db:
        existing = db.execute('SELECT * FROM mrna_benchmarks WHERE user_id=? AND name=?',
                              (owner, reference['name'])).fetchone()
        if existing:
            identifier = existing['id']
            if existing['definition'] != encoded:
                db.execute('UPDATE mrna_benchmarks SET definition=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (encoded,identifier))
                db.execute('DELETE FROM mrna_benchmark_scores WHERE benchmark_id=?', (identifier,))
        else:
            identifier = str(uuid4())
            db.execute('INSERT INTO mrna_benchmarks(id,user_id,name,definition) VALUES(?,?,?,?)',
                       (identifier,owner,reference['name'],encoded))
    return identifier


def score(owner, context):
    from .mrna import Batch, Record, capabilities, invoke, runtime_config
    initialize()
    with store.connection() as db:
        references = [dict(row) for row in db.execute(
            'SELECT * FROM mrna_benchmarks WHERE user_id=? ORDER BY name', (owner,))]
    if not references:
        return {'rows':[]}
    caps = capabilities()
    if not caps.get('ready'):
        raise RuntimeError(caps.get('message','The scientific runtime is unavailable.'))
    signature = {'release':VERSION, 'versions':caps.get('versions'), 'models':caps.get('models'),
                 'runtime':runtime_config()}
    rows = []
    for reference in references:
        definition = json.loads(reference['definition'])
        params = {**context.parameters.model_dump(), 'organism':definition['organism'], 'objective':'cai'}
        batch = Batch(name=definition['name'], mode='compare',
            records=[Record(name=definition['name'],sequence=definition['sequence'],group='Benchmarks')],
            parameters=params, five_prime_utr=definition['five_prime_utr'],
            three_prime_utr=definition['three_prime_utr'], poly_a=definition['poly_a'],
            fold_scope=context.fold_scope, temperature=context.temperature,
            predict_translation=bool(caps.get('models',{}).get('ribonn'))).model_dump()
        key = hashlib.sha256(json.dumps({'definition':definition,'batch':batch,'signature':signature},
                                        sort_keys=True).encode()).hexdigest()
        with _LOCK:
            lock = _SCORING_LOCKS.setdefault((str(store.db_path()),reference['id'],key),threading.Lock())
        with lock:
            with store.connection() as db:
                cached = db.execute('SELECT result FROM mrna_benchmark_scores WHERE benchmark_id=? AND context_key=?',
                                    (reference['id'],key)).fetchone()
            if cached:
                row = json.loads(cached['result'])
            else:
                result = invoke({'action':'run','batch':batch,'record':batch['records'][0],'index':0})
                if result.get('errors') or len(result.get('rows',[])) != 1:
                    raise RuntimeError('The benchmark could not be scored for these settings.')
                row = result['rows'][0]
                row.update(id='benchmark:'+reference['id'], name=definition['name'], strategy='benchmark',
                    benchmark={'id':reference['id'], 'source':definition.get('source',{}),
                               'transcript_sha256':definition['transcript_sha256']})
                with store.connection() as db:
                    db.execute('INSERT OR REPLACE INTO mrna_benchmark_scores(benchmark_id,context_key,result) VALUES(?,?,?)',
                               (reference['id'],key,json.dumps(row,allow_nan=False)))
                    db.execute('DELETE FROM mrna_benchmark_scores WHERE benchmark_id=? AND context_key NOT IN '
                               '(SELECT context_key FROM mrna_benchmark_scores WHERE benchmark_id=? ORDER BY created_at DESC LIMIT 16)',
                               (reference['id'],reference['id']))
            rows.append(row)
    return {'rows':rows}
