"""Atomic build-list saves, shared folder permissions and legacy inventory migration."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app import database as store
from auth_client import bootstrap_pin


class PlasmidLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB');os.environ['GOLDEN_GATE_DB']=str(Path(self.tmp.name)/'db.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        with store.connection() as db:self.fragment=db.execute('INSERT INTO fragments(name,sequence,plate_id,well,yield_ng) VALUES(?,?,?,?,?)',('Donor','GGTCTCAAAAAGATTACAGCTAGCTGACCCCCGAGACC','P','A1',300)).lastrowid
        self.recipe={'name':'Build A','enzyme':'BsaI','fragment_ids':[self.fragment],'circular':False}
        self.client.put('/api/workspace',json={'data':{'view':'build','draft':self.recipe}})
        for name in ['Build A','Build B']:
            response=self.client.post('/api/build-list',json=self.recipe|{'name':name});self.assertEqual(response.status_code,200,response.text)
        response=self.client.post('/api/worksheets',json={'scope':'build','name':'Test worksheet'});self.assertEqual(response.status_code,200,response.text)

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.tmp.cleanup()

    def preview(self,client=None):
        client=client or self.client;version=client.get('/api/workspace').json()['context_version']
        response=client.get('/api/build-list/plasmid-preview',params={'context_version':version});self.assertEqual(response.status_code,200,response.text);return response.json()

    def save(self,preview,client=None,**extra):
        return (client or self.client).post('/api/build-list/save-plasmids',json={'build_ids':[r['id'] for r in preview['items'] if r['eligible']],'context_version':preview['context_version'],'fingerprint':preview['fingerprint'],**extra})

    def test_bulk_save_preserves_products_and_reuses_records_in_worksheet_folder(self):
        preview=self.preview();self.assertTrue(all(i['eligible'] for i in preview['items']),preview)
        expected=self.client.post('/api/assemblies/preview',json=self.recipe).json()
        response=self.save(preview);self.assertEqual(response.status_code,200,response.text);data=response.json()
        self.assertEqual(data['folder']['name'],'Test worksheet');self.assertEqual(data['created'],2)
        for item in data['items']:
            saved=self.client.get('/api/plasmids/'+str(item['id'])).json()
            self.assertEqual(saved['sequence'],expected['sequence']);self.assertEqual(saved['features'],expected['features']);self.assertFalse(saved['circular']);self.assertEqual(saved['folder_name'],'Test worksheet')
        again=self.save(preview);self.assertEqual(again.status_code,200,again.text);self.assertEqual(again.json()['reused'],2)
        self.assertEqual(len(store.plasmids()),2);self.assertEqual(len(self.client.get('/api/build-list').json()['items']),2)
        self.assertEqual(len(self.client.get('/api/plasmid-folders').json()['items']),1)

    def test_folder_rename_move_remove_keeps_sequences_and_rejects_conflicts(self):
        saved=self.save(self.preview()).json();identifier=saved['items'][0]['id'];sequence=store.get_plasmid(identifier)['sequence']
        created=self.client.post('/api/plasmid-folders',json={'name':' Review '});self.assertEqual(created.status_code,201,created.text);folder=created.json()['id']
        self.assertEqual(self.client.post('/api/plasmid-folders',json={'name':'review'}).status_code,409)
        self.assertEqual(self.client.post('/api/plasmid-folders',json={'name':'  '}).status_code,422)
        self.assertEqual(self.client.post('/api/plasmid-folders/assign',json={'plasmid_ids':[identifier],'folder_id':folder}).status_code,200)
        self.assertEqual(self.client.patch('/api/plasmid-folders/'+str(folder),json={'name':'Reviewed'}).status_code,200)
        self.assertEqual(store.get_plasmid(identifier)['folder_name'],'Reviewed')
        self.assertEqual(self.client.post('/api/plasmid-folders/assign',json={'plasmid_ids':[identifier,999999],'folder_id':None}).status_code,404)
        self.assertEqual(store.get_plasmid(identifier)['folder_id'],folder)
        self.assertEqual(self.client.delete('/api/plasmid-folders/'+str(folder)).status_code,200)
        self.assertIsNone(store.get_plasmid(identifier)['folder_id']);self.assertEqual(store.get_plasmid(identifier)['sequence'],sequence)

    def test_stale_build_list_or_worksheet_does_not_save_anything(self):
        preview=self.preview();build_id=preview['items'][0]['id']
        self.client.put('/api/build-list/'+str(build_id),json=self.recipe|{'name':'Changed'})
        self.assertEqual(self.save(preview).status_code,409);self.assertEqual(store.plasmids(),[]);self.assertEqual(self.client.get('/api/plasmid-folders').json()['items'],[])
        preview=self.preview();self.client.post('/api/worksheets/new',json={'scope':'build','discard_unsaved':True})
        self.assertEqual(self.save(preview).status_code,409);self.assertEqual(store.plasmids(),[])

    def test_invalid_selected_build_rolls_back_all_records_and_folder(self):
        with store.connection() as db:db.execute('UPDATE build_list SET request=? WHERE id=(SELECT max(id) FROM build_list)',(json.dumps(self.recipe|{'fragment_ids':[999999]}),))
        preview=self.preview();self.assertFalse(preview['items'][-1]['eligible'])
        response=self.save(preview,build_ids=[i['id'] for i in preview['items']]);self.assertGreaterEqual(response.status_code,400,response.text)
        self.assertEqual(store.plasmids(),[]);self.assertEqual(self.client.get('/api/plasmid-folders').json()['items'],[])

    def test_upload_only_duplicate_and_reader_permissions_are_atomic(self):
        self.client.post('/api/auth/users',json={'username':'uploader','pin':'654321','can_upload':True,'can_edit':False,'can_archive':False,'can_manage_rules':False})
        self.client.post('/api/auth/users',json={'username':'reader','pin':'654321','can_upload':False,'can_edit':False,'can_archive':False,'can_manage_rules':False})
        duplicate=self.client.post('/api/assemblies',json=self.recipe|{'name':'Existing'});self.assertEqual(duplicate.status_code,200,duplicate.text)
        uploader=TestClient(app);uploader.post('/api/auth/login',json={'username':'uploader','pin':'654321'})
        for name in ['New product','Existing']:self.assertEqual(uploader.post('/api/build-list',json=self.recipe|{'name':name}).status_code,200)
        preview=self.preview(uploader);response=self.save(preview,uploader);self.assertEqual(response.status_code,403,response.text)
        self.assertEqual([p['name'] for p in store.plasmids()],['Existing']);self.assertEqual(self.client.get('/api/plasmid-folders').json()['items'],[])
        reader=TestClient(app);reader.post('/api/auth/login',json={'username':'reader','pin':'654321'})
        self.assertEqual(reader.post('/api/plasmid-folders',json={'name':'Denied'}).status_code,403)
        self.assertEqual(reader.post('/api/build-list/save-plasmids',json={}).status_code,403)
        uploader.close();reader.close()

    def test_folder_name_travels_with_workbench_inventory(self):
        from app.workbenches import Plasmid
        self.assertIsNone(Plasmid(id=1,name='Unfiled',sequence='ATGC',folder_name='  ').folder_name)
        saved=self.save(self.preview()).json();identifier=saved['items'][0]['id']
        self.client.put('/api/workspace',json={'data':{'draft':self.recipe|{'backbone_id':identifier,'fragment_ids':[]}}})
        bench=self.client.post('/api/workbenches',json={'name':'Portable plasmids'});self.assertEqual(bench.status_code,200,bench.text)
        bundle=self.client.get('/api/workbenches/'+bench.json()['id']+'/export').json()
        self.assertEqual(bundle['snapshot']['inventory']['plasmids'][0]['folder_name'],'Test worksheet')
        self.client.patch('/api/plasmids/'+str(identifier),json={'name':'Original elsewhere'})
        imported=self.client.post('/api/workbenches/import',files={'file':('folders.junc',json.dumps(bundle).encode(),'application/json')})
        self.assertEqual(imported.status_code,200,imported.text)
        opened=self.client.post('/api/workbenches/'+imported.json()['id']+'/open');self.assertEqual(opened.status_code,200,opened.text)
        copied=next(p for p in store.plasmids() if p['name']=='Build A')
        self.assertNotEqual(copied['id'],identifier);self.assertEqual(copied['folder_name'],'Test worksheet')

if __name__=='__main__':unittest.main()
