"""Assembly exports must not include unrelated library or removed-build stocks."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook
from pypdf import PdfReader
from auth_client import AuthenticatedClient as TestClient
from app.main import app
from test_bench_exports import csv_table


class AssemblyExportScopeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB');path=Path(self.folder.name)/'scope.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[],'genbank_files':[]}))
        self.client=TestClient(app);self.client.__enter__()
        text='Name,Plate ID,Well,Sequence,Yield ng,Stock ng/uL\nLeft,Used plate,A1,GGTCTCATTTGAACCGGATGGCGAGACC,300,5\nRight,Used plate,A2,GGTCTCAATGGCCAAAATTTGCGAGACC,300,5\nRemoved build input,Removed plate,B1,GGTCTCATTTGAAAAAATGGCGAGACC,300,5\nUNRELATED STOCK,Unrelated plate,C1,ACGTACGTACGT,300,5\nLeft,Unrelated plate,C2,GGTCTCATTTGAACCGGATGGCGAGACC,300,99\n'
        response=self.client.post('/api/uploads/plate?no_backbone=true',files={'file':('scope.csv',text,'text/csv')});self.assertEqual(response.status_code,200,response.text)
        rows=self.client.get('/api/fragments').json();self.ids={row['well']:row['id'] for row in rows}
        self.request=dict(name='Selected assembly',enzyme='BsaI',fragment_ids=[self.ids['A1'],self.ids['A2']],settings={'planner_stock_mode':'saved'})
    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()
    def assert_excel_scope(self,content,removed=True):
        book=load_workbook(io.BytesIO(content));all_cells='\n'.join(str(cell.value) for sheet in book for row in sheet for cell in row if cell.value is not None)
        for text in ('UNRELATED STOCK','Unrelated plate'):
            self.assertNotIn(text,all_cells)
        if removed:self.assertNotIn('Removed build input',all_cells);self.assertNotIn('Removed plate',all_cells)
        metadata=book['Fragment metadata'];self.assertEqual({metadata.cell(row,1).value for row in range(4,metadata.max_row+1)},{'Left','Right'} if removed else {'Left','Right','Removed build input'})
        return book
    def test_single_assembly_workbook_scopes_every_sheet_not_just_the_printed_metadata(self):
        response=self.client.post('/api/assemblies/worksheet?format=xlsx',json=self.request);self.assertEqual(response.status_code,200,response.text[:200]);book=self.assert_excel_scope(response.content)
        self.assertEqual(book['Resuspension inventory'].max_row,3)
        self.assertEqual({book['Resuspension inventory'].cell(row,1).value for row in (2,3)},set(self.request['fragment_ids']))
        self.assertEqual({book['Resuspension inventory'].cell(row,10).value for row in (2,3)},{5})
    def test_build_list_uses_only_active_assemblies_in_all_formats_and_preview(self):
        first=self.client.post('/api/build-list',json=self.request);self.assertEqual(first.status_code,200,first.text)
        second=self.client.post('/api/build-list',json=self.request|{'name':'Removed assembly','fragment_ids':[self.ids['B1'],self.ids['A2']]});self.assertEqual(second.status_code,200,second.text)
        self.assertEqual(self.client.delete('/api/build-list/'+str(second.json()['id'])).status_code,200)
        preview=self.client.get('/api/build-list').json()['export'];self.assertEqual({row[0] for row in preview['metadata']},{'Left','Right'})
        self.assertEqual({row[11] for row in preview['metadata']},{'Selected assembly / Final assembly'})
        for format in ('xlsx','csv','pdf'):
            response=self.client.get('/api/build-list/worksheet?format='+format);self.assertEqual(response.status_code,200)
            if format=='xlsx':self.assert_excel_scope(response.content)
            elif format=='csv':self.assertEqual({row['Fragment'] for row in csv_table(response.content,'Fragment metadata')},{'Left','Right'})
            else:
                text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
                for unused in ('UNRELATED STOCK','Removed build input','Unrelated plate','Removed plate'):self.assertNotIn(unused,text)
    def test_multiple_assemblies_export_the_union_of_used_stocks(self):
        for request in (self.request,self.request|{'name':'Second assembly','fragment_ids':[self.ids['B1'],self.ids['A2']]}):self.assertEqual(self.client.post('/api/build-list',json=request).status_code,200)
        response=self.client.get('/api/build-list/worksheet?format=xlsx');self.assertEqual(response.status_code,200);self.assert_excel_scope(response.content,removed=False)
        metadata=self.client.get('/api/build-list').json()['export']['metadata'];right=next(row for row in metadata if row[0]=='Right');self.assertIn('Selected assembly / Final assembly',right[11]);self.assertIn('Second assembly / Final assembly',right[11])
    def test_workbook_builder_scopes_library_inputs_and_preserves_instance_stocks(self):
        from app import database as store
        from app.exports import make_workbook
        from copy import deepcopy
        library=store.fragments();before=deepcopy(library)
        selected=[store.get_fragment(identifier) for identifier in self.request['fragment_ids']]
        selected[0]=selected[0]|{'stock_ng_ul':8,'role':'insert'}
        # Numeric plasmid IDs never select the same-numbered library fragment.
        selected.append(dict(id='plasmid:'+str(self.ids['C1']),name='Chosen backbone',role='backbone',sequence='ACGT'*500,physical_length=2000,stock_ng_ul=25))
        content=make_workbook(library,{'parts':selected,'name':'Scoped'},dict(no_backbone=False,backbone_stock_ng_ul=25))
        book=load_workbook(io.BytesIO(content));sheet=book['Resuspension inventory']
        self.assertEqual(sheet.max_row,4);self.assertEqual({sheet.cell(row,2).value for row in (2,3,4)},{'Left','Right','Chosen backbone'})
        self.assertEqual(sheet.cell(2,10).value,8);self.assertEqual(library,before)
        self.assertFalse(any('UNRELATED STOCK' in str(cell.value) or 'Unrelated plate' in str(cell.value) for sheet in book for row in sheet for cell in row))

    def test_detailed_build_and_nested_sheets_ignore_unconsumed_resuspension_rows(self):
        from app.exports import build_list_workbook,resuspension_plan
        from test_bench_exports import fixture
        assembly,settings=fixture();assembly['length']=6000
        unused=dict(id=999,name='Insert',physical_length=1000,stock_ng_ul=10,yield_ng=500,plate_id='UNUSED-PLAN-PLATE',well='C3')
        resuspension={'rows':resuspension_plan(assembly['parts']+[unused],settings)}
        assembly['resuspension']=resuspension
        assembly['nested_assemblies']=[{'children':[]}]
        assembly['nested_reactions']=[dict(name='Stage 1',enzyme='BsmBI',reaction=assembly['reaction'],resuspension=resuspension,errors=[])]
        request=dict(name='Assembly A',enzyme='BsaI',fragment_ids=[2],settings=settings)
        book=load_workbook(io.BytesIO(build_list_workbook([dict(request=request,plan=assembly,status='Ready')])))
        text=' '.join(str(cell.value) for sheet in book for row in sheet for cell in row if cell.value is not None)
        self.assertNotIn('UNUSED-PLAN-PLATE',text)
        for title,column in [('Resuspension',2),('Nested resuspension',3)]:
            sheet=book[title];self.assertIn('Insert',[sheet.cell(row,column).value for row in range(2,sheet.max_row+1)])

    def test_explicit_inventory_export_still_contains_all_requested_library_stocks(self):
        response=self.client.post('/api/inventory/worksheet?format=xlsx',json={'no_backbone':True,'planner_stock_mode':'saved'});self.assertEqual(response.status_code,200)
        sheet=load_workbook(io.BytesIO(response.content))['Resuspension inventory'];self.assertEqual(sheet.max_row,6);self.assertIn('UNRELATED STOCK',[sheet.cell(row,2).value for row in range(2,sheet.max_row+1)])

if __name__=='__main__':unittest.main()
