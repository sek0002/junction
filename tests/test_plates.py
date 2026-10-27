"""Informational site detection and coordinates for mixed plate maps."""
import unittest

from app.plates import fragment_site_info


class PlateSiteInfoTests(unittest.TestCase):
    def test_both_orientations_report_forward_strand_overhang_positions(self):
        seq='GGTCTCAACCTAACCGGTATGCGAGACC'
        info=fragment_site_info(seq)
        self.assertEqual(info['detected_enzymes'],['BsaI'])
        self.assertEqual(info['adapter_enzyme'],'BsaI')
        self.assertEqual([end['overhang'] for end in info['fusion_ends']],['ACCT','TATG'])
        for site in info['sites']:
            self.assertEqual(seq[site['overhang_start']:site['overhang_end']],site['overhang'])
        self.assertEqual(info['sites'][0]['overhang_start'],7)
        self.assertEqual(info['sites'][-1]['overhang_start'],len(seq)-11)
        self.assertEqual([site['location'] for site in info['sites']],['5′ adapter','3′ adapter'])

    def test_nested_enzyme_does_not_replace_outer_adapter_labels(self):
        seq='GGTCTCAACCTAACCGAGACGACGTACGTACGTCTCAAACCGGTATGCGAGACC'
        info=fragment_site_info(seq)
        self.assertEqual(set(info['detected_enzymes']),{'BsaI','BsmBI'})
        self.assertEqual(info['adapter_enzyme'],'BsaI')
        self.assertEqual([end['overhang'] for end in info['fusion_ends']],['ACCT','TATG'])
        self.assertEqual([s['location'] for s in info['sites'] if s['enzyme']=='BsmBI'],['Internal','Internal'])
        self.assertNotIn('errors',info['digest'])
        self.assertNotIn('valid',info['digest'])

    def test_dual_adapters_and_construct_coordinates(self):
        seq='CGTCTCAACCTAACCGGTATGCGAGACC';prefix='CAAACCAA'
        info=fragment_site_info(seq,prefix+seq+'TTTT')
        self.assertEqual(info['adapter_enzyme'],'BsmBI + BsaI')
        self.assertEqual(info['construct_offset'],len(prefix))
        for site in info['sites']:
            self.assertEqual(site['construct_start'],site['start']+len(prefix))
            self.assertEqual(site['construct_overhang_start'],site['overhang_start']+len(prefix))
        for end in info['fusion_ends']:
            self.assertEqual(end['construct_start'],end['start']+len(prefix))

    def test_hindiii_and_bbsi_overhangs_use_their_own_cut_offsets(self):
        seq='AAGCTTTTTGAAGACAAACGTCCCCAAAAGTCTTCTTT'
        info=fragment_site_info(seq)
        hind=next(s for s in info['sites'] if s['enzyme']=='HindIII')
        self.assertEqual(hind['overhang'],'AGCT')
        self.assertEqual((hind['overhang_start'],hind['overhang_end']),(1,5))
        bbs=[s for s in info['sites'] if s['enzyme']=='BbsI']
        self.assertEqual([s['overhang'] for s in bbs],['ACGT','CCAA'])
        self.assertEqual(info['fusion_ends'],[])

    def test_missing_flanking_bases_are_informational_not_a_failed_digest(self):
        info=fragment_site_info('CGTCTC')
        self.assertEqual(info['sites'][0]['overhang'],'')
        self.assertIsNone(info['sites'][0]['overhang_start'])
        self.assertEqual(info['fusion_ends'],[])
        self.assertEqual(info['detected_enzymes'],['BsmBI'])
        self.assertNotIn('errors',info['digest'])

    def test_no_sites_and_ambiguous_construct_mapping(self):
        info=fragment_site_info('ACGT','ACGTACGT')
        self.assertEqual(info['sites'],[])
        self.assertEqual(info['detected_enzymes'],[])
        self.assertIsNone(info['construct_offset'])


if __name__=='__main__':unittest.main()
