"""Auto orientation uses physical donor overhangs, never guesses a naked payload."""
import unittest
from app.design_engine import design
from app.sequence_engine import reverse_complement as rc
from test_design import donor, placeholder, clean_dna


class AutoOrientationTests(unittest.TestCase):
    def test_reverse_donor_is_resolved_at_the_fixed_left_end_and_insert_is_unchanged(self):
        sequence=clean_dna(10,200)
        source=rc(donor('TTTG','AACCAA','ACCT'))
        fixed=dict(id='old',kind='fragment',fragment_id=1,name='Existing',sequence=source,reverse=False)
        result=design([fixed,placeholder(sequence)],left_overhang='TTTG',right_overhang='TGCC')
        self.assertTrue(result['valid'],result['errors'])
        self.assertTrue(result['entries'][0]['reverse'])
        self.assertEqual(result['entries'][1]['sequence'],sequence)
        self.assertEqual(result['assembly']['sequence'],'TTTGAACCAAACCT'+sequence+'TGCC')
        feature=next(feature for feature in result['assembly']['features'] if feature.get('fragment_id')==1)
        self.assertTrue(feature['reverse_complement']);self.assertEqual(feature['strand'],-1)
        self.assertEqual(fixed['sequence'],source);self.assertFalse(fixed['reverse'])

    def test_compatible_chain_can_override_stale_manual_flags(self):
        first=donor('TTTG','AACCAA','ACCT');second=rc(donor('ACCT','TTGGCC','GGTG'))
        entries=[dict(id='one',kind='fragment',fragment_id=1,name='One',sequence=first,reverse=True),dict(id='two',kind='fragment',fragment_id=2,name='Two',sequence=second,reverse=False)]
        result=design(entries,left_overhang='TTTG',right_overhang='GGTG')
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual([node['reverse'] for node in result['entries']],[False,True])
        self.assertEqual(result['assembly']['sequence'],'TTTGAACCAAACCTTTGGCCGGTG')

    def test_no_matching_orientation_remains_a_failed_fixed_context(self):
        result=design([dict(id='one',kind='fragment',name='One',sequence=donor('TTTG','AACCAA','ACCT'))],left_overhang='CCAA',right_overhang='GGTG')
        self.assertFalse(result['valid']);self.assertIn('expected fixed',' '.join(result['errors']))

    def test_unflanked_insert_and_dynamic_inputs_keep_the_entered_direction(self):
        sequence=clean_dna(2)
        entry=placeholder(sequence,[dict(name='Cargo',start=100,end=260,mode='dynamic',variants=[dict(name='A',sequence='AACCGGTT')])])
        entry['reverse']=True  # A v0.5 draft already stores the displayed DNA.
        result=design([entry],left_overhang='TTTG',right_overhang='ACCT')
        self.assertTrue(result['valid'],result['errors'])
        self.assertEqual(result['assemblies'][0]['sequence'],'TTTG'+sequence+'ACCT')
        self.assertEqual(result['assemblies'][1]['sequence'],'TTTG'+sequence[:100]+'AACCGGTT'+sequence[260:]+'ACCT')


if __name__=='__main__':unittest.main()
