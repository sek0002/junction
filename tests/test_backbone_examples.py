"""Bundled backbones remain independent of replacement plate inventories."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from app import database as store
from app.backbone_examples import BACKBONE_EXAMPLES, EXAMPLE_ROOT, seed_backbone_examples
from app.exports import parse_sequence_file


class BackboneExamplesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_database = os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB'] = str(Path(self.directory.name) / 'isolated.sqlite3')

    def tearDown(self):
        if self.previous_database is None:
            os.environ.pop('GOLDEN_GATE_DB', None)
        else:
            os.environ['GOLDEN_GATE_DB'] = self.previous_database
        self.directory.cleanup()

    def test_restores_only_three_circular_examples_and_preserves_annotations(self):
        # Even an explicit empty plate manifest must not remove these references.
        store.db_path().with_suffix('.sources.json').write_text(json.dumps({
            'plate_files': [], 'genbank_files': []}))
        ids = seed_backbone_examples()
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(store.plasmids()), 3)
        self.assertEqual(store.fragments(), [])
        for pid, (key, name, filename, length) in zip(ids, BACKBONE_EXAMPLES):
            saved = store.get_plasmid(pid)
            original = parse_sequence_file((EXAMPLE_ROOT / filename).read_text(), filename)[0]
            self.assertEqual((saved['name'], saved['length'], saved['circular']), (name, length, True))
            self.assertEqual(saved['sequence'], original['sequence'])
            self.assertEqual(saved['features'], original['features'])
            self.assertTrue(saved['recipe']['example_backbone'])
            self.assertEqual(saved['recipe']['example_key'], key)
        # Hashes pin the exact three sequences rather than approximations.
        expected = {
            'pIVT_V2': 'ed5d02068c2c8aae5f192d908a877fdca0d3f59a22af657a77a605144e7184d1',
            'pULT_V2': 'd45554b791b7cc6f1897a8ae2780d02e5120a00ad93ab320b77bb539ef6c7945',
            'pHR_V2': '9ebf6eaf118fa09905922953929de8c7a85736fc3c7bed0a87f5fcdbcd1af2d1',
        }
        self.assertEqual({p['name']: hashlib.sha256(p['sequence'].encode()).hexdigest()
            for p in store.plasmids()}, expected)

    def test_idempotent_and_preserves_existing_recipe_stock_and_notes(self):
        ids = seed_backbone_examples()
        with store.connection() as db:
            db.execute('UPDATE plasmids SET recipe=?,stock_ng_ul=?,notes=? WHERE id=?',
                (json.dumps({'name': 'custom recipe', 'fragment_ids': [41, 42]}), 25, 'Measured stock', ids[0]))
            # An unrelated saved plasmid does not become an example.
        extra = store.save_plasmid('User plasmid', 'ACGT' * 100, notes='Keep me')
        self.assertEqual(seed_backbone_examples(), ids)
        self.assertEqual(seed_backbone_examples(), ids)
        self.assertEqual(len(store.plasmids()), 4)
        saved = store.get_plasmid(ids[0])
        self.assertEqual(saved['recipe']['fragment_ids'], [41, 42])
        self.assertEqual(saved['recipe']['name'], 'custom recipe')
        self.assertTrue(saved['recipe']['example_backbone'])
        self.assertEqual(saved['stock_ng_ul'], 25)
        self.assertEqual(saved['notes'], 'Measured stock')
        self.assertNotIn('example_backbone', store.get_plasmid(extra)['recipe'])
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM imports').fetchone()[0], 3)

    def test_retires_old_examples_without_deleting_or_changing_their_designs(self):
        store.initialize()
        legacy = []
        for path in sorted(EXAMPLE_ROOT.parent.glob('*.gb')):
            record = parse_sequence_file(path.read_text(), path.name)[0]
            pid = store.save_plasmid(record['name'], record['sequence'], record['features'],
                {'example_backbone': True, 'example_key': 'old_key', 'fragment_ids': [41, 42]},
                notes='Keep original reference')
            legacy.append(store.get_plasmid(pid))
        custom = store.save_plasmid('PHR_VE_STD', 'ACGT' * 50, notes='User design')
        ids = seed_backbone_examples()
        self.assertEqual(seed_backbone_examples(), ids)
        self.assertEqual(len(store.plasmids()), 8)
        for before in legacy:
            after = store.get_plasmid(before['id'])
            self.assertEqual(after['sequence'], before['sequence'])
            self.assertEqual(after['features'], before['features'])
            self.assertEqual(after['notes'], before['notes'])
            self.assertEqual(after['recipe']['fragment_ids'], [41, 42])
            self.assertTrue(after['recipe']['legacy_example'])
            self.assertNotIn('example_backbone', after['recipe'])
            self.assertNotIn('example_key', after['recipe'])
        self.assertNotIn('legacy_example', store.get_plasmid(custom)['recipe'])
        self.assertEqual({p['name'] for p in store.plasmids() if p['recipe'].get('example_backbone')},
            {'pIVT_V2', 'pULT_V2', 'pHR_V2'})


if __name__ == '__main__':
    unittest.main()
