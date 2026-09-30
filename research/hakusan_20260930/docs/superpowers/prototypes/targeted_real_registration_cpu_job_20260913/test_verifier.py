"""Synthetic verifier fixtures only; no production loading or remote call."""
import copy
import json
import unittest

import verify_registration as verify


def fixture():
    return {**verify.FIXED, "job_id": "123", "worker_pid": 456,
            "source_objects_restored": [], "strict_load_report": {
                "key_count": 61, "missing_keys": [], "unexpected_keys": [],
                "shape_mismatches": {}, "dtype_mismatches": {},
                "loaded_trainable_numel": 62622520, "trainable_numel": 62622520,
                "loaded_trainable_numel_ratio": 1.0, "prefix_rule": "exact",
                "native_preprocessing": "selftrain_singleton_per_example_leveling",
                "model_module": {"path": "/fixture/snapshot/files/src/spatial_attn_lightning.py",
                    "sha256": "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9",
                    "size": 37409}}}


def log(value):
    rows = [("CPU_CHILD_START=", {"pid": 456, "mode": "registration"}),
            ("REAL_REGISTRATION_BEGIN=", {"pid": 456, "job_id": "123", "cell": "B2"}),
            ("REAL_REGISTRATION_RESULT=", value)]
    return ("\n".join(p + json.dumps(v) for p, v in rows) + "\n").encode()


class VerifierTests(unittest.TestCase):
    def test_complete_synthetic_fixture(self):
        self.assertEqual(verify.verify_output(log(fixture()), "123", 456), fixture())

    def test_each_required_field_missing_rejected(self):
        for key in fixture():
            with self.subTest(key=key):
                value = fixture()
                del value[key]
                with self.assertRaises(RuntimeError):
                    verify.verify_result(value, "123", 456)

    def test_scientific_claims_rejected(self):
        for key, value in {"ready_for_gpu": True, "production_worker_issued": True,
                           "forward_calls": 1, "captures": 1, "cuda_initialized": True,
                           "production_preparation_validated": True,
                           "compiler_backend_entered": True}.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify.verify_result({**fixture(), key: value}, "123", 456)

    def test_missing_or_incomplete_cleanup_rejected(self):
        for key in ("hooks_removed", "compiler_authority_revoked", "temporary_directory_removed"):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify.verify_result({**fixture(), key: False}, "123", 456)

    def test_checkpoint_and_state_changes_rejected(self):
        for key, value in {"checkpoint_sha256": "0" * 64, "stages": 41,
                           "registered_state_entries": 59, "installed_hooks": 28,
                           "state_rng_runtime_unchanged": False,
                           "parent_state_bytes_equal": False}.items():
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify.verify_result({**fixture(), key: value}, "123", 456)

    def test_inexact_load_report_rejected(self):
        for key, value in {"missing_keys": ["x"], "loaded_trainable_numel_ratio": 0.9,
                           "key_count": 60, "prefix_rule": "changed"}.items():
            record = copy.deepcopy(fixture())
            record["strict_load_report"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                verify.verify_result(record, "123", 456)

    def test_boolean_integer_alias_rejected(self):
        with self.assertRaises(RuntimeError):
            verify.verify_result({**fixture(), "strict_load_calls": True}, "123", 456)

    def test_wrong_pid_or_job_rejected(self):
        for job, pid in (("124", 456), ("123", 457)):
            with self.subTest(job=job, pid=pid), self.assertRaises(RuntimeError):
                verify.verify_output(log(fixture()), job, pid)

    def test_duplicate_log_rejected(self):
        with self.assertRaises(RuntimeError):
            verify.verify_output(log(fixture()) * 2, "123", 456)

    def test_missing_begin_rejected(self):
        with self.assertRaises(RuntimeError):
            verify.verify_output(b"REAL_REGISTRATION_RESULT=" + json.dumps(fixture()).encode(), "123", 456)


if __name__ == "__main__":
    unittest.main(verbosity=2)
