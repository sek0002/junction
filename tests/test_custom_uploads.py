"""Manual imports keep sequence identity separate from physical stock identity."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import database as store
from app.main import app
from auth_client import bootstrap_pin


class CustomUploadTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB');os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'stocks.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        with store.connection() as db:
            self.source=db.execute('INSERT INTO fragments(name,plate_id,well,sequence,construct_sequence,stock_ng_ul,yield_ng,resuspension_ul) VALUES(?,?,?,?,?,?,?,?)',('Donor','Original','A1','GGTCTCAAAAAGATTACAGCTAGCTGACCCCCGAGACC','ACGT'*20,12,1200,100)).lastrowid
    def tearDown(self):
        self.client.close()
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()
    def upload(self,rows,**extra):return self.client.post('/api/uploads/custom',json={'rows':rows,**extra})
    def test_link_creates_independent_stock_with_free_location_and_no_coordinates(self):
        response=self.upload([{'name':'Donor aliquot','link':f'Donor (#{self.source})','concentration':25,'location':'Freezer -20 / blue box / tube 3'}]);self.assertEqual(response.status_code,200,response.text)
        new=store.get_fragment(response.json()['ids'][0]);old=store.get_fragment(self.source)
        self.assertNotEqual(new['id'],old['id']);self.assertEqual(new['sequence'],old['sequence']);self.assertEqual(new['construct_sequence'],old['construct_sequence']);self.assertEqual(new['stock_ng_ul'],25);self.assertIsNone(new['yield_ng']);self.assertIsNone(new['resuspension_ul']);self.assertFalse(new['yield_locked']);self.assertEqual(old['stock_ng_ul'],12);self.assertEqual(old['resuspension_ul'],100)
        self.assertEqual(new['custom_metadata']['linked_fragment_id'],old['id']);self.assertEqual(new['location'],'Freezer -20 / blue box / tube 3');self.assertEqual(new['plate_id'],'');self.assertEqual(new['well'],'')
        updated=self.client.patch('/api/fragments/'+str(new['id']),json={'resuspension_ul':40,'derive':'yield_ng'});self.assertEqual(updated.status_code,200,updated.text);self.assertEqual(updated.json()['yield_ng'],1000);self.assertEqual(updated.json()['stock_ng_ul'],25);self.assertEqual(store.get_fragment(old['id'])['resuspension_ul'],100)
        found=self.client.get('/api/fragments',params={'q':'Donor aliquot'}).json()[0];self.assertEqual(found['location'],new['location']);self.assertEqual(found['custom_metadata']['linked_fragment_name'],'Donor')
    def test_multiple_unlocated_stocks_and_retry_have_distinct_identity(self):
        rows=[{'name':'A','sequence':'ACGT'},{'name':'B','link':str(self.source)}]
        first=self.upload(rows,request_id='repeat');second=self.upload(rows,request_id='repeat');third=self.upload(rows,request_id='new')
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(second.json()['count'],0);self.assertEqual(second.json()['ids'],first.json()['ids']);self.assertEqual(third.json()['count'],2);self.assertEqual(len(store.fragments()),5)
        store.initialize();self.assertEqual(len(store.fragments()),5)
    def test_optional_plate_and_well_normalization_and_atomic_conflicts(self):
        result=self.upload([{'name':'A','sequence':'ACGT','plate':'New','well':'b02'}]);self.assertEqual(result.status_code,200,result.text);self.assertEqual(store.get_fragment(result.json()['ids'][0])['well'],'B2')
        before=len(store.fragments());bad=self.upload([{'name':'First','sequence':'ACGT'},{'name':'Conflict','sequence':'AAAA','plate':'New','well':'B2'}]);self.assertEqual(bad.status_code,422);self.assertEqual(len(store.fragments()),before)
        self.assertEqual(self.upload([{'name':'X','sequence':'ACGT','well':'Z55'}]).status_code,422)
    def test_invalid_or_ambiguous_sources_do_not_import(self):
        for row in ({'name':'X'},{'name':'X','sequence':'ACGTN'},{'name':'X','sequence':'ACGT','link':str(self.source)},{'name':'X','link':'not-found'},{'name':'X','sequence':'>a\nACGT\n>b\nACGT'},{'name':'X','sequence':'ACGT','concentration':-1}):
            response=self.upload([row]);self.assertEqual(response.status_code,422,response.text)
        with store.connection() as db:db.execute('INSERT INTO fragments(name,sequence) VALUES(?,?)',('Donor','ACGT'))
        self.assertEqual(self.upload([{'name':'X','link':'Donor'}]).status_code,422)
        with store.connection() as db:db.execute('UPDATE fragments SET archived_at=CURRENT_TIMESTAMP WHERE id=?',(self.source,))
        self.assertEqual(self.upload([{'name':'X','link':str(self.source)}]).status_code,422)
    def test_fasta_and_genbank_parse_and_annotations(self):
        response=self.client.post('/api/uploads/custom/parse',files={'file':('multi.fa',b'>one\nACGT\n>two\nTGCA','text/plain')});self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(response.json()['records']),2)
        gb=b'LOCUS       sample                     12 bp    DNA     linear\nDEFINITION  sample.\nFEATURES             Location/Qualifiers\n     misc_feature    2..6\n                     /label="tag"\nORIGIN\n        1 acgtacgtacgt\n//\n'
        response=self.client.post('/api/uploads/custom/parse',files={'file':('sample.gbk',gb,'text/plain')});self.assertEqual(response.status_code,200,response.text);record=response.json()['records'][0];self.assertTrue(record['features'])
        imported=self.upload([{'name':'Tagged','sequence':record['sequence'],'features':record['features'],'filename':'sample.gbk'}]);self.assertEqual(imported.status_code,200,imported.text);self.assertEqual(store.get_fragment(imported.json()['ids'][0])['custom_metadata']['features'],record['features'])
    def test_portable_bundle_keeps_anonymous_stocks_separate(self):
        response=self.upload([{'name':'Twin','link':str(self.source),'concentration':10},{'name':'Twin','link':str(self.source),'concentration':20}]);self.assertEqual(response.status_code,200,response.text)
        ids=response.json()['ids'];data={'draft':{'name':'Twins','enzyme':'BsaI','fragment_ids':ids},'view':'build'};r=self.client.put('/api/workspace',json={'data':data});self.assertEqual(r.status_code,200,r.text)
        bundle=self.client.post('/api/worksheets/export-current?scope=build');self.assertEqual(bundle.status_code,200,bundle.text)
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'other.sqlite3');store.initialize();other=TestClient(app);other.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        imported=other.post('/api/worksheets/import',files={'file':('twins.junc',bundle.content,'application/json')});self.assertEqual(imported.status_code,200,imported.text);opened=other.post('/api/worksheets/'+imported.json()['id']+'/open');self.assertEqual(opened.status_code,200,opened.text)
        stocks=store.fragments();self.assertEqual(len(stocks),2);self.assertEqual({r['stock_ng_ul'] for r in stocks},{10,20});self.assertEqual({r['plate_id'] for r in stocks},{''});other.close()
    def test_upload_rights_and_legacy_unique_well_migration(self):
        self.client.post('/api/auth/users',json={'username':'reader','pin':'654321','can_upload':False});other=TestClient(app);other.post('/api/auth/login',json={'username':'reader','pin':'654321'});self.assertEqual(other.post('/api/uploads/custom',json={'rows':[{'name':'X','sequence':'ACGT'}]}).status_code,403);other.close()
        # A database from before free-text locations retains stock IDs and quantities.
        db_path=Path(self.folder.name)/'legacy.sqlite3';db=sqlite3.connect(db_path);db.execute("CREATE TABLE fragments(id INTEGER PRIMARY KEY,name TEXT NOT NULL,plate_id TEXT NOT NULL DEFAULT '',well TEXT NOT NULL DEFAULT '',sequence TEXT NOT NULL,construct_sequence TEXT NOT NULL DEFAULT '',yield_ng REAL,stock_ng_ul REAL,resuspension_ul REAL,concentration_basis TEXT DEFAULT 'unknown',notes TEXT NOT NULL DEFAULT '',source_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(plate_id,well))");db.execute("INSERT INTO fragments(id,name,plate_id,well,sequence,stock_ng_ul) VALUES(77,'Old','Plate','A1','ACGT',22)");db.commit();db.close();os.environ['GOLDEN_GATE_DB']=str(db_path);store.initialize();self.assertEqual(store.get_fragment(77)['stock_ng_ul'],22)
        with store.connection() as db:
            db.execute("INSERT INTO fragments(name,sequence) VALUES('Free 1','ACGT')");db.execute("INSERT INTO fragments(name,sequence) VALUES('Free 2','ACGT')")
            with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO fragments(name,sequence,plate_id,well) VALUES('Collision','ACGT','Plate','A1')")

if __name__=='__main__':unittest.main()
