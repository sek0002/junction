"""Uploaded GenBank annotations survive comparison, restore and export."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook
from auth_client import AuthenticatedClient
from app import database as store
from app.main import app
from app.exports import genbank_bytes
from test_comparison import sequence


class CodingApiTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        path=Path(self.folder.name)/'coding.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text('{"plate_files":[],"genbank_files":[]}')
        self.client=AuthenticatedClient(app);self.client.__enter__()
        self.reference=sequence(150)+'ATGAAAGGGTAA'+sequence(170)
        self.query=sequence(150)+'ATGGAAGGGTAA'+sequence(170)
        store.save_plasmid('Coding reference',self.reference,circular=False)
        self.feature={'type':'CDS','label':'Uploaded reporter','raw_location':'151..162','qualifiers':{'codon_start':['1'],'transl_table':['1']}}

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()

    def test_uploaded_annotation_codon_consequences_are_returned_restored_and_exported(self):
        content=genbank_bytes('Query',self.query,[self.feature],circular=False)
        response=self.client.post('/api/compare?infer=false',files={'file':('query.gb',content,'text/plain')})
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();record=result['records'][0];match=record['matches'][0]
        self.assertEqual(match['name'],'Coding reference')
        row=match['coding_analysis']['regions'][0]
        self.assertEqual(row['source'],'query');self.assertEqual(row['effects'][0]['protein_change'],'K2E')
        self.assertEqual(match['changes'][0]['coding_effects'][0]['type'],'missense')
        request={'scope':'selected','records':[{'filename':'query.gb',**record}]}
        exported=self.client.post('/api/compare/export',json=request)
        self.assertEqual(exported.status_code,200,exported.text[:100] if exported.status_code!=200 else '')
        book=load_workbook(io.BytesIO(exported.content))
        self.assertEqual(book['Coding regions']['D2'].value,'Uploaded reporter')
        self.assertEqual(book['Coding changes']['F2'].value,'missense')
        self.assertEqual(book['Coding changes']['O2'].value,'K2E')
        self.assertIn('missense',book['Differences']['J2'].value)
        # Simulate a comparison saved before coding analysis was introduced.
        legacy=json.loads(json.dumps(result))
        for record in legacy['records']:
            record.pop('query_features',None)
            for candidate in record['matches']:candidate.pop('coding_analysis',None)
        with store.connection() as db:
            identifier=db.execute('SELECT id FROM comparison_runs ORDER BY id DESC').fetchone()['id']
            db.execute('UPDATE comparison_runs SET result=? WHERE id=?',(json.dumps(legacy),identifier))
        restored=self.client.get('/api/workspace/comparisons')
        self.assertEqual(restored.status_code,200,restored.text)
        restored_match=restored.json()['items'][0]['result']['records'][0]['matches'][0]
        self.assertEqual(restored_match['coding_analysis']['regions'][0]['effects'][0]['type'],'missense')


if __name__=='__main__':unittest.main()
