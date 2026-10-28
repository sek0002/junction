"""New donors must round-trip exactly through the production digest engine."""
import csv
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest

from auth_client import AuthenticatedClient as TestClient
from app.design_engine import design, scan_type_ii, fusion_key
from app.sequence_engine import digest_fragment, restriction_sites, reverse_complement
from app.main import app
from app.exports import parse_sequence_file


def clean_dna(seed=7, length=400):
    rng = random.Random(seed)
    while True:
        sequence = ''.join(rng.choice('ACGT') for _ in range(length))
        if not any(site['enzyme'] in ('BsaI','BsmBI') for site in restriction_sites('TTTG'+sequence+'ACCT')):
            return sequence


def placeholder(sequence, sections=None, key='insert'):
    return dict(id=key, kind='placeholder', name=key, sequence=sequence, sections=sections or [])


def donor(left, target, right):
    return 'GGTCTCA'+left+target+right+'CGAGACC'


class DesignEngineTests(unittest.TestCase):
    def test_native_overlaps_preserve_exact_sequence_for_both_enzymes(self):
        for enzyme in ('BsaI','BsmBI','BsmBI + BsaI'):
            for seed in range(15):
                sequence=clean_dna(seed)
                sections=[dict(name='Middle',start=120,end=260)]
                result=design([placeholder(sequence,sections)],enzyme,left_overhang='TTTG',right_overhang='ACCT')
                self.assertTrue(result['valid'],result['errors'])
                self.assertEqual(result['assembly']['sequence'],'TTTG'+sequence+'ACCT')
                self.assertEqual(len(result['generated']),3)
                for row in result['generated']:
                    parsed=digest_fragment(row['sequence'],enzyme)
                    self.assertTrue(parsed['valid'],parsed['errors'])
                    self.assertEqual(parsed['target'],row['target'])
                labels=['TTTG','ACCT']+[b['overhang'] for b in result['boundary_shifts']]
                self.assertEqual(len({fusion_key(label) for label in labels}),len(labels))
                self.assertFalse(any(label==reverse_complement(label) for label in labels))

    def test_free_ends_use_existing_terminal_bases_without_adding_sequence(self):
        sequence=clean_dna(5)
        result=design([placeholder(sequence)])
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['assembly']['sequence'],sequence)

    def test_adjacent_placeholders_share_one_native_junction(self):
        sequence=clean_dna(6)
        result=design([placeholder(sequence[:180],key='A'),placeholder(sequence[180:],key='B')],left_overhang='TTTG',right_overhang='ACCT')
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['assembly']['sequence'],'TTTG'+sequence+'ACCT')
        self.assertEqual(len(result['generated']),2)

    def test_strict_conflicting_boundary_fails_and_window_can_rescue_it(self):
        sequence=clean_dna(3)
        sequence=sequence[:100]+'TTTG'+sequence[104:]
        entry=placeholder(sequence,[dict(name='A',start=0,end=100)])
        failed=design([entry],left_overhang='TTTG',right_overhang='ACCT',window=0)
        self.assertFalse(failed['valid']);self.assertIn('non-conflicting',' '.join(failed['errors']))
        fixed=design([entry],left_overhang='TTTG',right_overhang='ACCT',window=20)
        self.assertTrue(fixed['valid'],fixed['errors'])
        self.assertNotEqual(fixed['boundary_shifts'][0]['actual'],100)
        self.assertEqual(fixed['assembly']['sequence'],'TTTG'+sequence+'ACCT')

    def test_dynamic_regions_stay_in_one_replaceable_fragment_with_constant_overhangs(self):
        sequence=clean_dna(2)
        sections=[dict(name='Promoter',start=0,end=140,mode='constant'),dict(name='Cargo',start=140,end=270,mode='dynamic')]
        result=design([placeholder(sequence,sections)],left_overhang='TTTG',right_overhang='ACCT')
        self.assertTrue(result['valid'],result['errors'])
        dynamic=[row for row in result['generated'] if row['region_mode']=='dynamic']
        self.assertEqual(len(dynamic),1)
        self.assertIn(sequence[140:270],dynamic[0]['target'])
        self.assertTrue(all(not (b['actual']<270 and b['actual']+4>140) for b in result['boundary_shifts']))
        self.assertEqual(result['assembly']['sequence'],'TTTG'+sequence+'ACCT')

    def test_pasted_dynamic_variants_preserve_constant_flanks_and_fragment_order(self):
        sequence=clean_dna(2)
        sections=[dict(name='Cargo',start=140,end=270,mode='dynamic',variants=[dict(name='Short',sequence='AACCAAGGTT'),dict(name='Long',sequence=clean_dna(9,220))])]
        result=design([placeholder(sequence,sections)],left_overhang='TTTG',right_overhang='ACCT')
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(len(result['assemblies']),3)
        expected=['TTTG'+sequence+'ACCT']+['TTTG'+sequence[:140]+variant['sequence']+sequence[270:]+'ACCT' for variant in sections[0]['variants']]
        self.assertEqual([item['sequence'] for item in result['assemblies']],expected)
        dynamic=[row for row in result['generated'] if row['region_mode']=='dynamic']
        self.assertEqual(len(dynamic),3)
        self.assertEqual(len({(row['left_overhang'],row['right_overhang']) for row in dynamic}),1)
        self.assertTrue(all(digest_fragment(row['sequence'],'BsaI')['valid'] for row in dynamic))

    def test_every_dynamic_combination_is_checked_and_active_sites_block_variants(self):
        sequence=clean_dna(2,600)
        sections=[dict(name='A',start=100,end=200,mode='dynamic',variants=[dict(name='A2',sequence='AACCGGTTAA')]),dict(name='B',start=350,end=450,mode='dynamic',variants=[dict(name='B2',sequence='TTGGAACCAA')])]
        result=design([placeholder(sequence,sections)],left_overhang='TTTG',right_overhang='ACCT')
        self.assertTrue(result['valid'],result['errors']);self.assertEqual(len(result['assemblies']),4)
        sections[0]['variants'][0]['sequence']='AAAGGTCTCAA'
        blocked=design([placeholder(sequence,sections)],left_overhang='TTTG',right_overhang='ACCT')
        self.assertFalse(blocked['valid']);self.assertIn('BsaI',' '.join(blocked['errors']))

    def test_dynamic_regions_without_constant_junction_flanks_do_not_mutate_dna(self):
        sequence=clean_dna(2)
        result=design([placeholder(sequence,[dict(name='A',start=0,end=200,mode='dynamic'),dict(name='B',start=200,end=400,mode='dynamic')])],left_overhang='TTTG',right_overhang='ACCT')
        self.assertFalse(result['valid']);self.assertEqual(result['generated'],[])
        self.assertIn('constant flanks',' '.join(result['errors']))

    def test_existing_fragment_orientation_and_internal_sites_are_checked(self):
        sequence=clean_dna(10,200)
        existing=donor('TTTG','AACCAA','ACCT')
        fixed=dict(id='old',kind='fragment',fragment_id=1,name='Existing',sequence=reverse_complement(existing),reverse=True)
        result=design([fixed,placeholder(sequence)],left_overhang='TTTG',right_overhang='TGCC')
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['assembly']['sequence'],'TTTG'+'AACCAA'+'ACCT'+sequence+'TGCC')
        cut=design([placeholder('AACCGGTCTCAACCAA')],left_overhang='TTTG',right_overhang='ACCT')
        self.assertFalse(cut['valid']);self.assertIn('BsaI',' '.join(cut['errors']))

    def test_common_type_ii_panel_scans_both_orientations_and_exclusions(self):
        sites=scan_type_ii('CCCGAGACGAAAGAATTCGGGAAGCTT')
        self.assertTrue(any(s['enzyme']=='BsmBI' and s['strand']==-1 for s in sites))
        self.assertEqual(sum(s['enzyme']=='HindIII' for s in sites),1)
        result=design([placeholder('CCGAATTCAAACCGG')],left_overhang='TTTG',right_overhang='ACCT',avoid_sites=['EcoRI'])
        self.assertFalse(result['valid'])

    def test_partial_preview_and_invalid_inputs_are_not_exportable(self):
        for sequence in ('','ACGTN','ACGT;DROP'):
            result=design([placeholder(sequence)],generate=False)
            self.assertFalse(result['complete']);self.assertFalse(result['valid'])
        result=design([placeholder('>example\n'+clean_dna())],generate=False)
        self.assertTrue(result['complete']);self.assertIsNone(result['assembly'])


class DesignAPITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB')
        path=Path(self.folder.name)/'test.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[],'genbank_files':[]}))
        self.client=TestClient(app);self.client.__enter__()
        self.payload=dict(name='Design test',enzyme='BsaI',entries=[placeholder(clean_dna(),[dict(name='Cargo',start=100,end=260,mode='dynamic')])],left_overhang='TTTG',right_overhang='ACCT')

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()

    def test_installed_backbones_and_native_fragment_exports(self):
        refs=self.client.get('/api/design/references?enzyme=BsmBI').json()
        self.assertEqual(len(refs['backbones']),3)
        self.assertTrue(all(row['slots'] for row in refs['backbones']))
        preview=self.client.post('/api/design/preview?generate=true',json=self.payload)
        self.assertEqual(preview.status_code,200,preview.text);self.assertTrue(preview.json()['valid'],preview.json()['errors'])
        response=self.client.post('/api/design/export?format=csv',json=self.payload)
        self.assertEqual(response.status_code,200,response.text)
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertTrue(rows);self.assertIn('dynamic',{row['Region'] for row in rows})
        fasta=self.client.post('/api/design/export?format=fasta',json=self.payload)
        self.assertEqual(fasta.status_code,200);self.assertEqual(fasta.text.count('>'),len(rows))
        gb=self.client.post('/api/design/export?format=gb',json=self.payload)
        self.assertEqual(gb.status_code,200,gb.text)
        self.assertEqual(parse_sequence_file(gb.text)[0]['sequence'],'TTTG'+clean_dna()+'ACCT')

    def test_variant_genbank_export_contains_all_ordered_products(self):
        payload=self.payload.copy()
        payload['name']='Long_design_name_for_the_exported_variant_records'
        payload['entries']=[placeholder(clean_dna(),[dict(name='Cargo',start=100,end=260,mode='dynamic',variants=[dict(name='Short',sequence='AACCTTGGAACC')])])]
        expected=self.client.post('/api/design/preview?generate=true',json=payload).json()
        self.assertTrue(expected['valid'],expected['errors'])
        response=self.client.post('/api/design/export?format=gb',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        records=parse_sequence_file(response.text)
        self.assertEqual(len(records),2)
        self.assertEqual(len({record['name'] for record in records}),2)
        self.assertEqual([record['sequence'] for record in records],[item['sequence'] for item in expected['assemblies']])

    def test_backbone_context_is_used_and_invalid_designs_cannot_download(self):
        bb=self.client.get('/api/design/references?enzyme=BsmBI').json()['backbones'][0]
        request=self.payload|dict(enzyme='BsmBI',backbone_id=bb['id'],slot_id=bb['slots'][0]['id'])
        response=self.client.post('/api/design/preview?generate=true',json=request)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['valid'],response.json()['errors']);self.assertTrue(response.json()['assembly']['circular'])
        response=self.client.post('/api/design/export',json=self.payload|dict(entries=[placeholder('GGTCTCAAAAAA')]))
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.post('/api/design/preview',json=self.payload|dict(excluded_overhangs=['AAAAA'])).status_code,422)

    def test_read_only_users_can_design_and_private_sandbox_does_not_change_inventory(self):
        self.client.get('/api/summary')
        created=self.client.post('/api/auth/users',json=dict(username='designer',pin='654321',role='user',can_upload=False,can_edit=False,can_archive=False,can_manage_rules=False))
        self.assertEqual(created.status_code,201,created.text)
        before=self.client.get('/api/summary').json()
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'designer','pin':'654321'}).status_code,200)
        result=self.client.post('/api/design/preview?generate=true',json=self.payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.post('/api/design/export?format=fasta',json=self.payload).status_code,200)
        state={'design':{'activeId':'one','designs':[self.payload|{'id':'one'}]}}
        self.assertEqual(self.client.put('/api/workspace',json={'data':state}).status_code,200)
        self.assertEqual(self.client.get('/api/workspace').json()['data'],state)
        self.assertEqual(self.client.get('/api/summary').json(),before)


if __name__=='__main__':unittest.main()
