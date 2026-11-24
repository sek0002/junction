"""Private validated parameter presets, recall and non-destructive archiving."""
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import database as store
from app.main import app
from auth_client import bootstrap_pin

class PresetTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB');os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'presets.sqlite3');store.initialize()
        self.admin=TestClient(app);self.admin.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        self.admin.post('/api/auth/users',json={'username':'alice','pin':'654321'});self.alice=TestClient(app);self.alice.post('/api/auth/login',json={'username':'alice','pin':'654321'})
    def tearDown(self):
        self.admin.close();self.alice.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()
    def test_save_recall_rename_and_archive_are_private(self):
        settings={'parameters':{'organism':'mus-musculus','gc_global_min':.5,'gc_global_max':.65,'avoid_sequences':['CGCGCG']},'five_prime_utr':'GGGCCC','three_prime_utr':'AAACCC','poly_a':126,'temperature':25,'fold_scope':'transcript','candidates':2}
        response=self.admin.post('/api/mrna/parameter-presets',json={'name':' Mouse  design ','settings':settings});self.assertEqual(response.status_code,200,response.text);preset=response.json();identifier=preset['id']
        self.assertEqual(preset['name'],'Mouse design');self.assertEqual(preset['settings']['poly_a'],126);self.assertEqual(preset['settings']['parameters']['avoid_sequences'],['CGCGCG'])
        self.assertNotIn('records',preset['settings']);self.assertNotIn('match_record_names',preset['settings'])
        self.assertEqual(self.admin.get('/api/mrna/parameter-presets').json()['items'][0]['id'],identifier);self.assertEqual(self.alice.get('/api/mrna/parameter-presets').json(),{'items':[]})
        self.assertEqual(self.alice.post('/api/mrna/parameter-presets',json={'id':identifier,'name':'Stolen','settings':settings}).status_code,404)
        self.assertEqual(self.alice.delete('/api/mrna/parameter-presets/'+identifier).status_code,404)
        renamed=self.admin.post('/api/mrna/parameter-presets',json={'id':identifier,'name':'Mouse revised','settings':settings|{'temperature':30}}).json();self.assertEqual(renamed['id'],identifier);self.assertEqual(renamed['settings']['temperature'],30)
        self.assertEqual(self.admin.delete('/api/mrna/parameter-presets/'+identifier).status_code,200);self.assertEqual(self.admin.get('/api/mrna/parameter-presets').json(),{'items':[]})
        with store.connection() as db:self.assertIsNotNone(db.execute('select archived_at from mrna_parameter_presets where id=?',(identifier,)).fetchone()[0])
    def test_invalid_settings_and_duplicate_names(self):
        self.assertEqual(self.admin.post('/api/mrna/parameter-presets',json={'name':'bad','settings':{'parameters':{'gc_global_min':.9,'gc_global_max':.2}}}).status_code,422)
        self.assertEqual(self.admin.post('/api/mrna/parameter-presets',json={'name':'bad','settings':{'five_prime_utr':'NNN'}}).status_code,422)
        self.assertEqual(self.admin.post('/api/mrna/parameter-presets',json={'name':'Stable'}).status_code,200)
        self.assertEqual(self.admin.post('/api/mrna/parameter-presets',json={'name':'stable'}).status_code,409)
        anonymous=TestClient(app);self.assertEqual(anonymous.get('/api/mrna/parameter-presets').status_code,401);anonymous.close()
