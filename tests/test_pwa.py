"""Install metadata, icon integrity and root service-worker scope."""
import io
import json
from pathlib import Path
import unittest
from auth_client import AuthenticatedClient as TestClient
import os
import tempfile
from app import database as store
from PIL import Image
from app.main import app


class PwaTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'test.sqlite3')
        store.initialize()
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def test_loading_markup_uses_toast_only_for_worksheet_navigation(self):
        for url,mode in [('/', 'splash'),('/?instance=123', 'splash'),('/?worksheet=123', 'worksheet')]:
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertIn('data-loading="'+mode+'"',response.text)
            self.assertNotIn('__JUNCTION_LOADING_MODE__',response.text)
            self.assertIn('id="worksheet-load-status"',response.text)
            self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_manifest_can_install_from_root_and_has_real_icon_sizes(self):
        response=self.client.get('/manifest.webmanifest')
        self.assertEqual(response.status_code,200)
        self.assertIn('application/manifest+json',response.headers['content-type'])
        manifest=response.json()
        self.assertEqual((manifest['id'],manifest['scope'],manifest['start_url'],manifest['display']),('/','/','/#home','standalone'))
        self.assertEqual({i['sizes'] for i in manifest['icons'] if i['purpose']=='any'},{'192x192','512x512'})
        for icon in manifest['icons']:
            image=Image.open(io.BytesIO(self.client.get(icon['src']).content))
            self.assertEqual('x'.join(map(str,image.size)),icon['sizes'])
            if icon['purpose']=='any':
                self.assertEqual(image.mode,'RGBA');self.assertEqual(image.getpixel((0,0))[3],0)
            else:
                self.assertEqual(image.convert('RGBA').getpixel((0,0))[3],255)

    def test_home_uses_transparent_vector_install_links_and_apple_icon(self):
        response=self.client.get('/')
        self.assertEqual(response.headers['cache-control'],'no-store')
        for expected in ['rel="manifest"','apple-touch-icon','mobile-web-app-capable','id="install-app"','id="install-dialog"','/static/assets/junction-mark-v4.svg','/static/pwa.js?v=1']:
            self.assertIn(expected,response.text)
        logo=Image.open(io.BytesIO(self.client.get('/static/assets/junction-mark-v4-4096.png').content))
        self.assertEqual(logo.size,(4096,4096));self.assertEqual(logo.mode,'RGBA')
        self.assertEqual(logo.getpixel((0,0))[3],0);self.assertEqual(logo.getpixel((2048,2048))[3],0)

    def test_worker_scope_and_offline_screen_are_updatable_and_available(self):
        response=self.client.get('/service-worker.js')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['service-worker-allowed'],'/')
        self.assertEqual(response.headers['cache-control'],'no-cache')
        self.assertIn('application/javascript',response.headers['content-type'])
        offline=self.client.get('/static/offline.html')
        self.assertEqual(offline.status_code,200);self.assertIn('Reconnect to the Junction server',offline.text)
