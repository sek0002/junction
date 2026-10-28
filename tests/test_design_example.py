"""Reference exports are available before a variant table can be generated."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy

from auth_client import AuthenticatedClient as TestClient
from app.main import app
from app.exports import parse_sequence_file
from app.sequence_engine import reverse_complement
from test_design import placeholder, clean_dna


class ExampleGenBankTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB')
        path=Path(self.folder.name)/'test.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[],'genbank_files':[]}))
        self.client=TestClient(app);self.client.__enter__()
        self.sequence=clean_dna(2,600)
        self.payload=dict(name='Reference review',enzyme='BsaI',entries=[placeholder(self.sequence,[
            dict(name='Promoter',start=0,end=100,mode='constant'),
            dict(name='Cargo',start=100,end=300,mode='dynamic',variants=[dict(name='Invalid batch input',sequence='ACGN')])])],
            left_overhang='TTTG',right_overhang='ACCT',use_table=True,
            table_rows=[dict(name='',dynamic_inputs={})])

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()

    def test_example_exports_one_reference_despite_incomplete_rows_or_invalid_alternatives(self):
        before=deepcopy(self.payload)
        self.assertEqual(self.client.post('/api/design/export?format=gb',json=self.payload).status_code,422)
        response=self.client.post('/api/design/export?format=example_gb',json=self.payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('_example.gb',response.headers['Content-Disposition'])
        records=parse_sequence_file(response.text);self.assertEqual(len(records),1)
        record=records[0];self.assertEqual(record['sequence'],'TTTG'+self.sequence+'ACCT')
        features={feature['label']:feature for feature in record['features']}
        self.assertEqual((features['Cargo']['start'],features['Cargo']['end']),(104,304))
        self.assertEqual(record['sequence'][features['Cargo']['start']:features['Cargo']['end']],self.sequence[100:300])
        self.assertIn('Dynamic region',features['Cargo']['qualifiers']['note'][0])
        self.assertEqual(self.payload,before)

    def test_circular_backbone_example_has_correct_reference_regions_and_topology(self):
        bb=self.client.get('/api/design/references?enzyme=BsmBI').json()['backbones'][0]
        payload=self.payload|dict(enzyme='BsmBI',backbone_id=bb['id'],slot_id=bb['slots'][0]['id'])
        response=self.client.post('/api/design/export?format=example_gb',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        record=parse_sequence_file(response.text)[0];self.assertTrue(record['circular'])
        cargo=next(feature for feature in record['features'] if feature['label']=='Cargo')
        self.assertEqual(record['sequence'][cargo['start']:cargo['end']],self.sequence[100:300])
        self.assertTrue(any('fusion:' in feature['label'] for feature in record['features']))

    def test_reverse_displayed_insert_is_not_reversed_twice_in_example(self):
        sequence=reverse_complement(self.sequence)
        payload=self.payload|dict(entries=[placeholder(sequence,[dict(name='Cargo',start=300,end=500,mode='dynamic')])])
        payload['entries'][0]['reverse']=True
        response=self.client.post('/api/design/export?format=example_gb',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        record=parse_sequence_file(response.text)[0]
        self.assertEqual(record['sequence'],'TTTG'+sequence+'ACCT')
        cargo=next(feature for feature in record['features'] if feature['label']=='Cargo')
        self.assertEqual(record['sequence'][cargo['start']:cargo['end']],reverse_complement(self.sequence[100:300]))

    def test_bad_reference_sequence_remains_blocked(self):
        payload=self.payload|dict(entries=[placeholder('AACCGGTCTCAACCTT')])
        self.assertEqual(self.client.post('/api/design/export?format=example_gb',json=payload).status_code,422)

    def test_free_ends_and_adjacent_insert_offsets_are_preserved(self):
        seq=self.sequence
        payload=self.payload|dict(left_overhang='',right_overhang='',entries=[
            placeholder(seq[:250],[dict(name='First',start=40,end=180,mode='constant')],key='first'),
            placeholder(seq[250:],[dict(name='Second',start=50,end=180,mode='dynamic')],key='second')])
        response=self.client.post('/api/design/export?format=example_gb',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        record=parse_sequence_file(response.text)[0];self.assertEqual(record['sequence'],seq)
        second=next(feature for feature in record['features'] if feature['label']=='Second')
        self.assertEqual((second['start'],second['end']),(300,430))


if __name__=='__main__':unittest.main()
