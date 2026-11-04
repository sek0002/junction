"""Physical destination assignment, snapshot sharing and saved planner volumes."""
from copy import deepcopy
import io
import json
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from app.assembly_plates import layout, qr_png
from app.bench_exports import assembly_sections
from app.main import app
from test_bench_exports import fixture, csv_table
import test_export_scope as scope_fixtures


class PlateLayoutTests(unittest.TestCase):
    def test_capacity_unique_wells_and_exact_calculated_transfers(self):
        assembly,settings=fixture();sections=[]
        for n in range(97):
            sections.extend(assembly_sections(assembly|{'name':f'Construct {n+1}'},settings,'BsaI'))
        before=deepcopy(sections)
        data=layout(sections,'2026-11-04','BL-'+'a'*32,'https://junction.example/exports/'+'x'*32)
        self.assertEqual([len(p['wells']) for p in data['plates']],[96,1])
        self.assertEqual(data['plates'][0]['wells'][-1]['well'],'H12')
        self.assertEqual(data['plates'][1]['wells'][0]['well'],'A1')
        self.assertNotEqual(data['plates'][0]['id'],data['plates'][1]['id'])
        self.assertIn('20261104',data['plates'][0]['id'])
        self.assertEqual(len({(r[5],r[6]) for r in data['transfers']}),97)
        for name,volume in [('Backbone',1.65),('Insert',3.3),('Master mix + reagents',4),('Water',11.05)]:
            rows=[r for r in data['transfers'] if r[3]==name]
            self.assertEqual(len(rows),97)
            self.assertTrue(all(abs(r[9]-volume)<1e-8 for r in rows))
        self.assertEqual(sections,before)
        self.assertEqual(list(dict.fromkeys(r[0] for r in data['transfers'])),['0405','0622','Reagents'])

    def test_nested_reactions_and_unknown_volumes_remain_explicit(self):
        assembly,settings=fixture();nested=deepcopy(assembly);nested['name']='Preparation'
        assembly['nested_reactions']=[nested|{'settings':settings,'enzyme':'BsmBI'}]
        assembly['reaction']['rows'][1]['volume_ul']=None
        sections=assembly_sections(assembly,settings,'BsaI')
        data=layout(sections,'2026-11-04','BL-'+'b'*32,'https://junction.example/exports/'+'x'*32)
        self.assertEqual([w['well'] for w in data['plates'][0]['wells']],['A1','A2'])
        self.assertEqual([w['enzyme'] for w in data['plates'][0]['wells']],['BsmBI','BsaI'])
        self.assertIsNone(next(r[9] for r in data['transfers'] if r[6]=='A2' and r[3]=='Insert'))

    def test_qr_has_quiet_border_and_encodes_the_download_url(self):
        from PIL import Image
        from reportlab.graphics.barcode.qrencoder import QRCode,QRErrorCorrectLevel
        url='https://junction.example/exports/'+'x'*32
        image=Image.open(io.BytesIO(qr_png(url)))
        qr=QRCode(None,QRErrorCorrectLevel.M);qr.addData(url);qr.make()
        self.assertEqual(image.size,((qr.getModuleCount()+8)*8,)*2)
        for x in range(image.width):self.assertEqual(image.getpixel((x,0)),(255,255,255))
        for y in range(qr.getModuleCount()):
            for x in range(qr.getModuleCount()):
                self.assertEqual(image.getpixel(((x+4)*8+4,(y+4)*8+4)),(0,0,0) if qr.isDark(y,x) else (255,255,255))


