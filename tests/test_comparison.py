"""Read-only comparison: enzyme ambiguity, fragment evidence, and strand coordinates."""
import random
import unittest
from app.comparison import compare_record, fragment_matches, MODES
from app.alignment import _rc
from app.sequence_engine import assemble


def sequence(n=350):
    rng=random.Random(982)
    return ''.join(rng.choice('ACGT') for _ in range(n))


class FragmentComparisonTests(unittest.TestCase):
    def setUp(self):
        self.payload=sequence()
        self.fragment={'id':1,'name':'Insert','plate_id':'P1','well':'B3',
            'sequence':'GGTCTCAAAAA'+self.payload+'CCCCCGAGACC'}
        self.retained='AAAA'+self.payload+'CCCC'

    def test_exact_payload_crosses_circle_origin_and_matches_reverse_strand(self):
        original='GACCATGC'+self.retained+'TATGCC'
        # Rotate inside payload, then reverse entire plasmid.
        query=_rc(original[100:]+original[:100])
        result=fragment_matches(query,[self.fragment],MODES,circular=True)
        hit=result['matches'][0]
        self.assertTrue(hit['exact'])
        self.assertEqual(hit['strand'],'-')
        self.assertEqual(hit['representation'],'Digested payload')
        self.assertEqual(hit['plate_id'],'P1')
        observed=''.join(query[a:b] for a,b in hit['query_spans'])
        self.assertEqual(observed,_rc(self.retained))
        self.assertEqual(len(hit['query_spans']),2)
        # Linear records cannot join across their file ends.
        linear=fragment_matches(query,[self.fragment],MODES,circular=False)
        self.assertFalse(any(h['exact'] for h in linear['matches']))

    def test_single_mutation_and_missing_segment_report_original_query_positions(self):
        point=170
        replacement=next(b for b in 'ACGT' if b!=self.retained[point])
        altered=self.retained[:point]+replacement+self.retained[point+1:]
        query='GGCCATG'+altered+'TACC'
        hit=fragment_matches(query,[self.fragment],('BsaI',),circular=False)['matches'][0]
        self.assertFalse(hit['exact'])
        self.assertEqual(hit['representation'],'Digested payload')
        self.assertEqual(len(hit['changes']),1)
        c=hit['changes'][0]
        self.assertEqual((c['type'],c['reference_start']),('substitution',point))
        self.assertEqual(c['original_query_spans'],[[7+point,8+point]])
        deleted=self.retained[:point]+self.retained[point+25:]
        hit=fragment_matches('GGCCATG'+deleted+'TACC',[self.fragment],('BsaI',),circular=False)['matches'][0]
        changes=hit['changes']
        self.assertTrue(any(c['type']=='deletion' and len(c['reference_bases'])==25 for c in changes),changes)

    def test_terminal_deletion_keeps_linear_query_end_coordinate(self):
        query='GGCCATG'+self.retained[:-20]
        hit=fragment_matches(query,[self.fragment],('BsaI',),circular=False)['matches'][0]
        deletion=next(c for c in hit['changes'] if c['type']=='deletion')
        self.assertEqual(len(deletion['reference_bases']),20)
        self.assertEqual(deletion['original_query_spans'],[[len(query),len(query)]])

    def test_no_saved_reference_still_returns_fragment_evidence(self):
        r=compare_record({'name':'Fragment only','sequence':self.retained,'circular':False},[self.fragment],[],infer=False)
        self.assertEqual(r['matches'],[])
        self.assertTrue(r['fragment_matches'][0]['exact'])
        self.assertEqual(r['enzyme_detection']['tested'],list(MODES))
        self.assertIsNone(r['enzyme_detection']['resolved_enzyme'])

    def test_auto_tests_all_modes_and_does_not_overclaim_unique_enzyme(self):
        a='GGTCTCAAAAA'+'ACGTCATGCTAGCTGA'+'CCCCCGAGACC'
        b='GGTCTCACCCC'+'TGCATCTGACTAGTCA'+'AAAACGAGACC'
        query='AAAAACGTCATGCTAGCTGACCCCTGCATCTGACTAGTCA'
        fragments=[{'id':1,'name':'a','sequence':a},{'id':2,'name':'b','sequence':b}]
        result=compare_record({'name':'Closed','sequence':query,'circular':True},fragments,[])
        self.assertTrue(result['matches'][0]['exact'])
        self.assertEqual(result['enzyme_detection']['site_counts'],{})
        self.assertEqual(result['enzyme_detection']['tested'],list(MODES))
        self.assertEqual(set(result['enzyme_detection']['compatible_assembly_modes']),{'BsaI','BsmBI + BsaI'})
        self.assertIsNone(result['enzyme_detection']['resolved_enzyme'])
        manual=compare_record({'name':'Closed','sequence':query},fragments,[],enzyme='BsaI')
        self.assertEqual(manual['enzyme_detection']['tested'],['BsaI'])
        self.assertEqual(manual['enzyme_detection']['resolved_enzyme'],'BsaI')

    def test_circular_reference_aliases_merge_origins_and_strands_without_losing_sources(self):
        reference=sequence()
        references=[{'id':1,'name':'Saved','sequence':reference,'circular':True,'source':'saved plasmid','assembly_enzymes':[]},
            {'id':2,'name':'Queued','sequence':_rc(reference[100:]+reference[:100]),'circular':True,'source':'Build list','assembly_enzymes':['BsaI']}]
        result=compare_record({'name':'q','sequence':reference},[],references,infer=False)
        self.assertEqual(result['candidate_count'],1)
        self.assertTrue(result['matches'][0]['exact'])
        self.assertEqual(result['matches'][0]['name'],'Saved')
        self.assertEqual(result['matches'][0]['assembly_enzymes'],['BsaI'])
        self.assertEqual(len(result['matches'][0]['aliases']),2)

    def test_saved_exact_match_keeps_inferred_fragment_assembly(self):
        parts=[{'id':1,'name':'a','sequence':'GGTCTCAAAAAACGTCATGCTAGCTGACCCCCGAGACC'},
               {'id':2,'name':'b','sequence':'GGTCTCACCCCTGCATCTGACTAGTCAAAAACGAGACC'}]
        query=assemble(parts,'BsaI')['sequence']
        result=compare_record({'name':'q','sequence':query,'circular':True},parts,
            [{'id':3,'name':'Saved','sequence':_rc(query[7:]+query[:7]),'source':'saved plasmid','circular':True}])
        match=result['matches'][0]
        self.assertTrue(match['exact'])
        self.assertEqual(set(match['parts']),{'a','b'})
        self.assertTrue(any(set(path['fragment_ids'])=={1,2} for path in match['assembly_paths']))

    def test_backbone_insert_search_handles_reverse_donor_and_reports_vector_mutation(self):
        vector={'id':3,'name':'Vector','sequence':'CACCAGAGACGTTAACTTACGTCTCACTCG'+sequence(500),
                'source':'saved plasmid','circular':True}
        parts=[{'id':1,'name':'a','sequence':'CGTCTCACACC'+'ACTGCTAGTACGATCGATCA'+'ATCCAGAGACG'},
               {'id':2,'name':'b','sequence':_rc('CGTCTCAATCC'+'GCTGACATTCAGTGCATACG'+'CTCGAGAGACG')}]
        built=assemble(parts,'BsmBI',vector)
        self.assertTrue(built['valid'],built['errors'])
        product=built['sequence']
        other=dict(vector,id=4,name='Other vector',sequence=vector['sequence'][:200]+next(base for base in 'ACGT' if base!=vector['sequence'][200])+vector['sequence'][201:])
        for altered in (False,True):
            query=product
            if altered:query=query[:50]+next(base for base in 'ACGT' if base!=query[50])+query[51:]
            result=compare_record({'name':'q','sequence':_rc(query[77:]+query[:77]),'circular':True},parts,[other,vector],enzyme='BsmBI')
            hit=result['matches'][0]
            self.assertEqual(hit['exact'],not altered)
            self.assertGreater(hit['identity'],.99)
            path=hit['assembly_paths'][0]
            self.assertEqual(path['backbone_id'],3)
            self.assertEqual(set(path['fragment_ids']),{1,2})
            self.assertIn(-1,path['part_orientations'])
            self.assertTrue(any(p.get('backbone_id')==4 for m in result['matches'] for p in m['assembly_paths']))
            if altered:self.assertEqual(len(hit['changes']),1)

    def test_shared_and_short_matches_remain_separate_evidence(self):
        shared='ACGTGCAATG'
        parts=[{'id':i,'name':str(i),'sequence':shared} for i in (1,2)]
        result=fragment_matches('TTT'+shared+'GGG',parts,MODES,circular=False)
        self.assertEqual(len(result['matches']),2)
        self.assertTrue(all(h['short_match'] for h in result['matches']))
        self.assertIn('not establish unique',result['metadata']['limitations'])
