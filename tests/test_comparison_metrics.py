"""A/T deletion adjustments preserve true measurements and visible differences."""
import copy
import unittest

from app.alignment import _rc, _summarize, compare_sequences, rank_candidates
from app.comparison import fragment_matches
from app.comparison_metrics import adjusted_percentages, annotate_percentages, match_rank, refresh_comparison_percentages
from test_comparison import sequence


class ComparisonPercentageTests(unittest.TestCase):
    def test_only_pure_deleted_runs_at_least_twenty_bases_are_excluded(self):
        for deleted, expected in [('A'*19,0),('A'*20,20),('T'*35,35),('AT'*20,0),('C'*30,0),('A'*20+'C',0)]:
            reference='GCCG'+deleted+'CGGC'
            query='GCCG'+'-'*len(deleted)+'CGGC'
            result=adjusted_percentages(reference,query)
            self.assertEqual(result['excluded_at_deletion_bp'],expected,deleted)
            self.assertAlmostEqual(result['adjusted_identity'],8/(len(reference)-expected))
        short=adjusted_percentages('G'+'A'*100+'C','G'+'A'*99+'-C')
        self.assertEqual(short['excluded_at_deletion_bp'],0)

    def test_substitutions_insertions_and_short_deletions_still_lower_adjusted_percentages(self):
        ar='CC'+'A'*20+'GG--TTT'
        aq='CT'+'-'*20+'GGACT-T'
        result=adjusted_percentages(ar,aq)
        self.assertEqual(result['excluded_at_deletion_bp'],20)
        self.assertEqual(result['adjusted_identity'],5/9)
        self.assertEqual(result['adjusted_reference_coverage'],6/7)
        self.assertEqual(result['adjusted_query_coverage'],6/8)

    def test_circular_origin_run_is_counted_once_and_linear_ends_stay_separate(self):
        ar='A'*10+'GCCG'+'A'*10
        aq='-'*10+'GCCG'+'-'*10
        circular=adjusted_percentages(ar,aq,True)
        self.assertEqual(circular['excluded_at_deletion_bp'],20)
        self.assertEqual(circular['adjusted_identity'],1)
        self.assertEqual(adjusted_percentages(ar,aq,False)['excluded_at_deletion_bp'],0)
        self.assertEqual(adjusted_percentages('A'*10,'-'*10,True)['excluded_at_deletion_bp'],0)
        self.assertEqual(adjusted_percentages('A'*20,'-'*20)['adjusted_identity'],0)

    def test_full_alignment_preserves_true_values_and_coordinates_in_both_orientations(self):
        left,right=sequence(200),sequence(220)
        reference=left+'A'*25+right
        query=left+right
        for observed in (query,_rc(query)):
            match=compare_sequences(reference,observed,circular=False)
            self.assertEqual(match['excluded_at_deletion_bp'],25)
            self.assertEqual(match['adjusted_identity'],1)
            self.assertEqual(match['adjusted_reference_coverage'],1)
            self.assertAlmostEqual(match['identity'],len(query)/len(reference))
            self.assertFalse(match['exact'])
            self.assertTrue(match['changes'][0]['excluded_from_adjusted_percentages'])
            self.assertEqual(len(match['changes'][0]['reference_bases']),25)
            self.assertTrue(match['changes'][0]['original_query_spans'])

    def test_candidates_rank_by_adjusted_identity_and_true_exact_matches_remain_first(self):
        reference=sequence(100)+'A'*40+sequence(150)
        query=sequence(100)+sequence(150)
        changed=query[:70]+('A' if query[70]!='A' else 'C')+query[71:]
        candidates=[{'name':'A deletion','sequence':reference,'circular':False}, {'name':'Substitution','sequence':changed,'circular':False}]
        ranked=rank_candidates(query,candidates)
        self.assertEqual(ranked[0]['name'],'A deletion')
        candidates.append({'name':'Exact','sequence':query,'circular':False})
        self.assertEqual(rank_candidates(query,candidates)[0]['name'],'Exact')

    def test_adjusted_identity_is_the_primary_rank_even_for_legacy_exact_flags(self):
        matches=[{'name':'Legacy flag','exact':True,'identity':.99,'adjusted_identity':.99},
                 {'name':'Adjusted match','exact':False,'identity':.9,'adjusted_identity':1}]
        self.assertEqual(sorted(matches,key=match_rank,reverse=True)[0]['name'],'Adjusted match')
        tied=[{'identity':.9,'adjusted_identity':1},{'identity':.95,'adjusted_identity':1}]
        self.assertEqual(sorted(tied,key=match_rank,reverse=True)[0]['identity'],.95)

    def test_fragment_matches_use_the_same_adjustment(self):
        reference=sequence(150)+'T'*24+sequence(160)
        query=reference[:150]+reference[174:]
        hit=fragment_matches(query,[{'id':1,'name':'Donor','sequence':reference}],('BsaI',),circular=False)['matches'][0]
        self.assertEqual(hit['excluded_at_deletion_bp'],24)
        self.assertEqual(hit['adjusted_identity'],1)
        self.assertEqual(hit['adjusted_reference_coverage'],1)
        self.assertFalse(hit['exact'])
        self.assertLess(hit['identity'],1)

    def test_saved_plasmid_and_fragment_results_are_upgraded_without_losing_differences(self):
        ar='GCCG'+'A'*24+'CGGC'
        aq='GCCG'+'-'*24+'CGGC'
        changes,_=_summarize(ar,aq,0,'+',8)
        old={'query_sequence':'GGGCCGCGGCTT','matches':[{'identity':.25,'aligned_reference':ar,'aligned_query':aq,'changes':copy.deepcopy(changes),'exact':False}],
             'fragment_matches':[{'reference_length':32,'query_spans':[[2,10]],'identity':.25,'coverage':.25,'changes':copy.deepcopy(changes),'exact':False}]}
        updated=refresh_comparison_percentages(copy.deepcopy(old))
        for match in (updated['matches'][0],updated['fragment_matches'][0]):
            self.assertEqual(match['adjusted_identity'],1)
            self.assertEqual(match['identity'],.25)
            self.assertEqual(match['excluded_at_deletion_bp'],24)
            self.assertTrue(match['changes'][0]['excluded_from_adjusted_percentages'])
        self.assertNotIn('adjusted_identity',old['matches'][0])

    def test_legacy_empty_result_lists_still_load(self):
        result={'records':[{'matches':None,'fragment_matches':None,'error':'No alignments'}]}
        self.assertEqual(refresh_comparison_percentages(result),result)


if __name__=='__main__':unittest.main()
