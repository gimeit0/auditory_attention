import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("erratum", Path(__file__).resolve().parents[1] / "numeric_sensitivity_erratum.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BoundTests(unittest.TestCase):
    def test_two_logits_can_move_oppositely(self):
        self.assertEqual(module.near_tie_fraction([[0.006, 0]], 0.004), 1)
        self.assertGreater(0.004, 0.006 - 0.004)

    def test_boundary_and_safe_margin(self):
        self.assertEqual(module.near_tie_fraction([[0.008, 0], [0.009, 0]], 0.004), 0.5)

    def test_pair_needs_sum(self):
        self.assertEqual(module.paired_bound(0.002, 0.002), 0.004)

    def test_invalid_values(self):
        for x, e in [([[float("nan"), 0]], .004), ([[1, 0]], -1), ([], .004)]:
            with self.assertRaises(ValueError):
                module.near_tie_fraction(x, e)


if __name__ == "__main__":
    unittest.main()
