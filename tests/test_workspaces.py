"""Shared inventory, isolated persistent sandboxes and admin authorization."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import database as store
from app.main import app
from auth_client import bootstrap_pin


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'test.sqlite3');store.initialize()
        self.admin=TestClient(app);self.admin.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        self.alice_info=self.admin.post('/api/auth/users',json={'username':'alice','pin':'654321'}).json()
        self.bob_info=self.admin.post('/api/auth/users',json={'username':'bob','pin':'654321'}).json()
        self.alice=TestClient(app);self.bob=TestClient(app)
        for client,name in [(self.alice,'alice'),(self.bob,'bob')]:self.assertEqual(client.post('/api/auth/login',json={'username':name,'pin':'654321'}).status_code,200)
        sequence='GGTCTCAAAAAACGTCATGCTAGCTGACCCCCGAGACC'
        with store.connection() as db:
            self.fragment_id=db.execute('INSERT INTO fragments(name,plate_id,well,sequence,yield_ng) VALUES(?,?,?,?,?)',('Shared donor','P1','A1',sequence,300)).lastrowid
        self.build={'name':'Private design','fragment_ids':[self.fragment_id],'enzyme':'BsaI'}

    def tearDown(self):
        for client in (self.admin,self.alice,self.bob):client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def test_library_shared_and_workspace_survives_signout_restart_and_account_switch(self):
        for client in (self.alice,self.bob):self.assertEqual(client.get('/api/fragments').json()[0]['name'],'Shared donor')
        alice={'draft':self.build,'plannerOverrides':{'insert_ratio':3},'view':'build'}
        bob={'draft':self.build|{'name':'Bob design'},'plannerOverrides':{'insert_ratio':1}}
        self.assertEqual(self.alice.put('/api/workspace',json={'data':alice,'user_id':self.bob_info['id']}).status_code,200)
        self.bob.put('/api/workspace',json={'data':bob})
        self.alice.post('/api/auth/logout');store.initialize()
        self.alice.post('/api/auth/login',json={'username':'alice','pin':'654321'})
        self.assertEqual(self.alice.get('/api/workspace').json()['data'],alice)
        self.assertEqual(self.bob.get('/api/workspace').json()['data'],bob)
        self.assertEqual(self.admin.get('/api/workspace').json()['data'],{})

    def test_name_mode_persists_with_builds_settings_and_private_drafts(self):
        request=self.build|{'name_mode':'auto'}
        created=self.alice.post('/api/build-list',json=request)
        self.assertEqual(created.status_code,200,created.text)
        identifier=created.json()['id']
        self.assertEqual(created.json()['request']['name_mode'],'auto')
        updated=self.alice.patch(f'/api/build-list/{identifier}/settings',json={'insert_ratio':2})
        self.assertEqual(updated.json()['request']['name_mode'],'auto')
        request=request|{'name':'Manually edited','name_mode':'manual'}
        self.assertEqual(self.alice.put(f'/api/build-list/{identifier}',json=request).status_code,200)
        self.assertEqual(self.alice.get('/api/build-list').json()['items'][0]['request']['name_mode'],'manual')
        self.alice.put('/api/workspace',json={'data':{'draft':request}})
        self.assertEqual(self.alice.get('/api/workspace').json()['data']['draft']['name_mode'],'manual')
        self.assertNotEqual(self.bob.get('/api/workspace').json()['data'].get('draft'),request)

    def test_builds_list_settings_delete_restore_and_export_are_owner_scoped(self):
        created=self.alice.post('/api/build-list',json=self.build);self.assertEqual(created.status_code,200,created.text);identifier=created.json()['id']
        own=self.bob.post('/api/build-list',json=self.build).json();self.assertEqual(own['request']['name'],'Private design')
        self.assertEqual([i['id'] for i in self.bob.get('/api/build-list').json()['items']],[own['id']])
        for response in [self.bob.put(f'/api/build-list/{identifier}',json=self.build),self.bob.patch(f'/api/build-list/{identifier}/settings',json={'insert_ratio':5}),self.bob.delete(f'/api/build-list/{identifier}'),self.bob.post(f'/api/build-list/{identifier}/restore')]:
            self.assertEqual(response.status_code,404,response.text)
        self.alice.delete(f'/api/build-list/{identifier}')
        self.assertIsNone(self.bob.get('/api/build-list').json()['last_removed_id'])
        self.assertEqual(self.alice.post(f'/api/build-list/{identifier}/restore').status_code,200)
        self.assertEqual(self.admin.get('/api/build-list').json()['items'],[])
        self.assertEqual(self.admin.get('/api/build-list/worksheet').status_code,422)
        self.assertEqual(self.alice.get('/api/build-list/worksheet?format=csv').status_code,200)

    def test_group_stock_changes_and_comparison_references_do_not_cross_owners(self):
        from app.auth import _user
        from app.main import comparison_references
        for client in (self.alice,self.bob):client.post('/api/build-list',json=self.build|{'starter_fragment_id':self.fragment_id,'fragment_ids':[]})
        result=self.alice.put('/api/build-list/backbone-stocks/apply',json={'kind':'fragment','id':self.fragment_id,'stock_ng_ul':77})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotEqual(self.bob.get('/api/build-list').json()['items'][0]['request']['settings']['backbone_stock_ng_ul'],77)
        # A valid one-fragment circle provides a distinguishable private reference.
        with store.connection() as db:
            db.execute("UPDATE fragments SET sequence='GGTCTCAAAAAACGTGACTAAAAAGAGACC' WHERE id=?",(self.fragment_id,))
            db.execute('DELETE FROM build_list')
        created=self.alice.post('/api/build-list',json=self.build)
        self.assertEqual(created.status_code,200,created.text)
        token=_user.set(self.alice_info)
        try:self.assertTrue(any(r['source']=='Build list' for r in comparison_references()))
        finally:_user.reset(token)
        token=_user.set(self.bob_info)
        try:self.assertFalse(any(r['source']=='Build list' for r in comparison_references()))
        finally:_user.reset(token)
        self.assertEqual(self.bob.get('/api/build-list').json()['items'],[])

    def test_permissions_enforced_for_live_sessions_and_private_planning_remains_available(self):
        rights={key:False for key in ('can_upload','can_edit','can_archive','can_manage_rules')}
        self.assertEqual(self.admin.patch('/api/auth/users/'+str(self.alice_info['id']),json=rights).status_code,200)
        blocked=[('PATCH',f'/api/fragments/{self.fragment_id}',{'yield_locked':False}),('PATCH','/api/plasmids/1',{'name':'x'}),('POST','/api/inventory/reset',{'fragment_ids':[self.fragment_id]}),('POST','/api/inventory/apply-rules',{}),('PUT','/api/inventory/rules',{}),('POST','/api/inventory/rules/reset',{}),('POST','/api/bin/archive',{'fragment_ids':[self.fragment_id]}),('POST','/api/bin/restore',{}),('POST','/api/assemblies',self.build)]
        for method,url,body in blocked:self.assertEqual(self.alice.request(method,url,json=body).status_code,403,url)
        for url in ('/api/uploads/plate','/api/uploads/plasmid'):
            self.assertEqual(self.alice.post(url,files={'file':('test.fa','>test\nACGT','text/plain')}).status_code,403)
        self.assertEqual(self.alice.get('/api/fragments').status_code,200)
        self.assertEqual(self.alice.post('/api/assemblies/preview',json=self.build).status_code,200)
        self.assertEqual(self.alice.post('/api/build-list',json=self.build).status_code,200)
        self.assertEqual(self.alice.put('/api/workspace',json={'data':{'draft':self.build}}).status_code,200)
        self.admin.patch('/api/auth/users/'+str(self.alice_info['id']),json={'can_edit':True})
        self.assertEqual(self.alice.patch(f'/api/fragments/{self.fragment_id}',json={'yield_locked':False}).status_code,200)
        self.assertEqual(self.alice.post('/api/bin/archive',json={}).status_code,403)

    def test_comparison_sources_results_and_failures_persist_privately(self):
        result=self.alice.post('/api/compare?infer=false',files={'file':('query.fa','>query\nACGTACGTACGTACGT','text/plain')})
        self.assertEqual(result.status_code,200,result.text);identifier=result.json()['sandbox_id']
        invalid=self.alice.post('/api/compare?infer=false',files={'file':('invalid.fa','>bad\nZZZZ','text/plain')});self.assertEqual(invalid.status_code,422)
        store.initialize();rows=self.alice.get('/api/workspace/comparisons').json()['items']
        self.assertEqual(len(rows),2);self.assertIn('ACGT',rows[0]['source']);self.assertIsNotNone(rows[0]['result']);self.assertTrue(rows[1]['error'])
        self.assertEqual(self.bob.get('/api/workspace/comparisons').json()['items'],[])
        self.assertEqual(self.bob.delete(f'/api/workspace/comparisons/{identifier}').status_code,404)
        self.assertEqual(self.bob.post('/api/compare?infer=false&sandbox_id='+str(identifier),files={'file':('evil.fa','>other\nACGT','text/plain')}).status_code,404)
        self.assertEqual(self.alice.delete(f'/api/workspace/comparisons/{identifier}').status_code,200)
        self.assertEqual(len(self.alice.get('/api/workspace/comparisons').json()['items']),1)
        self.bob.delete('/api/workspace/comparisons');self.assertEqual(len(self.alice.get('/api/workspace/comparisons').json()['items']),1)

    def test_deleted_user_loses_sessions_restore_recovers_same_sandbox_and_library_stays(self):
        self.alice.put('/api/workspace',json={'data':{'draft':self.build}})
        identifier=self.alice_info['id']
        self.assertEqual(self.admin.delete(f'/api/auth/users/{identifier}').status_code,200)
        self.assertEqual(self.alice.get('/api/workspace').status_code,401)
        self.assertEqual(self.alice.post('/api/auth/login',json={'username':'alice','pin':'654321'}).status_code,401)
        self.assertNotIn(identifier,[u['id'] for u in self.admin.get('/api/auth/users').json()])
        self.assertTrue(next(u for u in self.admin.get('/api/auth/users?include_deleted=true').json() if u['id']==identifier)['deleted_at'])
        self.admin.post(f'/api/auth/users/{identifier}/restore');self.admin.patch(f'/api/auth/users/{identifier}',json={'active':True})
        self.assertEqual(self.alice.post('/api/auth/login',json={'username':'alice','pin':'654321'}).status_code,200)
        self.assertEqual(self.alice.get('/api/workspace').json()['data']['draft'],self.build)
        self.assertEqual(len(self.bob.get('/api/fragments').json()),1)
        self.assertEqual(self.admin.delete('/api/auth/users/1').status_code,422)
        self.assertEqual(self.admin.patch('/api/auth/users/1',json={'is_admin':False}).status_code,422)

    def test_activity_is_admin_only_persistent_and_omits_payloads_and_pins(self):
        self.alice.patch(f'/api/fragments/{self.fragment_id}',json={'yield_locked':False})
        self.assertEqual(self.alice.get('/api/auth/activity').status_code,403)
        self.assertEqual(self.alice.delete('/api/auth/users/'+str(self.bob_info['id'])).status_code,403)
        store.initialize();result=self.admin.get('/api/auth/activity?user_id='+str(self.alice_info['id'])).json()
        self.assertTrue(any(r['target']==f'/api/fragments/{self.fragment_id}' for r in result['items']))
        text=json.dumps(result);self.assertNotIn('654321',text);self.assertNotIn('pin_hash',text);self.assertNotIn('yield_locked',text)
        self.assertTrue(all(r['username']=='alice' for r in result['items']))

    def test_stale_tab_cannot_read_or_write_using_another_accounts_cookie(self):
        headers={'X-Junction-User':str(self.bob_info['id'])}
        for response in [self.alice.get('/api/workspace',headers=headers),self.alice.put('/api/workspace',headers=headers,json={'data':{'wrong':'user'}}),self.alice.patch(f'/api/fragments/{self.fragment_id}',headers=headers,json={'yield_locked':False})]:
            self.assertEqual(response.status_code,409);self.assertEqual(response.headers['X-Junction-Account-Changed'],'1')
        self.assertEqual(self.alice.get('/api/workspace').json()['data'],{})

    def test_upload_permission_cannot_bypass_edit_or_archive_rights(self):
        pid=store.save_plasmid('Shared','ACGTACGT',circular=False)
        target='/api/auth/users/'+str(self.alice_info['id'])
        self.admin.patch(target,json={'can_edit':False,'can_archive':False})
        upload=lambda text:self.alice.post('/api/uploads/plasmid',files={'file':('test.fa',text,'text/plain')})
        self.assertEqual(upload('>New record\nACGTACGA').status_code,200)
        self.assertEqual(upload('>Shared\nACGTACGT').status_code,403)
        self.assertEqual(upload('>Would be partial\nACGTACTT\n>Shared\nACGTACGT').status_code,403)
        self.assertFalse(any(p['name']=='Would be partial' for p in store.plasmids()))
        self.admin.patch(target,json={'can_edit':True})
        self.admin.post('/api/bin/archive',json={'plasmid_ids':[pid]})
        self.assertEqual(upload('>Shared\nACGTACGT').status_code,403)
        with store.connection() as db:self.assertIsNotNone(db.execute('SELECT archived_at FROM plasmids WHERE id=?',(pid,)).fetchone()[0])

    def test_legacy_builds_migrate_once_to_admin_and_never_to_new_users(self):
        self.admin.post('/api/build-list',json=self.build)
        with store.connection() as db:db.execute('UPDATE build_list SET user_id=NULL')
        store.initialize();store.initialize()
        self.assertEqual(len(self.admin.get('/api/build-list').json()['items']),1)
        self.assertEqual(self.alice.get('/api/build-list').json()['items'],[])
        with store.connection() as db:self.assertEqual(db.execute('SELECT user_id FROM build_list').fetchone()[0],1)


if __name__=='__main__':unittest.main()
