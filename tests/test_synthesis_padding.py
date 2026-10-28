"""Synthesis padding must preserve donor digestion and export semantics."""
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest

from openpyxl import load_workbook
from auth_client import AuthenticatedClient as TestClient
from app.main import app
from app.synthesis_padding import (MOTIFS, synthesis_padding, padding_is_clean,
                                   gc_windows_ok, apply_synthesis_padding)
from app.design import DesignRequest
from app.design_exports import fragment_rows
from app.sequence_engine import digest_fragment
from test_design import clean_dna, placeholder


class PaddingTests(unittest.TestCase):
    def test_lengths_and_composition_across_short_fragment_sizes(self):
        rng = random.Random(93)
        for n in range(1, 302):
            source = ''.join(rng.choice('ACGT') for _ in range(n))
            with self.subTest(length=n):
                padding = synthesis_padding(source)
                self.assertEqual(len(source + padding), max(n, 300))
                self.assertEqual(padding, synthesis_padding(source))
                gc = sum(base in 'GC' for base in padding)
                self.assertLessEqual(abs(gc - len(padding) / 2), .5)
                self.assertTrue(gc_windows_ok(padding))
                self.assertTrue(padding_is_clean(source, padding))
                for motif in MOTIFS:
                    # Independent scan: no forbidden site may use any added base.
                    for start in range(max(0, n-len(motif)+1), len(source+padding)-len(motif)+1):
                        self.assertNotEqual((source+padding)[start:start+len(motif)], motif)

    def test_every_motif_orientation_and_boundary_split_is_checked(self):
        for motif in MOTIFS:
            for split in range(1, len(motif)):
                self.assertFalse(padding_is_clean(motif[:split], motif[split:]), (motif,split))
            self.assertFalse(padding_is_clean('AC', motif))
        self.assertTrue(padding_is_clean('GGTCTC', 'AT'))  # intentional pre-existing adapter
        self.assertFalse(padding_is_clean('AAAA', 'A'))
        self.assertFalse(padding_is_clean('C', 'GGGGG'))
        self.assertTrue(padding_is_clean('AAAAA', 'T'))

    def test_source_validation_and_existing_sites_preserved(self):
        for invalid in ('', 'ACGN', 'acgt', 'A C'):
            with self.assertRaises(ValueError):
                synthesis_padding(invalid)
        for tail in ('A'*7, 'T'*7, 'G'*7, 'C'*7, *MOTIFS):
            source = 'A' * (299-len(tail)) + tail
            result = source + synthesis_padding(source)
            self.assertEqual(result[:299], source)
            self.assertEqual(len(result), 300)
        self.assertEqual(synthesis_padding('A'*300), '')
        self.assertEqual(synthesis_padding('G'*301), '')

    def test_pseudorandom_padding_varies_with_original_fragment(self):
        self.assertNotEqual(synthesis_padding('ACGT'*20), synthesis_padding('TGCA'*20))
        self.assertFalse(DesignRequest().make_twist_compatible)


class PaddingAPITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.old = os.environ.get('GOLDEN_GATE_DB')
        path = Path(self.folder.name) / 'test.sqlite3'
        os.environ['GOLDEN_GATE_DB'] = str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[], 'genbank_files':[]}))
        self.client = TestClient(app)
        self.client.__enter__()
        self.payload = dict(name='Padded donors', enzyme='BsaI',
                            entries=[placeholder(clean_dna(7,100))],
                            left_overhang='TTTG', right_overhang='ACCT')
        self.base = self.generate(self.payload)

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.old is None:
            os.environ.pop('GOLDEN_GATE_DB',None)
        else:
            os.environ['GOLDEN_GATE_DB'] = self.old
        self.folder.cleanup()

    def generate(self,payload):
        response = self.client.post('/api/design/preview?generate=true',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()
        self.assertTrue(result['valid'],result['errors'])
        return result

    def test_default_off_and_padded_preview_preserve_assembly_and_digestion(self):
        off = self.generate(self.payload | {'make_twist_compatible':False})
        self.assertEqual(off,self.base)
        for enzyme,left,right in [('BsaI','BsaI','BsaI'),('BsmBI','BsmBI','BsmBI'),
                                  ('BsmBI + BsaI','BsmBI','BsaI'),('BsmBI + BsaI','BsaI','BsmBI')]:
            payload = self.payload | dict(enzyme=enzyme,left_adapter_enzyme=left,right_adapter_enzyme=right)
            base = self.generate(payload)
            padded = self.generate(payload | {'make_twist_compatible':True})
            self.assertEqual(padded['assemblies'],base['assemblies'])
            a,b = base['generated'][0],padded['generated'][0]
            self.assertEqual(b['length'],300)
            self.assertEqual(b['full_sequence'],a['full_sequence']+b['synthesis_padding'])
            for field in ('target_sequence','target','target_length','retained_sequence','five_prime_sequence','three_prime_sequence'):
                self.assertEqual(a[field],b[field],field)
            digested = digest_fragment(b['full_sequence'],enzyme)
            self.assertTrue(digested['valid'],digested['errors'])
            self.assertEqual(digested['target'],a['target'])
            self.assertEqual(digested['left_overhang'],a['left_overhang'])
            self.assertEqual(digested['right_overhang'],a['right_overhang'])
            self.assertEqual(a['sites'],b['sites'])
            again = deepcopy(padded)
            apply_synthesis_padding(again)
            self.assertEqual(again,padded)

    def test_adapter_free_export_and_long_fragments(self):
        for size in (100,292,300,400):
            payload = self.payload | dict(entries=[placeholder(clean_dna(7,size))],
                                          include_re_sites=False,make_twist_compatible=True)
            result = self.generate(payload)
            row = result['generated'][0]
            self.assertEqual(row['unpadded_full_sequence'],'TTTG'+clean_dna(7,size)+'ACCT')
            self.assertEqual(row['length'],max(size+8,300))
            self.assertEqual(row['padding_length'],max(0,300-size-8))

    def test_all_export_formats_and_unpadded_metadata(self):
        payload = self.payload | {'make_twist_compatible':True}
        result = self.generate(payload)
        expected = result['generated'][0]
        for fmt in ('csv','xlsx','fasta','target_fasta','assemblies_csv','gb'):
            response = self.client.post('/api/design/export?format='+fmt,json=payload)
            self.assertEqual(response.status_code,200,response.text[:200] if fmt!='xlsx' else '')
            if fmt=='csv':
                rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
                self.assertEqual(rows[0]['Full sequence'],expected['full_sequence'])
                self.assertEqual(rows[0]['3′ padding sequence'],expected['synthesis_padding'])
                self.assertEqual(int(rows[0]['3′ padding length nt']),expected['padding_length'])
                self.assertEqual(rows[0]['Unpadded full sequence'],self.base['generated'][0]['full_sequence'])
            elif fmt=='xlsx':
                wb=load_workbook(io.BytesIO(response.content))
                values=list(wb['Fragments'].values)
                row=dict(zip(values[0],values[1]))
                self.assertEqual(row['Full sequence'],expected['full_sequence'])
                self.assertEqual(row['Full length nt'],300)
                self.assertEqual(row['3′ padding length nt'],expected['padding_length'])
                self.assertEqual(row['Target sequence'],self.base['generated'][0]['target_sequence'])
                wb.close()
            elif fmt in ('fasta','target_fasta'):
                sequence=''.join(response.text.splitlines()[1:])
                field='full_sequence' if fmt=='fasta' else 'target_sequence'
                self.assertEqual(sequence,expected[field])
            else:
                off=self.client.post('/api/design/export?format='+fmt,json=self.payload)
                self.assertEqual(response.content,off.content)
        self.assertNotIn('3′ padding sequence',fragment_rows(self.base)[0])

    def test_checkbox_persists_and_invalid_design_still_blocks_export(self):
        state={'design':{'activeId':'one','designs':[self.payload|dict(id='one',make_twist_compatible=True)]}}
        self.assertEqual(self.client.put('/api/workspace',json={'data':state}).status_code,200)
        self.assertEqual(self.client.get('/api/workspace').json()['data'],state)
        payload=self.payload|dict(make_twist_compatible=True,entries=[placeholder('GGTCTCAAAA')])
        self.assertEqual(self.client.post('/api/design/export',json=payload).status_code,422)


if __name__ == '__main__':
    unittest.main()
