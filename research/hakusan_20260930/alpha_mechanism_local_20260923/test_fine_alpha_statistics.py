"""Synthetic checks for the fine-alpha readout statistics; no real data required."""
import unittest
import numpy as np
import fine_alpha_statistics as fs


def bank(n=6):
    return {i: dict(target_label=str(i % 3), target_speaker=f's{i % 3}', snr_bin='0', distractor_count='1',
                    scene_kind='mixed') for i in range(n)}


def arr(ids, pred, nll=0.0):
    logits = np.full((len(ids), 800), -5.0, dtype=np.float32); logits[np.arange(len(ids)), pred] = 5.0
    return dict(trial_ids=np.array(ids), logits=logits, nll=np.full(len(ids), nll, dtype=np.float32))


class GridTests(unittest.TestCase):
    def test_grid_codes_and_blocks(self):
        self.assertEqual(len(fs.CODES), 54); self.assertEqual(len(fs.FINE), 51)
        self.assertEqual([fs.value(c) for c in fs.CODES[-3:]], [0.75, 0.875, 1.0])
        self.assertEqual([fs.BLOCK_OF[c] for c in ('alpha_0170', 'alpha_0180', 'alpha_0350', 'alpha_0360', 'alpha_1000')],
                         ['A', 'B', 'B', 'C', 'C'])
        self.assertEqual(sum(v == 'A' for v in fs.BLOCK_OF.values()), 18)

    def test_first_passage_requires_staying_above(self):
        curve = [0]*51; curve[10] = 5; curve[40:] = [5]*11
        self.assertEqual(fs.first_passage(curve, 5), 0.40)
        self.assertIsNone(fs.first_passage([0]*51, 1))
        self.assertEqual(fs.first_passage([2]*51, 1), 0.0)

    def test_monotonicity_counts_decreases(self):
        curve = list(range(51)); curve[20] = 25
        m = fs.monotonicity(curve)
        self.assertEqual(m['decreasing_steps'], 1); self.assertEqual(m['decreases'][0]['from_alpha'], 0.20)

    def test_missing_array_and_order(self):
        with self.assertRaisesRegex(ValueError, 'MISSING'): fs.check_grid({})
        ids = [0, 1, 2]
        arrays = {(d, p, c): arr(ids, [0, 1, 2]) for p in fs.CODES for d, cs in (('main', fs.MAIN), ('clean', fs.CLEAN)) for c in cs}
        fs.check_grid(arrays)
        arrays['main', 'alpha_0500', 'silent'] = arr([2, 1, 0], [0, 1, 2])
        with self.assertRaisesRegex(ValueError, 'TRIAL_ORDER'): fs.check_grid(arrays)

    def test_control_d_keeps_alpha0_residual(self):
        ids = list(range(6)); b = bank()
        arrays = {}
        for p in fs.CODES:
            for c in fs.MAIN:
                pred = [0, 1, 2, 0, 1, 2] if c == 'correct' else [1, 2, 0, 1, 2, 0]
                if p == 'alpha_0000' and c == 'correct': pred = [0, 2, 0, 1, 2, 0]   # residual: 1 trial right
                arrays['main', p, c] = arr(ids, pred)
        cols = fs.control_columns(arrays, ids, b)
        self.assertEqual(cols['alpha_0000/correct_minus_shuffled/accuracy_pp'].tolist(), [100, 0, 0, 0, 0, 0])
        self.assertEqual(cols['alpha_1000/D_pp'].tolist(), [0, 100, 100, 100, 100, 100])


if __name__ == '__main__': unittest.main()
