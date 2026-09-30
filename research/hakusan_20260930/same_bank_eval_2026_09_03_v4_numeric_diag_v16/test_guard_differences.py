"""Bounded value-free rejection metadata, never a relaxed acceptance rule."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest

spec = importlib.util.spec_from_file_location(
    "guard_difference_tests", Path(__file__).with_name("diagnose_batch_invariance.py")
)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


class GuardDifferenceTests(unittest.TestCase):
    def public(self, before, after):
        error = diag._guard_mismatch_error(
            "post_reference_predict", "model_execution", 0, before, after
        )
        self.assertIn("lacks exact formal40 attestation", str(error))
        return diag._bounded_exception_diagnostic(error)["chain"][0]["guard_delta"]

    def test_scalar_paths_without_values(self):
        record = self.public(((1, "PRIVATE_SECRET"),), ((1, "OTHER_SECRET"),))
        self.assertEqual(record["component"], "model_execution")
        self.assertEqual(record["changes"], [{"path": [0, 1], "kind": "scalar"}])
        self.assertNotIn("SECRET", json.dumps(record))

    def test_sequence_length(self):
        self.assertEqual(
            self.public(((),), ((1,),))["changes"], [{"path": [0], "kind": "length"}]
        )

    def test_type_difference(self):
        self.assertEqual(
            self.public((1,), ("1",))["changes"], [{"path": [0], "kind": "type"}]
        )

    def test_hostile_leaf_not_executed(self):
        class Hostile:
            def __eq__(self, other):
                raise AssertionError("executed eq")

            def __repr__(self):
                raise AssertionError("executed repr")

        result = self.public((Hostile(),), (Hostile(),))
        self.assertEqual(result["changes"][0]["kind"], "opaque")

    def test_large_width_is_bounded(self):
        result = self.public(tuple(range(40000)), tuple(range(40000)))
        self.assertEqual(result["changes"][0]["kind"], "limit")
        self.assertLess(len(json.dumps(result)), 4096)

    def test_maximum_six_differences(self):
        result = self.public(tuple(range(100)), tuple(range(100, 200)))
        self.assertEqual(len(result["changes"]), 6)

    def test_deep_sequence_is_bounded(self):
        a, b = 1, 2
        for _ in range(150):
            a, b = (a,), (b,)
        result = self.public(a, b)
        self.assertEqual(result["changes"][0]["kind"], "limit")
        self.assertLessEqual(len(result["changes"][0]["path"]), 32)

    def test_malformed_metadata_not_exposed(self):
        error = diag.DiagnosticError("private")
        for metadata in (
            None,
            object(),
            ("SECRET", 0, ()),
            ("model_execution", -1, ()),
            ("model_execution", 0, (((), "SECRET"),)),
        ):
            error._guard_delta = metadata
            self.assertNotIn(
                "guard_delta", diag._bounded_exception_diagnostic(error)["chain"][0]
            )

    def test_unsupported_component_rejected_without_data(self):
        with self.assertRaisesRegex(ValueError, "component"):
            diag._guard_mismatch_error("test", "SECRET", 0, (), ())


if __name__ == "__main__":
    unittest.main()
