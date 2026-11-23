"""BsmBI preservation is explicit and never changes normal assembly QC."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from auth_client import AuthenticatedClient
from app.main import app
from app.design_engine import design
from app.design_table import table_design
from app.sequence_engine import digest_fragment, assemble
from test_design import placeholder, clean_dna

NESTED = 'AACCGTCTCAAGTCCGAGACGTTAA'


class NestedDesignTests(unittest.TestCase):
    def test_override_preserves_both_orientations_and_normal_qc_stays_strict(self):
        for enzyme in ('BsaI', 'BsmBI', 'BsmBI + BsaI'):
            with self.subTest(enzyme=enzyme):
                args=dict(enzyme=enzyme,left_overhang='TTTG',right_overhang='ACCT',avoid_sites=['BsmBI'])
                blocked=design([placeholder(NESTED)],**args)
                self.assertFalse(blocked['valid']);self.assertTrue(blocked['requires_bsmbi_override'])
                allowed=design([placeholder(NESTED)],**args,allow_internal_bsmbi=True)
                self.assertTrue(allowed['valid'],allowed['errors']);self.assertTrue(allowed['bsmbi_override'])
                self.assertEqual(allowed['assembly']['sequence'],'TTTG'+NESTED+'ACCT')
                self.assertIn('BsmBI override',' '.join(allowed['warnings']))
                self.assertEqual(allowed['generated'][0]['target'],NESTED)
                if enzyme!='BsaI':
                    self.assertFalse(allowed['assembly']['single_reaction_valid'])
                    self.assertFalse(digest_fragment(allowed['generated'][0]['sequence'],enzyme)['valid'])
                    self.assertFalse(assemble(allowed['generated'],enzyme,circular=False)['valid'])

    def test_other_excluded_sites_and_junction_errors_still_block(self):
        for sequence,avoid in [(NESTED+'GGTCTCAA',['BsmBI']), (NESTED+'AAGCTT',['BsmBI','HindIII'])]:
            result=design([placeholder(sequence)],'BsaI',left_overhang='TTTG',right_overhang='ACCT',avoid_sites=avoid,allow_internal_bsmbi=True)
            self.assertFalse(result['valid']);self.assertTrue(result['errors'])
        bad=dict(id='old',kind='fragment',fragment_id=1,name='Bad end',sequence='GGTCTCATTGCAACCAAACCTCGAGACC')
        result=design([bad,placeholder(NESTED)],left_overhang='TTTG',right_overhang='TGCC',allow_internal_bsmbi=True)
        self.assertFalse(result['valid']);self.assertIn('expected fixed',' '.join(result['errors']))

    def test_table_rows_and_individual_variants_keep_sites_without_changing_constant_ends(self):
        sequence=clean_dna(2)
        for table in (False,True):
            sections=[dict(name='Cargo',start=140,end=270,mode='dynamic',variants=[] if table else [dict(name='Nested',sequence=NESTED)])]
            for flag in (False,True):
                base=design([placeholder(sequence,sections)],'BsmBI',left_overhang='TTTG',right_overhang='ACCT',allow_internal_bsmbi=flag)
                result=table_design(base,[dict(name='Nested',dynamic_inputs={'insert:140:270':NESTED})],'BsmBI',allow_internal_bsmbi=flag) if table else base
                self.assertEqual(result['valid'],flag,result['errors']);self.assertTrue(result['requires_bsmbi_override'])
                if flag:
                    products=[r['sequence'] for r in result['assemblies']]
                    self.assertIn('TTTG'+sequence[:140]+NESTED+sequence[270:]+'ACCT',products)


class NestedDesignApiTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        path=Path(self.folder.name)/'nested.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[],'genbank_files':[]}))
        self.client=AuthenticatedClient(app);self.client.__enter__()
        self.body=dict(name='Nested test',enzyme='BsmBI',entries=[placeholder(NESTED)],left_overhang='TTTG',right_overhang='ACCT')

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def test_generation_and_export_require_explicit_override_and_exports_keep_warning(self):
        response=self.client.post('/api/design/preview?generate=true',json=self.body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['valid']);self.assertTrue(response.json()['requires_bsmbi_override'])
        self.assertEqual(self.client.post('/api/design/export?format=csv',json=self.body).status_code,422)
        self.body['allow_internal_bsmbi']=True
        generated=self.client.post('/api/design/preview?generate=true',json=self.body).json()
        self.assertTrue(generated['valid'],generated['errors'])
        exported=self.client.post('/api/design/export?format=csv',json=self.body)
        self.assertEqual(exported.status_code,200,exported.text)
        row=next(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
        self.assertEqual(row['Target sequence'],NESTED);self.assertIn('preserved',row['BsmBI override'])
        gb=self.client.post('/api/design/export?format=gb',json=self.body)
        self.assertEqual(gb.status_code,200,gb.text);self.assertIn('BsmBI override',gb.text)
