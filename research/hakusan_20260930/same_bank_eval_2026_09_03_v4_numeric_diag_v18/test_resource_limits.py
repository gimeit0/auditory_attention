"""Approved v18 time bounds and exact delta from the SHA-pinned v17 release."""

import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "same_bank_eval_2026_09_03_v4_numeric_diag_v17"
spec = importlib.util.spec_from_file_location(
    "resource_limit_diag", HERE / "diagnose_batch_invariance.py"
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


def versioned(source):
    return source.replace("20260903_v17", "20260903_v18").replace(
        "2026-09-03_v17", "2026-09-03_v18"
    )


class ResourceLimitsTests(unittest.TestCase):
    def launcher(self, **kwargs):
        return diag._ColdChildLauncher(
            "123", "a" * 64, "/tmp/audattn_v4_numdiag_123", **kwargs
        )

    def test_default_is_ninety_minutes(self):
        self.assertEqual(self.launcher().timeout_seconds, 5400.0)

    def test_ninety_minute_boundary_is_accepted(self):
        for value in (5400, 5400.0):
            with self.subTest(value=value):
                self.assertEqual(self.launcher(timeout_seconds=value).timeout_seconds, value)

    def test_values_immediately_above_boundary_are_rejected(self):
        for value in (5400.000001, 5401, 14400):
            with self.subTest(value=value), self.assertRaises(diag.DiagnosticError):
                self.launcher(timeout_seconds=value)

    def test_lower_positive_overrides_remain_bounded(self):
        for value in (0.1, 1, 3000, 3600, 3601):
            with self.subTest(value=value):
                self.assertEqual(self.launcher(timeout_seconds=value).timeout_seconds, value)

    def test_nonpositive_and_nonfinite_are_rejected(self):
        for value in (0, -0.1, -1, float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(diag.DiagnosticError):
                self.launcher(timeout_seconds=value)

    def test_non_native_numeric_types_are_rejected(self):
        class FloatSubclass(float):
            pass

        for value in (True, False, "5400", None, FloatSubclass(5400)):
            with self.subTest(value=repr(value)), self.assertRaises(diag.DiagnosticError):
                self.launcher(timeout_seconds=value)

    def test_initialization_does_not_start_or_wait_for_a_child(self):
        with mock.patch.object(diag.subprocess, "Popen") as popen:
            launcher = self.launcher()
        popen.assert_not_called()
        self.assertIsNone(launcher._active)
        self.assertEqual(launcher._attempted, set())

    def test_exact_diagnostic_delta_only_version_and_two_time_values(self):
        old = (PREVIOUS / "diagnose_batch_invariance.py").read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         "f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86")
        expected = versioned(old.decode()).replace(
            "timeout_seconds=3000.0", "timeout_seconds=5400.0"
        ).replace("0 < timeout_seconds <= 3600", "0 < timeout_seconds <= 5400")
        # This protects all matrix, numerics, mutable guards, signals and cleanup code.
        self.assertEqual((HERE / "diagnose_batch_invariance.py").read_text(), expected)

    def test_exact_runner_delta_only_version_and_four_hour_time(self):
        old = (PREVIOUS / "run_numeric_diag.sbatch").read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         "fd469355ed73e73878fbca8edc0590776c00083c156312c5f39f2b1deb0d34e3")
        expected = versioned(old.decode()).replace(
            "#SBATCH --time=01:00:00", "#SBATCH --time=04:00:00"
        )
        actual = (HERE / "run_numeric_diag.sbatch").read_text()
        self.assertEqual(actual, expected)
        self.assertEqual(actual.count("#SBATCH --time="), 1)
        for flag in ("--gpus=1", "--cpus-per-task=8", "--nodes=1", "--no-requeue"):
            self.assertIn("#SBATCH " + flag + "\n", actual)

    def test_submitter_is_version_only(self):
        old = (PREVIOUS / "submit_numeric_diag.py").read_bytes()
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         "3ae558e4d80193a8c3d2697b0c7a6e2283c7bad46a1acbcec1a2aaf4e0a967a9")
        self.assertEqual((HERE / "submit_numeric_diag.py").read_text(), versioned(old.decode()))

    def test_trace_is_byte_identical(self):
        data = (HERE / "numeric_trace.py").read_bytes()
        self.assertEqual(data, (PREVIOUS / "numeric_trace.py").read_bytes())
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b")

    def test_all_old_tests_preserved_only_approved_expectations_change(self):
        old_tests = sorted(PREVIOUS.glob("test_*.py"))
        self.assertEqual(len(old_tests), 22)
        for path in old_tests:
            expected = versioned(path.read_text())
            if path.name == "test_numeric_diag.py":
                expected = expected.replace("True, 0, -1, 3601,", "True, 0, -1, 5401,")
            if path.name == "test_submit_numeric_diag.py":
                expected = expected.replace('"--time=01:00:00"', '"--time=04:00:00"')
            with self.subTest(name=path.name):
                self.assertEqual((HERE / path.name).read_text(), expected)


if __name__ == "__main__":
    unittest.main()
