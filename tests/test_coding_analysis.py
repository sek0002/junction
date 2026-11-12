"""Coding consequences follow annotated frames, strands and actual gaps."""
import unittest
from Bio.Seq import Seq

from app.alignment import compare_sequences, _summarize
from app.coding_analysis import annotate_coding
from app.comparison import compare_record


def coding(reference, query, feature=None, query_features=None, circular=False):
    # Deterministic aligned strings support deliberately tiny codon fixtures.
    changes,_=_summarize(reference,query,0,'+',len(query.replace('-','')))
    match={'aligned_reference':reference,'aligned_query':query,'orientation':'+','rotation':0,
           'circular':circular,'features':[feature] if feature else [],'changes':changes}
    annotate_coding(match,query_features)
    return match


def cds(length, **qualifiers):
    return {'type':'CDS','label':'Reporter','raw_location':f'1..{length}','qualifiers':{k:[str(v)] for k,v in qualifiers.items()}}


class CodingAnalysisTests(unittest.TestCase):
    def test_synonymous_missense_stop_gain_stop_loss_and_start_loss(self):
        reference='ATGAAAGGGTAA'
        cases=[('ATGAAGGGGTAA','synonymous','K2K'),('ATGGAAGGGTAA','missense','K2E'),
               ('ATGTAAGGGTAA','stop_gained','K2*'),('ATGAAAGGGTAC','stop_lost','*4Y'),
               ('ACGAAAGGGTAA','start_lost','M1T')]
        for query,kind,change in cases:
            match=coding(reference,query,cds(12))
            row=match['coding_analysis']['regions'][0]
            self.assertEqual(row['effects'][0]['type'],kind,query)
            self.assertEqual(row['effects'][0]['protein_change'],change)
            self.assertEqual(row['reference_frame'],1)
            self.assertEqual(match['changes'][0]['coding_effects'][0]['type'],kind)

    def test_reverse_strand_joined_cds_and_codon_start(self):
        reference='ATGAAAGGGTAA';query='ATGGAAGGGTAA'
        r=str(Seq(reference).reverse_complement());q=str(Seq(query).reverse_complement())
        row=coding(r,q,cds(12)|{'raw_location':'complement(1..12)'})['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_protein'],'MKG*');self.assertEqual(row['query_protein'],'MEG*')
        self.assertEqual(row['reference_frame'],-1)
        self.assertEqual(row['effects'][0]['protein_change'],'K2E')
        joined=cds(15)|{'raw_location':'join(1..6,10..15)'}
        row=coding('ATGAAACCCGGGTAA','ATGGAACCCGGGTAA',joined)['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_protein'],'MKG*')
        self.assertEqual(row['effects'][0]['type'],'missense')
        row=coding('CATGAAAGGGTAA','CATGGAAGGGTAA',cds(13,codon_start=2))['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_frame'],2);self.assertEqual(row['effects'][0]['protein_change'],'K2E')

    def test_complement_join_and_origin_crossing_preserve_biological_order(self):
        protein_dna='ATGAAAGGGTAA';changed='ATGGAAGGGTAA'
        r=str(Seq(protein_dna).reverse_complement());q=str(Seq(changed).reverse_complement())
        row=coding(r[:6]+'CCC'+r[6:],q[:6]+'CCC'+q[6:],cds(15)|{'raw_location':'complement(join(1..6,10..15))'})['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_protein'],'MKG*');self.assertEqual(row['effects'][0]['protein_change'],'K2E')
        row=coding(protein_dna[6:]+'CCC'+protein_dna[:6],changed[6:]+'CCC'+changed[:6],cds(15)|{'raw_location':'join(10..15,1..6)'},circular=True)['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_protein'],'MKG*');self.assertEqual(row['effects'][0]['protein_change'],'K2E')

    def test_alternative_code_and_initiator_codons_are_respected(self):
        row=coding('ATGTGATAA','ATGTGGTAA',cds(9,transl_table=2))['coding_analysis']['regions'][0]
        self.assertEqual(row['effects'][0]['type'],'synonymous')
        self.assertEqual(row['effects'][0]['reference_aa'],'W')
        row=coding('GTGAAATAA','ATGAAATAA',cds(9,transl_table=11))['coding_analysis']['regions'][0]
        self.assertEqual(row['reference_protein'],'MK*');self.assertEqual(row['query_protein'],'MK*')
        self.assertEqual(row['effects'][0]['type'],'synonymous')

    def test_indels_frameshift_context_and_frame_restoration(self):
        r='ATGAAA'+'-'+'GGG'+'TAA'
        q='ATGAAA'+'C'+'GGA'+'TAA'
        row=coding(r,q,cds(12))['coding_analysis']['regions'][0]
        self.assertTrue(row['frameshift'])
        self.assertEqual([effect['type'] for effect in row['effects']],['frameshift','frameshift_context'])
        row=coding('ATGAAA---GGGTAA','ATGAAACCCGGGTAA',cds(12))['coding_analysis']['regions'][0]
        self.assertFalse(row['frameshift']);self.assertEqual(row['effects'][0]['type'],'inframe_insertion')

    def test_intron_substitutions_are_not_called_coding_changes(self):
        match=coding('ATGAAACCCGGGTAA','ATGAAACGCGGGTAA',cds(15)|{'raw_location':'join(1..6,10..15)'})
        row=match['coding_analysis']['regions'][0]
        self.assertFalse(row['protein_changed']);self.assertEqual(row['effects'],[])
        self.assertEqual(match['coding_analysis']['unassigned_substitution_bp'],1)

    def test_uploaded_cds_is_projected_through_rotation_and_reverse_complement(self):
        reference='CCGATGAAAGGGTAACTG'
        query='CCGATGGAAGGGTAACTG'
        for reverse in (False,True):
            rotated=query[7:]+query[:7]
            uploaded=str(Seq(rotated).reverse_complement()) if reverse else rotated
            # Original CDS query positions 3..15 become a wrapped feature after rotation.
            feature=cds(len(uploaded))|{'raw_location':'join(15..18,1..8)'}
            if reverse:
                feature['raw_location']='complement(join(11..18,1..4))'
            match=compare_sequences(reference,uploaded,True);match['circular']=True;match['features']=[]
            annotate_coding(match,[feature])
            row=match['coding_analysis']['regions'][0]
            self.assertEqual(row['source'],'query')
            self.assertEqual(row['reference_protein'],'MKG*')
            self.assertEqual(row['query_protein'],'MEG*')

    def test_unannotated_orfs_are_labelled_predictions_and_scan_six_frames(self):
        reference='ATG'+'AAA'*35+'TAA'
        query='ATG'+'GAA'+'AAA'*34+'TAA'
        match=coding(reference,query)
        report=match['coding_analysis']
        self.assertTrue(report['predicted']);self.assertEqual(len(report['frames']['reference']),6)
        self.assertTrue(all(row['basis']=='predicted_orf' for row in report['regions']))
        self.assertTrue(any(effect['type']=='missense' for row in report['regions'] for effect in row['effects']))

    def test_exceptions_unknown_codes_and_invalid_features_do_not_break_comparison(self):
        report=coding('ATGAAATAA','ATGGAATAA',cds(9,transl_except='(pos:4..6,aa:Sec)'))['coding_analysis']
        self.assertEqual(report['regions'][0]['effects'][0]['type'],'uncertain')
        self.assertTrue(report['regions'][0]['warnings'])
        report=coding('ATGAAATAA','ATGGAATAA',cds(9,transl_table=999))['coding_analysis']
        self.assertEqual(report['regions'],[]);self.assertTrue(report['warnings'])

    def test_no_reference_still_exposes_uploaded_translation_without_a_comparison_claim(self):
        result=compare_record({'name':'Only query','sequence':'ATGAAATAA','features':[cds(9)],'circular':False},[],[],infer=False)
        self.assertEqual(result['matches'],[])
        report=result['query_coding_analysis']
        self.assertTrue(report['query_only'])
        row=report['regions'][0]
        self.assertEqual(row['source'],'query');self.assertEqual(row['query_protein'],'MK*')
        self.assertIsNone(row['protein_changed']);self.assertIsNone(row['reference_frame'])

    def test_partial_and_ambiguous_cds_are_flagged_without_false_protein_certainty(self):
        report=coding('CATGAAATAA','CATGGAATAA',cds(10,codon_start=2)|{'raw_location':'<1..10'})['coding_analysis']
        self.assertEqual(report['regions'][0]['effects'][0]['protein_change'],'K2E')
        row=coding('ATGNNNTAA','ATGAAATAA',cds(9))['coding_analysis']['regions'][0]
        self.assertIsNone(row['protein_changed']);self.assertEqual(row['effects'][0]['type'],'uncertain')

    def test_adjusted_poly_a_deletions_still_report_coding_frameshifts(self):
        reference='ATG'+'A'*25+'GCT'*20+'TAA';query=reference[:3]+reference[28:]
        result=compare_record({'name':'Query','sequence':query,'circular':False},[],[
            {'id':1,'name':'Reference','source':'saved plasmid','sequence':reference,'features':[cds(len(reference))],'circular':False}
        ],infer=False)
        match=result['matches'][0]
        self.assertEqual(match['adjusted_identity'],1)
        self.assertTrue(match['coding_analysis']['regions'][0]['frameshift'])


if __name__=='__main__':unittest.main()