class SavedAssemblyExportTests(unittest.TestCase):
    setUp=scope_fixtures.AssemblyExportScopeTests.setUp
    tearDown=scope_fixtures.AssemblyExportScopeTests.tearDown

    def create(self,format='xlsx'):
        self.assertEqual(self.client.post('/api/build-list',json=self.request).status_code,200)
        response=self.client.get('/api/build-list/worksheet',params={'format':format,'export_date':'2026-11-04'})
        self.assertEqual(response.status_code,200,response.text[:200] if response.status_code!=200 else '')
        return response

    def test_excel_and_saved_zip_share_exact_worksheet_maps_and_volumes(self):
        response=self.create();url=response.headers['X-Junction-Export-URL'];book=load_workbook(io.BytesIO(response.content))
        self.assertIn('Plate map 1',book.sheetnames);self.assertEqual(len(book['Plate map 1']._images),1)
        self.assertEqual(book['Plate map 1']['A35'].hyperlink.target,url)
        self.assertEqual(book['Plate assignments']['B2'].value,'A1')
        self.assertEqual(book['Plate assignments']['C2'].value,'Selected assembly')
        rows=list(book['Well transfers'].values);self.assertEqual({r[3] for r in rows[1:]},{'Left','Right','Master mix + reagents','Water'})
        source_rows=[r for r in rows[1:] if r[4]=='insert']
        self.assertEqual({r[2] for r in source_rows},{'A1','A2'});self.assertEqual({r[6] for r in source_rows},{'A1'})
        planner=self.client.get('/api/build-list').json()['items'][0]['plan']['reaction']['rows']
        volumes={r[3]:r[9] for r in source_rows}
        for row in planner:self.assertAlmostEqual(volumes[row['name']],row['volume_ul'])
        exported=self.client.get('/api/build-list/exports').json()['items'];self.assertEqual(len(exported),1)
        self.assertEqual(exported[0]['download_url'],url)
        with TestClient(app) as anonymous:
            page=anonymous.get(url);self.assertEqual(page.status_code,200);self.assertIn('Download all',page.text)
            bundle=anonymous.get(url+'/bundle.zip');self.assertEqual(bundle.status_code,200)
            with ZipFile(io.BytesIO(bundle.content)) as archive:
                self.assertEqual(archive.read(exported[0]['worksheet']),response.content)
                manifest=json.loads(archive.read('manifest.json'));self.assertEqual(manifest['download_url'],url)
                self.assertTrue(archive.read(manifest['plates'][0]+'.png').startswith(b'\x89PNG'))
                self.assertTrue(archive.read('plate-maps.pdf').startswith(b'%PDF'))
                self.assertIn('Selected assembly',archive.read('well-transfers.csv').decode('utf-8-sig'))
            original=anonymous.get(url+'/files/'+exported[0]['worksheet']);self.assertEqual(original.content,response.content)
            self.assertEqual(anonymous.get('/api/build-list/exports').status_code,401)
            self.assertEqual(anonymous.get('/exports/'+'z'*32).status_code,404)
            self.assertEqual(anonymous.get(url+'/files/other.sqlite3').status_code,404)
            self.assertEqual(anonymous.post(url,follow_redirects=False).status_code,303)

    def test_snapshot_survives_build_changes_and_new_exports_get_new_ids(self):
        original=self.create('csv');url=original.headers['X-Junction-Export-URL']
        build=self.client.get('/api/build-list').json()['items'][0]
        self.assertEqual(self.client.patch(f'/api/build-list/{build["id"]}/settings',json={'reaction_volume_ul':30}).status_code,200)
        changed=self.client.get('/api/build-list/worksheet?format=csv')
        self.assertNotEqual(changed.headers['X-Junction-Export-URL'],url)
        meta=self.client.get('/api/build-list/exports').json()['items'];old=next(x for x in meta if x['download_url']==url)
        self.assertEqual(self.client.get(url+'/files/'+old['worksheet']).content,original.content)
        self.assertEqual(csv_table(original.content,'Plate assignments')[0]['Total µL'],'20.00')
        self.assertEqual(csv_table(changed.content,'Plate assignments')[0]['Total µL'],'30.00')

    def test_export_listing_is_private_and_linked_to_current_worksheet(self):
        saved=self.client.post('/api/worksheets',json={'scope':'build','name':'Plate worksheet','notes':''});self.assertEqual(saved.status_code,200,saved.text)
        self.create('csv');listed=self.client.get('/api/build-list/exports').json()['items'][0]
        self.assertEqual(listed['worksheet_id'],saved.json()['id']);self.assertEqual(listed['worksheet_name'],'Plate worksheet')
        created=self.client.post('/api/auth/users',json={'username':'other','pin':'123456'});self.assertEqual(created.status_code,201,created.text)
        with TestClient(app) as other:
            self.assertEqual(other.post('/api/auth/login',json={'username':'other','pin':'123456'}).status_code,200)
            self.assertEqual(other.get('/api/build-list/exports').json()['items'],[])

    def test_pdf_and_csv_include_maps_assignments_and_grouped_transfers(self):
        csv_response=self.create('csv')
        rows=csv_table(csv_response.content,'Well transfers')
        self.assertEqual({r['Destination well'] for r in rows},{'A1'})
        self.assertEqual({r['Fragment / reagent'] for r in rows},{'Left','Right','Master mix + reagents','Water'})
        pdf=self.client.get('/api/build-list/worksheet?format=pdf');self.assertEqual(pdf.status_code,200)
        pages=PdfReader(io.BytesIO(pdf.content)).pages;text='\n'.join(p.extract_text() for p in pages)
        for required in ('Plate key','Fragment metadata','JUNC-','Well transfers','Source well','Selected assembly'):
            self.assertIn(required,' '.join(text.split()))
        self.assertTrue(all(p.mediabox.width<p.mediabox.height for p in pages))


if __name__=='__main__':unittest.main()
