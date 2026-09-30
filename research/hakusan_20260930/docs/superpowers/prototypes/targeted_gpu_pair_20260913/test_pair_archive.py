"""Synthetic CPU arrays and AST checks only; not real model/CUDA execution."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_adapter as adapter  # noqa: E402
import pass_archive as archive  # noqa: E402


def binding(role="reference", pid=None):
    return {"pair_nonce": "a" * 32, "role": role, "pid": os.getpid() if pid is None else pid,
            "cell": "B2", "input_sha256": "b" * 64, "package_sha256": "c" * 64}


def arrays(index):
    values = {}
    for n, name in enumerate(archive.COARSE + archive.DERIVED):
        dtype = np.int64 if name == "pred_label" else np.bool_ if name == "correct" else np.float32
        shape = (32, 3) if name in archive.COARSE else (32,)
        value = np.arange(np.prod(shape)).reshape(shape) + n + index
        values[name] = value.astype(dtype)
    return values, {n: values[n].copy() for n in archive.OFFICIAL}


def contract():
    passes = {}
    for index in (0, 1):
        values, _ = arrays(index)
        boundaries = {}
        for name, array in values.items():
            raw = array.tobytes()
            base = {"dtype": array.dtype.str, "shape": list(array.shape), "nbytes": len(raw), "sha256": archive.digest(raw)}
            width = len(raw) // 32
            rows = [{"trial_id": i, "dtype": array.dtype.str, "shape": list(array.shape[1:]) or [1],
                     "nbytes": width, "sha256": archive.digest(raw[i * width:(i + 1) * width])} for i in range(32)]
            boundaries[name] = {"aggregate": base, "rows": rows}
        passes[f"pass{index + 1}"] = {"boundaries": boundaries}
    return {"trials": [{"trial_id": i} for i in range(32)], "cells": {"B2": {"passes": passes}},
            "scope": "SYNTHETIC_ARRAY_TEST_ONLY"}


def produce(root, role="reference"):
    writer = archive.PassArchive(root, binding(role))
    try:
        for index, size in enumerate((16, 1)):
            bounds, outputs = arrays(index)
            writer.capture_pass(f"pass{index + 1}", size, list(range(32)), bounds, outputs,
                                {"scope": "synthetic fixture, not original pass commitment"})
        return writer.finish(), writer.binding
    finally:
        writer.close()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pair-array-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "archive"

    def make(self):
        self.receipt, self.bound = produce(self.root)
        return archive.verify_archive(self.root, self.receipt, self.bound, contract())

    def verify(self, parent=None):
        return archive.verify_archive(self.root, self.receipt, self.bound, parent or contract())

    def rewrite_manifest(self, transform):
        path = self.root / "manifest.json"
        value = json.loads(path.read_bytes())
        transform(value)
        raw = archive.canonical(value)
        path.write_bytes(raw)
        self.receipt = {"size": len(raw), "sha256": archive.digest(raw)}

    def test_complete_all_40_arrays(self):
        self.assertEqual(self.make()["passes"][1]["batch_size"], 1)
        self.assertEqual(len(list(self.root.iterdir())), 41)

    def test_reject_corrupted_raw_bytes(self):
        self.make()
        path = self.root / "000.bin"
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.verify()

    def test_reject_missing_file(self):
        self.make()
        (self.root / "000.bin").unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_reject_extra_file(self):
        self.make()
        (self.root / "extra").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.verify()

    def test_reject_self_rehashed_wrong_array(self):
        self.make()
        raw = (np.arange(96, dtype=np.float32) + 100).tobytes()
        (self.root / "000.bin").write_bytes(raw)
        self.rewrite_manifest(lambda v: v["passes"][0]["boundaries"]["raw_scene"].update(sha256=archive.digest(raw)))
        with self.assertRaisesRegex(ValueError, "parent array"):
            self.verify()

    def test_reject_wrong_external_manifest_sha(self):
        self.make()
        self.receipt["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.verify()

    def test_reject_wrong_external_pid(self):
        self.make()
        self.bound["pid"] += 1
        with self.assertRaisesRegex(ValueError, "external identity"):
            self.verify()

    def test_reject_pass_order(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"].reverse())
        with self.assertRaisesRegex(ValueError, "schedule"):
            self.verify()

    def test_reject_trial_relabel(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"][0]["trial_ids"].reverse())
        with self.assertRaisesRegex(ValueError, "schedule"):
            self.verify()

    def test_reject_boundary_missing(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"][0]["boundaries"].pop("nll"))
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.verify()

    def test_reject_file_path_traversal(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"][0]["boundaries"]["raw_scene"].update(file="../000.bin"))
        with self.assertRaisesRegex(ValueError, "artifact order"):
            self.verify()

    def test_reject_shape_relabel(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"][0]["boundaries"]["raw_scene"].update(shape=[16, 6]))
        with self.assertRaisesRegex(ValueError, "parent array"):
            self.verify()

    def test_reject_dtype_relabel(self):
        self.make()
        self.rewrite_manifest(lambda v: v["passes"][0]["boundaries"]["raw_scene"].update(dtype="<i8"))
        with self.assertRaisesRegex(ValueError, "byte budget/shape"):
            self.verify()

    def test_reject_parent_row_order(self):
        self.make()
        parent = contract()
        parent["cells"]["B2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["rows"].reverse()
        with self.assertRaisesRegex(ValueError, "parent row order"):
            self.verify(parent)

    def test_reject_parent_row_digest(self):
        self.make()
        parent = contract()
        parent["cells"]["B2"]["passes"]["pass1"]["boundaries"]["raw_scene"]["rows"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "per-trial"):
            self.verify(parent)

    def test_reject_symlink_file(self):
        self.make()
        path = self.root / "000.bin"
        path.rename(self.base / "outside")
        path.symlink_to(self.base / "outside")
        with self.assertRaises(OSError):
            self.verify()

    def test_reject_hardlink_file(self):
        self.make()
        os.link(self.root / "000.bin", self.base / "hardlink")
        with self.assertRaisesRegex(ValueError, "link"):
            self.verify()

    def test_reject_fifo_without_blocking(self):
        self.make()
        (self.root / "000.bin").unlink()
        os.mkfifo(self.root / "000.bin", 0o600)
        with self.assertRaisesRegex(ValueError, "artifact type"):
            self.verify()

    def test_reject_file_permissions(self):
        self.make()
        (self.root / "000.bin").chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode"):
            self.verify()

    def test_reject_ancestor_symlink(self):
        self.make()
        (self.base / "alias").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            archive.directory(self.base / "alias")

    def test_reject_duplicate_json_even_rehashed(self):
        self.make()
        path = self.root / "manifest.json"
        raw = path.read_bytes().replace(b'{"binding":', b'{"schema_version":1,"binding":', 1)
        path.write_bytes(raw)
        self.receipt = {"size": len(raw), "sha256": archive.digest(raw)}
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.verify()

    def test_fail_closed_partial_capture_retained(self):
        writer = archive.PassArchive(self.root, binding())
        self.addCleanup(writer.close)
        bounds, outputs = arrays(0)
        bounds["raw_cue"][0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            writer.capture_pass("pass1", 16, list(range(32)), bounds, outputs, {})
        self.assertTrue((self.root / "000.bin").is_file())
        self.assertFalse((self.root / "manifest.json").exists())
        with self.assertRaisesRegex(ValueError, "failed"):
            writer.finish()

    def test_no_overwrite_existing_root(self):
        self.make()
        with self.assertRaises(FileExistsError):
            produce(self.root)
        self.verify()

    def test_noncontiguous_multichunk_native_bytes(self):
        for dtype in (np.float16, np.float32, np.float64, np.int64, np.bool_):
            source = (np.arange(800000).reshape(1000, 800) % 8192).astype(dtype).T
            pieces = list(archive.array_chunks(source))
            self.assertTrue(all(len(p) <= archive.CHUNK for p in pieces))
            self.assertEqual(b"".join(pieces), source.tobytes(order="C"))

    def test_array_budget_before_iterator(self):
        source = np.broadcast_to(np.array([1.0]), (32, 1024, 1024))
        with mock.patch.object(np, "nditer", side_effect=AssertionError("must not copy")):
            with self.assertRaisesRegex(ValueError, "budget"):
                next(archive.array_chunks(source))

    def test_no_unsupported_dtype_or_cast(self):
        for dtype in (np.uint8, np.complex64, object, ">f4"):
            with self.subTest(dtype=str(dtype)), self.assertRaisesRegex(ValueError, "native ndarray"):
                list(archive.array_chunks(np.ones((32,), dtype=dtype)))

    def test_no_empty_arrays(self):
        with self.assertRaisesRegex(ValueError, "shape"):
            list(archive.array_chunks(np.zeros((0, 3), dtype=np.float32)))

    def test_incomplete_archive_not_committed(self):
        writer = archive.PassArchive(self.root, binding())
        self.addCleanup(writer.close)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            writer.finish()
        self.assertFalse((self.root / "manifest.json").exists())

    def test_forged_writer_pid_rejected(self):
        with self.assertRaisesRegex(ValueError, "actual process"):
            archive.PassArchive(self.root, binding(pid=os.getpid() + 1))

    def test_synthetic_oracle_cannot_enter_pinned_parent_verifier(self):
        with self.assertRaisesRegex(ValueError, "reviewed Job685198"):
            archive.verify_pinned_parent_pair(None, None, archive.canonical(contract()))

    def test_two_fresh_processes_byte_exact_and_binding_rejection(self):
        processes = []
        for role in ("reference", "observed"):
            code = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--fixture", str(self.base / role), role]
            processes.append(subprocess.Popen(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        refs = []
        for role, process in zip(("reference", "observed"), processes):
            try:
                out, err = process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            self.assertEqual(process.returncode, 0, err.decode())
            receipt, external = json.loads(out)
            self.assertEqual(external["pid"], process.pid)
            refs.append((self.base / role, receipt, external))
        result = archive.verify_content_pair(*refs, contract=contract())
        self.assertEqual(result["arrays_rehashed"], 80)
        self.assertFalse(result["ready_for_gpu"])
        self.assertFalse(result["execution_authority_verified"])
        refs[1][2]["pair_nonce"] = "d" * 32
        with self.assertRaisesRegex(ValueError, "identity"):
            archive.verify_content_pair(*refs, contract=contract())


class AdapterTests(unittest.TestCase):
    def test_both_parent_asts_exactly_recover(self):
        for role in ("reference", "observed"):
            tree, audit = adapter.derive(role)
            self.assertTrue(audit["original_ast_restored_exactly"])
            self.assertEqual(audit["artifact_calls_inserted"], 3)
            compile(tree, "test-only", "exec")

    def test_inserts_no_extra_forward_or_warmup(self):
        for role in ("reference", "observed"):
            tree, _ = adapter.derive(role)
            calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
            self.assertEqual(sum(n.endswith(".run_trace_pass") for n in calls), 1)
            for name in ("torch.compile", "torch.manual_seed", "torch._dynamo.reset", "torch.load"):
                self.assertNotIn(name, calls)

    def test_collector_archives_then_checks_original_unchanged(self):
        # Explicit fake pass/CPU scratch, not a real guard or GPU test.
        from types import SimpleNamespace
        values, outputs = arrays(0)
        result = SimpleNamespace(pass_id="pass1", batch_size=16, trial_ids=tuple(range(32)), outputs=outputs,
                                 boundary_records={n: {"tensor": values[n]} for n in archive.COARSE})
        result.boundary_records["derived"] = {n: {"tensor": values[n]} for n in archive.DERIVED}
        scratch = mock.Mock()
        diag = SimpleNamespace(encode_pass_evidence=lambda _: {"synthetic": True}, _cpu_artifact_array=lambda a: a)
        writer = mock.Mock()
        collector = adapter.PassCollector(SimpleNamespace(diag=diag), scratch, writer, spill=True)
        collector.names = (archive.COARSE + archive.DERIVED, archive.COARSE)
        collector.capture(result)
        scratch.spill.assert_called_once_with(result)
        self.assertEqual(writer.capture_pass.call_args.args[0:3], ("pass1", 16, list(range(32))))
        self.assertEqual(collector.count, 1)
        with self.assertRaisesRegex(ValueError, "both complete"):
            collector.after()

    def test_collector_rejects_commitment_mutation(self):
        from types import SimpleNamespace
        bounds, outputs = arrays(0)
        records = {n: {"tensor": bounds[n]} for n in archive.COARSE}
        records["derived"] = {n: {"tensor": bounds[n]} for n in archive.DERIVED}
        result = SimpleNamespace(pass_id="pass1", batch_size=16, trial_ids=tuple(range(32)), outputs=outputs, boundary_records=records)
        diag = SimpleNamespace(encode_pass_evidence=mock.Mock(side_effect=[{"old": 1}, {"new": 2}]), _cpu_artifact_array=lambda a: a)
        collector = adapter.PassCollector(SimpleNamespace(diag=diag), mock.Mock(), mock.Mock(), spill=False)
        collector.names = (archive.COARSE + archive.DERIVED, archive.COARSE)
        with self.assertRaisesRegex(ValueError, "altered pass"):
            collector.capture(result)

    def test_reject_unknown_role(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            adapter.derive("A2")

    def test_source_change_rejected(self):
        with mock.patch.object(Path, "read_bytes", return_value=b"changed"):
            with self.assertRaisesRegex(ValueError, "source differs"):
                adapter.derive("reference")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--fixture":
        print(json.dumps(produce(Path(sys.argv[2]), sys.argv[3])))
    else:
        unittest.main()
