"""Junction context and exact/RC database reuse are reported independently."""
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app import database as store
from app.main import app
from app.design_engine import design,fusion_key
from app.design_overhangs import overhang_report,database_index
from app.sequence_engine import reverse_complement as rc
from auth_client import bootstrap_pin
from test_design import clean_dna,placeholder,donor


def fixture():
    result=design([placeholder(clean_dna(),[dict(name='Cargo',start=100,end=260,mode='dynamic')])],left_overhang='TTTG',right_overhang='ACCT')
    assert result['valid'],result['errors']
    return result


def stock(identifier,name,sequence,**extra):return dict(id=identifier,name=name,sequence=sequence,plate_id='Plate A',well='B2',location='Freezer 1',**extra)


class OverhangReportTests(unittest.TestCase):
    def test_new_native_junctions_include_positions_and_both_fragment_ends(self):
        base=fixture();report=overhang_report(base,'BsaI')
        self.assertEqual(report['summary']['new'],2);self.assertEqual(report['summary']['existing'],2);self.assertEqual(report['summary']['assembly_conflicts'],0);self.assertTrue(report['summary']['assembly_validated'])
        for row in report['rows']:
            self.assertEqual(row['assembly_status'],'clear')
            if row['kind']=='new':self.assertEqual(len(row['uses']),2);self.assertIsNotNone(row['boundaries'][0]['actual'])
        self.assertEqual(report['summary']['database_reused'],0)
    def test_database_exact_rc_active_inactive_and_selected_inputs_stay_separate(self):
        base=fixture();label=base['boundary_shifts'][0]['overhang'];base['entries'].append(dict(kind='fragment',id='selected',fragment_id=7,name='Chosen',digest={'left_overhang':'','right_overhang':''}))
        records=[stock(7,'Chosen',donor(label,'AACCAA','CCCC')),stock(8,'Other stock',donor(rc(label),'AACCAA','CCCC')),stock(9,'BsmBI only',donor(label,'AACCAA','CCCC').replace('GGTCTC','CGTCTC').replace('GAGACC','GAGACG')),stock(10,'Archived',donor(label,'AACCAA','CCCC'),archived_at='old')]
        report=overhang_report(base,'BsaI',fragments=records);row=next(row for row in report['rows'] if fusion_key(row['overhang'])==fusion_key(label));matches={match['id']:match for match in row['database_matches']}
        self.assertEqual(set(matches),{7,8,9});self.assertTrue(matches[7]['in_assembly']);self.assertFalse(matches[8]['in_assembly']);self.assertTrue(any(site['reverse_complement'] for site in matches[8]['sites']));self.assertFalse(matches[9]['sites'][0]['active_enzyme']);self.assertEqual(row['database_reuse_count'],2);self.assertEqual(report['summary']['fragments_scanned'],3)
    def test_repeated_real_junctions_conflict_but_a_matching_join_is_counted_once(self):
        def entry(name,left,right):return dict(kind='fragment',id=name,name=name,fragment_id=1,digest={'left_overhang':left,'right_overhang':right})
        base={'entries':[entry('A','TTTG','AAGC'),entry('B','AAGC','GCTT'),entry('C','GCTT','ACCT')],'valid':False}
        report=overhang_report(base,'BsaI');row=next(row for row in report['rows'] if fusion_key(row['overhang'])==fusion_key('AAGC'))
        self.assertEqual(row['assembly_status'],'conflict');self.assertIn('separate junctions',' '.join(row['assembly_messages']));self.assertEqual(report['summary']['assembly_conflicts'],1)
        base['entries'][1]['digest']['right_overhang']='CTGA';base['entries'][2]['digest']['left_overhang']='CTGA';self.assertEqual(overhang_report(base,'BsaI')['summary']['assembly_conflicts'],0)
    def test_mismatch_reports_both_labels_and_source_names(self):
        base=design([dict(kind='fragment',id='A',name='Donor A',fragment_id=1,sequence=donor('TTTG','AACCAA','AAGC')),dict(kind='fragment',id='B',name='Donor B',fragment_id=2,sequence=donor('ACCT','AACCAA','CTGA'))])
        self.assertFalse(base['valid']);report=overhang_report(base,'BsaI');self.assertGreaterEqual(report['summary']['assembly_conflicts'],2)
        text=' '.join(message for row in report['rows'] for message in row['assembly_messages']);self.assertIn('Donor A → Donor B',text);self.assertIn('do not match',text)
    def test_failed_boundary_is_labelled_candidate_and_collision_is_visible(self):
        sequence=clean_dna();sequence=sequence[:100]+'TTTG'+sequence[104:]
        base=design([placeholder(sequence,[dict(name='Section',start=100,end=260)])],left_overhang='TTTG',right_overhang='ACCT',window=0)
        self.assertFalse(base['valid']);report=overhang_report(base,'BsaI');row=next(row for row in report['rows'] if fusion_key(row['overhang'])==fusion_key('TTTG'))
        self.assertEqual(row['kind'],'candidate');self.assertEqual(row['assembly_status'],'conflict');self.assertIsNone(row['boundaries'][0]['actual']);self.assertGreater(report['summary']['pending'],0)
    def test_repeated_requested_boundaries_are_visible_when_no_set_was_generated(self):
        base={'valid':False,'entries':[dict(kind='placeholder',id='Insert',name='Insert',run=0)],'runs':[dict(index=0,name='Insert',sequence='AAAAACCTGGAAAAACCTGGAAAA',trim_left=0,requested=[4,14],left_overhang='TTTG',right_overhang='CGAA')]}
        report=overhang_report(base,'BsaI');row=next(row for row in report['rows'] if row['overhang']=='ACCT')
        self.assertEqual(row['kind'],'candidate');self.assertEqual(row['assembly_status'],'conflict');self.assertIn('Requested boundaries share',' '.join(row['assembly_messages']));self.assertEqual(len(row['boundaries']),2)

    def test_palindrome_and_exclusion_are_independent_of_database_reuse(self):
        base={'valid':False,'entries':[dict(kind='fragment',id='A',name='Donor',digest={'left_overhang':'GATC','right_overhang':'ACCT'})]}
        report=overhang_report(base,'BsaI',excluded=['AGGT']);by_key={fusion_key(row['overhang']):row for row in report['rows']}
        self.assertEqual(by_key['GATC']['assembly_status'],'warning');self.assertEqual(by_key['ACCT']['assembly_status'],'conflict');self.assertEqual(report['summary']['database_reused'],0)
    def test_circular_database_sites_and_cut_overhangs_can_wrap_origin(self):
        label='AAGC';circle='GGTCTCA'+label+'AACCAA';circle=circle[3:]+circle[:3]
        plasmids=[stock(1,'Circular plasmid',circle,circular=True,recipe={}),stock(2,'Backbone',circle,circular=True,recipe={'backbone_template':True})]
        index=database_index([],plasmids,{fusion_key(label)},set(),2,'BsaI');matches=index[fusion_key(label)]
        self.assertEqual(len(matches),2);self.assertEqual(matches[('plasmid',1)]['sites'][0]['overhang'],label);self.assertTrue(matches[('plasmid',1)]['sites'][0]['wraps_origin']);self.assertEqual(matches[('plasmid',2)]['kind'],'backbone');self.assertTrue(matches[('plasmid',2)]['in_assembly'])


class OverhangReportAPITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB');os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'report.sqlite3');store.initialize();self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        self.payload=dict(name='Readout',enzyme='BsaI',entries=[placeholder(clean_dna(),[dict(name='Cargo',start=100,end=260,mode='dynamic')])],left_overhang='TTTG',right_overhang='ACCT')
    def tearDown(self):
        self.client.close()
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()
    def test_database_reuse_is_advisory_and_does_not_change_design_or_block_export(self):
        first=self.client.post('/api/design/preview?generate=true',json=self.payload);self.assertEqual(first.status_code,200,first.text);base=first.json();label=base['boundary_shifts'][0]['overhang']
        with store.connection() as db:db.execute('INSERT INTO fragments(name,sequence,location) VALUES(?,?,?)',('Other stock',donor(rc(label),'AACCAA','CCCC'),'Freezer 7'))
        result=self.client.post('/api/design/preview?generate=true',json=self.payload).json();self.assertTrue(result['valid'],result['errors']);self.assertEqual(result['assembly']['sequence'],base['assembly']['sequence']);self.assertGreater(result['overhang_report']['summary']['database_reused'],0)
        row=next(row for row in result['overhang_report']['rows'] if row['kind']=='new' and fusion_key(row['overhang'])==fusion_key(label));self.assertEqual(row['assembly_status'],'clear');self.assertEqual(row['database_matches'][0]['location'],'Freezer 7')
        self.assertEqual(self.client.post('/api/design/export?format=csv',json=self.payload).status_code,200)
        self.assertNotIn('overhang_report',self.client.post('/api/design/preview?generate=false',json=self.payload).json())
    def test_table_variants_share_one_report_without_duplicate_junction_conflicts(self):
        payload=self.payload|{'use_table':True,'table_rows':[dict(name='Alpha',dynamic_inputs={'insert:100:260':'ACGT'}),dict(name='Beta',dynamic_inputs={'insert:100:260':'TTGG'})]}
        response=self.client.post('/api/design/preview?generate=true',json=payload);self.assertEqual(response.status_code,200,response.text);result=response.json();self.assertTrue(result['valid'],result['errors']);self.assertEqual(len(result['assemblies']),2);report=result['overhang_report'];self.assertEqual(report['summary']['new'],2);self.assertEqual(report['summary']['assembly_conflicts'],0)

if __name__=='__main__':unittest.main()
