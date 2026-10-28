"""Named private sandboxes, portable DNA dependencies and safe replacement."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import database as store
from app.main import app
from app.workbenches import encode
from auth_client import bootstrap_pin


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'source.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        with store.connection() as db:
            self.fragment=db.execute('INSERT INTO fragments(name,sequence,plate_id,well,yield_ng) VALUES(?,?,?,?,?)',('Donor','GGTCTCAAAAAACGTCATGCTAGCTGACCCCCGAGACC','P1','A1',300)).lastrowid
        self.draft={'name':'Saved assembly','enzyme':'BsaI','fragment_ids':[self.fragment],'settings':{'insert_ratio':2,'fragment_stock_overrides':{str(self.fragment):{'stock_ng_ul':20,'yield_ng':300,'resuspension_ul':15}}}}
        self.client.put('/api/workspace',json={'data':{'draft':self.draft,'view':'build','plannerOverrides':{'insert_ratio':2}}})
        response=self.client.post('/api/build-list',json=self.draft);self.assertEqual(response.status_code,200,response.text);self.build=response.json()['id']

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def save(self,name='Experiment'):
        response=self.client.post('/api/workbenches',json={'name':name,'notes':'Bench notes'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def exported(self,identifier):
        response=self.client.get('/api/workbenches/'+identifier+'/export')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('.junc',response.headers['content-disposition'])
        return response

    def test_save_metadata_private_list_and_download_contain_only_snapshot_data(self):
        record=self.save();listing=self.client.get('/api/workbenches').json()
        self.assertEqual(listing['current']['id'],record['id']);self.assertEqual(record['metadata']['builds'],1)
        self.assertEqual(record['metadata']['fragments'],1);self.assertEqual(record['notes'],'Bench notes')
        value=self.exported(record['id']).json();self.assertEqual(value['format_version'],1)
        self.assertEqual(value['snapshot']['inventory']['fragments'][0]['sequence'],store.get_fragment(self.fragment)['sequence'])
        self.assertEqual(value['sha256'],hashlib.sha256(encode(value['snapshot']).encode()).hexdigest())
        self.assertNotIn('pin_hash',encode(value));self.assertNotIn('auth_sessions',encode(value))
        self.client.post('/api/auth/users',json={'username':'other','pin':'654321'})
        other=TestClient(app);other.post('/api/auth/login',json={'username':'other','pin':'654321'})
        self.assertEqual(other.get('/api/workbenches').json()['items'],[])
        self.assertEqual(other.get('/api/workbenches/'+record['id']+'/export').status_code,404)
        self.assertEqual(other.post('/api/workbenches/'+record['id']+'/open').status_code,404)
        other.close()

    def test_new_autosaves_named_instance_and_unsaved_new_requires_explicit_choice(self):
        self.assertEqual(self.client.post('/api/workbenches/new',json={}).status_code,409)
        record=self.save();data=self.client.get('/api/workspace').json()['data'];data['draft']['name']='Latest name'
        self.client.put('/api/workspace',json={'data':data})
        response=self.client.post('/api/workbenches/new',json={})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['autosaved'],record['id'])
        self.assertEqual(self.exported(record['id']).json()['snapshot']['workspace']['draft']['name'],'Latest name')
        self.assertEqual(self.client.get('/api/workspace').json()['data'],{})
        self.assertEqual(self.client.get('/api/build-list').json()['items'],[])
        self.assertEqual(self.client.post('/api/workbenches/new',json={'discard_unsaved':True}).status_code,200)

    def test_loading_restores_builds_and_draft_and_saves_an_unnamed_recovery_copy(self):
        record=self.save();self.client.post('/api/workbenches/new',json={})
        self.client.put('/api/workspace',json={'data':{'draft':self.draft|{'name':'Unsaved work'}}})
        response=self.client.post('/api/workbenches/'+record['id']+'/open')
        self.assertEqual(response.status_code,200,response.text)
        draft=self.client.get('/api/workspace').json()['data'];self.assertEqual(draft['draft']['name'],'Saved assembly')
        self.assertEqual(draft['workbench_id'],record['id'])
        self.assertEqual(len(self.client.get('/api/build-list').json()['items']),1)
        listing=self.client.get('/api/workbenches').json()['items']
        recovery=next(item for item in listing if item['metadata'].get('automatic'))
        self.assertEqual(self.exported(recovery['id']).json()['snapshot']['workspace']['draft']['name'],'Unsaved work')

    def test_file_roundtrip_to_a_different_database_remaps_ids_and_preserves_existing_rows(self):
        record=self.save();content=self.exported(record['id']).content
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'destination.sqlite3');store.initialize()
        with store.connection() as db:
            occupied=db.execute('INSERT INTO fragments(name,sequence,plate_id,well) VALUES(?,?,?,?)',('Different donor','ACGT','P1','A1')).lastrowid
        destination=TestClient(app);destination.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        imported=destination.post('/api/workbenches/import',files={'file':('shared.junc',content,'application/json')})
        self.assertEqual(imported.status_code,200,imported.text)
        identifier=imported.json()['id'];self.assertNotEqual(identifier,record['id'])
        opened=destination.post('/api/workbenches/'+identifier+'/open');self.assertEqual(opened.status_code,200,opened.text)
        workspace=destination.get('/api/workspace').json()['data'];new_id=workspace['draft']['fragment_ids'][0]
        self.assertNotEqual(new_id,occupied);self.assertEqual(store.get_fragment(occupied)['sequence'],'ACGT')
        imported_fragment=store.get_fragment(new_id)
        self.assertTrue(imported_fragment['plate_id'].startswith('JUNC-'));self.assertEqual(imported_fragment['well'],'A1')
        self.assertEqual(workspace['draft']['settings']['fragment_stock_overrides'][str(new_id)]['stock_ng_ul'],20)
        self.assertEqual(destination.get('/api/build-list').json()['items'][0]['request']['fragment_ids'],[new_id])
        destination.close()

    def test_import_validates_format_checksum_and_reference_closure_without_writes(self):
        record=self.save();original=self.exported(record['id']).json()
        for mutate in [lambda v:v.update(format='foreign'),lambda v:v.update(sha256='bad'),lambda v:v['snapshot']['inventory'].update(fragments=[])]:
            value=json.loads(json.dumps(original));mutate(value)
            if value['sha256']!='bad':value['sha256']=hashlib.sha256(encode(value['snapshot']).encode()).hexdigest()
            response=self.client.post('/api/workbenches/import',files={'file':('bad.junc',json.dumps(value),'application/json')})
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(len(self.client.get('/api/workbenches').json()['items']),1)

    def test_missing_inventory_requires_upload_rights_and_rolls_back_the_switch(self):
        content=self.exported(self.save()['id']).content
        self.client.post('/api/auth/users',json={'username':'reader','pin':'654321','can_upload':False,'can_edit':False})
        reader=TestClient(app);reader.post('/api/auth/login',json={'username':'reader','pin':'654321'})
        imported=reader.post('/api/workbenches/import',files={'file':('shared.junc',content,'application/json')}).json()
        with store.connection() as db:db.execute('UPDATE fragments SET archived_at=CURRENT_TIMESTAMP WHERE id=?',(self.fragment,))
        reader.put('/api/workspace',json={'data':{'view':'design'}})
        response=reader.post('/api/workbenches/'+imported['id']+'/open')
        self.assertEqual(response.status_code,403,response.text)
        self.assertEqual(reader.get('/api/workspace').json()['data'],{'view':'design'})
        self.assertEqual(len(reader.get('/api/workbenches').json()['items']),1)
        reader.close()

    def test_import_rejects_malformed_workspace_shapes_without_saving(self):
        original=self.exported(self.save()['id']).json()
        for key in ('backboneStocks','compareView','design'):
            value=json.loads(json.dumps(original));value['snapshot']['workspace'][key]=['invalid']
            value['sha256']=hashlib.sha256(encode(value['snapshot']).encode()).hexdigest()
            response=self.client.post('/api/workbenches/import',files={'file':('bad.junc',json.dumps(value),'application/json')})
            self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(len(self.client.get('/api/workbenches').json()['items']),1)

    def test_restricted_users_can_save_share_and_load_existing_inventory(self):
        self.client.post('/api/auth/users',json={'username':'reader','pin':'654321','can_upload':False,'can_edit':False})
        content=self.exported(self.save()['id']).content
        reader=TestClient(app);reader.post('/api/auth/login',json={'username':'reader','pin':'654321'})
        imported=reader.post('/api/workbenches/import',files={'file':('shared.junc',content,'application/json')})
        self.assertEqual(imported.status_code,200,imported.text)
        response=reader.post('/api/workbenches/'+imported.json()['id']+'/open');self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(reader.post('/api/workbenches/export-current').status_code,200)
        reader.close()


if __name__=='__main__':unittest.main()
