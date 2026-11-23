"""mRNA scientific integration, private jobs, validation, and exports."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.main import app
from app import database as store
from app.mrna import Batch, Record, Parameters, capabilities, invoke, runtime_config
from app.mrna_worker import gc_profile
from auth_client import bootstrap_pin

SEQUENCE='ATGGAGGACGCCAAGAACATCAAGAAGGGCCCCGCCCCCTTCTACCCCCTGGAGGACGGCACCGCCGGCGAGCAGCTGCACAAGGCCATGAAGAGGTACGCCCTGTGA'

class ScientificTests(unittest.TestCase):
    def test_invalid_inputs_and_constraints(self):
        for sequence in ['ATGNNNTAA','ATGG','   ']:
            with self.assertRaises(ValidationError):Record(name='bad',sequence=sequence)
        with self.assertRaises(ValidationError):Parameters(gc_global_min=.8,gc_global_max=.5)
        with self.assertRaises(ValidationError):Parameters(organism='mus-musculus',objective='tai')
        with self.assertRaises(ValidationError):Record(name='bad',sequence=SEQUENCE,preserve_regions=[(2,20)])
        with self.assertRaises(ValidationError):Batch(records=[Record(name='duplicate',sequence=SEQUENCE)]*2)
        self.assertEqual(Record(name='RNA',sequence='aug gaa uaa').sequence,'ATGGAATAA')

    def test_gc_windows_include_last_window_and_merge_hotspots(self):
        profile,spots,window=gc_profile('GGGGAAAATTTT',4,.25,.75)
        self.assertEqual(profile[0],[1,1]);self.assertEqual(profile[-1],[9,0]);self.assertEqual(len(profile),9)
        self.assertEqual(spots[0],{'start':1,'end':4,'kind':'high','peak':1.0})
        self.assertEqual(spots[-1]['end'],12)
        short=gc_profile('GCA',40,.3,.7)
        self.assertEqual(short[0],[[1,.66667]]);self.assertEqual(short[2],3)

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(),'Optional local scientific runtime not configured')
    def test_real_fold_scores_and_synonymous_design(self):
        payload=Batch(name='Real engine',mode='design',records=[Record(name='Reporter',sequence=SEQUENCE,preserve_regions=[(1,12)])]).model_dump()
        result=invoke({'action':'run','batch':payload,'record':payload['records'][0],'index':0})
        self.assertFalse(result['errors'],result['errors']);self.assertEqual(len(result['rows']),2)
        before,after=result['rows'];self.assertEqual(before['protein'],after['protein']);self.assertEqual(after['cds'][:12],SEQUENCE[:12])
        for row in result['rows']:
            self.assertTrue(row['metrics']['protein_preserved']);self.assertEqual(len(row['coordinates']),len(row['fold_sequence']));self.assertEqual(len(row['structure']),len(row['fold_sequence']))
            self.assertLessEqual(row['metrics']['mfe'],0);self.assertGreater(row['metrics']['cai'],0);self.assertGreater(row['metrics']['predicted_half_life'],0)
            self.assertAlmostEqual(row['metrics']['mfe_density'],row['metrics']['mfe']/len(row['fold_sequence']),places=5)
            self.assertAlmostEqual(row['metrics']['gc'],sum(x in 'GC' for x in row['cds'])/len(row['cds']))
        with open(runtime_config()['csc']) as f:weights={r['codon']:float(r['293T_ORFome']) for r in csv.DictReader(f)}
        codons=[SEQUENCE[i:i+3] for i in range(0,len(SEQUENCE)-3,3)]
        self.assertAlmostEqual(before['metrics']['csc'],sum(weights[c] for c in codons)/len(codons))
        params=Batch(records=[Record(name='Full',sequence=SEQUENCE)],five_prime_utr='GCGCGC',three_prime_utr='AAACCC',poly_a=10,fold_scope='transcript',temperature=25).model_dump()
        row=invoke({'action':'run','batch':params,'record':params['records'][0],'index':0})['rows'][0]
        self.assertEqual(row['transcript'],'GCGCGC'+SEQUENCE+'AAACCC'+'A'*10)
        self.assertEqual(len(row['structure']),len(row['transcript']));self.assertEqual(row['regions']['cds'],[7,114])

    @unittest.skipUnless(runtime_config().get('ribonn_command'),'Optional RiboNN trained runtime not configured')
    def test_real_ribonn_ensemble(self):
        root=Path(__file__).resolve().parents[1]
        preset=json.loads((root/'app/data/mrna/elements.json').read_text())[0]
        payload=Batch(records=[Record(name='Translation',sequence=SEQUENCE)],five_prime_utr=preset['utr5'],three_prime_utr=preset['utr3'],predict_translation=True).model_dump()
        row=invoke({'action':'run','batch':payload,'record':payload['records'][0],'index':0})['rows'][0]
        self.assertIsInstance(row['metrics']['translation'],float)
        self.assertGreater(len(row['tissue_predictions']),50)
        self.assertAlmostEqual(row['metrics']['translation'],sum(row['tissue_predictions'].values())/len(row['tissue_predictions']),places=5)
        self.assertIn('RiboNN',row['model_versions']['translation'])
        with self.assertRaises(ValidationError):Batch(records=[Record(name='Missing UTRs',sequence=SEQUENCE)],predict_translation=True)

class PrivateJobTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'mrna.sqlite3');store.initialize()
        self.admin=TestClient(app);self.admin.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        for name in ['alice','bob']:
            response=self.admin.post('/api/auth/users',json={'username':name,'pin':'654321','can_upload':False,'can_edit':False,'can_archive':False,'can_manage_rules':False})
            self.assertEqual(response.status_code,201,response.text)
        self.alice=TestClient(app);self.bob=TestClient(app)
        for client,name in [(self.alice,'alice'),(self.bob,'bob')]:self.assertEqual(client.post('/api/auth/login',json={'username':name,'pin':'654321'}).status_code,200)

    def tearDown(self):
        for client in [self.admin,self.alice,self.bob]:client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def wait(self,identifier):
        for _ in range(100):
            response=self.alice.get('/api/mrna/jobs/'+identifier);self.assertEqual(response.status_code,200,response.text)
            data=response.json()
            if data['status'] not in ['queued','running']:return data
            time.sleep(.15)
        self.fail('Local mRNA job did not finish in time')

    def test_auth_validation_and_private_drafts(self):
        anon=TestClient(app);self.assertEqual(anon.get('/api/mrna/jobs').status_code,401);anon.close()
        response=self.alice.post('/api/mrna/jobs',json={'records':[{'name':'bad','sequence':'ATGNNN'}]});self.assertEqual(response.status_code,422)
        state={'view':'mrna','mrna':{'draft':{'records':[{'name':'private','sequence':SEQUENCE}]}}}
        self.assertEqual(self.alice.put('/api/workspace',json={'data':state}).status_code,200)
        self.assertEqual(self.alice.get('/api/workspace').json()['data'],state)
        self.assertNotIn('mrna',self.bob.get('/api/workspace').json()['data'])
        response=self.alice.get('/');self.assertIn('data-view="mrna"',response.text);self.assertIn('/static/mrna.js',response.text)

    def test_mrna_survives_newer_page_scoped_worksheet_switches(self):
        mrna={'draft':{'records':[{'name':'Keep my RNA','sequence':SEQUENCE}]},'result':{'rows':[]}}
        state={'view':'mrna','mrna':mrna,'draft':{'name':'Assembly A','enzyme':'BsaI','fragment_ids':[]},'design':{'designs':[{'id':'design-a','name':'Design A','enzyme':'BsaI','entries':[]}],'activeId':'design-a'},'compareView':{'jobs':{}}}
        self.assertEqual(self.alice.put('/api/workspace',json={'data':state}).status_code,200)
        for scope in ['build','design','compare']:
            saved=self.alice.post('/api/worksheets',json={'scope':scope,'name':scope+' compatibility'})
            self.assertEqual(saved.status_code,200,saved.text)
            changed=self.alice.post('/api/worksheets/new',json={'scope':scope,'discard_unsaved':True})
            self.assertEqual(changed.status_code,200,changed.text)
            self.assertEqual(self.alice.get('/api/workspace').json()['data']['mrna'],mrna)
            opened=self.alice.post('/api/worksheets/'+saved.json()['id']+'/open')
            self.assertEqual(opened.status_code,200,opened.text)
            self.assertEqual(self.alice.get('/api/workspace').json()['data']['mrna'],mrna)

    def test_workbench_roundtrip_preserves_mrna_data(self):
        state={'view':'mrna','mrna':{'draft':{'records':[{'name':'Portable RNA','sequence':SEQUENCE}]},'result':{'rows':[]}}}
        self.assertEqual(self.alice.put('/api/workspace',json={'data':state}).status_code,200)
        saved=self.alice.post('/api/workbenches',json={'name':'RNA workbench'});self.assertEqual(saved.status_code,200,saved.text)
        bundle=self.alice.get('/api/workbenches/'+saved.json()['id']+'/export')
        self.assertEqual(bundle.json()['snapshot']['workspace']['mrna'],state['mrna'])
        imported=self.bob.post('/api/workbenches/import',files={'file':('rna.junc',bundle.content,'application/json')})
        self.assertEqual(imported.status_code,200,imported.text)
        opened=self.bob.post('/api/workbenches/'+imported.json()['id']+'/open');self.assertEqual(opened.status_code,200,opened.text)
        self.assertEqual(self.bob.get('/api/workspace').json()['data']['mrna'],state['mrna'])

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(),'Optional local scientific runtime not configured')
    def test_cancel_active_batch(self):
        import threading
        from unittest.mock import patch
        from app.mrna import capabilities
        capabilities()
        entered=threading.Event();release=threading.Event()
        def wait_for_cancel(*args,**kwargs):
            entered.set();release.wait(timeout=5)
            return {'rows':[],'errors':[]}
        with patch('app.mrna.invoke',side_effect=wait_for_cancel):
            response=self.alice.post('/api/mrna/jobs',json={'records':[{'name':'Cancel me','sequence':SEQUENCE}]})
            self.assertEqual(response.status_code,202,response.text);identifier=response.json()['id']
            self.assertTrue(entered.wait(timeout=3));self.assertEqual(self.alice.post('/api/mrna/jobs/'+identifier+'/cancel',json={}).status_code,200)
            release.set();self.assertEqual(self.wait(identifier)['status'],'cancelled')

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(),'Optional local scientific runtime not configured')
    def test_multiplex_partial_results_exports_and_ownership(self):
        payload={'name':'Private multiplex','records':[{'name':'=Unsafe label','sequence':SEQUENCE},{'name':'Internal stop','sequence':'ATGTAAGGGTAA'}]}
        response=self.alice.post('/api/mrna/jobs',json=payload);self.assertEqual(response.status_code,202,response.text)
        identifier=response.json()['id'];data=self.wait(identifier)
        self.assertEqual(data['status'],'partial',data);self.assertEqual(len(data['result']['rows']),1);self.assertIn('internal stop',data['result']['errors'][0]['error'])
        self.assertEqual(self.bob.get('/api/mrna/jobs/'+identifier).status_code,404)
        self.assertEqual(self.bob.post('/api/mrna/jobs/'+identifier+'/cancel',json={}).status_code,404)
        self.assertEqual(self.bob.get('/api/mrna/jobs/'+identifier+'/export').status_code,404)
        self.assertEqual(self.bob.get('/api/mrna/jobs').json()['items'],[])
        csv_response=self.alice.get('/api/mrna/jobs/'+identifier+'/export?format=csv')
        row=list(csv.DictReader(io.StringIO(csv_response.text)))[0]
        self.assertTrue(row['name'].startswith("'="));self.assertLess(float(row['mfe']),0)
        self.assertEqual(self.alice.get('/api/mrna/jobs/'+identifier+'/export?format=fasta').text.count('>'),1)
        self.assertEqual(self.alice.get('/api/mrna/jobs/'+identifier+'/export?format=json').json()['id'],identifier)
        dbn=self.alice.get('/api/mrna/jobs/'+identifier+'/export?format=dbn').text.splitlines();self.assertEqual(len(dbn[1]),len(dbn[2]))
        caps=self.alice.get('/api/mrna/capabilities').json()
        if not caps['models']['ribonn']:
            self.assertEqual(self.alice.post('/api/mrna/jobs',json={'records':payload['records'][:1],'predict_translation':True}).status_code,422)

if __name__=='__main__':unittest.main()
