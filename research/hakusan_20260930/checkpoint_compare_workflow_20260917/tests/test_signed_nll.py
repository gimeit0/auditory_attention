"""Signed-difference supplement tests; no model inference or remote operations."""

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "signed_review", Path(__file__).resolve().parents[1] / "review_s2_results.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SignedTests(unittest.TestCase):
    def test_direction_and_population_std(self):
        r = m.signed_difference([3, 7], [2, 4])
        self.assertEqual((r["mean"], r["std"], r["max_abs"]), (2, 1, 3))
        self.assertEqual(r["positive_count"], 2)
        self.assertEqual(r["std_ddof"], 0)

    def test_zero_mean_can_hide_large_differences(self):
        r = m.signed_difference([4, 2], [2, 4])
        self.assertEqual((r["mean"], r["std"], r["max_abs"]), (0, 2, 2))
        self.assertEqual((r["positive_count"], r["negative_count"]), (1, 1))

    def test_swapping_changes_only_sign_and_counts(self):
        a, b = m.signed_difference([1, 3], [2, 6]), m.signed_difference([2, 6], [1, 3])
        self.assertEqual(a["mean"], -b["mean"])
        self.assertEqual(a["std"], b["std"])
        self.assertEqual(a["max_abs"], b["max_abs"])

    def test_empty_and_singleton(self):
        self.assertIsNone(m.signed_difference([], [])["std"])
        self.assertEqual(m.signed_difference([1], [2])["std"], 0)

    def test_invalid_pair_shapes(self):
        for a, b in [([1, 2], [1]), ([[1]], [[1]]), (1, 1)]:
            with self.subTest(a=a), self.assertRaises(ValueError):
                m.signed_difference(a, b)

    def test_nonfinite_rejected(self):
        for x in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(x=x), self.assertRaises(ValueError):
                m.signed_difference([x], [1])


if __name__ == "__main__":
    unittest.main()
