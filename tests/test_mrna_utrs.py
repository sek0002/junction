"""Pinned native UTR references and compatibility with existing construct components."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from app.mrna import capabilities

DATA = Path(__file__).resolve().parents[1] / 'app/data/mrna'

class UTRReferenceTests(unittest.TestCase):
    def test_native_references_and_poly_a_boundary(self):
        catalog=json.loads((DATA/'utrs.json').read_text())
        expected={('utr5','NM_000558.5'):[1,37],('utr3','NM_000558.5'):[467,577],
                  ('utr5','NM_008218.2'):[1,35],('utr3','NM_008218.2'):[465,557]}
        found={}
        for end,entries in catalog.items():
            self.assertEqual(len({x['id'] for x in entries}),len(entries))
            for entry in entries:
                self.assertRegex(entry['sequence'],r'^[ACGT]+$')
                if 'accession' not in entry:continue
                found[end,entry['accession']]=entry['region']
                self.assertEqual(len(entry['sequence']),entry['region'][1]-entry['region'][0]+1)
                self.assertEqual(hashlib.sha256(entry['sequence'].encode()).hexdigest(),entry['sha256'])
                self.assertTrue(entry['source'].startswith('https://www.ncbi.nlm.nih.gov/nuccore/'))
        self.assertEqual(found,expected)
        mouse=next(x for x in catalog['utr3'] if x.get('accession')=='NM_008218.2')
        self.assertTrue(mouse['sequence'].endswith('TAGGAAG'))
        self.assertFalse(mouse['sequence'].endswith('A'*12))

    def test_all_existing_components_remain_selectable_by_end(self):
        catalog=json.loads((DATA/'utrs.json').read_text())
        elements=json.loads((DATA/'elements.json').read_text())
        for end in ('utr5','utr3'):
            self.assertTrue({e[end] for e in elements}<={e['sequence'] for e in catalog[end]})

    def test_catalog_available_without_optional_scientific_runtime(self):
        with patch('app.mrna.capabilities_cached',return_value={'ready':False,'models':{},'message':'Offline'}):
            result=capabilities()
        self.assertFalse(result['ready'])
        self.assertEqual(set(result['utrs']),{'utr5','utr3'})
        for end in result['utrs']:
            self.assertEqual({x['accession'] for x in result['utrs'][end] if 'accession' in x},{'NM_000558.5','NM_008218.2'})
