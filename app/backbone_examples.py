"""Three circular backbone references, separate from plate inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import database as store
from .exports import parse_sequence_file


EXAMPLE_ROOT = Path(__file__).resolve().parents[1] / 'examples' / 'backbones'
# These are the original saved designs, not inferred from any newly uploaded plate.
BACKBONE_EXAMPLES = (
    ('pivt_v2', 'pIVT_V2', 'pIVT_V2.gb', 2827),
    ('pult_v2', 'pULT_V2', 'pULT_V2.gb', 7457),
    ('phr_v2', 'pHR_V2', 'pHR_V2.gb', 7760),
)
# Exact retired examples remain in the library for provenance, with a marker
# that excludes them from backbone selection. A user's altered sequence under
# one of these names is not silently retired.
LEGACY_EXAMPLE_HASHES = {
    'PHR_U6_TRUNC': '233eb675cd0c169359821c358a92bbbbb17422170e0729e649d60369ba6184c5',
    'PHR_U6_STD': '96643ecceb0762cf0bd15c76015258125eeb9740617a7c87c5252f5e38ebb7ce',
    'PHR_VE_TRUNC': '42f6fd4f26bafd82a97bf717b3ccabd088ac861b6656d8e27843d4342aea609e',
    'PHR_VE_STD': '9ebf6eaf118fa09905922953929de8c7a85736fc3c7bed0a87f5fcdbcd1af2d1',
}


def seed_backbone_examples() -> list[int]:
    """Ensure the three bundled examples exist and return their stable-order IDs.

    The reference set is independent of the inventory source manifest. Matching
    existing designs keep their annotations, notes, stocks and recipe fields;
    only the example markers are added. Import history and plasmids are committed
    together, so restarts do not duplicate or partially import an example.
    """
    sources = []
    for key, name, filename, length in BACKBONE_EXAMPLES:
        path = EXAMPLE_ROOT / filename
        content = path.read_bytes()
        records = parse_sequence_file(content.decode('utf8'), filename)
        if len(records) != 1:
            raise ValueError(f'Backbone example {filename} must contain one record.')
        record = records[0]
        if record['name'] != name or len(record['sequence']) != length or not record['circular']:
            raise ValueError(f'Backbone example {filename} does not match its circular reference.')
        sources.append((key, filename, content, record))

    store.initialize()
    ids = []
    with store.connection() as db:
        for saved in db.execute('SELECT id,name,sequence,recipe FROM plasmids').fetchall():
            if hashlib.sha256(saved['sequence'].encode()).hexdigest() != LEGACY_EXAMPLE_HASHES.get(saved['name']):
                continue
            recipe = json.loads(saved['recipe'])
            recipe.pop('example_backbone', None)
            recipe.pop('example_key', None)
            recipe['legacy_example'] = True
            db.execute('UPDATE plasmids SET recipe=? WHERE id=?', (json.dumps(recipe), saved['id']))
        for key, filename, content, record in sources:
            digest = hashlib.sha256(content).hexdigest()
            db.execute('INSERT OR IGNORE INTO imports(filename,digest,kind,row_count) VALUES(?,?,?,?)',
                ('backbones/' + filename, digest, 'genbank', 1))
            source_id = db.execute('SELECT id FROM imports WHERE digest=? AND kind=?',
                (digest, 'genbank')).fetchone()['id']
            markers = {'example_backbone': True, 'example_key': key}
            saved=next((row for row in db.execute('SELECT id,recipe FROM plasmids WHERE sequence=? ORDER BY id',(record['sequence'],)).fetchall()
                if json.loads(row['recipe']).get('example_key')==key),None)
            if saved is None:
                db.execute('''INSERT OR IGNORE INTO plasmids
                    (name,sequence,circular,features,recipe,notes,source_id)
                    VALUES(?,?,?,?,?,?,?)''',
                    (record['name'], record['sequence'], 1, json.dumps(record['features']),
                     json.dumps(markers), 'Original backbone example.', source_id))
                saved = db.execute('SELECT id,recipe FROM plasmids WHERE name=? AND sequence=?',
                    (record['name'], record['sequence'])).fetchone()
            recipe = json.loads(saved['recipe'])
            recipe.pop('legacy_example', None)
            recipe.update(markers)
            db.execute('UPDATE plasmids SET recipe=? WHERE id=?', (json.dumps(recipe), saved['id']))
            ids.append(saved['id'])
    return ids
