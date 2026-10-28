"""Query matching must not override automatic assembly orientation or inventory filters."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from auth_client import AuthenticatedClient as TestClient
from app import database as store
from app.main import app
from app.fragment_search import match_fragment
from app.sequence_engine import fragment_orientations, reverse_complement as rc


class FragmentSearchTests(unittest.TestCase):
    def setUp(self):
        self.target='GACATCGTACGGTTA'
        self.fragment=dict(name='Unique cargo',sequence='GGTCTCAACCT'+self.target+'TGCTCGAGACC',
                           construct_sequence='',plate_id='Do not search plates',well='A12')
        self.variants=fragment_orientations(self.fragment['sequence'],'BsaI')

    def match(self,query):
        return match_fragment(self.fragment,query,self.variants)

    def test_four_base_overhangs_and_complements_outrank_internal_dna(self):
        for query,side,reverse in [('ACCT','left',False),('AGGT','left',True),('TGCT','right',False),('AGCA','right',True)]:
            match=self.match(query)['search_match']
            self.assertEqual((match['kind'],match['side'],match['reverse_complement']),('overhang',side,reverse))
        self.assertEqual(self.match('GACA')['search_match']['kind'],'sequence')

    def test_exact_dna_and_reverse_complement_queries_include_whitespace_and_case(self):
        before=dict(self.fragment)
        for query,reverse in [(self.target,False),(rc(self.target).lower(),True),(' '+rc(self.target)[:6]+'\n'+rc(self.target)[6:]+' ',True)]:
            match=self.match(query)['search_match']
            self.assertEqual(match['kind'],'sequence')
            self.assertEqual(match['reverse_complement'],reverse)
            self.assertEqual(self.fragment['sequence'][match['start']:match['end']],self.target)
        self.assertEqual(self.fragment,before)
        self.assertFalse(self.match('GTAC')['search_match']['reverse_complement'])

    def test_names_autocorrection_and_empty_queries_work_without_plate_or_well_matches(self):
        for query in ('Unique cargo','cargo','uniqe cargo'):
            self.assertEqual(self.match(query)['search_match']['kind'],'name')
        self.assertEqual(self.match('')['search_score'],1)
        for query in ('A12','Do not search plates','GACATCNGTACGG','GACA;TCG'):
            self.assertIsNone(self.match(query))
        self.assertIsNone(self.match('GA'))

    def test_construct_only_dna_is_searchable_and_short_overhang_query_does_not_guess_orientation(self):
        self.fragment['construct_sequence']='TTAACTGAGCAT'+self.fragment['sequence']
        match=self.match(rc('TTAACTGAGCAT'))['search_match']
        self.assertEqual(match['source'],'construct_sequence')
        self.assertTrue(match['reverse_complement'])
        self.assertEqual(self.variants[0]['reverse_complement'],False)
        self.assertTrue(self.match('AGGT')['search_match']['reverse_complement'])
        self.assertEqual(self.variants[0]['reverse_complement'],False)


class FragmentSearchAPITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.old=os.environ.get('GOLDEN_GATE_DB')
        path=Path(self.folder.name)/'test.sqlite3';os.environ['GOLDEN_GATE_DB']=str(path)
        path.with_suffix('.sources.json').write_text(json.dumps({'plate_files':[],'genbank_files':[]}))
        self.client=TestClient(app);self.client.__enter__()
        self.target='GACATCGTACGGTTA'
        with store.connection() as db:
            self.ids=[db.execute('INSERT INTO fragments(name,plate_id,well,sequence,yield_ng) VALUES(?,?,?,?,?)',
                (name,plate,'A1','GGTCTCAACCT'+self.target+'TGCTCGAGACC',300)).lastrowid
                for name,plate in [('One donor','P1'),('Another donor','P2')]]

    def tearDown(self):
        self.client.__exit__(None,None,None)
        if self.old is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.old
        self.folder.cleanup()

    def test_sequence_matches_retain_plate_limit_and_compatible_end_filters(self):
        response=self.client.get('/api/fragments',params={'q':rc(self.target),'enzyme':'BsaI','plate':'P1','left':'ACCT','limit':1})
        self.assertEqual(response.status_code,200,response.text)
        rows=response.json();self.assertEqual([r['id'] for r in rows],[self.ids[0]])
        self.assertTrue(rows[0]['search_match']['reverse_complement']);self.assertFalse(rows[0]['reverse_complement'])
        self.assertNotIn('sequence',rows[0]);self.assertNotIn('construct_sequence',rows[0])
        # Query strand and the orientation required by the neighboring overhang differ.
        reverse=self.client.get('/api/fragments',params={'q':self.target,'left':'AGCA'}).json()
        self.assertTrue(reverse[0]['reverse_complement']);self.assertFalse(reverse[0]['search_match']['reverse_complement'])
        self.assertEqual(self.client.get('/api/fragments',params={'q':self.target,'left':'AAAA'}).json(),[])
        with store.connection() as db:db.execute('UPDATE fragments SET archived_at=CURRENT_TIMESTAMP WHERE id=?',(self.ids[0],))
        self.assertEqual(self.client.get('/api/fragments',params={'q':self.target,'plate':'P1'}).json(),[])
        self.assertEqual(self.client.get('/api/fragments',params={'q':'A'*5001}).status_code,422)
