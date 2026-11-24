"""Private reference ownership, cache invalidation and scoring context."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import database as store
from app.mrna_benchmarks import register
from auth_client import bootstrap_pin


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'benchmarks.sqlite3');store.initialize()
        self.admin=TestClient(app);self.admin.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        self.clients=[]
        for name in ('alice','bob'):
            response=self.admin.post('/api/auth/users',json={'username':name,'pin':'654321'})
            self.assertEqual(response.status_code,201,response.text)
            client=TestClient(app);client.post('/api/auth/login',json={'username':name,'pin':'654321'})
            self.clients.append(client)
        self.alice,self.bob=self.clients
        with store.connection() as db:self.owner=db.execute("SELECT id FROM auth_users WHERE username='alice'").fetchone()[0]
        self.definition={'name':'Private reference fixture','sequence':'ATG'+'GCT'*18+'TAATGA',
            'five_prime_utr':'GGGCCC','three_prime_utr':'AAACCC','poly_a':126,'organism':'mus-musculus',
            'source':{'sequence_section':'Final construct','dna_template_promoter':'TAATACGACTCACTATA'}}

    def tearDown(self):
        for client in [self.admin,*self.clients]:client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    @staticmethod
    def fake_score(payload):
        batch=payload['batch'];record=payload['record']
        transcript=batch['five_prime_utr']+record['sequence']+batch['three_prime_utr']+'A'*batch['poly_a']
        return {'rows':[{'id':'0-0','name':record['name'],'parameters':batch['parameters'],
            'transcript':transcript,'metrics':{'gc':.5},'sha256':hashlib.sha256(transcript.encode()).hexdigest()}], 'errors':[]}

    def test_ownership_and_authentication(self):
        register(self.owner,self.definition)
        anonymous=TestClient(app)
        self.assertEqual(anonymous.post('/api/mrna/benchmarks/score',json={}).status_code,401);anonymous.close()
        self.assertEqual(self.bob.post('/api/mrna/benchmarks/score',json={}).json(),{'rows':[]})
        with patch('app.mrna.capabilities',return_value={'ready':True,'models':{'ribonn':True}}),patch('app.mrna.invoke',side_effect=self.fake_score):
            response=self.alice.post('/api/mrna/benchmarks/score',json={})
        self.assertEqual(response.status_code,200,response.text)
        row=response.json()['rows'][0]
        self.assertEqual(row['name'],self.definition['name']);self.assertEqual(row['strategy'],'benchmark')
        self.assertEqual(row['parameters']['organism'],'mus-musculus')
        self.assertEqual(row['transcript'],'GGGCCC'+self.definition['sequence']+'AAACCC'+'A'*126)
        self.assertEqual(row['benchmark']['transcript_sha256'],row['sha256'])

    def test_context_cache_and_source_updates(self):
        identifier=register(self.owner,self.definition)
        context={'parameters':{'organism':'homo-sapiens','objective':'tai','gc_window_size':60},'fold_scope':'transcript','temperature':25}
        with patch('app.mrna.capabilities',return_value={'ready':True,'models':{'ribonn':True}}),patch('app.mrna.invoke',side_effect=self.fake_score) as invoke:
            for _ in range(2):
                result=self.alice.post('/api/mrna/benchmarks/score',json=context)
                self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(invoke.call_count,1)
            batch=invoke.call_args.args[0]['batch']
            self.assertEqual(batch['parameters']['gc_window_size'],60)
            self.assertEqual(batch['parameters']['organism'],'mus-musculus');self.assertEqual(batch['parameters']['objective'],'cai')
            self.assertEqual(batch['fold_scope'],'transcript');self.assertEqual(batch['temperature'],25)
            self.assertTrue(batch['predict_translation'])
            self.assertEqual(register(self.owner,self.definition),identifier)
            self.alice.post('/api/mrna/benchmarks/score',json=context);self.assertEqual(invoke.call_count,1)
            self.alice.post('/api/mrna/benchmarks/score',json={**context,'temperature':30});self.assertEqual(invoke.call_count,2)
            register(self.owner,{**self.definition,'sequence':self.definition['sequence'].replace('GCT','GCC')})
            self.alice.post('/api/mrna/benchmarks/score',json=context);self.assertEqual(invoke.call_count,3)

    def test_checksum_is_verified_before_registration(self):
        with self.assertRaisesRegex(ValueError,'checksum'):
            register(self.owner,{**self.definition,'transcript_sha256':'0'*64})

    def test_builtin_reference_is_shared_and_reuses_scores_across_users(self):
        with self.assertRaisesRegex(ValueError,'administrator'):
            register(self.owner,self.definition,global_reference=True)
        with store.connection() as db:administrator=db.execute("SELECT id FROM auth_users WHERE username='admin'").fetchone()[0]
        identifier=register(administrator,self.definition)
        self.assertEqual(register(administrator,self.definition,global_reference=True),identifier)
        with patch('app.mrna.capabilities',return_value={'ready':True,'models':{'ribonn':True}}),patch('app.mrna.invoke',side_effect=self.fake_score) as invoke:
            for client in (self.alice,self.bob):
                response=client.post('/api/mrna/benchmarks/score',json={})
                self.assertEqual(response.status_code,200,response.text)
                row=response.json()['rows'][0]
                self.assertTrue(row['benchmark']['builtin'])
                self.assertEqual(row['benchmark']['id'],identifier)
            self.assertEqual(invoke.call_count,1)
