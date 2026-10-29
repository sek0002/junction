"""Worksheet changes stay on one page; workbench bundles carry all worksheets."""
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


class WorksheetTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB');os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'worksheets.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        with store.connection() as db:
            self.fid=db.execute('INSERT INTO fragments(name,sequence,plate_id,well,yield_ng) VALUES(?,?,?,?,?)',('Donor','GGTCTCAAAAAGATTACAGCTAGCTGACCCCCGAGACC','P1','A1',300)).lastrowid
        self.draft={'name':'Assembly A','enzyme':'BsaI','fragment_ids':[self.fid]}
        self.design={'id':'design-a','name':'Design A','enzyme':'BsaI','entries':[]}
        self.workspace={'draft':self.draft,'view':'build','design':{'designs':[self.design],'activeId':'design-a'},'compareView':{'search':'sample','jobs':{}},'uploadRuleOverrides':{'insert_ratio':3}}
        self.client.put('/api/workspace',json={'data':self.workspace});self.client.post('/api/build-list',json=self.draft)

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def save(self,scope,name=None):
        r=self.client.post('/api/worksheets',json={'scope':scope,'name':name or scope+' worksheet'});self.assertEqual(r.status_code,200,r.text);return r.json()

    def test_new_and_open_assembly_include_build_list_without_changing_other_pages(self):
        saved=self.save('build');r=self.client.post('/api/worksheets/new',json={'scope':'build'});self.assertEqual(r.status_code,200,r.text)
        data=self.client.get('/api/workspace').json()['data'];self.assertNotIn('draft',data);self.assertEqual(data['design'],self.workspace['design']);self.assertEqual(data['compareView'],self.workspace['compareView']);self.assertEqual(self.client.get('/api/build-list').json()['items'],[])
        r=self.client.post('/api/worksheets/'+saved['id']+'/open');self.assertEqual(r.status_code,200,r.text)
        data=self.client.get('/api/workspace').json()['data'];self.assertEqual(data['draft']['name'],'Assembly A');self.assertEqual(data['design'],self.workspace['design']);self.assertEqual(len(self.client.get('/api/build-list').json()['items']),1)

    def test_design_only_file_and_import_preserve_assembly_and_shared_inventory(self):
        saved=self.save('design');r=self.client.get('/api/worksheets/'+saved['id']+'/export');self.assertEqual(r.status_code,200,r.text);value=r.json()
        self.assertEqual(value['format'],'junction-worksheet');self.assertEqual(value['scope'],'design');self.assertEqual(value['snapshot']['builds'],[]);self.assertNotIn('draft',value['snapshot']['workspace']);self.assertEqual(value['snapshot']['inventory']['fragments'],[])
        imported=self.client.post('/api/worksheets/import',files={'file':('design.junc',r.content,'application/json')});self.assertEqual(imported.status_code,200,imported.text)
        self.assertEqual(self.client.post('/api/worksheets/'+imported.json()['id']+'/open').status_code,200)
        data=self.client.get('/api/workspace').json()['data'];self.assertEqual(data['draft']['name'],'Assembly A');self.assertEqual(len(self.client.get('/api/build-list').json()['items']),1);self.assertEqual(len(store.fragments()),1)

    def test_workbench_contains_registry_and_roundtrips_after_a_new_instance(self):
        self.save('build');self.save('design');self.save('compare')
        r=self.client.post('/api/workbenches',json={'name':'All pages'});self.assertEqual(r.status_code,200,r.text);identifier=r.json()['id']
        exported=self.client.get('/api/workbenches/'+identifier+'/export').json();self.assertEqual(len(exported['snapshot']['worksheets']),3)
        self.assertEqual(len(self.client.get('/api/worksheets?scope=build').json()['items']),1)
        self.client.post('/api/workbenches/new',json={});self.assertEqual(self.client.get('/api/worksheets?scope=build').json()['items'],[])
        r=self.client.post('/api/workbenches/'+identifier+'/open');self.assertEqual(r.status_code,200,r.text)
        for scope in ('build','design','compare'):
            listing=self.client.get('/api/worksheets?scope='+scope).json();self.assertEqual(len(listing['items']),1);self.assertIsNotNone(listing['current'])
        extracted=self.client.get('/api/workbenches/'+identifier+'/export?scope=build').json();self.assertEqual(extracted['format'],'junction-worksheet');self.assertEqual(extracted['snapshot']['workspace']['draft']['name'],'Assembly A');self.assertNotIn('design',extracted['snapshot']['workspace'])

    def test_export_ignores_unset_current_worksheet_pointers(self):
        data=self.workspace|{'worksheet_ids':{'build':None,'design':None,'compare':None}}
        self.client.put('/api/workspace',json={'data':data})
        response=self.client.post('/api/workbenches/export-current');self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['snapshot']['worksheet_active'],{})

    def test_new_unnamed_workbench_starts_fresh_without_deleting_saved_worksheets(self):
        self.save('design')
        r=self.client.post('/api/workbenches/new',json={'discard_unsaved':True});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/worksheets?scope=design').json()['items'],[])
        self.assertEqual(len(self.client.get('/api/worksheets?scope=design&archived=true').json()['items']),1)

    def test_workbench_export_includes_live_edits_to_current_saved_worksheet(self):
        self.save('design')
        data=self.client.get('/api/workspace').json()['data'];data['design']['designs'][0]['name']='Latest design';self.client.put('/api/workspace',json={'data':data})
        exported=self.client.post('/api/workbenches/export-current').json();record=exported['snapshot']['worksheets'][0]
        self.assertEqual(record['snapshot']['workspace']['design']['designs'][0]['name'],'Latest design')

    def test_design_save_is_independent_of_unavailable_assembly_inputs(self):
        with store.connection() as db:db.execute('DELETE FROM fragments WHERE id=?',(self.fid,))
        r=self.client.post('/api/worksheets',json={'scope':'design','name':'Still available'});self.assertEqual(r.status_code,200,r.text)

    def test_worksheet_file_can_remap_fragment_ids_on_another_installation(self):
        content=self.client.post('/api/worksheets/export-current?scope=build').content
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'other.sqlite3');store.initialize()
        with store.connection() as db:
            occupied=db.execute('INSERT INTO fragments(name,sequence,plate_id,well) VALUES(?,?,?,?)',('Other donor','ACGT','P1','A1')).lastrowid
        client=TestClient(app);client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        imported=client.post('/api/worksheets/import',files={'file':('assembly.junc',content,'application/json')});self.assertEqual(imported.status_code,200,imported.text)
        response=client.post('/api/worksheets/'+imported.json()['id']+'/open');self.assertEqual(response.status_code,200,response.text)
        data=client.get('/api/workspace').json()['data'];self.assertNotEqual(data['draft']['fragment_ids'][0],occupied);self.assertEqual(store.get_fragment(occupied)['sequence'],'ACGT')
        self.assertEqual(len(client.get('/api/build-list').json()['items']),1);client.close()

    def test_archive_is_recoverable_and_private(self):
        saved=self.save('build');self.assertEqual(self.client.delete('/api/worksheets/'+saved['id']).status_code,200)
        self.assertEqual(self.client.get('/api/worksheets?scope=build').json()['items'],[])
        archived=self.client.get('/api/worksheets?scope=build&archived=true').json();self.assertEqual(len(archived['items']),1)
        self.assertEqual(self.client.post('/api/worksheets/'+saved['id']+'/restore').status_code,200)
        self.client.post('/api/auth/users',json={'username':'other','pin':'654321'});other=TestClient(app);other.post('/api/auth/login',json={'username':'other','pin':'654321'})
        self.assertEqual(other.get('/api/worksheets?scope=build').json()['items'],[]);self.assertEqual(other.get('/api/worksheets/'+saved['id']+'/export').status_code,404);self.assertEqual(other.delete('/api/worksheets/'+saved['id']).status_code,404);other.close()

    def test_unsaved_new_requires_choice_and_bad_scope_or_checksum_is_rejected(self):
        self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'build'}).status_code,409)
        self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'uploads','discard_unsaved':True}).status_code,422)
        value=self.client.post('/api/worksheets/export-current?scope=build').json();value['sha256']='bad'
        r=self.client.post('/api/worksheets/import',files={'file':('bad.junc',json.dumps(value),'application/json')});self.assertEqual(r.status_code,422)
        self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'build','discard_unsaved':True}).status_code,200)

    def test_junction_problems_identify_source_and_follow_selected_enzyme(self):
        sequence='GGTCTCA'+'AAAA'+'ACGTCGTCTCGACT'+'CCCC'+'C'+'GAGACC'
        with store.connection() as db:db.execute('INSERT INTO fragments(name,sequence,plate_id,well) VALUES(?,?,?,?)',('Nested donor',sequence,'P2','A1'))
        single=self.client.get('/api/library/metrics?enzyme=BsaI').json()
        self.assertEqual(single['qc_enzyme'],'BsaI')
        self.assertFalse(any(problem['source']=='Nested donor' for item in single['junctions'] for problem in item['problems']))
        dual=self.client.get('/api/library/metrics',params={'enzyme':'BsmBI + BsaI'}).json()
        problems=[problem for item in dual['junctions'] for problem in item['problems'] if problem['source']=='Nested donor']
        self.assertTrue(problems);self.assertTrue(all(p['source_type']=='fragments' for p in problems))
        self.assertTrue(any('Internal BsmBI site' in p['message'] for p in problems))

    def test_legacy_designs_migrate_once_and_junctions_group_reverse_complements(self):
        data=self.workspace;data['design']['designs'].append(self.design|{'id':'design-b','name':'Design B'});self.client.put('/api/workspace',json={'data':data})
        r=self.client.post('/api/worksheets/bootstrap');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['migrated'],2);self.assertEqual(self.client.post('/api/worksheets/bootstrap').json()['migrated'],0)
        metrics=self.client.get('/api/library/metrics');self.assertEqual(metrics.status_code,200,metrics.text);self.assertEqual(metrics.json()['designs'],2)
        overhangs=[j['overhang'] for j in metrics.json()['junctions']];self.assertEqual(len(overhangs),len(set(overhangs)));self.assertIn('AAAA',overhangs)
        for item in metrics.json()['junctions']:self.assertLessEqual(item['overhang'],item['reverse_complement'])

    def test_named_autosave_updates_same_record_for_all_pages(self):
        identifiers={scope:self.save(scope)['id'] for scope in ('build','design','compare')}
        data=self.client.get('/api/workspace').json()['data'];data['draft']['name']='Changed assembly';data['design']['designs'][0]['name']='Changed design';data['compareView']['search']='changed sample'
        result=self.client.put('/api/workspace',json={'data':data});self.assertEqual(result.status_code,200,result.text)
        for scope,identifier in identifiers.items():
            listing=self.client.get('/api/worksheets?scope='+scope).json();self.assertEqual(len(listing['items']),1);self.assertEqual(listing['current']['id'],identifier)
            exported=self.client.get('/api/worksheets/'+identifier+'/export').json()['snapshot']['workspace']
            if scope=='build':self.assertEqual(exported['draft']['name'],'Changed assembly')
            elif scope=='design':self.assertEqual(exported['design']['designs'][0]['name'],'Changed design')
            else:self.assertEqual(exported['compareView']['search'],'changed sample')
        with store.connection() as db:
            records=db.execute('SELECT payload FROM saved_worksheets').fetchall();self.assertEqual(len(records),3);self.assertTrue(any('Changed assembly' in row['payload'] for row in records))

    def test_switching_unsaved_draft_and_named_worksheet_never_creates_recovered_copies(self):
        for scope in ('build','design','compare'):
            saved=self.save(scope)
            self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':scope}).status_code,200)
            data=self.client.get('/api/workspace').json()['data']
            if scope=='build':data['draft']=self.draft|{'name':'Unsaved build'}
            elif scope=='design':data['design']={'designs':[self.design|{'name':'Unsaved design'}],'activeId':'design-a'}
            else:data['compareView']={'search':'Unsaved compare','jobs':{}}
            self.assertEqual(self.client.put('/api/workspace',json={'data':data}).status_code,200)
            for unused in range(3):
                opened=self.client.post('/api/worksheets/'+saved['id']+'/open');self.assertEqual(opened.status_code,200,opened.text)
                draft=self.client.post('/api/worksheets/draft/open',json={'scope':scope});self.assertEqual(draft.status_code,200,draft.text)
                restored=self.client.get('/api/workspace').json()['data']
                if scope=='build':self.assertEqual(restored['draft']['name'],'Unsaved build')
                elif scope=='design':self.assertEqual(restored['design']['designs'][0]['name'],'Unsaved design')
                else:self.assertEqual(restored['compareView']['search'],'Unsaved compare')
            self.assertEqual(len(self.client.get('/api/worksheets?scope='+scope).json()['items']),1)
        with store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM worksheet_drafts').fetchone()[0],3)

    def test_empty_new_clears_draft_and_dirty_new_requires_choice(self):
        self.client.post('/api/worksheets/new',json={'scope':'build','discard_unsaved':True})
        self.assertFalse(self.client.get('/api/worksheets?scope=build').json()['has_content'])
        self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'build'}).status_code,200)
        data=self.client.get('/api/workspace').json()['data'];data['draft']=self.draft
        self.client.put('/api/workspace',json={'data':data});self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'build'}).status_code,409)
        self.assertEqual(self.client.post('/api/worksheets/new',json={'scope':'build','discard_unsaved':True}).status_code,200)
        with store.connection() as db:payload=json.loads(db.execute("SELECT payload FROM worksheet_drafts WHERE scope='build'").fetchone()['payload']);self.assertNotIn('draft',payload['workspace'])

    def test_workbench_preserves_inactive_unsaved_drafts(self):
        saved=self.save('design');self.client.post('/api/worksheets/new',json={'scope':'design'})
        data=self.client.get('/api/workspace').json()['data'];data['design']={'designs':[self.design|{'name':'Draft retained'}],'activeId':'design-a'};self.client.put('/api/workspace',json={'data':data})
        self.client.post('/api/worksheets/'+saved['id']+'/open')
        saved_bench=self.client.post('/api/workbenches',json={'name':'Drafts too'});self.assertEqual(saved_bench.status_code,200,saved_bench.text)
        identifier=saved_bench.json()['id'];exported=self.client.get('/api/workbenches/'+identifier+'/export').json();self.assertEqual(exported['snapshot']['worksheet_drafts']['design']['workspace']['design']['designs'][0]['name'],'Draft retained')
        self.client.post('/api/workbenches/new',json={});self.client.post('/api/workbenches/'+identifier+'/open');self.client.post('/api/worksheets/draft/open',json={'scope':'design'})
        self.assertEqual(self.client.get('/api/workspace').json()['data']['design']['designs'][0]['name'],'Draft retained')

    def test_incomplete_design_fields_still_persist_without_blocking_other_pages(self):
        saved=self.save('build');data=self.client.get('/api/workspace').json()['data'];data['design']['designs'][0]['left_overhang']='AC';data['draft']['name']='Build still saves'
        response=self.client.put('/api/workspace',json={'data':data});self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/workspace').json()['data']['design']['designs'][0]['left_overhang'],'AC')
        with store.connection() as db:self.assertIn('Build still saves',db.execute('SELECT payload FROM saved_worksheets WHERE id=?',(saved['id'],)).fetchone()['payload'])

    def test_legacy_automatic_recoveries_move_to_archive_and_one_draft(self):
        from app.worksheets import save_record,capture
        # API establishes the authenticated context; construct the old automatic rows directly.
        with store.connection() as db:
            uid=db.execute('SELECT id FROM auth_users WHERE username=?',('admin',)).fetchone()['id']
            snapshot=self.client.post('/api/worksheets/export-current?scope=build').json()['snapshot']
            for number in range(3):db.execute('INSERT INTO saved_worksheets(id,user_id,scope,name,notes,payload,metadata) VALUES(?,?,?,?,?,?,?)',(f'recovered-{number}',uid,'build','Recovered Build','Automatic recovery snapshot.',encode(snapshot),encode({'automatic':True})))
        response=self.client.get('/api/worksheets?scope=build');self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['items'],[])
        self.assertEqual(len(self.client.get('/api/worksheets?scope=build&archived=true').json()['items']),3)
        self.assertEqual(self.client.post('/api/worksheets/recovered-1/restore').status_code,200)
        self.assertEqual(len(self.client.get('/api/worksheets?scope=build').json()['items']),1)
        with store.connection() as db:self.assertEqual(db.execute("SELECT count(*) FROM worksheet_drafts WHERE scope='build'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
