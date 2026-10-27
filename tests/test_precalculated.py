"""Source plans seed once; new uploads and subsequent edits retain their rules."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from auth_client import AuthenticatedClient as TestClient
from app import database as store
from app.imports import import_plate,parse_plate,read_sheet
from app.inventory import inventory_records,reset_records
from app.precalculated import precalculated_rows
from app.main import app

ROOT=Path(__file__).resolve().parents[1]


def source(plate='pSHPs0101TEST',water=10,mass=9.9,use=.99):
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['Name','Plate ID','Well','Sequence','Yield (ng)','Conc (ng/uL)','H2O','Mass (0.05pmol)','Volume'])
    writer.writerow(['Source fragment',plate,'A1','ACGT'*75,100,10,water,mass,use])
    return stream.getvalue().encode()


class PrecalculatedTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        self.db=Path(self.folder.name)/'test.sqlite3';os.environ['GOLDEN_GATE_DB']=str(self.db)
        self.db.with_suffix('.sources.json').write_text('{"plate_files":[],"genbank_files":[]}')
        store.initialize()

    def tearDown(self):
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def test_two_csv_tables_use_their_own_column_positions(self):
        content=source()+b'\n\nPlate ID,Name,Well,Sequence,Conc (ng/uL),H2O,Yield (ng),Volume,Mass (0.05pmol)\npSHPs0202TEST,Second,B2,'+b'ACGT'*75+b',20,15,300,0.495,9.9\n'
        rows,audit=precalculated_rows(content,'combined.csv')
        self.assertEqual(len(rows),2);self.assertEqual(rows[1]['plate_id'],'pSHPs0202TEST')
        self.assertEqual(rows[1]['yield_ng'],300);self.assertEqual(rows[1]['stock_ng_ul'],20)
        self.assertEqual(rows[1]['resuspension_ul'],15);self.assertTrue(all(not a['corrections'] for a in audit))

    def test_existing_dna_keeps_its_id_and_receives_source_defaults_once(self):
        initial=b'Name,Plate ID,Well,Sequence,Yield ng\nSource fragment,pSHPs0101TEST,A1,'+b'ACGT'*75+b',100\n'
        import_plate(initial,'old.csv');identifier=store.fragments()[0]['id']
        result=import_plate(source(),'initial.csv',precalculated=True)
        self.assertEqual((result['count'],result['updated']),(0,1))
        part=store.get_fragment(identifier);self.assertEqual(part['stock_ng_ul'],10);self.assertEqual(part['default_resuspension_ul'],10)
        client=TestClient(app);changed=client.patch('/api/fragments/'+str(identifier),json={'stock_ng_ul':20})
        self.assertEqual(changed.status_code,200,changed.text)
        import_plate(source(),'initial.csv',precalculated=True)
        self.assertEqual(store.get_fragment(identifier)['stock_ng_ul'],20)
        reset_records([identifier]);part=store.get_fragment(identifier)
        self.assertEqual(part['stock_ng_ul'],10);self.assertEqual(part['resuspension_ul'],10)
        self.assertEqual(part['yield_ng'],100);self.assertTrue(part['stock_saved'])
        self.assertEqual(inventory_records([part])[0]['default_stock_ng_ul'],10)

    def test_future_uploads_ignore_initial_only_conc_h2o_and_use_defaults(self):
        client=TestClient(app)
        result=client.post('/api/uploads/plate?no_backbone=true',files={'file':('future.csv',source('New plate'),'text/csv')})
        self.assertEqual(result.status_code,200,result.text)
        part=store.fragments()[0];self.assertFalse(part['stock_saved']);self.assertIsNone(part['default_stock_ng_ul'])
        row=inventory_records([part])[0]
        self.assertFalse(row['saved']);self.assertNotEqual(row['stock_ng_ul'],10)
        self.assertLess(row['resuspension_ul'],100);self.assertGreaterEqual(row['input_volume_ul'],1);self.assertLessEqual(row['input_volume_ul'],5)

    def test_stale_arithmetic_is_reported_and_stock_plan_is_corrected(self):
        rows,audit=precalculated_rows(source(water=99,mass=12,use=4),'stale.csv')
        self.assertEqual(rows[0]['resuspension_ul'],10)
        self.assertEqual({c['field'] for c in audit[0]['corrections']},{'H2O','Mass (0.05pmol)','Volume'})
        self.assertAlmostEqual(audit[0]['target_ng'],9.9);self.assertAlmostEqual(audit[0]['use_ul'],.99)

    def test_missing_cached_values_reject_import_without_partial_rows(self):
        data=source().replace(b',100,10,10,9.9,0.99',b',100,10,,9.9,0.99')
        with self.assertRaisesRegex(ValueError,'recalculate and save'):
            import_plate(data,'missing.csv',precalculated=True)
        self.assertEqual(store.fragments(),[])

    def test_initial_upgrade_preserves_an_archived_plate(self):
        initial=b'Name,Plate ID,Well,Sequence,Yield ng\nSource fragment,pSHPs0101TEST,A1,'+b'ACGT'*75+b',100\n'
        import_plate(initial,'old.csv');identifier=store.fragments()[0]['id']
        store.move_to_bin([],[],plate_ids=['pSHPs0101TEST'])
        result=import_plate(source(),'initial.csv',precalculated=True)
        self.assertEqual(result['updated'],1)
        self.assertEqual(store.fragments(),[])
        with store.connection() as db:
            row=db.execute('SELECT stock_ng_ul FROM fragments WHERE id=?',(identifier,)).fetchone()
            self.assertEqual(row['stock_ng_ul'],10)
            self.assertIsNotNone(db.execute('SELECT archived_at FROM plates').fetchone()['archived_at'])

    def test_real_strict_workbook_and_all_initial_values_verify(self):
        manifest=json.loads((ROOT/'data/golden_gate.sources.json').read_text());checks=[]
        for filename in manifest['precalculated_plate_files']:
            rows,audit=precalculated_rows((ROOT/'data'/filename).read_bytes(),Path(filename).name)
            checks+=audit
            self.assertTrue(rows)
        self.assertEqual(len(checks),173);self.assertTrue(all(not row['corrections'] for row in checks))
        self.assertEqual(len({r['plate_id'] for r in checks}),6)
        self.assertEqual(sum(bool(r['warnings']) for r in checks),42)
        strict=next(n for n in manifest['precalculated_plate_files'] if '0711' in n)
        self.assertEqual(len(read_sheet((ROOT/'data'/strict).read_bytes(),Path(strict).name)),22)

    def test_real_initial_defaults_restart_and_reset_without_resurrecting_archives(self):
        self.db.with_suffix('.sources.json').unlink()
        with TestClient(app) as client:
            parts=store.fragments();self.assertEqual(len(parts),218)
            self.assertEqual(sum(bool(p['stock_saved']) for p in parts),173)
            f1=next(p for p in parts if p['name']=='F1');identifier=f1['id']
            self.assertEqual(f1['stock_ng_ul'],40);self.assertAlmostEqual(f1['resuspension_ul'],43.575)
            client.patch('/api/fragments/'+str(identifier),json={'stock_ng_ul':41})
        with TestClient(app) as restarted:
            self.assertEqual(store.get_fragment(identifier)['stock_ng_ul'],41)
            reset_records([identifier]);self.assertEqual(store.get_fragment(identifier)['stock_ng_ul'],40)
            recipe=next(r for r in restarted.get('/api/recipes').json() if r['name']=='pIVT_V2')
            result=restarted.post('/api/assemblies/preview',json={'name':'Verify source stocks','enzyme':'BsaI','fragment_ids':recipe['no_backbone_fragment_ids'],'settings':{'planner_stock_mode':'saved','assume_target_stock':False}})
            self.assertEqual(result.status_code,200,result.text)
            row=next(r for r in result.json()['reaction']['rows'] if r['id']==identifier)
            self.assertEqual(row['concentration_ng_ul'],40);self.assertAlmostEqual(row['volume_ul'],1.4916)
