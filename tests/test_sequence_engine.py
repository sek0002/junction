import csv
import unittest
from pathlib import Path

from app.sequence_engine import (
    assemble, digest_fragment, find_backbone_slots, prepare_backbone,
    restriction_sites, reverse_complement,
)


def donor(left, target, right, enzyme="BsaI"):
    forward, reverse = ("GGTCTC", "GAGACC") if enzyme == "BsaI" else ("CGTCTC", "GAGACG")
    return "GCGT" + forward + "A" + left + target + right + "C" + reverse + "ACGCA"


def backbone(left="TTTG", right="TTTC"):
    return "ACGCAA" + left + "C" + "GAGACC" + "AAAGATATC" + "GGTCTC" + "A" + right + "AACCGG"


def retained_bsmBI_cassette(left, right):
    return left + "C" + "GAGACG" + "AAAGATATC" + "CGTCTC" + "A" + right


class GoldenGateTests(unittest.TestCase):
    def test_reverse_complement_resolves_whole_fragment_and_preserves_forward_preference(self):
        from app.sequence_engine import fragment_orientations
        for enzyme in ('BsaI','BsmBI','BsmBI + BsaI'):
            adapter='BsmBI' if enzyme=='BsmBI' else 'BsaI'
            first=donor('TTTG','AACCGG','ATGG',adapter)
            second=donor('CAAA','ACCTGA','CCAT',adapter)
            variants=fragment_orientations(second,enzyme)
            self.assertEqual(variants[1]['sequence'],reverse_complement(variants[0]['sequence']))
            result=assemble([{'id':1,'name':'First','sequence':first},{'id':2,'name':'Reverse','sequence':second}],enzyme,circular=None)
            self.assertTrue(result['valid'],result['errors']);self.assertTrue(result['circular'])
            self.assertEqual(result['sequence'],'TTTGAACCGGATGGTCAGGT')
            self.assertEqual([c['reverse_complement'] for c in result['fragment_checks']],[False,True])
            feature=next(f for f in result['features'] if f.get('fragment_id')==2)
            self.assertEqual(feature['strand'],-1)
            already_forward=assemble([{'sequence':first},{'sequence':reverse_complement(second)}],enzyme,circular=None)
            self.assertTrue(already_forward['valid']);self.assertFalse(any(c['reverse_complement'] for c in already_forward['fragment_checks']))

    def test_reverse_orientation_still_reports_internal_active_sites(self):
        second=donor('CAAA','AAAGGTCTCAAA','CCAT')
        result=assemble([{'sequence':donor('TTTG','AACCGG','ATGG')},{'sequence':second}],'BsaI',circular=None)
        self.assertFalse(result['valid'])
        self.assertTrue(result['fragment_checks'][1]['reverse_complement'])
        self.assertTrue(any('Internal BsaI' in e for e in result['fragment_checks'][1]['errors']))

    def test_dual_digest_mixes_adapter_enzymes_and_donors(self):
        mixed=donor('TTTG','AACCGG','ATGG').replace('GGTCTC','CGTCTC')
        digest=digest_fragment(mixed,'BsmBI + BsaI')
        self.assertTrue(digest['valid'],digest['errors'])
        self.assertEqual((digest['left_adapter_enzyme'],digest['right_adapter_enzyme']),('BsmBI','BsaI'))
        result=assemble([{'name':'mixed','sequence':mixed},
            {'name':'BsaI','sequence':donor('ATGG','CCAAAA','TTTG')}], 'BsmBI + BsaI',circular=None)
        self.assertTrue(result['valid'],result['errors'])
        self.assertTrue(result['circular'])
        self.assertEqual(result['sequence'],'TTTGAACCGGATGGCCAAAA')
        self.assertEqual(result['retained_cassettes'],[])

    def test_dual_digest_checks_both_internal_enzymes(self):
        for motif in ('CGTCTC','GAGACG','GGTCTC','GAGACC'):
            seq=donor('TTTG','AA'+motif+'AA','ATGG')
            result=digest_fragment(seq,'BsmBI + BsaI')
            self.assertFalse(result['valid'],motif)
            self.assertTrue(any('Internal ' in message for message in result['errors']))
        seq=donor('TTTG','AAGAGACGAA','ATGG')
        self.assertTrue(digest_fragment(seq,'BsaI')['valid'])
        self.assertFalse(digest_fragment(seq,'BsmBI + BsaI')['valid'])

    def test_dual_backbone_supports_mixed_cassette_and_origin_rotation(self):
        seq=backbone().replace('GAGACC','GAGACG')
        expected=prepare_backbone(seq,'BsmBI + BsaI')
        self.assertTrue(expected['valid'],expected['errors'])
        self.assertEqual((expected['left_overhang'],expected['right_overhang']),('TTTC','TTTG'))
        for offset in range(len(seq)):
            digest=prepare_backbone(seq[offset:]+seq[:offset],'BsmBI + BsaI')
            self.assertTrue(digest['valid'],digest['errors'])
            self.assertEqual(digest['sequence'],expected['sequence'])
        self.assertTrue(assemble([{'name':'insert','sequence':donor('TTTG','AACCGG','TTTC', 'BsmBI')}],
            'BsmBI + BsaI',backbone={'name':'vector','sequence':seq})['valid'])

    def test_cassette_labels_follow_boundary_enzymes_in_dual_mode(self):
        sequences=[(backbone(),'BsaI','BsaI','BsaI'),
            (backbone().replace('GGTCTC','CGTCTC').replace('GAGACC','GAGACG'),'BsmBI','BsmBI','BsmBI'),
            (backbone().replace('GAGACC','GAGACG'),'Dual cut','BsmBI','BsaI'),
            (backbone().replace('GGTCTC','CGTCTC'),'Dual cut','BsaI','BsmBI')]
        for sequence,kind,left_enzyme,right_enzyme in sequences:
            slots=find_backbone_slots(sequence,'BsmBI + BsaI')
            self.assertEqual(len(slots),1)
            slot=slots[0]
            self.assertTrue(slot['label'].startswith(kind+' cassette 1:'))
            self.assertEqual(slot['cut_type'],kind)
            self.assertEqual((slot['left_boundary_enzyme'],slot['right_boundary_enzyme']),(left_enzyme,right_enzyme))
            for offset in range(len(sequence)):
                rotated=find_backbone_slots(sequence[offset:]+sequence[:offset],'BsmBI + BsaI')[0]
                self.assertEqual(rotated['label'],slot['label'])

    def test_dual_backbone_rejects_other_active_cuts(self):
        seq=backbone()+'AACGTCTCAAAA'
        self.assertTrue(prepare_backbone(seq,'BsaI')['valid'])
        self.assertFalse(prepare_backbone(seq,'BsmBI + BsaI')['valid'])

    def test_dual_checks_both_sites_created_at_circle_origin(self):
        for leading,enzyme in [('G','BsaI'),('C','BsmBI')]:
            first=donor('GTCT','CAAAA','ATGG')
            second=donor('ATGG','AAC'+leading,'GTCT').replace('GTCTCGAGACC','GTCTAGAGACC')
            result=assemble([{'name':'a','sequence':first},{'name':'b','sequence':second}],
                'BsmBI + BsaI',circular=None)
            self.assertFalse(result['valid'])
            self.assertTrue(any(s['enzyme']==enzyme and s['wraps_origin'] for s in result['restriction_sites']))
            self.assertTrue(all(any('Retained '+enzyme in e for e in c['errors']) for c in result['fragment_checks']))

    def test_digest_removes_outer_sites_and_buffers(self):
        result = digest_fragment(donor("TTTG", "AACCGG", "ATGG"), "BsaI")
        self.assertEqual(result["sequence"], "TTTGAACCGGATGG")
        self.assertEqual(result["target"], "AACCGG")
        self.assertEqual(result["errors"], [])
        self.assertEqual(restriction_sites(result["sequence"]), [])

    def test_internal_other_enzyme_is_preserved(self):
        target = "AAGAGACGTTTAGTCGTCTCAA"
        result = digest_fragment(donor("TTTG", target, "ATGG"), "BsaI")
        self.assertEqual(result["target"], target)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len([s for s in restriction_sites(result["sequence"]) if s["enzyme"] == "BsmBI"]), 2)

    def test_internal_selected_enzyme_is_error(self):
        result = digest_fragment(donor("TTTG", "AAAGGTCTCAA", "ATGG"), "BsaI")
        self.assertFalse(result["valid"])
        self.assertTrue(any("Internal BsaI" in message for message in result["errors"]))

    def test_bsmBI_and_whitespace(self):
        result = digest_fragment(" \n" + donor("TTTG", "AACCGG", "ATGG", "BsmBI").lower(), "bsmbi")
        self.assertEqual(result["sequence"], "TTTGAACCGGATGG")
        self.assertTrue(result["valid"])

    def test_bad_sequence_and_missing_adapters(self):
        self.assertFalse(digest_fragment("NACG", "BsaI")["valid"])
        self.assertFalse(digest_fragment("ACGTACGT", "BsaI")["valid"])

    def test_backbone_cut_labels_and_retained_sequence(self):
        seq = backbone()
        slots = find_backbone_slots(seq, "BsaI")
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["left_overhang"], "TTTG")
        self.assertEqual(slots[0]["right_overhang"], "TTTC")
        result = prepare_backbone(seq, "BsaI")
        self.assertEqual(result["left_overhang"], "TTTC")
        self.assertEqual(result["right_overhang"], "TTTG")
        self.assertEqual(result["sequence"], "TTTCAACCGGACGCAATTTG")
        self.assertTrue(result["valid"])

    def test_backbone_rotation_across_origin(self):
        seq = backbone()
        reference = prepare_backbone(seq, "BsaI")["sequence"]
        for offset in range(len(seq)):
            rotated = seq[offset:] + seq[:offset]
            result = prepare_backbone(rotated, "BsaI")
            self.assertTrue(result["valid"], (offset, result))
            self.assertEqual(result["sequence"], reference)

    def test_multiple_backbone_cassettes_are_not_silently_ignored(self):
        seq = backbone() + backbone("ATGG", "GTTC")
        slots = find_backbone_slots(seq, "BsaI")
        self.assertEqual(len(slots), 2)
        self.assertTrue(all(slot["errors"] for slot in slots))
        self.assertFalse(prepare_backbone(seq, "BsaI")["valid"])
        self.assertFalse(prepare_backbone(seq, "BsaI", slots[0]["id"])["valid"])

    def test_circular_assembly_and_junctions(self):
        parts = [{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                 {"name": "b", "sequence": donor("ATGG", "CCAAAA", "GTTC")},
                 {"name": "c", "sequence": donor("GTTC", "GCAACC", "TTTG")}]
        result = assemble(parts, "BsaI")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sequence"], "TTTGAACCGGATGGCCAAAAGTTCGCAACC")
        self.assertEqual(len(result["junctions"]), 3)
        self.assertTrue(result["junctions"][-1]["circular_closure"])
        self.assertEqual(result["restriction_sites"], [])
        self.assertTrue(all(check["valid"] for check in result["fragment_checks"]))

    def test_assembly_with_vector(self):
        result = assemble([{"name": "donor", "sequence": donor("TTTG", "AACGCC", "TTTC")}],
                          "BsaI", {"name": "vector", "sequence": backbone()})
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sequence"], "TTTCAACCGGACGCAATTTGAACGCC")
        self.assertEqual(len(result["junctions"]), 2)

    def test_linear_product_has_both_terminal_labels(self):
        result = assemble([{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                           {"name": "b", "sequence": donor("ATGG", "CCAAAA", "GTTC")}],
                          "BsaI", circular=False)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sequence"], "TTTGAACCGGATGGCCAAAAGTTC")

    def test_auto_detects_circular_fragment_chain(self):
        parts = [{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                 {"name": "b", "sequence": donor("ATGG", "CCAAAA", "GTTC")},
                 {"name": "c", "sequence": donor("GTTC", "GCAACC", "TTTG")}]
        result = assemble(parts, "BsaI", circular=None)
        explicit = assemble(parts, "BsaI", circular=True)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["circular"])
        self.assertTrue(result["circular_detected"])
        self.assertTrue(result["topology_auto_detected"])
        self.assertEqual(result["topology"], "circular")
        self.assertEqual(result["sequence"], explicit["sequence"])
        self.assertEqual(len(result["junctions"]), 3)

    def test_auto_open_chain_is_linear_without_a_failed_closure(self):
        parts = [{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                 {"name": "b", "sequence": donor("ATGG", "CCAAAA", "GTTC")}]
        result = assemble(parts, "BsaI", circular=None)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["circular"])
        self.assertFalse(result["circular_detected"])
        self.assertEqual(result["topology"], "linear")
        self.assertEqual(result["sequence"], "TTTGAACCGGATGGCCAAAAGTTC")
        self.assertEqual(len(result["junctions"]), 1)
        self.assertFalse(any(item["circular_closure"] for item in result["junctions"]))

    def test_auto_matching_ends_do_not_hide_an_internal_mismatch(self):
        parts = [{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                 {"name": "b", "sequence": donor("TCTG", "CCAAAA", "CCTA")},
                 {"name": "c", "sequence": donor("GAGA", "AACC", "TTTG")}]
        result = assemble(parts, "BsaI", circular=None)
        self.assertFalse(result["valid"])
        self.assertFalse(result["circular"])
        self.assertFalse(result["circular_detected"])
        self.assertIn("ATGGTCTG", result["sequence"])
        self.assertTrue(any("Incompatible junction a → b" in item for item in result["errors"]))
        self.assertFalse(any("Incompatible junction c → a" in item for item in result["errors"]))

    def test_auto_single_self_closing_donor_deduplicates_terminal_label(self):
        result = assemble([{"name": "a", "sequence": donor("TTTG", "AACCGG", "TTTG")}],
                          "BsaI", circular=None)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["circular"])
        self.assertEqual(result["sequence"], "TTTGAACCGG")
        self.assertEqual(len(result["junctions"]), 1)
        self.assertTrue(result["junctions"][0]["circular_closure"])

    def test_auto_does_not_call_invalid_digests_circular(self):
        for sequence in (donor("TTTG", "AAAGGTCTCAA", "TTTG"), "NACG"):
            result = assemble([{"name": "a", "sequence": sequence}], "BsaI", circular=None)
            self.assertFalse(result["valid"])
            self.assertFalse(result["circular"])
            self.assertFalse(result["circular_detected"])
            self.assertEqual(result["topology"], "linear")

    def test_auto_empty_assembly_is_invalid_linear(self):
        result = assemble([], "BsaI", circular=None)
        self.assertFalse(result["valid"])
        self.assertFalse(result["circular"])
        self.assertEqual(result["sequence"], "")
        self.assertEqual(result["topology"], "linear")

    def test_explicit_circular_still_requires_a_matching_closure(self):
        result = assemble([{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")}],
                          "BsaI", circular=True)
        self.assertFalse(result["valid"])
        self.assertTrue(result["circular"])
        self.assertFalse(result["circular_detected"])
        self.assertFalse(result["topology_auto_detected"])
        self.assertTrue(any("Incompatible junction a → a" in item for item in result["errors"]))

    def test_auto_checks_sites_created_across_circular_origin(self):
        first = donor("GTCT", "CAAAA", "ATGG")
        second = donor("ATGG", "AACG", "GTCT").replace("GTCTCGAGACC", "GTCTAGAGACC")
        self.assertTrue(digest_fragment(first, "BsaI")["valid"])
        self.assertTrue(digest_fragment(second, "BsaI")["valid"])
        result = assemble([{"name": "a", "sequence": first}, {"name": "b", "sequence": second}],
                          "BsaI", circular=None)
        self.assertTrue(result["circular_detected"])
        self.assertFalse(result["valid"])
        sites = [item for item in result["restriction_sites"] if item["enzyme"] == "BsaI"]
        self.assertEqual(len(sites), 1)
        self.assertTrue(sites[0]["wraps_origin"])
        self.assertTrue(all(any("Retained BsaI" in message for message in check["errors"])
                            for check in result["fragment_checks"]))

    def test_actual_pIVT_fragments_close_but_prefix_does_not(self):
        source = Path(__file__).resolve().parents[1] / "examples" / "platemap_pSHPs0921B1498017B.csv"
        with source.open() as stream:
            rows = {row["Name"].split(" ")[0]: row for row in csv.DictReader(stream)}
        parts = [{"name": rows[name]["Name"], "sequence": rows[name]["Construct Sequence (Insert + Adapters)"]}
                 for name in ("F1", "F2", "F4", "F10", "F11")]
        closed = assemble(parts, "BsaI", circular=None)
        self.assertTrue(closed["valid"], closed["errors"])
        self.assertTrue(closed["circular"])
        self.assertEqual(closed["length"], 2827)
        prefix = assemble(parts[:2], "BsaI", circular=None)
        self.assertTrue(prefix["valid"], prefix["errors"])
        self.assertFalse(prefix["circular"])
        self.assertEqual(prefix["length"], 2031)
        reordered = assemble([parts[0], parts[2], parts[1], *parts[3:]], "BsaI", circular=None)
        self.assertFalse(reordered["valid"])
        self.assertFalse(reordered["circular"])

    def test_incompatible_junction_preserves_unmatched_labels(self):
        result = assemble([{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                           {"name": "b", "sequence": donor("TCTG", "CCAAAA", "GTTC")}],
                          "BsaI", circular=False)
        self.assertFalse(result["valid"])
        self.assertIn("ATGGTCTG", result["sequence"])
        self.assertFalse(result["junctions"][0]["compatible"])
        self.assertTrue(all(any("Incompatible junction a → b" in message for message in check["errors"])
                            for check in result["fragment_checks"]))

    def test_reverse_complement_fusion_collision(self):
        result = assemble([{"name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
                           {"name": "b", "sequence": donor("ATGG", "CCAAAA", "CCAT")}],
                          "BsaI", circular=False)
        self.assertFalse(result["valid"])
        self.assertTrue(any("collision" in message for message in result["errors"]))
        self.assertTrue(all(any("collision" in message for message in check["errors"])
                            for check in result["fragment_checks"]))

    def test_fragment_checks_keep_unaffected_fragments_valid(self):
        result = assemble([
            {"id": 1, "name": "a", "sequence": donor("TTTG", "AACCGG", "ATGG")},
            {"id": 2, "name": "b", "sequence": donor("ATGG", "CCAAAA", "GTTC")},
            {"id": 3, "name": "c", "sequence": donor("AGTT", "CCAACC", "TCTA")},
        ], "BsaI", circular=False)
        self.assertFalse(result["valid"])
        self.assertEqual([check["valid"] for check in result["fragment_checks"]], [True, False, False])

    def test_fragment_checks_report_digest_failure(self):
        result = assemble([{"id": 1, "name": "bad", "sequence": "ACGTACGT"}], "BsaI", circular=None)
        self.assertFalse(result["fragment_checks"][0]["valid"])
        self.assertTrue(result["fragment_checks"][0]["errors"])

    def test_restriction_site_across_circle_origin(self):
        seq = "CTCAAAAGGT"
        self.assertFalse(any(site["enzyme"] == "BsaI" for site in restriction_sites(seq)))
        sites = [site for site in restriction_sites(seq, True) if site["enzyme"] == "BsaI"]
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["start"], 7)
        self.assertTrue(sites[0]["wraps_origin"])

    def test_palindromic_hindIII_counted_once(self):
        sites = restriction_sites("AAAGCTTAA")
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["enzyme"], "HindIII")

    def test_reverse_complement_utility(self):
        self.assertEqual(reverse_complement("aagc"), "GCTT")

    def test_historical_F21_four_fragment_reconstruction(self):
        sequence = (
            "caaaagcctaggcctccaaaaaagcctcctcactacttctggaatagctcagaggccgaggcggcctcggcctctgcataaataaaaaaaattagtcagccatggggcggagaatgggcggaactgggcggagttaggggcgggatgggcggagttaggggcgggactatggttgctgactaattgagatgcatgctttgcatacttctgcctgctggggagcctggggactttccacacctggttgctgactaattgagatgcatgctttgcatacttctgcctgctggggagcctggggactttccacaccctaactgacacacattccacagctgcattaatgaatcggccaacgcgcggggagaggcggtttgcgtattgggcgctcttccgcttcctcgctcactgactcgctgcgctcggtcgttcggctgcggcgagcggtatcagctcactcaaaggcggtaatacggttatccacagaatcaggggataacgcaggaaagaacatgtgagcaaaaggccagcaaaaggccaggaaccgtaaaaaggccgcgttgctggcgtt"
        ).upper()
        self.assertEqual(len(sequence), 571)
        targets = [sequence[:144], sequence[148:278], sequence[282:428], sequence[432:]]
        labels = ["TTTG", "ATGG", "TCTG", "GTTC", "TTTC"]
        parts = [{"name": name, "sequence": donor(labels[i], target, labels[i + 1])}
                 for i, (name, target) in enumerate(zip(["F21(mod)", "F24", "F25", "F26"], targets))]
        result = assemble(parts, "BsaI", circular=False)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["sequence"], "TTTG" + sequence + "TTTC")
        self.assertEqual(result["restriction_sites"], [])

    def test_retained_second_round_duplicate_GGTG_warns_first_round_remains_valid(self):
        payload = "AACCGG" + retained_bsmBI_cassette("AAAC", "GGTG") + "AACGCC" + retained_bsmBI_cassette("CGAG", "GGTG") + "AACCGG"
        result = assemble([{"name": "pULT example", "sequence": donor("TTTG", payload, "TTTG")}], "BsaI")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(len(result["retained_cassettes"]), 2)
        self.assertTrue(any("Second-round BsmBI overhang collision" in message and "GGTG" in message for message in result["warnings"]))
        self.assertTrue(any("4 recognition site(s)" in message for message in result["warnings"]))

    def test_distinct_second_round_cassettes_are_listed_without_collision(self):
        payload = "AACCGG" + retained_bsmBI_cassette("AAAC", "GGTG") + "AACGCC" + retained_bsmBI_cassette("TTGT", "GGGA") + "AACCGG"
        result = assemble([{"name": "pHR example", "sequence": donor("TTTG", payload, "TTTG")}], "BsaI")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual([(item["left_overhang"], item["right_overhang"]) for item in result["retained_cassettes"]], [("AAAC", "GGTG"), ("TTGT", "GGGA")])
        self.assertTrue(any("Donor compatibility has not been checked" in message for message in result["warnings"]))
        self.assertFalse(any("Second-round BsmBI overhang collision" in message for message in result["warnings"]))

    def test_SPLINTR_same_direction_extras_are_reported(self):
        payload = "AACCGGCGTCTCAAACCGGCGTCTCAACCGG" + retained_bsmBI_cassette("CGAG", "GGTG") + "AACCGG"
        result = assemble([{"name": "SPLINTR example", "sequence": donor("TTTG", payload, "TTTG")}], "BsaI")
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(len(result["retained_cassettes"]), 1)
        self.assertTrue(any("They face the same direction" in message for message in result["warnings"]))

    def test_site_created_only_after_fusion_is_an_active_enzyme_error(self):
        # A + GAGACC right adapter avoids a pre-existing GGTCTC across the
        # first donor's GTCT fusion label and its discarded spacer.
        first = donor("TTTG", "AACG", "GTCT").replace("GTCTCGAGACC", "GTCTAGAGACC")
        second = donor("GTCT", "CAAAA", "TTTC")
        self.assertTrue(digest_fragment(first, "BsaI")["valid"])
        self.assertTrue(digest_fragment(second, "BsaI")["valid"])
        result = assemble([{"name": "a", "sequence": first}, {"name": "b", "sequence": second}], "BsaI", circular=False)
        self.assertFalse(result["valid"])
        self.assertTrue(any("assembled product retains 1 BsaI" in message for message in result["errors"]))

    def test_extra_site_crossing_overhang_adapter_boundary_is_not_ignored(self):
        result = digest_fragment(donor("TTTG", "AACG", "GTCT"), "BsaI")
        self.assertFalse(result["valid"])
        self.assertTrue(any("adapter boundary" in message for message in result["errors"]))

    def test_second_round_linear_boundary_is_not_invented(self):
        # A reverse site at the left terminus lacks the upstream fusion label.
        result = assemble([{"name": "linear", "sequence": donor("TTTG", "GAGACGAAACGTCTCAATGG", "TTTC")}], "BsaI", circular=False)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["retained_cassettes"], [])


if __name__ == "__main__":
    unittest.main()
