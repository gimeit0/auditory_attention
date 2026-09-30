"""Offline 756262 anchor comparator: real arrays against themselves, and single-bit changes."""
import copy
import unittest
import numpy as np
import fine_alpha_v4_anchor as anchor
from analyze_fine_alpha_756262 import load_block, COLLECTED


class AnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = {'C': load_block(COLLECTED/'state/attempt/C/output', {})}

    def v4(self):
        c = self.old['C']
        return {'A': {('A',)+k[1:]: dict(v) for k, v in c.items()}, 'B': {('B',)+k[1:]: dict(v) for k, v in c.items()}}

    def test_identical_bits_pass(self):
        r = anchor.compare(self.v4(), self.old)
        self.assertTrue(r['passed']); self.assertEqual(r['arrays_compared'], 12)

    def test_any_single_change_fails(self):
        for block, p, field in (('A', 'alpha_0500', 'logits'), ('B', 'alpha_0750', 'nll'), ('B', 'alpha_0750', 'trial_ids')):
            v4 = self.v4(); key = (block, 'clean', p, 'zero_cue'); row = dict(v4[block][key])
            row[field] = np.array(row[field], copy=True)
            if field == 'trial_ids': row[field][[0, 1]] = row[field][[1, 0]]
            else: row[field].flat[0] = np.nextafter(row[field].flat[0], np.inf)
            v4[block][key] = row
            with self.subTest(field=field):
                r = anchor.compare(v4, self.old)
                self.assertFalse(r['passed']); self.assertEqual(r['status'], 'V4_ANCHOR_MISMATCH_756262')

    def test_mapping(self):
        self.assertEqual(anchor.ANCHORS, {'alpha_0500': ('A', 'C'), 'alpha_0750': ('B', 'C')})


if __name__ == '__main__': unittest.main()
