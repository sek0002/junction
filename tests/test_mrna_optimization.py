"""Uridine depletion respects immutable codons while remaining a hard constraint elsewhere."""
from pathlib import Path
import unittest
from app.mrna import Batch, Record, Parameters, invoke, runtime_config
from app.mrna_optimization import mutable_regions


class PreservedUridineTests(unittest.TestCase):
    def test_overlaps_adjacent_regions_and_terminal_codons(self):
        self.assertEqual(mutable_regions(30, [(16, 21), (4, 9), (7, 15), (25, 30)]),
                         [(1, 3), (22, 24)])
        self.assertEqual(mutable_regions(30, [(1, 30)]), [])
        self.assertEqual(mutable_regions(30, []), [(1, 30)])

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(), 'Optional scientific runtime')
    def test_real_depletion_only_changes_unprotected_wobble_codons(self):
        sequence = 'ATG' + 'GATAGT' + 'GCT' * 15 + 'TAA'
        params = Parameters(enable_uridine_depletion=True, gc_global_min=0, gc_global_max=1,
            gc_window_min=0, gc_window_max=1, avoid_repeat_length=None,
            avoid_poly_a=None, avoid_poly_t=None, avoid_poly_c=None, avoid_poly_g=None)
        for preserved in ([], [(4, 6), (7, 9)], [(1, len(sequence))]):
            with self.subTest(preserved=preserved):
                batch = Batch(mode='design', parameters=params,
                    records=[Record(name='Locked GAT and AGT', sequence=sequence,
                                    preserve_regions=preserved)]).model_dump()
                result = invoke({'action':'run', 'batch':batch, 'record':batch['records'][0], 'index':0})
                self.assertFalse(result['errors'], result['errors'])
                before, after = result['rows']
                self.assertEqual(before['protein'], after['protein'])
                locked = {i for a,b in preserved for i in range(a-1,b)}
                for i in range(0, len(sequence), 3):
                    if i in locked:
                        self.assertEqual(after['cds'][i:i+3], sequence[i:i+3])
                    else:
                        self.assertNotEqual(after['cds'][i+2], 'T')
                if preserved:
                    self.assertEqual(after['optimization']['uridine_depletion']['exempt_regions'],
                                     [list(r) for r in preserved])

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(), 'Optional scientific runtime')
    def test_other_hard_constraints_are_not_exempted_at_junctions(self):
        sequence = 'ATG' + 'GATAGT' + 'GCT' * 15 + 'TAA'
        params = Parameters(enable_uridine_depletion=True, avoid_sequences=['GATAGT'],
            gc_global_min=0, gc_global_max=1, gc_window_min=0, gc_window_max=1,
            avoid_repeat_length=None, avoid_poly_a=None, avoid_poly_t=None,
            avoid_poly_c=None, avoid_poly_g=None)
        batch = Batch(mode='design', parameters=params, records=[Record(name='Motif conflict',
            sequence=sequence, preserve_regions=[(4,9)])]).model_dump()
        result = invoke({'action':'run', 'batch':batch, 'record':batch['records'][0], 'index':0})
        self.assertTrue(result['errors'])
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['cds'], sequence)
