"""Checks for circular plasmid alignment and bounded assembly discovery."""
import random
import unittest
from app.alignment import compare_sequences, infer_database_candidates, rank_candidates


def random_sequence(length=8000):
    rng = random.Random(176)
    return ''.join(rng.choice('ACGT') for _ in range(length))


def rc(sequence):
    return sequence.translate(str.maketrans('ACGT', 'TGCA'))[::-1]


class CircularAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.reference = random_sequence()

    def rotated(self, sequence):
        return sequence[2050:] + sequence[:2050]

    def test_rotation_and_reverse_complement_are_exact(self):
        for query in [self.rotated(self.reference), rc(self.rotated(self.reference))]:
            match = compare_sequences(self.reference, query)
            self.assertTrue(match['exact'])
            self.assertEqual(match['identity'], 1)
            self.assertEqual(match['reference_coverage'], 1)
            self.assertEqual(match['query_coverage'], 1)
            self.assertEqual(match['aligned_bp'], len(self.reference))
            self.assertFalse(match['changes'])

    def test_rotated_single_base_substitution(self):
        original = self.reference[2187]
        alternate = next(b for b in 'ACGT' if b != original)
        query = self.reference[:2187] + alternate + self.reference[2188:]
        match = compare_sequences(self.reference, self.rotated(query))
        self.assertEqual(match['reference_coverage'], 1)
        self.assertEqual(match['query_coverage'], 1)
        self.assertLess(match['identity'], 1)
        self.assertEqual(len(match['changes']), 1)
        change = match['changes'][0]
        self.assertEqual((change['type'], change['reference_start'], change['reference_end']), ('substitution', 2187, 2188))
        self.assertEqual(change['reference_bases'], original)
        self.assertEqual(change['query_bases'], alternate)

    def test_large_missing_segment_and_insert(self):
        query = self.reference[:3400] + self.reference[4341:]
        match = compare_sequences(self.reference, self.rotated(query))
        self.assertEqual(len(match['changes']), 1)
        change = match['changes'][0]
        self.assertEqual(change['type'], 'deletion')
        self.assertEqual(len(change['reference_bases']), 941)
        self.assertAlmostEqual(match['reference_coverage'], (len(self.reference)-941)/len(self.reference))
        self.assertEqual(match['query_coverage'], 1)
        self.assertEqual(match['aligned_reference'].replace('-', ''), self.reference)
        inserted = 'AACCGGTTAACC'
        query = self.reference[:3400] + inserted + self.reference[3400:]
        match = compare_sequences(self.reference, self.rotated(query))
        self.assertEqual(len(match['changes']), 1)
        self.assertEqual(match['changes'][0]['type'], 'insertion')
        self.assertEqual(len(match['changes'][0]['query_bases']), len(inserted))
        self.assertEqual(match['reference_coverage'], 1)
        self.assertAlmostEqual(match['query_coverage'], len(self.reference)/(len(self.reference)+len(inserted)))

    def test_candidate_ranking_prefers_exact_circle(self):
        result = rank_candidates(self.rotated(self.reference), [
            {'id': 'different', 'name': 'other', 'sequence': random_sequence(300)},
            {'id': 'correct', 'name': 'correct', 'sequence': self.reference}], limit=2)
        self.assertEqual(result[0]['id'], 'correct')
        self.assertTrue(result[0]['exact'])

    def test_indel_shifted_origin_does_not_create_false_terminal_differences(self):
        rng=random.Random(0)
        reference=''.join(rng.choice('ACGT') for _ in range(500))
        query=reference[:80]+'A'*17+reference[80:200]+'GGCCAGCAAAAGGCCAGGAACCGTAAAAAGGCCGCGTTGCTGGCGTT'+reference[200:350]+reference[375:]
        for uploaded in (query[80:]+query[:80],rc(query[80:]+query[:80])):
            result=compare_sequences(reference,uploaded)
            self.assertEqual(len(result['changes']),3)
            self.assertEqual(sorted((c['type'],len(c['reference_bases']),len(c['query_bases'])) for c in result['changes']),
                             [('deletion',25,0),('insertion',0,17),('insertion',0,47)])

    def test_inference_closes_graph_and_excludes_internal_sites(self):
        a = 'GGTCTCAAAAA' + 'ACGTCATGCTAGCTGA' + 'CCCCCGAGACC'
        b = 'GGTCTCACCCC' + 'TGCATCTGACTAGTCA' + 'AAAACGAGACC'
        bad = 'GGTCTCACCCC' + 'TGCA' + 'GGTCTC' + 'ACTAGTCA' + 'AAAACGAGACC'
        query = 'AAAAACGTCATGCTAGCTGACCCCTGCATCTGACTAGTCA'
        result = infer_database_candidates(query, [
            {'id': 1, 'name': 'a', 'sequence': a},
            {'id': 2, 'name': 'b', 'sequence': b},
            {'id': 3, 'name': 'bad', 'sequence': bad}])
        self.assertEqual(len(result['candidates']), 1)
        self.assertIn(3, result['metadata']['fragments_excluded'])
        self.assertTrue(compare_sequences(result['candidates'][0]['sequence'], query)['exact'])

    def test_inference_reports_capped_search(self):
        # One edge per unique donor; more than 24 possible starts triggers cap.
        fragments = [{'id': i, 'name': str(i), 'sequence': 'GGTCTCAAAAAACGTCATGCTAGCTGACCCCCGAGACC'} for i in range(30)]
        result = infer_database_candidates('AAAAACGTCATGCTAGCTGA', fragments)
        self.assertFalse(result['metadata']['complete_search'])

    def test_short_circle_limit_does_not_hide_longer_exact_assembly(self):
        parts=[{'id':1,'name':'a','left_overhang':'AAAA','right_overhang':'CCCC','target':'ACGTACGTTGCAACGTAGCA'},
               {'id':2,'name':'b','left_overhang':'CCCC','right_overhang':'GGTT','target':'TGCATCGATGCTACGATCGA'},
               {'id':3,'name':'c','left_overhang':'GGTT','right_overhang':'AAAA','target':'GACATCGTACGATCAGTCAG'},
               {'id':4,'name':'short','left_overhang':'CCCC','right_overhang':'AAAA','target':'TGCAT'}]
        query=''.join(p['left_overhang']+p['target'] for p in parts[:3])
        result=infer_database_candidates(query,parts,max_candidates=1)
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(compare_sequences(result['candidates'][0]['sequence'],query)['exact'])
        self.assertFalse(result['metadata']['complete_search'])

    def test_dual_inference_rejects_sites_created_across_origin(self):
        for last_base in ('G','C'):
            parts=[{'id':1,'name':'a','left_overhang':'GTCT','right_overhang':'ATGG','target':'CAAAA'},
                   {'id':2,'name':'b','left_overhang':'ATGG','right_overhang':'GTCT','target':'AAC'+last_base}]
            query='GTCTCAAAAATGGAAC'+last_base
            result=infer_database_candidates(query,parts,enzyme='BsmBI + BsaI')
            self.assertEqual(result['candidates'],[])


if __name__ == '__main__':
    unittest.main()
