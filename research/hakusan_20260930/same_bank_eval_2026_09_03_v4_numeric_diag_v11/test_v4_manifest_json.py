"""Historical v4 JSON versus diagnostic-owned JSON; CPU fixtures, no cluster."""

import dataclasses
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "v4_json_boundary_fixtures", PACKAGE / "test_numeric_diag.py"
)
fixtures = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixtures
spec.loader.exec_module(fixtures)
diag = fixtures.diagnose
trace = fixtures.trace
v4_bytes = fixtures._v4_json_bytes
sha = fixtures._sha256


class V4ManifestReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = pathlib.Path(temporary.name).resolve()
        self.root = self.base / "v4"
        self.root.mkdir()
        self.path = self.root / "input_freeze.json"
        self.value = {"z": "日本語 é", "a": [1, -0.0, 1e-9, {"x": True}]}
        self.install(v4_bytes(self.value))

    def install(self, raw):
        self.path.write_bytes(raw)
        self.contract = dataclasses.replace(
            diag.production_contract(), v4_root=self.root, manifest_sha256=sha(raw)
        )

    def read(self):
        return diag._read_v4_manifest(self.contract)

    def test_historical_writer_is_accepted_with_exact_bytes_and_no_writes(self):
        before = trace.fingerprint_tree(self.root)
        value, record = self.read()
        self.assertEqual(value, self.value)
        self.assertEqual(record["sha256"], self.contract.manifest_sha256)
        self.assertEqual(record["path"], str(self.path))
        self.assertEqual(record["relative_path"], "input_freeze.json")
        self.assertEqual(self.path.read_bytes(), v4_bytes(self.value))
        self.assertEqual(trace.fingerprint_tree(self.root), before)

    def test_audit_and_execution_accept_the_same_pinned_v4_bytes(self):
        audit, audit_record = diag._read_canonical_json(
            trace, self.path, self.root, self.contract.manifest_sha256
        )
        execution, execution_record = self.read()
        self.assertEqual(audit, execution)
        self.assertEqual(audit_record["sha256"], execution_record["sha256"])

    def test_compact_diagnostic_encoding_is_not_a_v4_manifest_encoding(self):
        self.install(trace.canonical_json_bytes(self.value))
        with self.assertRaisesRegex(diag.DiagnosticError, "noncanonical v4 manifest"):
            self.read()

    def test_owner_reader_still_rejects_pretty_json_even_with_correct_sha(self):
        with self.assertRaisesRegex(diag.DiagnosticError, "noncanonical owner JSON"):
            diag._owner_read_json(
                self.path, root=self.root, expected_sha=self.contract.manifest_sha256
            )

    def test_owner_reader_still_accepts_compact_and_rejects_reformatting(self):
        payload = trace.canonical_json_bytes(self.value)
        self.install(payload)
        value, _ = diag._owner_read_json(
            self.path, root=self.root, expected_sha=sha(payload)
        )
        self.assertEqual(value, self.value)
        self.install(v4_bytes(self.value))
        with self.assertRaisesRegex(diag.DiagnosticError, "noncanonical owner JSON"):
            diag._owner_read_json(self.path, root=self.root)

    def test_hash_is_checked_before_parsing_not_after_format_validation(self):
        self.contract = dataclasses.replace(self.contract, manifest_sha256="0" * 64)
        with mock.patch.object(diag.json, "loads", side_effect=AssertionError("parse")):
            with self.assertRaisesRegex(
                diag.DiagnosticError, "v4 manifest hash changed"
            ):
                self.read()

    def test_invalid_hash_is_rejected_before_file_read(self):
        for invalid in (None, "", "0" * 63, "G" * 64):
            with self.subTest(invalid=invalid):
                self.contract = dataclasses.replace(
                    self.contract, manifest_sha256=invalid
                )
                with mock.patch.object(
                    diag,
                    "_read_stable_source_bytes",
                    side_effect=AssertionError("read"),
                ):
                    with self.assertRaises(diag.DiagnosticError):
                        self.read()

    def test_other_whitespace_or_key_order_is_not_silently_recanonicalized(self):
        original = v4_bytes(self.value)
        cases = [
            b" " + original,
            original + b"\n",
            original.rstrip(b"\n"),
            original.replace(b"\n", b"\r\n"),
            (json.dumps(self.value, indent=4, sort_keys=True) + "\n").encode(),
            (json.dumps(self.value, indent=2, sort_keys=False) + "\n").encode(),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.install(raw)
                with self.assertRaises(diag.DiagnosticError):
                    self.read()

    def test_duplicate_keys_at_top_and_nested_levels_are_rejected(self):
        cases = [
            b'{\n  "a": 1,\n  "a": 1\n}\n',
            b'{\n  "a": {\n    "x": 1,\n    "x": 2\n  }\n}\n',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.install(raw)
                with self.assertRaises(diag.DiagnosticError):
                    self.read()

    def test_nonfinite_numbers_are_rejected_even_with_matching_hash(self):
        for token in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            with self.subTest(token=token):
                self.install(b'{\n  "a": ' + token + b"\n}\n")
                with self.assertRaises(diag.DiagnosticError):
                    self.read()

    def test_nonobjects_invalid_encodings_and_trailing_data_are_rejected(self):
        cases = [
            b"[]\n",
            b"null\n",
            b"42\n",
            b"{",
            b"\xff",
            v4_bytes(self.value) + b"{}\n",
            b"\xef\xbb\xbf" + v4_bytes(self.value),
            v4_bytes(self.value).decode().encode("utf-16"),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.install(raw)
                with self.assertRaises(diag.DiagnosticError):
                    self.read()

    def test_missing_fixed_filename_is_not_replaced_by_another_json(self):
        self.path.rename(self.root / "other.json")
        with self.assertRaises(diag.DiagnosticError):
            self.read()

    def test_symlinked_manifest_is_rejected(self):
        target = self.root / "original.json"
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(diag.DiagnosticError):
            self.read()

    def test_hardlinked_manifest_is_rejected(self):
        os.link(self.path, self.root / "alias.json")
        with self.assertRaises(diag.DiagnosticError):
            self.read()

    def test_symlinked_root_is_rejected(self):
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.contract = dataclasses.replace(self.contract, v4_root=alias)
        with self.assertRaises(diag.DiagnosticError):
            self.read()

    def test_parent_traversal_is_rejected(self):
        self.contract = dataclasses.replace(
            self.contract, v4_root=self.root / ".." / "v4"
        )
        with self.assertRaises(diag.DiagnosticError):
            self.read()

    def test_file_change_during_read_is_rejected(self):
        real_read = os.read
        changed = False

        def race(fd, length):
            nonlocal changed
            if not changed:
                changed = True
                self.path.write_bytes(v4_bytes(dict(self.value, changed=True)))
            return real_read(fd, length)

        with mock.patch.object(diag.os, "read", side_effect=race):
            with self.assertRaises(diag.DiagnosticError):
                self.read()
        self.assertTrue(changed)


class V4ManifestLifecycleTests(unittest.TestCase):
    def file_owner(self):
        fixture = fixtures.CoordinatorFileOwnerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_pre_and_post_reach_matrix_and_preserve_historical_root(self):
        fixture = fixtures.ResultVerifierTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        before = trace.fingerprint_tree(fixture.files.v4)
        report = fixture.complete()
        self.assertEqual(report["status"], "DIAGNOSTIC_COMPLETE")
        self.assertIsNone(report["primary_error"])
        self.assertEqual(report["post_errors"], [])
        self.assertEqual(report["pre"], report["post"])
        self.assertEqual(trace.fingerprint_tree(fixture.files.v4), before)

    def test_owner_matrix_routes_external_manifest_without_relaxing_owned_reader(self):
        fixture = self.file_owner()
        owner = fixture.owner()
        owner.authorize()
        owner.claim()
        result = {"summary": {"targeted_trace_cells": []}}
        with (
            mock.patch.object(diag, "_historical_scene_binding", return_value={}),
            mock.patch.object(diag, "_worker_historical_hashes", return_value={}),
            mock.patch.object(diag, "_ColdChildLauncher"),
            mock.patch.object(
                diag, "_run_matrix_sequence", return_value=result
            ) as matrix,
            mock.patch.object(
                diag, "_owner_read_json", side_effect=AssertionError("owner reader")
            ),
        ):
            owner.matrix()
        matrix.assert_called_once()

    def test_real_result_verifier_reads_pretty_manifest_without_writes_or_inference(
        self,
    ):
        fixture = fixtures.ResultVerifierTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.complete()
        before = trace.fingerprint_tree(fixture.root)
        with (
            mock.patch.object(
                diag.subprocess, "Popen", side_effect=AssertionError("no inference")
            ),
            mock.patch.object(
                diag, "atomic_create_bytes", side_effect=AssertionError("no writes")
            ),
            mock.patch.object(
                diag, "_read_v4_manifest", wraps=diag._read_v4_manifest
            ) as reader,
        ):
            result = fixture.verify()
        self.assertEqual(result["status"], "DIAGNOSTIC_RESULTS_VERIFIED")
        self.assertTrue(result["results_verified"])
        self.assertGreaterEqual(reader.call_count, 3)
        self.assertEqual(trace.fingerprint_tree(fixture.root), before)

    def test_actual_byte_change_after_precheck_still_fails_closed(self):
        fixture = self.file_owner()
        owner = fixture.owner()

        def changed_matrix():
            path = fixture.v4 / "input_freeze.json"
            value = json.loads(path.read_bytes())
            path.write_bytes(v4_bytes(dict(value, changed=True)))
            return {
                "status": "MATRIX_EVIDENCE_VERIFIED",
                "summary": {},
                "summary_record": {},
            }

        owner.matrix = changed_matrix
        report = diag._coordinate(fixture.args, owner)
        self.assertEqual(report["status"], "DIAGNOSTIC_FAILED")
        self.assertTrue(
            any(
                error["code"] == "INVALID_BOUND_INPUT_CHANGED"
                and "v4 manifest hash changed" in error["message"]
                for error in report["post_errors"]
            )
        )
        self.assertFalse((fixture.root / "state/DIAGNOSTIC_COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
