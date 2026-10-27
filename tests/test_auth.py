"""Authentication boundaries, persistent sessions, roles and PIN lifecycle."""
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import database as store
from app.auth import COOKIE, verify_pin, initial_pin_path
from auth_client import bootstrap_pin
from app.main import app


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'test.sqlite3')
        store.initialize();self.pin=bootstrap_pin();self.client=TestClient(app)

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def login(self,client=None,username='admin',pin=None):
        if pin is None:pin=self.pin
        return (client or self.client).post('/api/auth/login',json={'username':username,'pin':pin})

    def test_pages_apis_downloads_and_docs_require_login(self):
        for path in ('/','/static/index.html','/docs','/redoc'):
            result=self.client.get(path,follow_redirects=False)
            self.assertEqual(result.status_code,303,path);self.assertEqual(result.headers['location'],'/login')
        for path in ('/api/summary','/api/fragments','/api/build-list','/api/health','/openapi.json','/api/plasmids/1/genbank'):
            self.assertEqual(self.client.get(path).status_code,401,path)
        self.assertEqual(self.client.post('/api/bin/archive',json={}).status_code,401)
        for path in ('/login','/manifest.webmanifest','/service-worker.js','/static/assets/junction-mark-v4.svg','/static/login.js'):
            self.assertEqual(self.client.get(path).status_code,200,path)

    def test_bootstrap_hash_cookie_attributes_and_no_secret_outputs(self):
        with store.connection() as db:encoded=db.execute('SELECT pin_hash FROM auth_users').fetchone()[0]
        self.assertNotIn(self.pin,encoded);self.assertTrue(verify_pin(self.pin,encoded))
        result=self.login();self.assertEqual(result.status_code,200)
        self.assertTrue(result.json()['user']['is_admin']);self.assertNotIn('pin',result.text.lower())
        self.assertIn('HttpOnly',result.headers['set-cookie']);self.assertIn('SameSite=strict',result.headers['set-cookie'])
        self.assertIn('Max-Age=604800',result.headers['set-cookie']);self.assertEqual(result.headers['cache-control'],'no-store')
        self.assertEqual(self.client.get('/api/summary').status_code,200)
        self.assertEqual(self.client.get('/login',follow_redirects=False).headers['location'],'/')
        with TestClient(app,base_url='https://testserver') as secure:
            response=self.login(secure);self.assertIn('Secure',response.headers['set-cookie'])

    def test_first_run_pin_is_private_unique_and_not_replaced_on_restart(self):
        path=initial_pin_path()
        self.assertEqual(len(self.pin),12);self.assertTrue(self.pin.isdigit())
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        store.initialize();self.assertEqual(path.read_text().strip(),self.pin)
        with patch.dict(os.environ,{'GOLDEN_GATE_DB':str(Path(self.folder.name)/'other.sqlite3')}):
            store.initialize();self.assertNotEqual(bootstrap_pin(),self.pin)
        with patch.dict(os.environ,{'GOLDEN_GATE_INITIAL_ADMIN_PIN':'invalid'}):
            store.initialize();self.assertEqual(bootstrap_pin(),self.pin)

    def test_existing_admin_without_bootstrap_marker_is_never_reset(self):
        with store.connection() as db:db.execute("DELETE FROM settings WHERE key='auth_bootstrapped'")
        initial_pin_path().unlink()
        store.initialize()
        self.assertFalse(initial_pin_path().exists())
        self.assertEqual(self.login().status_code,200)

    def test_session_survives_restart_and_logout_revokes_copied_cookie(self):
        self.login();token=self.client.cookies.get(COOKIE)
        with store.connection() as db:
            stored=db.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        self.assertEqual(stored,hashlib.sha256(token.encode()).hexdigest());self.assertNotEqual(stored,token)
        store.initialize()
        other=TestClient(app);other.cookies.set(COOKIE,token)
        self.assertEqual(other.get('/api/auth/session').status_code,200)
        self.assertEqual(other.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/api/summary').status_code,401);other.close()

    def test_expired_and_forged_tokens_are_rejected(self):
        self.client.cookies.set(COOKIE,'forged');self.assertEqual(self.client.get('/api/summary').status_code,401)
        self.client.cookies.clear();self.login()
        with store.connection() as db:db.execute('UPDATE auth_sessions SET expires_at=?',(int(time.time())-1,))
        self.assertEqual(self.client.get('/api/summary').status_code,401)

    def test_wrong_pin_lockout_persists_and_unknown_users_match_error(self):
        unknown=self.login(username='missing');wrong=self.login(pin='000001')
        self.assertEqual(unknown.status_code,401);self.assertEqual(unknown.json(),wrong.json())
        for _ in range(4):self.assertEqual(self.login(pin='000001').status_code,401)
        store.initialize();self.assertEqual(self.login().status_code,429)
        with store.connection() as db:db.execute('UPDATE auth_attempts SET window_start=?',(int(time.time())-901,))
        self.assertEqual(self.login().status_code,200)

    def test_regular_users_login_but_cannot_manage_accounts(self):
        self.login();created=self.client.post('/api/auth/users',json={'username':'Researcher','pin':'987654'})
        self.assertEqual(created.status_code,201,created.text);self.assertFalse(created.json()['is_admin'])
        self.assertEqual(self.client.post('/api/auth/users',json={'username':'RESEARCHER','pin':'987654'}).status_code,409)
        other=TestClient(app);self.assertEqual(self.login(other,'RESEARCHER','987654').status_code,200)
        self.assertEqual(other.get('/api/summary').status_code,200)
        for response in (other.get('/api/auth/users'),other.post('/api/auth/users',json={'username':'other','pin':'000000'}),other.patch('/api/auth/users/1',json={'pin':'999999'})):
            self.assertEqual(response.status_code,403)
        other.close()

    def test_reset_pin_and_disable_revoke_sessions(self):
        self.login();user=self.client.post('/api/auth/users',json={'username':'user','pin':'987654'}).json()
        other=TestClient(app);self.login(other,'user','987654')
        self.assertEqual(self.client.patch('/api/auth/users/'+str(user['id']),json={'pin':'222222'}).status_code,200)
        self.assertEqual(other.get('/api/summary').status_code,401)
        self.assertEqual(self.login(other,'user','987654').status_code,401)
        self.assertEqual(self.login(other,'user','222222').status_code,200)
        self.client.patch('/api/auth/users/'+str(user['id']),json={'active':False})
        self.assertEqual(other.get('/api/summary').status_code,401);self.assertEqual(self.login(other,'user','222222').status_code,401)
        self.client.patch('/api/auth/users/'+str(user['id']),json={'active':True})
        self.assertEqual(self.login(other,'user','222222').status_code,200);other.close()

    def test_pin_change_persists_and_seed_never_resets_it(self):
        self.login();token=self.client.cookies.get(COOKIE)
        wrong=self.client.post('/api/auth/pin',json={'current_pin':'000001','new_pin':'654321'})
        self.assertEqual(wrong.status_code,400)
        result=self.client.post('/api/auth/pin',json={'current_pin':self.pin,'new_pin':'654321'})
        self.assertEqual(result.status_code,200);self.assertNotIn('654321',result.text)
        self.assertFalse(initial_pin_path().exists())
        self.client.cookies.set(COOKIE,token);self.assertEqual(self.client.get('/api/summary').status_code,401)
        store.initialize();self.client.cookies.clear();self.assertEqual(self.login().status_code,401);self.assertEqual(self.login(pin='654321').status_code,200)
        self.assertEqual(self.client.patch('/api/auth/users/1',json={'active':False}).status_code,422)

    def test_cross_origin_writes_blocked_before_login_or_changes(self):
        self.assertEqual(self.client.post('/api/auth/login',headers={'Origin':'https://evil.test'},json={'username':'admin','pin':self.pin}).status_code,403)
        self.login()
        for headers in ({'Origin':'https://evil.test'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.client.post('/api/auth/logout',headers=headers).status_code,403)
        self.assertEqual(self.client.get('/api/auth/session').status_code,200)
        self.assertEqual(self.client.post('/api/auth/logout',headers={'Origin':'http://testserver'}).status_code,200)

    def test_validation_errors_do_not_echo_pins(self):
        result=self.client.post('/api/auth/login',json={'username':'admin','pin':'sensitive-invalid-value'})
        self.assertEqual(result.status_code,422);self.assertNotIn('sensitive-invalid-value',result.text)
        self.login()
        result=self.client.post('/api/auth/users',json={'username':'x','pin':'secretvalue'})
        self.assertEqual(result.status_code,422);self.assertNotIn('secretvalue',result.text)
