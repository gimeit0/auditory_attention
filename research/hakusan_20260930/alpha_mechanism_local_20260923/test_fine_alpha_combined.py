"""Combined 0-1 grid plumbing on real 756262 arrays with the v4 slots FAKED from 756262 copies (not science)."""
import csv
import unittest
import numpy as np
import fine_alpha_combined as fc
from analyze_fine_alpha_756262 import load_block, COLLECTED, PACKAGE


class CombinedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = {b: load_block(COLLECTED/'state/attempt'/b/'output', {}) for b in 'ABC'}
        new = {b: {} for b in 'AB'}
        for c in fc.NEW:
            b = fc.NEW_BLOCK[c]
            for d, conds in (('main', fc.MAIN), ('clean', fc.CLEAN)):
                for cond in conds: new[b][(b, d, fc.code(c), cond)] = cls.old['C'][('C', d, 'alpha_0750' if c >= 750 else 'alpha_0500', cond)]
        for d, conds in (('main', fc.MAIN), ('clean', fc.CLEAN)):
            for cond in conds: new['A'][('A', d, 'original', cond)] = cls.old['A'][('A', d, 'original', cond)]
        cls.new = new
        with (PACKAGE/'frozen_bank.tsv').open() as f: cls.bank = {int(r['trial_id']): r for r in csv.DictReader(f, delimiter='\t')}

    def test_grid(self):
        self.assertEqual(len(fc.GRID), 82); self.assertEqual(len(fc.FINE_REGION), 76)
        self.assertEqual(fc.GRID[-6:], (800, 850, 875, 900, 950, 1000))
        self.assertEqual([fc.NEW_BLOCK[c] for c in (500, 640, 650, 950)], ['A', 'A', 'B', 'B'])

    def test_assemble_sources_and_cross_job_original(self):
        arrays, source, checks = fc.assemble(self.old, self.new)
        self.assertEqual(source['alpha_0500'], ('756262', 'C')); self.assertEqual(source['alpha_0510'], ('757288', 'A'))
        self.assertEqual(source['alpha_0950'], ('757288', 'B')); self.assertEqual(source['alpha_0875'], ('756262', 'C'))
        self.assertTrue(all(checks.values()))
        broken = {b: dict(v) for b, v in self.new.items()}
        k = ('A', 'main', 'original', 'correct'); row = dict(broken['A'][k]); row['logits'] = row['logits'].copy(); row['logits'][0, 0] += 1
        broken['A'][k] = row
        self.assertFalse(fc.assemble(self.old, broken)[2]['original_cross_job/main/correct'])

    def test_sustained_onset_and_boundary(self):
        vals = [0, .1, .2, .3]
        self.assertEqual(fc.sustained_onset(vals, [0, 5, 0, 5], 5), .3)
        self.assertIsNone(fc.sustained_onset(vals, [0, 0, 0, 0], 1))
        part = {fc.code(c): dict(accuracy_below_half_original=c < 600, logit_above_ten_times_original=c < 700,
                                 collapse=c < 700) for c in fc.GRID}
        b = fc.collapse_boundary(part)
        self.assertEqual(b['accuracy_below_half_original']['first_free_alpha'], 0.6)
        self.assertEqual(b['collapse'], dict(first_free_alpha=0.7, last_flagged_alpha=0.69))

    def test_analyze_runs_on_full_grid(self):
        arrays, _, _ = fc.assemble(self.old, self.new)
        r = fc.analyze(arrays, self.bank)
        self.assertEqual(len(r['snr_bins']), 5); self.assertEqual(r['units']['main_mixed']['info']['trials'], 1800)
        self.assertEqual(r['transitions']['mixed']['point']['1pp'], 0.32)   # 0-0.50 part is the real 756262 curve


if __name__ == '__main__': unittest.main()
