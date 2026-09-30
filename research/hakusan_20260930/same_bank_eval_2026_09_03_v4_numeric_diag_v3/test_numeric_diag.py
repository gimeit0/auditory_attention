"""Behavioral tests for the numerical diagnostic's read-only primitives."""

from __future__ import annotations

import dataclasses
import ast
import collections
import contextlib
import hashlib
import importlib.util
import itertools
import json
import os
import pathlib
import random
import signal
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
import torch


PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent


def load_test_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path.resolve(strict=True))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


trace = load_test_module("numeric_trace_task1_test", PACKAGE_ROOT / "numeric_trace.py")
DIAGNOSER = PACKAGE_ROOT / "diagnose_batch_invariance.py"
diagnose = (
    load_test_module("diagnose_batch_invariance_task3_test", DIAGNOSER)
    if DIAGNOSER.exists()
    else None
)


def _field(value: object) -> bytes:
    """Independent wire-format fixture: an unsigned 64-bit length plus UTF-8."""
    encoded = str(value).encode("utf-8")
    return len(encoded).to_bytes(8, "big") + encoded


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class FilePrimitiveTests(unittest.TestCase):
    """Each test names the observable production regression it catches."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary_directory.name) / "root"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_file(self, relative_path: str, payload: bytes) -> pathlib.Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_canonical_json_prevents_ambiguous_order_spacing_or_non_ascii_output(
        self,
    ) -> None:
        # Break caught: a serializer that is non-canonical or permits non-finite JSON.
        canonical_json_bytes = trace.canonical_json_bytes
        self.assertEqual(
            canonical_json_bytes({"z": "é", "a": [2, {"b": True}]}),
            b'{"a":[2,{"b":true}],"z":"\\u00e9"}\n',
        )
        with self.assertRaises(ValueError):
            canonical_json_bytes({"not_a_number": float("nan")})

    def test_read_stable_bytes_reports_descriptor_bytes_and_all_pinned_identity_fields(
        self,
    ) -> None:
        # Break caught: returning path-derived metadata or omitting an identity field.
        path = self.write_file("input.bin", b"alpha\x00beta")
        expected_mtime_ns = 1_700_000_000_123_456_789
        os.utime(path, ns=(expected_mtime_ns, expected_mtime_ns))
        expected_stat = path.stat()

        payload, record = trace.read_stable_bytes(path, allowed_root=self.root)

        self.assertEqual(payload, b"alpha\x00beta")
        self.assertEqual(
            record,
            {
                "relative_path": "input.bin",
                "mode": stat.S_IMODE(expected_stat.st_mode),
                "size": 10,
                "st_mtime_ns": expected_mtime_ns,
                "st_dev": expected_stat.st_dev,
                "st_ino": expected_stat.st_ino,
                "sha256": "4163834372780d81f2af66f279e9f9561be95535729c56c283fe298aee15582e",
            },
        )

    def test_canonical_allowed_root_rejects_a_file_outside_the_resolved_root(
        self,
    ) -> None:
        # Break caught: a lexical-prefix containment check accepting an outside path.
        inside = self.write_file("inside.bin", b"inside")
        outside = pathlib.Path(self.temporary_directory.name) / "outside.bin"
        outside.write_bytes(b"outside")
        canonical_spelling = self.root / "subdir" / ".."
        (self.root / "subdir").mkdir()

        payload, _ = trace.read_stable_bytes(inside, allowed_root=canonical_spelling)
        self.assertEqual(payload, b"inside")
        with self.assertRaises(trace.TraceContractError):
            trace.read_stable_bytes(outside, allowed_root=canonical_spelling)

    def test_pinned_regular_file_rejects_symlink_and_hard_link_aliases(self) -> None:
        # Break caught: following an alias that defeats single-file identity pinning.
        original = self.write_file("original.bin", b"immutable")
        symlink = self.root / "symlink.bin"
        os.symlink("original.bin", symlink)
        hard_link = self.root / "hard-link.bin"
        os.link(original, hard_link)

        for aliased_path in (symlink, hard_link):
            with self.subTest(path=aliased_path.name):
                with self.assertRaises(trace.TraceContractError):
                    trace.stable_file_record(aliased_path, allowed_root=self.root)

    def test_replacement_between_lstat_and_open_is_rejected(self) -> None:
        # Break caught: reading a different inode than the one inspected before open.
        path = self.write_file("replaceable.bin", b"before")
        replacement = self.root / "replacement.bin"
        replacement.write_bytes(b"after")
        real_open = trace.os.open

        def replace_before_open(opened_path, flags, *args, **kwargs):
            os.replace(replacement, path)
            return real_open(opened_path, flags, *args, **kwargs)

        with mock.patch.object(trace.os, "open", side_effect=replace_before_open):
            with self.assertRaises(trace.TraceContractError):
                trace.read_stable_bytes(path, allowed_root=self.root)

    def test_reads_fail_closed_when_o_nofollow_is_unavailable(self) -> None:
        # Break caught: silently opening a symlink-capable pathname without O_NOFOLLOW.
        path = self.write_file("input.bin", b"safe")
        with mock.patch.object(trace.os, "O_NOFOLLOW", None):
            with self.subTest(reader="pinned file"):
                with self.assertRaises(trace.TraceContractError):
                    trace.read_stable_bytes(path, allowed_root=self.root)
            with self.subTest(reader="tree"):
                with self.assertRaises(trace.TraceContractError):
                    trace.fingerprint_tree(self.root)

    def test_tree_fingerprint_rejects_hard_linked_ordinary_files(self) -> None:
        # Break caught: accepting a multiply linked file in a bound tree read.
        source = self.write_file("source.bin", b"shared inode")
        os.link(source, self.root / "alias.bin")

        with self.assertRaises(trace.TraceContractError):
            trace.fingerprint_tree(self.root)

    def test_tree_fingerprint_does_not_traverse_directory_replaced_by_symlink(
        self,
    ) -> None:
        # Break caught: path-based directory scanning following a replacement symlink.
        protected_directory = self.root / "protected"
        protected_directory.mkdir()
        (protected_directory / "expected.bin").write_bytes(b"inside")
        outside_directory = pathlib.Path(self.temporary_directory.name) / "outside"
        outside_directory.mkdir()
        (outside_directory / "escaped.bin").write_bytes(b"outside")
        real_scandir = trace.os.scandir
        real_open = trace.os.open

        def replace_before_path_scandir(directory):
            if (
                not isinstance(directory, int)
                and pathlib.Path(directory) == protected_directory
            ):
                (protected_directory / "expected.bin").unlink()
                protected_directory.rmdir()
                os.symlink(outside_directory, protected_directory)
            return real_scandir(directory)

        def replace_after_directory_open(opened_path, flags, *args, **kwargs):
            descriptor = real_open(opened_path, flags, *args, **kwargs)
            if pathlib.Path(opened_path).name == "protected":
                (protected_directory / "expected.bin").unlink()
                protected_directory.rmdir()
                os.symlink(outside_directory, protected_directory)
            return descriptor

        with mock.patch.object(
            trace.os, "scandir", side_effect=replace_before_path_scandir
        ):
            with mock.patch.object(
                trace.os, "open", side_effect=replace_after_directory_open
            ):
                with self.assertRaises(trace.TraceContractError):
                    trace.fingerprint_tree(self.root)

    def test_verify_file_record_rechecks_every_identity_field_and_content(self) -> None:
        # Break caught: accepting a stale path record after its file changes.
        path = self.write_file("verified.bin", b"first version")
        record = trace.stable_file_record(path, allowed_root=self.root)
        self.assertEqual(
            trace.verify_file_record(record, allowed_root=self.root), record
        )

        path.write_bytes(b"second version")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_file_record(record, allowed_root=self.root)

    def test_tree_fingerprint_uses_sorted_length_prefixed_records_and_does_not_follow_symlinks(
        self,
    ) -> None:
        # Break caught: delimiter-ambiguous, unsorted, or symlink-following tree hashes.
        first = self.write_file("z.bin", b"z\x00payload")
        second = self.write_file("a/name\nwith:delimiter.bin", b"a payload")
        symlink = self.root / "a-link.bin"
        os.symlink("z.bin", symlink)
        os.utime(first, ns=(1_700_000_010_000_000_001, 1_700_000_010_000_000_001))
        os.utime(second, ns=(1_700_000_020_000_000_002, 1_700_000_020_000_000_002))

        fingerprint = trace.fingerprint_tree(self.root)
        expected_entries = []
        for path in (self.root / "a", second, symlink, first):
            observed = path.lstat()
            relative_path = path.relative_to(self.root).as_posix()
            if stat.S_ISREG(observed.st_mode):
                entry_type, target = "file", ""
            elif stat.S_ISDIR(observed.st_mode):
                entry_type, target = "directory", ""
            elif stat.S_ISLNK(observed.st_mode):
                entry_type, target = "symlink", os.readlink(path)
            else:
                self.fail(f"unexpected fixture type: {path}")
            expected_entries.append(
                {
                    "relative_path": relative_path,
                    "type": entry_type,
                    "mode": stat.S_IMODE(observed.st_mode),
                    "size": observed.st_size,
                    "st_mtime_ns": observed.st_mtime_ns,
                    "st_dev": observed.st_dev,
                    "st_ino": observed.st_ino,
                    "symlink_target": target,
                }
            )
        expected_entries.sort(key=lambda entry: entry["relative_path"].encode("utf-8"))
        tree_payload = b"".join(
            b"".join(
                _field(entry[field])
                for field in (
                    "relative_path",
                    "type",
                    "mode",
                    "size",
                    "st_mtime_ns",
                    "st_dev",
                    "st_ino",
                    "symlink_target",
                )
            )
            for entry in expected_entries
        )
        expected_content_records = [
            ("a/name\nwith:delimiter.bin", 9, _sha256(b"a payload")),
            ("z.bin", 9, _sha256(b"z\x00payload")),
        ]
        content_payload = b"".join(
            b"".join(_field(value) for value in content_record)
            for content_record in expected_content_records
        )

        self.assertEqual(fingerprint["entries"], expected_entries)
        self.assertEqual(fingerprint["tree_sha256"], _sha256(tree_payload))
        self.assertEqual(fingerprint["content_sha256"], _sha256(content_payload))
        self.assertEqual(fingerprint["entry_count"], 4)
        self.assertEqual(fingerprint["entries"][1]["symlink_target"], "z.bin")

    def test_tree_fingerprint_changes_on_identity_or_content(self) -> None:
        # Break caught: a content aggregate that ignores ordinary-file bytes.
        self.write_file("input.bin", b"before")
        before = trace.fingerprint_tree(self.root)
        (self.root / "input.bin").write_bytes(b"changed")
        after = trace.fingerprint_tree(self.root)
        self.assertNotEqual(before["content_sha256"], after["content_sha256"])


class NumericTraceTests(unittest.TestCase):
    """Behavioral coverage for immutable tensor and runtime diagnostic records."""

    def test_tensor_bytes_preserve_bfloat16_bits_and_normalize_noncontiguous_layout(
        self,
    ) -> None:
        # Break caught: casting bfloat16 or hashing strided storage rather than logical tensor bytes.
        base = torch.tensor([[1.0, -2.5], [3.25, 0.0]], dtype=torch.bfloat16)
        noncontiguous = base.transpose(0, 1)
        expected = (
            noncontiguous.detach()
            .cpu()
            .contiguous()
            .view(torch.uint8)
            .numpy()
            .tobytes()
        )

        self.assertFalse(noncontiguous.is_contiguous())
        self.assertEqual(trace.canonical_tensor_bytes(noncontiguous), expected)
        self.assertEqual(
            trace.canonical_tensor_bytes(noncontiguous),
            trace.canonical_tensor_bytes(noncontiguous.contiguous()),
        )
        record = trace.tensor_record(noncontiguous, boundary="logits")
        self.assertEqual(record["dtype"], "torch.bfloat16")
        self.assertEqual(record["shape"], [2, 2])
        self.assertEqual(record["sha256"], _sha256(expected))

    def test_tensor_record_rejects_python_containers_without_an_explicit_tensor_contract(
        self,
    ) -> None:
        # Break caught: silently coercing arbitrary nested Python values into evidence tensors.
        for value in ([1.0, 2.0], (1.0, 2.0)):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(trace.TraceContractError):
                    trace.tensor_record(value, boundary="scores")

    def test_per_trial_records_bind_batch_axis_trial_ids_and_slice_content(
        self,
    ) -> None:
        # Break caught: associating trial IDs with an unsliced batch or allowing ambiguous IDs.
        values = np.array([[1, 2], [3, 4]], dtype=np.int16)
        records = trace.per_trial_tensor_records(
            values, trial_ids=(101, 202), boundary="nll", batch_axis=0
        )
        self.assertEqual([entry["trial_id"] for entry in records], [101, 202])
        self.assertEqual([entry["shape"] for entry in records], [[2], [2]])
        self.assertEqual(
            [entry["sha256"] for entry in records],
            [
                _sha256(np.array([1, 2], dtype=np.int16).tobytes()),
                _sha256(np.array([3, 4], dtype=np.int16).tobytes()),
            ],
        )
        for bad_ids in ((101, 101), (101,), (101, 202, 303)):
            with self.subTest(trial_ids=bad_ids):
                with self.assertRaises(trace.TraceContractError):
                    trace.per_trial_tensor_records(
                        values, trial_ids=bad_ids, boundary="nll"
                    )

    def test_compare_rejects_shape_dtype_or_trial_alignment_before_calculating_differences(
        self,
    ) -> None:
        # Break caught: treating incompatible tensors as numerical finite differences.
        cases = (
            (
                np.zeros((2, 2), dtype=np.float32),
                np.zeros((2, 3), dtype=np.float32),
                (1, 2),
            ),
            (
                np.zeros((2, 2), dtype=np.float32),
                np.zeros((2, 2), dtype=np.float64),
                (1, 2),
            ),
            (
                np.zeros((2, 2), dtype=np.float32),
                np.zeros((2, 2), dtype=np.float32),
                (1,),
            ),
            (
                np.zeros((2, 2), dtype=np.float32),
                np.zeros((2, 2), dtype=np.float32),
                (1, 1),
            ),
        )
        for left, right, trial_ids in cases:
            with self.subTest(
                shape=right.shape, dtype=right.dtype, trial_ids=trial_ids
            ):
                got = trace.compare_aligned_tensor(
                    left, right, trial_ids=trial_ids, boundary="nll"
                )
                self.assertFalse(got["schema_valid"])
                self.assertFalse(got["finite_valid"])
                self.assertIsNone(got["max_abs"])
                self.assertFalse(got["bitwise_equal"])

    def test_compare_classifies_nonfinite_values_as_invalid_not_as_a_difference(
        self,
    ) -> None:
        # Break caught: emitting an ordinary DIFF result for NaN or either infinity pattern.
        patterns = (
            (
                np.array([[np.nan], [1.0]], dtype=np.float32),
                np.array([[0.0], [1.0]], dtype=np.float32),
                "NaN",
                "finite",
            ),
            (
                np.array([[np.inf], [1.0]], dtype=np.float32),
                np.array([[-np.inf], [1.0]], dtype=np.float32),
                "+Inf",
                "-Inf",
            ),
            (
                np.array([[-np.inf], [1.0]], dtype=np.float32),
                np.array([[np.inf], [1.0]], dtype=np.float32),
                "-Inf",
                "+Inf",
            ),
        )
        for left, right, expected_left, expected_right in patterns:
            with self.subTest(left=expected_left, right=expected_right):
                got = trace.compare_aligned_tensor(
                    left, right, trial_ids=(7, 8), boundary="nll"
                )
                self.assertFalse(got["schema_valid"])
                self.assertFalse(got["finite_valid"])
                self.assertFalse(got["bitwise_equal"])
                self.assertIsNone(got["max_abs"])
                self.assertEqual(got["classification"], "NONFINITE")
                self.assertEqual(
                    got["nonfinite_locations"],
                    [{"index": [0, 0], "left": expected_left, "right": expected_right}],
                )

    def test_compare_retains_same_bit_nonfinite_equality_while_rejecting_finite_schema(
        self,
    ) -> None:
        # Break caught: coupling byte equality to finite arithmetic validation and losing independent bit evidence.
        values = np.array([[np.nan], [np.inf], [-np.inf]], dtype=np.float32)
        got = trace.compare_aligned_tensor(
            values, values.copy(), trial_ids=(1, 2, 3), boundary="nll"
        )
        self.assertFalse(got["schema_valid"])
        self.assertFalse(got["finite_valid"])
        self.assertTrue(got["bitwise_equal"])
        self.assertEqual(got["classification"], "NONFINITE")

    def test_original_canary_delta_is_preserved_as_finite_diff(self) -> None:
        # Break caught: losing the historical finite canary delta to tolerance or nonfinite handling.
        left = np.zeros((32,), dtype=np.float32)
        right = left.copy()
        right[17] = np.float32(0.0077362060546875)
        got = trace.compare_aligned_tensor(
            left, right, trial_ids=tuple(range(32)), boundary="nll"
        )
        self.assertTrue(got["schema_valid"])
        self.assertTrue(got["finite_valid"])
        self.assertFalse(got["bitwise_equal"])
        self.assertGreater(got["max_abs"], 1e-6)
        self.assertEqual(got["worst"]["trial_id"], 17)
        self.assertEqual(got["worst"]["flat_index"], 17)
        self.assertEqual(got["worst"]["index"], [17])
        self.assertEqual(got["quantile_method"], "linear")
        self.assertEqual(
            got["element_abs_quantiles"],
            {"p50": 0.0, "p95": 0.0, "p99": 0.005337982177734384},
        )
        self.assertEqual(
            got["trial_max_abs_quantiles"],
            {"p50": 0.0, "p95": 0.0, "p99": 0.005337982177734384},
        )

    def test_compare_reports_exact_worst_class_location_and_linear_quantiles(
        self,
    ) -> None:
        # Break caught: flattening a worst mismatch without preserving trial/class coordinates or quantile rule.
        left = np.zeros((2, 3), dtype=np.float32)
        right = np.array([[0.0, 2.0, 1.0], [4.0, 3.0, 0.0]], dtype=np.float32)
        got = trace.compare_aligned_tensor(
            left, right, trial_ids=(10, 20), boundary="logits", class_axis=1
        )
        self.assertEqual(
            got["worst"],
            {
                "flat_index": 3,
                "index": [1, 0],
                "trial_id": 20,
                "left_value": 0.0,
                "right_value": 4.0,
                "class_index": 0,
            },
        )
        self.assertEqual(got["max_abs"], 4.0)
        self.assertEqual(got["max_rel"], 1.0)
        self.assertEqual(
            got["element_abs_quantiles"], {"p50": 1.5, "p95": 3.75, "p99": 3.95}
        )
        self.assertEqual(
            got["trial_max_abs_quantiles"], {"p50": 3.0, "p95": 3.9, "p99": 3.98}
        )

    def test_compare_binds_floor_mismatch_count_and_both_worst_operand_values(
        self,
    ) -> None:
        # Break caught: an audit record that cannot reproduce its relative error or inspect its worst mismatch.
        left = np.array([[0.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        right = np.array([[1.0, 2.0], [5.0, 0.0]], dtype=np.float32)
        got = trace.compare_aligned_tensor(
            left, right, trial_ids=(100, 200), boundary="logits", relative_floor=0.25
        )
        self.assertEqual(got["relative_denominator_floor"], 0.25)
        self.assertEqual(got["mismatch_count"], 3)
        self.assertEqual(
            got["worst"],
            {
                "flat_index": 3,
                "index": [1, 1],
                "trial_id": 200,
                "left_value": 4.0,
                "right_value": 0.0,
            },
        )

    def test_compare_rejects_nonfinite_floor_without_emitting_non_json_values(
        self,
    ) -> None:
        # Break caught: accepting NaN/infinite denominator controls that make relative evidence non-finite or vacuous.
        values = np.array([[0.0], [1.0]], dtype=np.float32)
        for floor in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(relative_floor=floor):
                got = trace.compare_aligned_tensor(
                    values,
                    values,
                    trial_ids=(1, 2),
                    boundary="nll",
                    relative_floor=floor,
                )
                self.assertFalse(got["schema_valid"])
                self.assertEqual(got["classification"], "SCHEMA_INVALID")
                trace.canonical_json_bytes(got)

    def test_runtime_record_keeps_device_batch_and_cache_bindings_json_compatible(
        self,
    ) -> None:
        # Break caught: omitting execution settings needed to reproduce an observed comparison.
        got = trace.runtime_record(
            device=torch.device("cpu"),
            autocast_enabled=False,
            pass_batch_sizes=(1, 32),
            cache_dirs={"z": "/tmp/z", "a": "/tmp/a"},
        )
        self.assertEqual(
            got,
            {
                "device": "cpu",
                "autocast_enabled": False,
                "pass_batch_sizes": [1, 32],
                "cache_dirs": {"a": "/tmp/a", "z": "/tmp/z"},
            },
        )


class _StateFixture(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor([1.0, 2.0]))
        self.register_buffer("offset", torch.tensor([3.0]))


class StateAndInventoryTests(unittest.TestCase):
    """Behavioral coverage for model/RNG state and artifact inventory contracts."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary_directory.name) / "artifacts"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _record(self, relative_path: str, payload: bytes) -> dict[str, object]:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return trace.stable_file_record(path, allowed_root=self.root)

    def test_model_snapshot_records_sorted_parameters_and_buffers_with_identity_version_and_content(
        self,
    ) -> None:
        # Break caught: snapshots that omit buffers or lose object/version/content identity.
        model = _StateFixture()
        got = trace.snapshot_model_state(model)
        entries = got["entries"]
        self.assertEqual(
            [(entry["kind"], entry["name"]) for entry in entries],
            [("buffer", "offset"), ("parameter", "weight")],
        )
        by_name = {entry["name"]: entry for entry in entries}
        self.assertEqual(by_name["weight"]["object_id"], id(model.weight))
        self.assertEqual(by_name["offset"]["object_id"], id(model.offset))
        self.assertEqual(by_name["weight"]["version"], model.weight._version)
        self.assertEqual(by_name["offset"]["shape"], [1])
        self.assertEqual(by_name["weight"]["dtype"], "torch.float32")
        self.assertEqual(by_name["weight"]["device"], "cpu")
        self.assertEqual(
            by_name["offset"]["sha256"],
            _sha256(np.array([3.0], dtype=np.float32).tobytes()),
        )

    def test_model_comparison_detects_content_or_version_mutated_at_either_checkpoint(
        self,
    ) -> None:
        # Break caught: comparing only the first/last checkpoint and missing a parameter or buffer mutation.
        model = _StateFixture()
        before = trace.snapshot_model_state(model)
        with torch.no_grad():
            model.offset.add_(1.0)
        between = trace.snapshot_model_state(model)
        with torch.no_grad():
            model.weight.mul_(2.0)
        after = trace.snapshot_model_state(model)
        got = trace.compare_model_snapshots(before, between, after)
        self.assertFalse(got["state_unchanged"])
        self.assertEqual(
            got["before_to_between"]["changed"], [{"kind": "buffer", "name": "offset"}]
        )
        self.assertEqual(
            got["between_to_after"]["changed"],
            [{"kind": "parameter", "name": "weight"}],
        )

    def test_model_comparison_rejects_snapshots_missing_required_audit_identity_fields(
        self,
    ) -> None:
        # Break caught: treating a partial state snapshot as proof that model state did not change.
        snapshot = trace.snapshot_model_state(_StateFixture())
        for missing_key in (
            "identity",
            "_version",
            "shape",
            "dtype",
            "device",
            "sha256",
        ):
            with self.subTest(missing_key=missing_key):
                malformed = {"entries": [dict(entry) for entry in snapshot["entries"]]}
                del malformed["entries"][0][missing_key]
                with self.assertRaises(trace.TraceContractError):
                    trace.compare_model_snapshots(snapshot, malformed, snapshot)

    def test_rng_snapshot_captures_python_numpy_torch_cpu_and_available_cuda_without_invalidating_cell(
        self,
    ) -> None:
        # Break caught: omitting an RNG family or treating an RNG difference as numerical-cell invalidity.
        before = trace.snapshot_rng_state()
        self.assertEqual(
            set(before["families"]),
            {
                "numpy",
                "python",
                "torch_cpu",
                *{f"torch_cuda:{index}" for index in range(torch.cuda.device_count())},
            },
        )
        for record in before["families"].values():
            self.assertEqual(
                record["encoding"],
                "base64-pickle-v4"
                if record["family"] in {"python", "numpy"}
                else "base64-raw",
            )
            self.assertEqual(len(record["sha256"]), 64)
        _ = (np.random.random(), torch.rand(1).item())
        import random

        _ = random.random()
        after = trace.snapshot_rng_state()
        got = trace.compare_rng_snapshots(before, before, after)
        self.assertTrue(got["schema_valid"])
        self.assertTrue(got["rng_changed"])
        self.assertFalse(got["invalidates_cell"])
        self.assertEqual(
            got["between_to_after"]["changed"], ["numpy", "python", "torch_cpu"]
        )

    def test_rng_comparison_fails_closed_for_missing_or_badly_encoded_required_families(
        self,
    ) -> None:
        # Break caught: accepting an empty, incomplete, or unauthenticated RNG snapshot as unchanged.
        snapshot = trace.snapshot_rng_state()
        empty = trace.compare_rng_snapshots({"families": {}}, snapshot, snapshot)
        self.assertFalse(empty["schema_valid"])
        self.assertFalse(empty["invalidates_cell"])
        missing = {"families": dict(snapshot["families"])}
        del missing["families"]["python"]
        self.assertFalse(
            trace.compare_rng_snapshots(snapshot, missing, snapshot)["schema_valid"]
        )
        malformed = {
            "families": {
                name: dict(record) for name, record in snapshot["families"].items()
            }
        }
        malformed["families"]["numpy"]["sha256"] = "0" * 64
        self.assertFalse(
            trace.compare_rng_snapshots(snapshot, malformed, snapshot)["schema_valid"]
        )

    def test_rng_snapshot_uses_capture_time_cuda_cardinality_when_visibility_changes(
        self,
    ) -> None:
        # Break caught: invalidating a persisted valid CUDA snapshot because the reviewing host sees fewer devices.
        captured = trace.snapshot_rng_state()
        captured = {
            "cuda_device_count": 1,
            "families": {
                name: dict(record) for name, record in captured["families"].items()
            },
        }
        cuda_record = dict(captured["families"]["torch_cpu"])
        cuda_record["family"] = "torch_cuda:0"
        captured["families"]["torch_cuda:0"] = cuda_record
        with mock.patch.object(torch.cuda, "device_count", return_value=0):
            got = trace.compare_rng_snapshots(captured, captured, captured)
        self.assertTrue(got["schema_valid"])
        self.assertFalse(got["rng_changed"])

    def test_rng_rejects_huge_captured_cuda_count_without_expanding_cardinality(
        self,
    ) -> None:
        # Break caught: constructing an attacker-controlled range from a tiny malformed persisted snapshot.
        snapshot = trace.snapshot_rng_state()
        malicious = {
            "cuda_device_count": 10**12,
            "families": {
                name: dict(record)
                for name, record in snapshot["families"].items()
                if not name.startswith("torch_cuda:")
            },
        }
        with mock.patch(
            "builtins.range", side_effect=AssertionError("CUDA cardinality expanded")
        ):
            got = trace.compare_rng_snapshots(malicious, malicious, malicious)
        self.assertFalse(got["schema_valid"])
        self.assertFalse(got["invalidates_cell"])

    def test_inventory_accepts_exact_regular_files_and_reports_total_payload(
        self,
    ) -> None:
        # Break caught: inventory verification that ignores an expected artifact or its aggregate payload.
        expected = [
            self._record("nested/a.bin", b"abc"),
            self._record("b.bin", b"defg"),
        ]
        got = trace.verify_artifact_inventory(
            self.root, expected=expected, allowed_total_bytes=7
        )
        self.assertEqual(got["total_bytes"], 7)
        self.assertEqual(
            [entry["relative_path"] for entry in got["records"]],
            ["b.bin", "nested/a.bin"],
        )

    def test_inventory_fails_closed_on_escape_alias_nonregular_and_manifest_set_or_content_errors(
        self,
    ) -> None:
        # Break caught: accepting an inventory that can hide files, aliases, altered content, or a path outside root.
        expected = [self._record("good.bin", b"good")]
        escaped = dict(expected[0])
        escaped["relative_path"] = "../escape.bin"
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=[escaped])
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(
                self.root, expected=[expected[0], expected[0]]
            )
        (self.root / "extra.bin").write_bytes(b"extra")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)
        (self.root / "extra.bin").unlink()
        os.symlink("good.bin", self.root / "alias.bin")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)
        (self.root / "alias.bin").unlink()
        os.link(self.root / "good.bin", self.root / "hard.bin")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)
        (self.root / "hard.bin").unlink()
        (self.root / "good.bin").write_bytes(b"changed")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)

    def test_inventory_rejects_total_worst_case_payload_above_budget(self) -> None:
        # Break caught: accepting a pinned payload that exceeds the immutable artifact budget.
        expected = [self._record("payload.bin", b"12345678")]
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(
                self.root, expected=expected, allowed_total_bytes=7
            )

    def test_inventory_caller_cannot_relax_immutable_one_gib_ceiling(self) -> None:
        # Break caught: a caller raising the public budget parameter above the fixed evidence ceiling.
        expected = [self._record("small.bin", b"small")]
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(
                self.root, expected=expected, allowed_total_bytes=(1 << 30) + 1
            )

    def test_inventory_rejects_missing_path_fifo_and_same_size_sha_mutation(
        self,
    ) -> None:
        # Break caught: accepting absent, non-regular, or same-size content-substituted evidence.
        expected = [self._record("good.bin", b"good")]
        (self.root / "good.bin").unlink()
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)

        expected = [self._record("good.bin", b"good")]
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)
        (self.root / "pipe").unlink()

        (self.root / "good.bin").write_bytes(b"evil")
        with self.assertRaises(trace.TraceContractError):
            trace.verify_artifact_inventory(self.root, expected=expected)


class RealV4ManifestScopeTests(unittest.TestCase):
    """Real v4 five-group shape plus independently bound layout lock."""

    def manifest(self):
        groups = (
            "inputs",
            "historical_evidence",
            "completion",
            "models",
            "checkpoint_selection",
        )
        value = {}
        ordinal = 0
        for group, count in zip(groups, (11, 3, 3, 3, 4)):
            value[group] = {}
            for index in range(count):
                value[group][str(index)] = dict(
                    path=f"/fixture/file-{ordinal}",
                    size=ordinal + 1,
                    sha256=f"{ordinal + 1:064x}",
                )
                ordinal += 1
        value["layout"] = {
            "evaluation_lock": dict(
                path="/fixture/state/evaluation.lock", size=424, sha256="f" * 64
            )
        }
        return value

    def test_layout_lock_is_not_a_twenty_fifth_input(self):
        value = self.manifest()
        actual = diagnose._collect_pinned_records(value)
        self.assertEqual(len(actual), 24)
        self.assertEqual(
            [r["path"] for r in actual], [f"/fixture/file-{i}" for i in range(24)]
        )

    def test_collector_matches_actual_frozen_v4_walker(self):
        path = (
            PACKAGE_ROOT.parent
            / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py"
        )
        source = ast.parse(path.read_text())
        function = next(
            n
            for n in source.body
            if isinstance(n, ast.FunctionDef) and n.name == "verify_frozen_manifest"
        )
        walk = next(
            n
            for n in function.body
            if isinstance(n, ast.FunctionDef) and n.name == "walk"
        )
        groups = next(
            n
            for n in function.body
            if isinstance(n, ast.For)
            and isinstance(n.target, ast.Name)
            and n.target.id == "group_name"
        )
        value = self.manifest()
        value["inputs"]["unrelated_list"] = [value["layout"]["evaluation_lock"]]
        value["pinned_files"] = [value["layout"]["evaluation_lock"]]
        namespace = dict(
            Mapping=collections.abc.Mapping,
            Any=object,
            manifest=value,
            EvaluationError=RuntimeError,
            verified={},
            identity_diagnostics={},
            pinned_file=lambda path, label, sha: dict(path=path, sha256=sha),
            validate_persistent_file_identity=lambda *args: {},
        )
        exec(
            compile(
                ast.Module(body=[walk, groups], type_ignores=[]), str(path), "exec"
            ),
            namespace,
        )
        actual = [
            (r["path"], r["sha256"]) for r in diagnose._collect_pinned_records(value)
        ]
        expected = [(r["path"], r["sha256"]) for r in namespace["verified"].values()]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 24)

    def test_record_in_unrelated_list_or_override_does_not_replace_groups(self):
        value = self.manifest()
        value["pinned_files"] = [value["layout"]["evaluation_lock"]]
        value["extra"] = [value["layout"]["evaluation_lock"]]
        self.assertEqual(len(diagnose._collect_pinned_records(value)), 24)

    def test_missing_or_nonmapping_group_is_rejected(self):
        for group in (
            "inputs",
            "historical_evidence",
            "completion",
            "models",
            "checkpoint_selection",
        ):
            for invalid in (None, [], "not-a-group"):
                value = self.manifest()
                value[group] = invalid
                with self.subTest(group=group, invalid=invalid):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._collect_pinned_records(value)

    def test_nested_mapping_and_duplicate_role_order_match_v4(self):
        value = self.manifest()
        original = value["inputs"]["0"]
        value["inputs"]["0"] = {"nested": original}
        value["completion"]["0"] = dict(original)
        actual = diagnose._collect_pinned_records(value)
        self.assertEqual(len(actual), 24)
        self.assertEqual(actual[0], actual[14])


class RealV4LockBindingTests(unittest.TestCase):
    def test_layout_lock_is_verified_separately_from_24_role_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp).resolve()
            (root / "tools").mkdir()
            (root / "state").mkdir()
            names = [
                "tools/locked_same_bank_eval.py",
                "tools/run_locked_same_bank_eval.sbatch",
            ]
            names += [f"file-{i}" for i in range(22)]
            records = []
            for name in names + ["state/evaluation.lock"]:
                path = root / name
                path.write_bytes(name.encode())
                records.append(
                    dict(
                        path=str(path),
                        size=len(name.encode()),
                        sha256=hashlib.sha256(name.encode()).hexdigest(),
                    )
                )
            lock = records.pop()
            manifest = dict(
                inputs={str(i): r for i, r in enumerate(records)},
                historical_evidence={},
                completion={},
                models={},
                checkpoint_selection={},
                layout={"evaluation_lock": lock},
            )
            contract = dataclasses.replace(
                diagnose.production_contract(),
                v4_root=root,
                evaluator_sha256=records[0]["sha256"],
                runner_sha256=records[1]["sha256"],
                lock_sha256=lock["sha256"],
            )
            verified = diagnose._verify_v4_pinned_records(trace, manifest, contract)
            self.assertEqual(len(verified), 24)
            for change in (
                {},
                {"evaluation_lock": dict(lock, sha256="0" * 64)},
                {"evaluation_lock": dict(lock, path=str(root / "file-0"))},
            ):
                with self.subTest(layout=change):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._verify_v4_pinned_records(
                            trace, dict(manifest, layout=change), contract
                        )
            (root / "state/evaluation.lock").write_bytes(b"changed")
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._verify_v4_pinned_records(trace, manifest, contract)


class FrozenContractTests(unittest.TestCase):
    """Task 3 frozen-input, selection, inventory, and publication contracts."""

    def setUp(self) -> None:
        self.assertIsNotNone(diagnose, "Task 3 diagnoser is missing")
        self.temporary_directory = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = pathlib.Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        if hasattr(self, "temporary_directory"):
            self.temporary_directory.cleanup()

    def complete_audit(self, production):
        clips = self.root / "tools/test-clips"
        clips.mkdir(exist_ok=True)
        snapshot = self.root / "tools/test-snapshot"
        snapshot.mkdir(exist_ok=True)
        (clips / "a.wav").write_bytes(b"clip")
        (snapshot / "x.py").write_bytes(b"X=1\n")
        clip = {
            **trace.stable_file_record(clips / "a.wav", allowed_root=clips),
            "type": "file",
            "uses": [{"trial_id": 0, "role": "target"}],
        }
        source = {
            **trace.stable_file_record(snapshot / "x.py", allowed_root=snapshot),
            "type": "file",
            "observed_import": True,
        }
        trials = [
            {
                "ordinal": i,
                "trial_id": i,
                "bank_row_index": i,
                "identity": {column: i for column in diagnose.TRIAL_IDENTITY_COLUMNS},
            }
            for i in range(32)
        ]
        pinned = [
            {
                "role_ordinal": i,
                "path": f"/frozen/{i}",
                "type": "file",
                "size": i,
                "sha256": f"{i:064x}",
            }
            for i in range(24)
        ]
        return {
            "schema_version": 1,
            "status": "AUDIT_PASS",
            "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
            "v4_contract": diagnose._contract_json(diagnose.production_contract()),
            "roots": {
                "v4_root": str(diagnose.V4_ROOT),
                "diagnostic_root": str(self.root),
                "clips_dir": str(clips),
                "snapshot_files": str(snapshot),
            },
            "v4": {"pinned_file_count": 24, "verified_pinned_files": pinned},
            "trials": trials,
            "clips": [clip],
            "snapshot_files": [source],
            "production_files": production,
        }

    def test_compiled_contract_has_every_reviewed_fixed_identity(self) -> None:
        # Break caught: a production path/hash/protocol/role becoming caller-controlled or stale.
        contract = diagnose.production_contract()
        self.assertEqual(
            str(contract.v4_root),
            "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4",
        )
        self.assertEqual(
            str(diagnose.DIAGNOSTIC_ROOT),
            "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v3",
        )
        self.assertEqual(
            str(diagnose.PRODUCTION_PYTHON),
            "/home/s2510040/miniconda3/envs/attn/bin/python",
        )
        self.assertEqual(str(diagnose.SBATCH_PATH), "/usr/bin/sbatch")
        self.assertEqual(
            contract.v4_protocol,
            "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1",
        )
        self.assertEqual(
            contract.evaluation_role,
            "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
        )
        self.assertEqual(
            contract.evaluator_sha256,
            "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
        )
        self.assertEqual(
            contract.runner_sha256,
            "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495",
        )
        self.assertEqual(
            contract.manifest_sha256,
            "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5",
        )
        self.assertEqual(
            contract.lock_sha256,
            "63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710",
        )
        self.assertEqual(
            contract.formal40_sha256,
            "2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff",
        )
        with self.assertRaises(Exception):
            contract.v4_root = pathlib.Path("/tmp/override")

    def test_manifest_validation_requires_all_24_records_schema2_and_exact_formal40(
        self,
    ) -> None:
        # Break caught: accepting a partial v4 freeze or old snapshot-manifest schema.
        records = [
            {
                "path": f"/frozen/file-{i}",
                "size": i + 1,
                "sha256": f"{i + 1:064x}",
                "type": "file",
            }
            for i in range(24)
        ]
        manifest = {
            "schema_version": 1,
            "protocol_id": diagnose.V4_PROTOCOL,
            "evaluation_role": diagnose.EVALUATION_ROLE,
            "inputs": {str(i): r for i, r in enumerate(records)},
            "historical_evidence": {},
            "completion": {},
            "checkpoint_selection": {},
            "models": {
                "formal40": {
                    "path": "/frozen/formal-final.ckpt",
                    "basename": "formal-final.ckpt",
                    "epoch": 40,
                    "global_step": 69440,
                    "sha256": diagnose.FORMAL40_SHA256,
                }
            },
        }
        source = {"schema_version": 2, "semantic_files": [], "provenance_files": []}
        got = diagnose.validate_v4_manifest(manifest, source)
        self.assertEqual(got["pinned_file_count"], 24)
        for changed in (
            dict(manifest, inputs={str(i): r for i, r in enumerate(records[:-1])}),
            dict(manifest, protocol_id="wrong"),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.validate_v4_manifest(changed, source)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.validate_v4_manifest(manifest, dict(source, schema_version=1))
        wrong_model = json.loads(json.dumps(manifest))
        wrong_model["models"]["formal40"]["global_step"] = 69439
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.validate_v4_manifest(wrong_model, source)
        duplicate_roles = list(records)
        duplicate_roles[-1] = dict(records[0])
        self.assertEqual(
            diagnose.validate_v4_manifest(
                dict(
                    manifest, inputs={str(i): r for i, r in enumerate(duplicate_roles)}
                ),
                source,
            )["pinned_file_count"],
            24,
        )
        conflicting = list(duplicate_roles)
        conflicting[-1] = dict(conflicting[-1], sha256="f" * 64)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.validate_v4_manifest(
                dict(manifest, inputs={str(i): r for i, r in enumerate(conflicting)}),
                source,
            )

    def test_select_trials_calls_frozen_selector_and_preserves_original_rows_and_identity(
        self,
    ) -> None:
        # Break caught: selecting independently, losing original row indices, or omitting identity.
        import pandas as pd

        columns = list(diagnose.TRIAL_IDENTITY_COLUMNS)
        rows = []
        for index in range(40):
            rows.append(
                {
                    name: (
                        index
                        if name
                        not in {
                            "scene_kind",
                            "target_speaker",
                            "target_gender",
                            "target_norm",
                        }
                        else f"{name}-{index}"
                    )
                    for name in columns
                }
            )
            rows[-1]["distractor_1_label"] = index
        bank = pd.DataFrame(rows, index=range(100, 140))
        calls = []
        evaluator = types.SimpleNamespace(
            _select_smoke_bank=lambda frame, count: (
                calls.append((frame is bank, count))
                or frame.iloc[[3, 1]].copy().reset_index(drop=True)
            )
        )
        got = diagnose.select_trials(evaluator, bank, count=2)
        self.assertEqual(calls, [(True, 2)])
        self.assertEqual(
            [(item.ordinal, item.trial_id, item.bank_row_index) for item in got],
            [(0, 3, 103), (1, 1, 101)],
        )
        self.assertEqual(tuple(got[0].identity), diagnose.TRIAL_IDENTITY_COLUMNS)

    def test_select_trials_rejects_duplicate_or_reordered_trial_identity(self) -> None:
        # Break caught: ambiguous duplicate identities or selector output not traceable to the bank.
        import pandas as pd

        bank = pd.DataFrame(
            {name: [0, 1, 2] for name in diagnose.TRIAL_IDENTITY_COLUMNS}
        )
        bank["trial_id"] = [10, 11, 12]
        duplicate = types.SimpleNamespace(
            _select_smoke_bank=lambda frame, count: frame.iloc[[0, 0]].reset_index(
                drop=True
            )
        )
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.select_trials(duplicate, bank, count=2)

    def test_trial_identity_matches_job584990_and_derives_probe_for_clean_and_mixed(
        self,
    ) -> None:
        # Break caught: freezing result-frame columns or the raw clean distractor label as authoritative identity.
        import pandas as pd

        authoritative = (
            "control_subset",
            "distractor_count",
            "probe_distractor_label",
            "scene_kind",
            "snr_bin",
            "target_gender",
            "target_label",
            "target_speaker",
            "snr_db",
            "trial_id",
        )
        bank = pd.DataFrame(
            [
                {
                    "trial_id": 9,
                    "scene_kind": "clean",
                    "control_subset": 0,
                    "target_speaker": "01",
                    "target_gender": "f",
                    "target_label": 3,
                    "distractor_count": 0,
                    "snr_bin": -1,
                    "snr_db": float("nan"),
                    "distractor_1_label": 777,
                },
                {
                    "trial_id": 4,
                    "scene_kind": "mixed",
                    "control_subset": 1,
                    "target_speaker": "02",
                    "target_gender": "m",
                    "target_label": 5,
                    "distractor_count": 1,
                    "snr_bin": 2,
                    "snr_db": 1.5,
                    "distractor_1_label": 88,
                },
            ],
            index=[101, 202],
        )
        evaluator = types.SimpleNamespace(
            _select_smoke_bank=lambda frame, count: frame.reset_index(drop=True)
        )
        got = diagnose.select_trials(evaluator, bank, count=2)
        self.assertEqual(diagnose.TRIAL_IDENTITY_COLUMNS, authoritative)
        self.assertEqual(tuple(got[0].identity), authoritative)
        self.assertEqual(got[0].identity["probe_distractor_label"], 0)
        self.assertEqual(got[1].identity["probe_distractor_label"], 88)

    def test_clip_inventory_binds_all_active_roles_and_rejects_aliases_escape_and_duplicate_rows(
        self,
    ) -> None:
        # Break caught: omitting an active audio role or accepting an aliased/escaping clip.
        import pandas as pd

        clips = self.root / "clips"
        clips.mkdir()
        row = {"trial_id": 7}
        expected = []
        for ordinal, role in enumerate(diagnose.ROLE_NAMES):
            row[f"{role}_index"] = ordinal if ordinal < 3 else -1
            row[f"{role}_path"] = f"{role}.wav" if ordinal < 3 else ""
            if ordinal < 3:
                payload = role.encode("ascii")
                (clips / f"{role}.wav").write_bytes(payload)
                expected.append(
                    (f"{role}.wav", len(payload), hashlib.sha256(payload).hexdigest())
                )
        got = diagnose.collect_clip_records(pd.DataFrame([row]), clips_dir=clips)
        self.assertEqual(
            [(x["relative_path"], x["size"], x["sha256"]) for x in got],
            sorted(expected),
        )
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_clip_records(pd.DataFrame([row, row]), clips_dir=clips)
        escaped = dict(row)
        escaped["target_path"] = "../escape.wav"
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_clip_records(pd.DataFrame([escaped]), clips_dir=clips)
        (clips / "target.wav").unlink()
        os.symlink("correct_cue.wav", clips / "target.wav")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_clip_records(pd.DataFrame([row]), clips_dir=clips)

    def test_snapshot_inventory_freezes_both_schema2_collections_and_rejects_unlisted_use(
        self,
    ) -> None:
        # Break caught: freezing only login-time imports or allowing a worker to execute unbound source.
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        entries = []
        for name, payload in (
            ("selftrain/__init__.py", b""),
            ("src/model.py", b"VALUE=3\n"),
        ):
            path = snapshot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            entries.append(
                {
                    "path": name,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "type": "file",
                }
            )
        manifest = {
            "schema_version": 2,
            "semantic_files": [entries[1]],
            "provenance_files": [entries[0], dict(entries[1])],
        }
        got = diagnose.collect_snapshot_records(
            manifest, [snapshot / "src/model.py"], snapshot_files=snapshot
        )
        self.assertEqual(
            {item["relative_path"] for item in got},
            {"selftrain/__init__.py", "src/model.py"},
        )
        bad = json.loads(json.dumps(manifest))
        bad["provenance_files"][-1]["sha256"] = "f" * 64
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_snapshot_records(bad, [], snapshot_files=snapshot)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_snapshot_records(
                manifest, [snapshot / "evil.py"], snapshot_files=snapshot
            )

    def test_exact_layout_and_check_only_are_read_only(self) -> None:
        # Break caught: accepting missing/extra/symlinked production directories or mutating during check.
        for name in diagnose.DIAGNOSTIC_LAYOUT:
            (self.root / name).mkdir(mode=0o700)
        production = []
        for name in diagnose.PRODUCTION_FILES:
            (self.root / "tools" / name).write_bytes(name.encode("ascii"))
            production.append(
                trace.stable_file_record(
                    self.root / "tools" / name, allowed_root=self.root / "tools"
                )
            )
        audit = self.complete_audit(production)
        diagnose._freeze_inputs(
            confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
            diagnostic_root=self.root,
            contract=diagnose.production_contract(),
            audit_loader=lambda **kwargs: audit,
        )
        freeze = self.root / "input_freeze.json"
        digest = hashlib.sha256(freeze.read_bytes()).hexdigest()
        before = trace.fingerprint_tree(self.root)
        got = diagnose._check_only(
            expected_input_freeze_sha256=digest,
            diagnostic_root=self.root,
            contract=diagnose.production_contract(),
            audit_loader=lambda **kwargs: audit,
        )
        after = trace.fingerprint_tree(self.root)
        self.assertEqual(got["status"], "CHECK_PASS")
        self.assertEqual(got["input_freeze_sha256"], digest)
        self.assertEqual(before, after)
        (self.root / "logs").rmdir()
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._check_only(
                expected_input_freeze_sha256=digest,
                diagnostic_root=self.root,
                contract=diagnose.production_contract(),
                audit_loader=lambda **kwargs: audit,
            )

    def test_create_once_publication_and_nonblocking_shared_lock(self) -> None:
        # Break caught: overwriting immutable evidence or waiting indefinitely behind an exclusive holder.
        target = self.root / "evidence.json"
        diagnose.atomic_create_json(target, {"z": 1, "a": "é"})
        self.assertEqual(target.read_bytes(), b'{"a":"\\u00e9","z":1}\n')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            diagnose.atomic_create_bytes(target, b"replacement")
        lock = self.root / "lock"
        lock.write_bytes(b"lock")
        with diagnose.shared_v4_lock(lock):
            with diagnose.shared_v4_lock(lock):
                pass
        with open(lock, "rb") as handle:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(diagnose.DiagnosticError):
                with diagnose.shared_v4_lock(lock):
                    pass

    def test_atomic_publication_revalidates_final_mode_identity_and_bytes(self) -> None:
        # Break caught: reporting success after the published name was tampered with during linking.
        target = self.root / "tampered"
        real_link = diagnose.os.link

        def tampering_link(src, dst, **kwargs):
            result = real_link(src, dst, **kwargs)
            os.chmod(target, 0o644)
            return result

        with mock.patch.object(diagnose.os, "link", side_effect=tampering_link):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.atomic_create_bytes(target, b"reviewed")

    def test_atomic_publication_closes_parent_descriptor_when_temp_open_fails(
        self,
    ) -> None:
        # Break caught: leaking the already-open parent directory fd on temp creation failure.
        target = self.root / "failure"
        real_open = diagnose.os.open
        directory_fds = []

        def failing_open(path, flags, *args, **kwargs):
            if kwargs.get("dir_fd") is not None and flags & os.O_CREAT:
                raise OSError("injected temp-open failure")
            descriptor = real_open(path, flags, *args, **kwargs)
            if pathlib.Path(path) == self.root and flags & getattr(
                os, "O_DIRECTORY", 0
            ):
                directory_fds.append(descriptor)
            return descriptor

        with mock.patch.object(diagnose.os, "open", side_effect=failing_open):
            with self.assertRaises(OSError):
                diagnose.atomic_create_bytes(target, b"x")
        self.assertEqual(len(directory_fds), 1)
        with self.assertRaises(OSError):
            os.fstat(directory_fds[0])

    def test_atomic_publication_rejects_final_file_changed_after_descriptor_read(
        self,
    ) -> None:
        # Break caught: a final-path mutation in the gap after EOF but before publication returns.
        target = self.root / "late-race"
        real_open, real_read = diagnose.os.open, diagnose.os.read
        final_fds = set()
        mutated = [False]

        def tracking_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if (
                path == target.name
                and kwargs.get("dir_fd") is not None
                and not flags & os.O_CREAT
            ):
                final_fds.add(descriptor)
            return descriptor

        def mutating_read(descriptor, size):
            chunk = real_read(descriptor, size)
            if descriptor in final_fds and not chunk and not mutated[0]:
                mutated[0] = True
                target.write_bytes(b"evilbytes")
            return chunk

        with (
            mock.patch.object(diagnose.os, "open", side_effect=tracking_open),
            mock.patch.object(diagnose.os, "read", side_effect=mutating_read),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.atomic_create_bytes(target, b"reviewed!")

    def test_atomic_publication_closes_parent_fd_on_write_fsync_and_link_failures(
        self,
    ) -> None:
        # Break caught: exceptions after temp creation skipping the later parent-fd close block.
        for phase in ("write", "fsync", "link"):
            with self.subTest(phase=phase):
                target = self.root / f"failure-{phase}"
                real_open, real_write, real_fsync, real_link = (
                    diagnose.os.open,
                    diagnose.os.write,
                    diagnose.os.fsync,
                    diagnose.os.link,
                )
                directory_fds = []

                def tracking_open(path, flags, *args, **kwargs):
                    fd = real_open(path, flags, *args, **kwargs)
                    if pathlib.Path(path) == self.root and flags & getattr(
                        os, "O_DIRECTORY", 0
                    ):
                        directory_fds.append(fd)
                    return fd

                def maybe_write(fd, data):
                    if phase == "write":
                        raise OSError("injected write failure")
                    return real_write(fd, data)

                fsync_calls = [0]

                def maybe_fsync(fd):
                    fsync_calls[0] += 1
                    if phase == "fsync" and fsync_calls[0] == 1:
                        raise OSError("injected temp fsync failure")
                    return real_fsync(fd)

                def maybe_link(*args, **kwargs):
                    if phase == "link":
                        raise OSError("injected link failure")
                    return real_link(*args, **kwargs)

                with (
                    mock.patch.object(diagnose.os, "open", side_effect=tracking_open),
                    mock.patch.object(diagnose.os, "write", side_effect=maybe_write),
                    mock.patch.object(diagnose.os, "fsync", side_effect=maybe_fsync),
                    mock.patch.object(diagnose.os, "link", side_effect=maybe_link),
                ):
                    with self.assertRaises(OSError):
                        diagnose.atomic_create_bytes(target, b"payload")
                self.assertEqual(len(directory_fds), 1)
                try:
                    os.fstat(directory_fds[0])
                    closed = False
                except OSError:
                    closed = True
                if not closed:
                    os.close(directory_fds[0])
                self.assertTrue(closed)

    def test_freeze_binds_four_tools_trials_clips_sources_and_refuses_overwrite(
        self,
    ) -> None:
        # Break caught: an incomplete or mutable diagnostic input freeze.
        for name in diagnose.DIAGNOSTIC_LAYOUT:
            (self.root / name).mkdir(mode=0o700)
        tools = self.root / "tools"
        tool_records = []
        for name in diagnose.PRODUCTION_FILES:
            payload = name.encode("ascii")
            (tools / name).write_bytes(payload)
            tool_records.append(
                trace.stable_file_record(tools / name, allowed_root=tools)
            )
        audit = self.complete_audit(tool_records)
        got = diagnose._freeze_inputs(
            confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
            diagnostic_root=self.root,
            contract=diagnose.production_contract(),
            audit_loader=lambda **kwargs: audit,
        )
        self.assertEqual(got["status"], "INPUTS_FROZEN")
        payload = json.loads((self.root / "input_freeze.json").read_text())
        self.assertEqual(payload["diagnostic_protocol"], diagnose.DIAGNOSTIC_PROTOCOL)
        self.assertEqual(len(payload["production_files"]), 4)
        self.assertEqual(len(payload["v4"]["verified_pinned_files"]), 24)
        with self.assertRaises(FileExistsError):
            diagnose._freeze_inputs(
                confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
                diagnostic_root=self.root,
                contract=diagnose.production_contract(),
                audit_loader=lambda **kwargs: audit,
            )

    def test_freeze_rejects_count_only_contracts(self) -> None:
        # Break caught: accepting attacker-chosen/count-only input-freeze content.
        for name in diagnose.DIAGNOSTIC_LAYOUT:
            (self.root / name).mkdir(mode=0o700)
        production = []
        for name in diagnose.PRODUCTION_FILES:
            (self.root / "tools" / name).write_bytes(name.encode())
            production.append(
                trace.stable_file_record(
                    self.root / "tools" / name, allowed_root=self.root / "tools"
                )
            )
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._freeze_inputs(
                confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
                diagnostic_root=self.root,
                contract=diagnose.production_contract(),
                audit_loader=lambda **kwargs: {
                    "status": "AUDIT_PASS",
                    "trials": [{"trial_id": i} for i in range(32)],
                    "production_files": production,
                    "v4": {
                        "pinned_file_count": 24,
                        "verified_pinned_files": [
                            {"path": f"/f/{i}", "size": i, "sha256": f"{i:064x}"}
                            for i in range(24)
                        ],
                    },
                },
            )

    def test_check_only_reconstructs_and_rejects_schema_valid_freeze_mutations(
        self,
    ) -> None:
        # Break caught: trusting a self-consistent canonical freeze instead of rebuilding live inputs.
        mutations = (
            lambda value: value["trials"][0]["identity"].__setitem__(
                "target_label", 999
            ),
            lambda value: value["clips"][0]["uses"][0].__setitem__(
                "role", "correct_cue"
            ),
            lambda value: value["snapshot_files"][0].__setitem__(
                "observed_import", False
            ),
            lambda value: value["v4"]["verified_pinned_files"][0].__setitem__(
                "sha256", "f" * 64
            ),
        )
        original_root = self.root
        for mutate in mutations:
            with (
                self.subTest(mutation=mutate),
                tempfile.TemporaryDirectory(dir="/private/tmp") as raw,
            ):
                self.root = pathlib.Path(raw)
                for name in diagnose.DIAGNOSTIC_LAYOUT:
                    (self.root / name).mkdir(mode=0o700)
                production = []
                for name in diagnose.PRODUCTION_FILES:
                    (self.root / "tools" / name).write_bytes(name.encode())
                    production.append(
                        trace.stable_file_record(
                            self.root / "tools" / name, allowed_root=self.root / "tools"
                        )
                    )
                audit = self.complete_audit(production)
                diagnose._freeze_inputs(
                    confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
                    diagnostic_root=self.root,
                    contract=diagnose.production_contract(),
                    audit_loader=lambda **kwargs: audit,
                )
                freeze = self.root / "input_freeze.json"
                value = json.loads(freeze.read_text())
                mutate(value)
                freeze.unlink()
                freeze.write_bytes(trace.canonical_json_bytes(value))
                digest = hashlib.sha256(freeze.read_bytes()).hexdigest()
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._check_only(
                        expected_input_freeze_sha256=digest,
                        diagnostic_root=self.root,
                        contract=diagnose.production_contract(),
                        audit_loader=lambda **kwargs: audit,
                    )
        self.root = original_root

    def test_public_freeze_and_check_reject_internal_root_contract_or_loader_injection(
        self,
    ) -> None:
        # Break caught: exposing hermetic seams as a production bypass around compiled identities.
        with self.assertRaises(TypeError):
            diagnose.freeze_inputs(
                confirm_protocol=diagnose.DIAGNOSTIC_PROTOCOL,
                diagnostic_root=self.root,
                _audit_loader=lambda **kwargs: {},
            )
        with self.assertRaises(TypeError):
            diagnose.check_only(
                expected_input_freeze_sha256="0" * 64,
                diagnostic_root=self.root,
                contract=diagnose.production_contract(),
                _audit_loader=lambda **kwargs: {},
            )

    def test_snapshot_entry_points_reject_symlinked_supplied_root(self) -> None:
        # Break caught: resolving a snapshot-root symlink before checking its named type.
        real = self.root / "real-snapshot"
        real.mkdir()
        alias = self.root / "snapshot-alias"
        alias.symlink_to(real, target_is_directory=True)
        source = real / "x.py"
        source.write_bytes(b"X=1\n")
        entry = {
            "path": "x.py",
            "size": 4,
            "sha256": hashlib.sha256(b"X=1\n").hexdigest(),
            "type": "file",
        }
        manifest = {
            "schema_version": 2,
            "semantic_files": [entry],
            "provenance_files": [],
        }
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.collect_snapshot_records(manifest, [], snapshot_files=alias)
        scene_files = {
            "selftrain/__init__.py": b"",
            "selftrain/data/__init__.py": b"",
            "selftrain/data/diotic_attention.py": b"class WaveformCache: pass\n",
            "selftrain/scripts/__init__.py": b"",
            "selftrain/scripts/eval_full_pilot.py": b"def _raw_scene_batch(): pass\ndef _correct_cue_batch(): pass\n",
        }
        records = {}
        for relative, payload in scene_files.items():
            path = real / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            records[relative] = {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "type": "file",
            }
        with self.assertRaises(diagnose.DiagnosticError):
            with diagnose.frozen_scene_context(alias, records):
                pass

    def test_layout_rejects_symlinked_root(self) -> None:
        # Break caught: resolving and accepting a symlink in place of the fixed diagnostic root.
        real = self.root / "real"
        real.mkdir(mode=0o700)
        for name in diagnose.DIAGNOSTIC_LAYOUT:
            (real / name).mkdir(mode=0o700)
        alias = self.root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._validate_layout(alias, require_freeze=False)

    def test_every_public_cli_emits_one_canonical_json_document_on_stdout(self) -> None:
        # Break caught: banners/warnings preceding JSON or non-canonical public output.
        commands = (
            ("audit-inputs",),
            ("freeze-inputs", "--confirm-protocol", diagnose.DIAGNOSTIC_PROTOCOL),
            ("check-only", "--expected-input-freeze-sha256", "0" * 64),
        )
        for arguments in commands:
            with self.subTest(command=arguments[0]):
                outcome = subprocess.run(
                    [sys.executable, "-I", "-B", str(DIAGNOSER), *arguments],
                    text=True,
                    capture_output=True,
                    check=False,
                    env={
                        **os.environ,
                        "PYTHONNOUSERSITE": "1",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONHASHSEED": "0",
                    },
                )
                self.assertNotEqual(outcome.returncode, 0)
                document = json.loads(outcome.stdout)
                self.assertEqual(
                    outcome.stdout.encode(), trace.canonical_json_bytes(document)
                )


class IsolatedImportTests(unittest.TestCase):
    """Task 3 exact-source loader and manifest-backed importer regressions."""

    def setUp(self) -> None:
        self.assertIsNotNone(diagnose, "Task 3 diagnoser is missing")
        self.temporary_directory = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = pathlib.Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        if hasattr(self, "temporary_directory"):
            self.temporary_directory.cleanup()

    def test_sha_bound_numeric_trace_loads_under_isolated_python(self) -> None:
        # Break caught: relying on the script directory being present under -I.
        outcome = subprocess.run(
            [sys.executable, "-I", "-B", str(DIAGNOSER), "_self-test-isolated-loader"],
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
            },
        )
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        document = json.loads(outcome.stdout)
        self.assertEqual(document["status"], "ISOLATED_IMPORT_PASS")
        self.assertFalse(document["package_root_on_sys_path"])
        self.assertEqual(outcome.stdout.encode(), trace.canonical_json_bytes(document))

    def test_loader_executes_verified_descriptor_bytes_and_ignores_stale_pyc(
        self,
    ) -> None:
        # Break caught: verifying one pathname read but importing replacement/bytecode bytes.
        source = self.root / "bound.py"
        source.write_bytes(b"VALUE = 'reviewed'\n")
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        sys.modules.pop("task3_bound_attack", None)
        (self.root / "bound.pyc").write_bytes(b"malicious bytecode")
        module = diagnose.load_verified_source_module(
            source,
            expected_size=len(payload),
            expected_sha256=digest,
            module_name="task3_bound_attack",
        )
        self.assertEqual(module.VALUE, "reviewed")
        self.assertEqual(module.__file__, str(source.resolve()))
        sys.modules.pop("task3_bound_attack", None)

    def test_loader_executes_returned_descriptor_bytes_after_pathname_replacement(
        self,
    ) -> None:
        # Break caught: re-opening a verified pathname for execution after bootstrap verification.
        source = self.root / "race.py"
        source.write_bytes(b"VALUE = 'reviewed'\n")
        replacement = self.root / "replacement.py"
        replacement.write_bytes(b"VALUE = 'malicious'\n")
        verified, record = diagnose._read_stable_source_bytes(
            source, allowed_root=self.root
        )

        def bootstrap_then_replace(path, *, allowed_root):
            replacement.replace(source)
            return verified, record

        sys.modules.pop("task3_replacement_attack", None)
        with mock.patch.object(
            diagnose, "_read_stable_source_bytes", side_effect=bootstrap_then_replace
        ):
            module = diagnose.load_verified_source_module(
                source,
                expected_size=len(verified),
                expected_sha256=hashlib.sha256(verified).hexdigest(),
                module_name="task3_replacement_attack",
            )
        self.assertEqual(module.VALUE, "reviewed")
        sys.modules.pop("task3_replacement_attack", None)

    def test_verified_evaluator_exposes_only_reviewed_read_inference_surface(
        self,
    ) -> None:
        # Break caught: giving diagnostic code access to v4 publication functions.
        source = self.root / "evaluator.py"
        source.write_text(
            "\n".join(
                f"def {name}(*a, **k): return {name!r}"
                for name in (
                    *diagnose.V4_EVALUATOR_WHITELIST,
                    "run_evaluation",
                    "_create_attempt_directory",
                )
            )
            + "\n"
        )
        payload = source.read_bytes()
        facade = diagnose.load_verified_v4_evaluator(
            trace, source, len(payload), hashlib.sha256(payload).hexdigest()
        )
        self.assertEqual(set(facade.__dict__), set(diagnose.V4_EVALUATOR_WHITELIST))
        self.assertFalse(hasattr(facade, "run_evaluation"))

    def test_manifest_source_loader_handles_packages_records_imports_and_releases_callbacks(
        self,
    ) -> None:
        # Break caught: normal/path/pyc import bypass or callbacks retained beyond frozen context.
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        files = {
            "selftrain/__init__.py": b"",
            "selftrain/data/__init__.py": b"",
            "selftrain/data/diotic_attention.py": b"class WaveformCache: pass\n",
            "selftrain/scripts/__init__.py": b"",
            "selftrain/scripts/eval_full_pilot.py": b"def _raw_scene_batch(): return 'raw'\ndef _correct_cue_batch(): return 'cue'\n",
            "corpus/binaural_attention_h5.py": b"VALUE = 'frozen-corpus'\n",
        }
        records = {}
        for relative, payload in files.items():
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            records[relative] = {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "type": "file",
            }
        old_corpus = types.ModuleType("corpus.binaural_attention_h5")
        old_corpus.VALUE = "preloaded"
        sys.modules["corpus.binaural_attention_h5"] = old_corpus
        with diagnose.frozen_scene_context(snapshot, records) as api:
            import corpus.binaural_attention_h5 as corpus_module

            self.assertEqual(corpus_module.VALUE, "frozen-corpus")
            self.assertEqual(api.raw_scene_batch(), "raw")
            self.assertEqual(api.correct_cue_batch(), "cue")
            self.assertTrue(issubclass(api.waveform_cache_class, object))
            self.assertEqual(
                {x["relative_path"] for x in api.imported_source_records}, set(files)
            )
            callbacks = (api.raw_scene_batch, api.correct_cue_batch)
        self.assertNotIn("selftrain.data.diotic_attention", sys.modules)
        self.assertNotIn("selftrain.scripts.eval_full_pilot", sys.modules)
        self.assertTrue(
            all(callback.__module__.startswith("selftrain.") for callback in callbacks)
        )
        self.assertIs(sys.modules["corpus.binaural_attention_h5"], old_corpus)
        with self.assertRaises(diagnose.DiagnosticError):
            api.raw_scene_batch()
        with self.assertRaises(diagnose.DiagnosticError):
            api.waveform_cache_class()
        sys.modules.pop("corpus.binaural_attention_h5", None)

    def test_real_v4_historical_scene_binding_shape_is_required(self) -> None:
        # Break caught: reading the obsolete historical_evidence.scene_binding location.
        binding = {
            "trials": 10000,
            "scene_hashes": 10000,
            "identity_columns": list(diagnose.TRIAL_IDENTITY_COLUMNS),
            "scene_hash_vector_sha256": "a" * 64,
        }
        self.assertEqual(
            diagnose._historical_scene_binding(
                {"audits": {"job584990_scene_binding": binding}}
            ),
            binding,
        )
        for bad in ({}, {"audits": {"job584990_scene_binding": {"trials": 9999}}}):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._historical_scene_binding(bad)
        wrong = dict(binding, identity_columns=["trial_id"])
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._historical_scene_binding(
                {"audits": {"job584990_scene_binding": wrong}}
            )


class _Task4Cochleagram:
    def __init__(self, calls, *, container="tuple", mutate_input=False):
        self.calls = calls
        self.container = container
        self.mutate_input = mutate_input
        self.call_count = 0

    def full_rep(self, value, background):
        self.call_count += 1
        self.calls.append("scene_coch" if self.call_count % 2 else "cue_coch")
        if background is not None:
            raise AssertionError("frozen cochleagram background must be None")
        selected = "scene" if self.call_count % 2 else "cue"
        if self.mutate_input is True or self.mutate_input == selected:
            value.add_(1.0)
        result = value
        if self.container == "tuple":
            return result, None
        if self.container == "list":
            return [result, None]
        if self.container == "tensor":
            return result
        return ["not-a-tensor", None]


class _Task4Model(torch.nn.Module):
    def __init__(
        self,
        calls=None,
        *,
        coch_container="tuple",
        mutate_feature=False,
        bad_logits_shape=False,
        mutate_normalized=False,
    ):
        super().__init__()
        self.calls = calls if calls is not None else []
        self.register_buffer("anchor", torch.tensor([1.0]))
        self.coch_gram = types.SimpleNamespace(
            full_rep=_Task4Cochleagram(
                self.calls,
                container=coch_container,
                mutate_input=mutate_normalized,
            ).full_rep
        )
        self.audio_transforms = lambda value: value
        self.mutate_feature = mutate_feature
        self.bad_logits_shape = bad_logits_shape
        self.eval()
        for parameter in self.parameters():
            parameter.requires_grad_(False)

    def forward(self, cue_features, scene_features, background):
        self.calls.append("model")
        if background is not None:
            raise AssertionError("frozen model background must be None")
        if self.mutate_feature is True or self.mutate_feature == "scene":
            scene_features.add_(1.0)
        if self.mutate_feature == "cue":
            cue_features.add_(1.0)
        batch = int(scene_features.shape[0])
        width = 799 if self.bad_logits_shape else 800
        base = (scene_features + cue_features).reshape(batch, -1).mean(dim=1)
        offsets = torch.arange(width, dtype=base.dtype, device=base.device)
        return base[:, None] + offsets[None, :] / 1000.0


class _InferenceAllocatedMutationModel(_Task4Model):
    """Creates and mutates tensors whose inference-mode version is unavailable."""

    def __init__(self, calls=None):
        super().__init__(calls)
        state = {"calls": 0}

        def full_rep(value, background):
            state["calls"] += 1
            self.calls.append("scene_coch" if state["calls"] % 2 else "cue_coch")
            created = value.clone()
            created.add_(1.0)
            return created, None

        self.coch_gram = types.SimpleNamespace(full_rep=full_rep)


class _SanitizingModel(_Task4Model):
    def __init__(self, calls=None, *, inject_feature_nan=False):
        super().__init__(calls)
        state = {"calls": 0}

        def full_rep(value, background):
            state["calls"] += 1
            self.calls.append("scene_coch" if state["calls"] % 2 else "cue_coch")
            cleaned = torch.nan_to_num(value)
            if inject_feature_nan:
                cleaned = cleaned.clone()
                cleaned.reshape(-1)[0] = float("nan")
            return cleaned, None

        self.coch_gram = types.SimpleNamespace(full_rep=full_rep)

    def forward(self, cue_features, scene_features, background):
        return super().forward(
            torch.nan_to_num(cue_features), torch.nan_to_num(scene_features), background
        )


class _Task4Evaluator:
    def __init__(
        self,
        calls=None,
        *,
        mutate_raw=False,
        reference_delta=0.0,
        model_to_load=None,
        sanitize_raw=False,
        inject_normalized_nan=False,
        strict_load_hook=None,
        preprocess_hook=None,
    ):
        self.calls = calls if calls is not None else []
        self.mutate_raw = mutate_raw
        self.reference_delta = reference_delta
        self.model_to_load = model_to_load
        self.sanitize_raw = sanitize_raw
        self.inject_normalized_nan = inject_normalized_nan
        self.preprocess_count = 0
        self.predict_calls = []
        self.load_calls = []
        self.strict_load_hook = strict_load_hook
        self.preprocess_hook = preprocess_hook
        self.configure_hook = None
        self.predict_mutate_raw = False

    def singleton_native_preprocess(self, model, raw):
        self.preprocess_count += 1
        self.calls.append(
            "scene_preprocess" if self.preprocess_count % 2 else "cue_preprocess"
        )
        if self.preprocess_hook is not None:
            self.preprocess_hook(self.preprocess_count)
        selected = "scene" if self.preprocess_count % 2 else "cue"
        if (
            self.mutate_raw is True
            and selected == "scene"
            or self.mutate_raw == selected
        ):
            raw.add_(1.0)
        raw = model.audio_transforms(raw)
        result = torch.nan_to_num(raw) if self.sanitize_raw else raw + 0.0
        if self.inject_normalized_nan:
            result = result.clone()
            result.reshape(-1)[0] = float("nan")
        return result

    def predict_batch(self, model, raw_scene, raw_cue, labels, probes, device):
        self.calls.append("frozen_predict_batch")
        self.predict_calls.append(
            (id(model), int(raw_scene.shape[0]), id(raw_scene), id(raw_cue))
        )
        if self.predict_mutate_raw:
            raw_scene.add_(1.0)
        batch = int(raw_scene.shape[0])
        labels_np = labels.detach().cpu().numpy().astype(np.int64, copy=True)
        return {
            "pred_label": labels_np,
            "nll": np.arange(batch, dtype=np.float32)
            + np.float32(self.reference_delta),
            "p_target": np.full(batch, 0.5, dtype=np.float32),
            "p_probe_distractor": np.full(batch, 0.25, dtype=np.float32),
        }

    def strict_load_model(self, manifest, model_id, device=None):
        self.load_calls.append((manifest, model_id, device))
        if self.strict_load_hook is not None:
            self.strict_load_hook()
        model = self.model_to_load or _Task4Model(self.calls)
        model.to(device)
        report = {
            "key_count": 1,
            "missing_keys": [],
            "unexpected_keys": [],
            "shape_mismatches": {},
            "dtype_mismatches": {},
            "prefix_rule": "exact",
            "loaded_trainable_numel": 1,
            "trainable_numel": 1,
            "loaded_trainable_numel_ratio": 1.0,
            "native_preprocessing": "selftrain_singleton_per_example_leveling",
            "model_module": {"path": "/frozen/src/spatial_attn_lightning.py"},
        }
        return model, report

    def _configure_runtime(self, allow_cpu):
        if self.configure_hook is not None:
            self.configure_hook()
        self.calls.append(("configure_runtime", allow_cpu))
        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.set_float32_matmul_precision("medium")
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        return torch.device("cpu")


@contextlib.contextmanager
def _task4_hermetic_worker_context(evaluator, scene_api_override=None):
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        files = {
            "evaluator": (root / "evaluator.py", b"verified evaluator bytes\n"),
            "manifest": (root / "input_freeze.json", b'{"verified":true}\n'),
            "pinned": (root / "pinned.bin", b"pinned\n"),
            "source": (root / "source.py", b"source\n"),
        }
        for path, payload in files.values():
            path.write_bytes(payload)
        records = {
            name: trace.stable_file_record(path, allowed_root=root)
            for name, (path, _) in files.items()
        }
        manifest = {"verified": True}
        capability = diagnose._issue_hermetic_frozen_capability(
            evaluator=evaluator,
            manifest=manifest,
            root=root,
            evaluator_record=records["evaluator"],
            manifest_record=records["manifest"],
            pinned_records=[records["pinned"]],
            source_records=[records["source"]],
        )
        scene_api = scene_api_override or types.SimpleNamespace()
        object.__setattr__(scene_api, "imported_source_records", (records["source"],))
        with diagnose._hermetic_frozen_scene_scope(
            capability,
            scene_api,
            (records["source"],),
        ):
            yield {
                "evaluator": evaluator,
                "manifest": manifest,
                "scene_api": scene_api,
                "imported_source_records": (records["source"],),
                "_frozen_context_capability": capability,
            }


@contextlib.contextmanager
def _task4_lazy_source_worker_context(evaluator, before_issue=None):
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        payloads = {
            "evaluator": b"verified evaluator bytes\n",
            "manifest": b'{"verified":true}\n',
            "pinned": b"pinned\n",
            "source": b"source\n",
            "lazy": b"lazy source\n",
        }
        paths = {name: root / f"{name}.bin" for name in payloads}
        for name, path in paths.items():
            path.write_bytes(payloads[name])
        records = {
            name: trace.stable_file_record(path, allowed_root=root)
            for name, path in paths.items()
        }
        manifest = {"verified": True}
        scene_api = types.SimpleNamespace(imported_source_records=(records["source"],))
        if before_issue is not None:
            before_issue(scene_api, records["lazy"])
        capability = diagnose._issue_hermetic_frozen_capability(
            evaluator=evaluator,
            manifest=manifest,
            root=root,
            evaluator_record=records["evaluator"],
            manifest_record=records["manifest"],
            pinned_records=[records["pinned"]],
            source_records=[records["source"], records["lazy"]],
        )
        with diagnose._hermetic_frozen_scene_scope(
            capability,
            scene_api,
            scene_api.imported_source_records,
        ):
            yield (
                {
                    "evaluator": evaluator,
                    "manifest": manifest,
                    "scene_api": scene_api,
                    "imported_source_records": scene_api.imported_source_records,
                    "_frozen_context_capability": capability,
                },
                scene_api,
                records["lazy"],
            )


@contextlib.contextmanager
def _task4_attested_context(evaluator, model):
    evaluator.model_to_load = model
    with _task4_hermetic_worker_context(evaluator) as worker_context:
        prepared = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
        evaluator.calls.clear()
        with diagnose._prediction_evaluator_context(
            evaluator,
            model=model,
            attestation=prepared["_formal40_worker_attestation"],
        ):
            yield prepared


class _Task4Cache:
    instances = []

    def __init__(self, *, max_items):
        self.max_items = max_items
        self.calls = []
        self.__class__.instances.append(self)


class _Task4SceneAPI:
    waveform_cache_class = _Task4Cache

    def __init__(self, *, corrupt_trial=None, exited=False):
        self.corrupt_trial = corrupt_trial
        self.exited = exited
        self.imported_source_records = (
            {"relative_path": "selftrain/scripts/eval_full_pilot.py"},
        )
        self.raw_calls = []
        self.cue_calls = []

    def _require_active(self):
        if self.exited:
            raise diagnose.DiagnosticError("frozen scene API used after context exit")

    def raw_scene_batch(self, frame, cache, clips_dir, *, snr_errors):
        self._require_active()
        self.raw_calls.append(
            (
                tuple(int(x) for x in frame["trial_id"]),
                id(cache),
                id(snr_errors),
                pathlib.Path(clips_dir),
            )
        )
        snr_errors.extend(float(x) / 1000.0 for x in frame["trial_id"])
        rows = []
        for trial_id in frame["trial_id"]:
            value = float(trial_id)
            if self.corrupt_trial == int(trial_id):
                value += 0.5
            rows.append(torch.full((2, 4), value, dtype=torch.float32))
        return torch.stack(rows)

    def correct_cue_batch(self, frame, cache, clips_dir):
        self._require_active()
        self.cue_calls.append(
            (
                tuple(int(x) for x in frame["trial_id"]),
                id(cache),
                pathlib.Path(clips_dir),
            )
        )
        return torch.stack(
            [
                torch.full((2, 4), float(trial_id) / 10.0, dtype=torch.float32)
                for trial_id in frame["trial_id"]
            ]
        )


def _task4_bank(count=4):
    import pandas as pd

    return pd.DataFrame(
        {
            "trial_id": list(range(100, 100 + count)),
            "target_label": [index % 800 for index in range(count)],
            "distractor_1_label": [(index + 1) % 800 for index in range(count)],
            "scene_kind": ["mixed"] * count,
        },
        index=list(range(20, 20 + count)),
    )


def _task4_trials(bank):
    return tuple(
        diagnose.TrialSpec(
            index, int(row.trial_id), int(bank_index), {"trial_id": int(row.trial_id)}
        )
        for index, (bank_index, row) in enumerate(bank.iterrows())
    )


def _task4_scene_hashes(bank):
    return {
        int(trial_id): hashlib.sha256(
            trace.canonical_tensor_bytes(
                torch.full((2, 4), float(trial_id), dtype=torch.float32)
            )
        ).hexdigest()
        for trial_id in bank["trial_id"]
    }


class PredictionPathTests(unittest.TestCase):
    """Task 4 frozen operator, scene, model-load, and mutation contracts."""

    def setUp(self):
        self.calls = []
        self.evaluator = _Task4Evaluator(self.calls)
        self.model = _Task4Model(self.calls)
        self.device = torch.device("cpu")
        self.bank = _task4_bank()
        self.trials = _task4_trials(self.bank)
        self.hashes = _task4_scene_hashes(self.bank)
        _Task4Cache.instances.clear()

    def test_matrix_and_execution_order_are_exact_and_immutable(self):
        # Break caught: adding a cell, changing the sole variables, or moving equivalence after interpretation.
        self.assertEqual(tuple(diagnose.CELL_SPECS), ("A1", "A2", "B1", "B2"))
        self.assertEqual(
            [
                (key, value.cell_id, value.autocast_enabled, value.pass_batch_sizes)
                for key, value in diagnose.CELL_SPECS.items()
            ],
            [
                ("A1", "A1", True, (16, 16)),
                ("A2", "A2", True, (16, 1)),
                ("B1", "B1", False, (16, 16)),
                ("B2", "B2", False, (16, 1)),
            ],
        )
        self.assertEqual(
            diagnose.EXECUTION_ORDER,
            ("REFERENCE_COLD", "A2", "EQUIVALENCE", "A1", "B1", "B2"),
        )
        with self.assertRaises(Exception):
            diagnose.CELL_SPECS["A2"].autocast_enabled = False

    def test_callable_seal_budget_has_exact_boundary_and_rejects_wide_graph(self):
        # Break caught: enqueueing a wide graph before checking the shared cap,
        # or recursively following __wrapped__ until Python raises RecursionError.
        import functools

        def graph_with_children(count):
            children = tuple(
                functools.partial(int, base=index + 2) for index in range(count)
            )

            def root():
                return children[0] if children else None

            return root

        with self.subTest(case="exact-cap"):
            exact = diagnose._callable_graph_fingerprint(graph_with_children(9_999))
            self.assertTrue(exact)
        with self.subTest(case="cap-plus-one"):
            with self.assertRaisesRegex(diagnose.DiagnosticError, "limit|budget"):
                diagnose._callable_graph_fingerprint(graph_with_children(10_000))
        with self.subTest(case="deep-wrapped"):

            def wrapped():
                return None

            for _ in range(1_100):

                def child():
                    return None

                child.__wrapped__ = wrapped
                wrapped = child
            with self.assertRaisesRegex(diagnose.DiagnosticError, "limit|budget|depth"):
                diagnose._callable_graph_fingerprint(wrapped)

    def test_data_free_seals_do_not_execute_repr_str_or_getattr(self):
        # Break caught: liveness executing defaults, scalar repr, spoofed array
        # attributes, or registry-key string conversion before rejection.
        with self.subTest(case="defaults"):
            events = []

            class Poison:
                def __repr__(self):
                    events.append("repr")
                    return "poison"

            poison = Poison()

            def with_defaults(value=poison, *, option=poison):
                return value, option

            diagnose._callable_graph_fingerprint(with_defaults)
            self.assertEqual(events, [])

        with self.subTest(case="scalar-subclass"):
            events = []

            class PoisonInt(int):
                def __repr__(self):
                    events.append("scalar-repr")
                    return "7"

            diagnose._execution_configuration_fingerprint(PoisonInt(7))
            self.assertEqual(events, [])

        with self.subTest(case="spoof-array"):
            events = []

            class SpoofedArray:
                __module__ = "torch.spoofed"

                def __getattribute__(self, name):
                    if name in {"shape", "dtype", "device", "_version"}:
                        events.append(f"getattr:{name}")
                        raise AttributeError(name)
                    return object.__getattribute__(self, name)

            diagnose._execution_configuration_fingerprint(SpoofedArray())
            self.assertEqual(events, [])

        for registry_name in ("_modules", "_parameters", "_buffers"):
            with self.subTest(case=f"registry:{registry_name}"):
                events = []

                class PoisonKey:
                    def __hash__(self):
                        return 1

                    def __str__(self):
                        events.append("str")
                        return "poison-key"

                model = _Task4Model([])
                registry = object.__getattribute__(model, "__dict__")[registry_name]
                registry[PoisonKey()] = None
                events.clear()
                with self.assertRaises(diagnose.DiagnosticError):
                    if registry_name == "_modules":
                        diagnose._direct_model_module_inventory(model)
                    else:
                        diagnose._registered_state_fingerprint(model, registry_name)
                self.assertEqual(events, [])

    def test_alias_default_module_chain_and_callable_hook_helper_are_sealed(self):
        # Break caught: bytecode-local/default aliases and callable-object hook
        # helpers remaining outside the transitive execution graph.
        for case, source in (
            (
                "local-global-alias",
                "def role(value):\n alias = dependency\n"
                " return alias.API.helper(value)\n",
            ),
            (
                "default-module",
                "def role(value, module=dependency):\n"
                " return module.API.helper(value)\n",
            ),
            (
                "module-class-chain",
                "def role(value):\n return dependency.API.helper(value)\n",
            ),
        ):
            with self.subTest(case=case):
                invoked = []
                dependency = types.ModuleType(f"_task4_round5_{case}")

                class API:
                    @staticmethod
                    def helper(value):
                        return value

                dependency.API = API
                namespace = {"dependency": dependency}
                exec(source, namespace)
                role = namespace["role"]
                before = diagnose._callable_graph_fingerprint(role)
                API.helper = staticmethod(lambda value: invoked.append(case) or value)
                self.assertNotEqual(diagnose._callable_graph_fingerprint(role), before)
                self.assertEqual(invoked, [])

        with self.subTest(case="callable-object-hook"):
            invoked = []

            class CallableHook:
                def helper(self, *args, **kwargs):
                    return None

                def __call__(self, *args, **kwargs):
                    return self.helper(*args, **kwargs)

            model = _Task4Model([])
            hook = CallableHook()
            model.register_forward_hook(hook)
            before = diagnose._model_execution_fingerprint(model)
            CallableHook.helper = lambda *args, **kwargs: invoked.append("hook-helper")
            self.assertNotEqual(diagnose._model_execution_fingerprint(model), before)
            self.assertEqual(invoked, [])

    def test_audio_compose_nested_module_state_and_hooks_reject_before_execution(self):
        # Break caught: AudioCompose list children being sealed only as shallow
        # objects rather than as a complete nn.Module execution tree.
        for mutation in ("training", "buffer", "hook"):
            invoked = []

            class Child(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.register_buffer("scale", torch.tensor(1.0))

                def forward(self, value):
                    invoked.append("forward")
                    return value * self.scale

            class AudioCompose(torch.nn.Module):
                def __init__(self, transforms):
                    super().__init__()
                    self.transforms = list(transforms)

                def forward(self, value):
                    for transform in self.transforms:
                        value = transform(value)
                    return value

            child = Child().eval()
            model = _Task4Model([])
            model.audio_transforms = AudioCompose((child,))
            model.eval()
            evaluator = _Task4Evaluator(model_to_load=model)
            with (
                self.subTest(mutation=mutation),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                if mutation == "training":
                    child.train()
                elif mutation == "buffer":
                    child.scale.add_(1.0)
                else:
                    child.register_forward_hook(lambda *args: invoked.append("hook"))
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._live_inference_attestation(
                            model, f"round5_{mutation}"
                        )
                self.assertEqual(invoked, [])

    def test_trace_path_preserves_frozen_order_schema_list_or_tuple_and_defers_digests(
        self,
    ):
        # Break caught: a reordered operator, a missing output, or trace synchronization inserted before prediction.
        class TraceProxy:
            def __getattr__(proxy_self, name):
                return getattr(trace, name)

            def tensor_record(proxy_self, value, *, boundary):
                if not boundary.startswith("model_"):
                    self.assertIn(
                        "model",
                        self.calls,
                        f"digest before official model output at {boundary}",
                    )
                return trace.tensor_record(value, boundary=boundary)

        for container in ("tuple", "list"):
            with self.subTest(container=container):
                self.calls.clear()
                model = _Task4Model(self.calls, coch_container=container)
                with mock.patch.object(
                    diagnose, "_get_trace", return_value=TraceProxy()
                ):
                    with _task4_attested_context(self.evaluator, model):
                        got = diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.full((2, 2, 4), 2.0),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(11, 22),
                        )
                self.assertEqual(
                    self.calls[:5],
                    [
                        "scene_preprocess",
                        "cue_preprocess",
                        "scene_coch",
                        "cue_coch",
                        "model",
                    ],
                )
                self.assertEqual(
                    set(got.outputs),
                    {"pred_label", "nll", "p_target", "p_probe_distractor"},
                )
                self.assertEqual(got.native_logits.shape, (2, 800))
                self.assertEqual(got.trial_ids, (11, 22))
                for boundary, record in got.outputs.evidence.items():
                    self.assertEqual(
                        record["guard"]["post_content"],
                        record["aggregate"],
                        f"guard/content record is unbound at {boundary}",
                    )

    def test_capture_gate_observes_all_official_operators_before_any_capture_or_digest(
        self,
    ):
        # Break caught: copying immediately after model() but before official outputs exist.
        events = []
        originals = {
            "log_softmax": torch.Tensor.log_softmax,
            "exp": torch.Tensor.exp,
            "argmax": torch.Tensor.argmax,
            "gather": torch.Tensor.gather,
            "squeeze": torch.Tensor.squeeze,
            "neg": torch.Tensor.__neg__,
            "cpu": torch.Tensor.cpu,
            "numpy": torch.Tensor.numpy,
        }

        def observed(name):
            def call(value, *args, **kwargs):
                events.append(name)
                return originals[name](value, *args, **kwargs)

            return call

        original_capture = diagnose._capture_tensor
        original_validate = diagnose._validate_official_outputs

        def validate(*args, **kwargs):
            result = original_validate(*args, **kwargs)
            events.append("official_schema_finite_valid")
            return result

        def capture(value):
            self.assertIn("log_softmax", events)
            self.assertIn("exp", events)
            self.assertIn("argmax", events)
            self.assertGreaterEqual(events.count("gather"), 3)
            for required in (
                "squeeze",
                "neg",
                "cpu",
                "numpy",
                "official_schema_finite_valid",
            ):
                self.assertIn(required, events)
            return original_capture(value)

        class TraceProxy:
            def __getattr__(proxy_self, name):
                return getattr(trace, name)

            def tensor_record(proxy_self, value, *, boundary):
                # Issuance snapshots happen before a batch; activation captures
                # still require all official outputs for that batch.
                if not boundary.startswith("model_"):
                    self.assertIn("argmax", events)
                    self.assertGreaterEqual(events.count("gather"), 3)
                return trace.tensor_record(value, boundary=boundary)

        with (
            mock.patch.object(torch.Tensor, "log_softmax", observed("log_softmax")),
            mock.patch.object(torch.Tensor, "exp", observed("exp")),
            mock.patch.object(torch.Tensor, "argmax", observed("argmax")),
            mock.patch.object(torch.Tensor, "gather", observed("gather")),
            mock.patch.object(torch.Tensor, "squeeze", observed("squeeze")),
            mock.patch.object(torch.Tensor, "__neg__", observed("neg")),
            mock.patch.object(torch.Tensor, "cpu", observed("cpu")),
            mock.patch.object(torch.Tensor, "numpy", observed("numpy")),
            mock.patch.object(
                diagnose, "_validate_official_outputs", side_effect=validate
            ),
            mock.patch.object(diagnose, "_capture_tensor", side_effect=capture),
            mock.patch.object(diagnose, "_get_trace", return_value=TraceProxy()),
            _task4_attested_context(self.evaluator, self.model),
        ):
            got = diagnose.trace_predict_batch(
                self.model,
                torch.ones((2, 2, 4)),
                torch.ones((2, 2, 4)),
                torch.tensor([1, 2]),
                torch.tensor([3, 4]),
                self.device,
                autocast_enabled=True,
                trial_ids=(1, 2),
            )
        self.assertTrue(got.outputs.official_outputs_complete)

    def test_inference_disabled_tensors_require_exact_worker_attestation(self):
        # Break caught: treating version=None as dynamic mutation detection.
        model = _InferenceAllocatedMutationModel()
        evaluator = _Task4Evaluator(model_to_load=model)
        with diagnose._prediction_evaluator_context(evaluator):
            with self.assertRaisesRegex(diagnose.DiagnosticError, "attestation"):
                diagnose.trace_predict_batch(
                    model,
                    torch.ones((2, 2, 4)),
                    torch.ones((2, 2, 4)),
                    torch.tensor([1, 2]),
                    torch.tensor([3, 4]),
                    self.device,
                    autocast_enabled=True,
                    trial_ids=(1, 2),
                )
        with _task4_hermetic_worker_context(evaluator) as worker_context:
            prepared = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
            self.assertIn("_formal40_worker_attestation", prepared)
            forged = dataclasses.replace(prepared["_formal40_worker_attestation"])
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=forged,
            ):
                with self.assertRaisesRegex(diagnose.DiagnosticError, "attestation"):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            other_model = _Task4Model()
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=other_model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaisesRegex(diagnose.DiagnosticError, "attestation"):
                    diagnose.trace_predict_batch(
                        other_model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )

    def test_worker_attestation_is_revoked_when_frozen_scene_scope_exits(self):
        # Break caught: reusing an issued attestation after its source/import scope ended.
        calls = []
        model = _Task4Model(calls)
        evaluator = _Task4Evaluator(calls, model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as worker_context:
            prepared = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
        calls.clear()
        with diagnose._prediction_evaluator_context(
            evaluator,
            model=model,
            attestation=attestation,
        ):
            with self.assertRaisesRegex(diagnose.DiagnosticError, "attestation|scope"):
                diagnose.trace_predict_batch(
                    model,
                    torch.ones((2, 2, 4)),
                    torch.ones((2, 2, 4)),
                    torch.tensor([1, 2]),
                    torch.tensor([3, 4]),
                    self.device,
                    autocast_enabled=True,
                    trial_ids=(1, 2),
                )
        self.assertNotIn("model", calls)

    def test_nonfinite_hidden_boundaries_fail_even_when_official_outputs_are_finite(
        self,
    ):
        # Break caught: a sanitizing downstream operator masking invalid upstream evidence.
        cases = (
            (_Task4Evaluator(sanitize_raw=True), _SanitizingModel(), "raw"),
            (
                _Task4Evaluator(inject_normalized_nan=True),
                _SanitizingModel(),
                "normalized",
            ),
            (_Task4Evaluator(), _SanitizingModel(inject_feature_nan=True), "feature"),
        )
        for evaluator, model, boundary in cases:
            with self.subTest(boundary=boundary):
                raw = torch.ones((2, 2, 4))
                if boundary == "raw":
                    raw.reshape(-1)[0] = float("nan")
                with _task4_attested_context(evaluator, model):
                    with self.assertRaisesRegex(diagnose.DiagnosticError, "non-finite"):
                        diagnose.trace_predict_batch(
                            model,
                            raw,
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=False,
                            trial_ids=(1, 2),
                        )
        finite = torch.ones((2, 2), dtype=torch.float32)
        invalid = finite.clone()
        invalid[0, 0] = float("nan")
        for boundary in (
            "raw_scene",
            "normalized_scene",
            "scene_features",
            "log_probabilities",
            "target_logit",
        ):
            values = {
                "raw_scene": finite,
                "normalized_scene": finite,
                "scene_features": finite,
                "log_probabilities": finite,
            }
            derived = {"target_logit": finite[:, 0]}
            if boundary in values:
                values[boundary] = invalid
            else:
                derived[boundary] = invalid[:, 0]
            with self.subTest(helper_boundary=boundary):
                with self.assertRaisesRegex(diagnose.DiagnosticError, "non-finite"):
                    diagnose._require_finite_trace_values(values, derived)

    def test_trace_rejects_undeclared_coch_output_batch_axis_and_bad_logits(self):
        # Break caught: guessing a feature batch axis or accepting non-[B,800] model output.
        cases = (
            _Task4Model(coch_container="tensor"),
            _Task4Model(coch_container="invalid"),
            _Task4Model(bad_logits_shape=True),
        )
        for model in cases:
            with self.subTest(model=model):
                with _task4_attested_context(_Task4Evaluator(), model):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=False,
                            trial_ids=(1, 2),
                        )

        class WrongBatchCoch:
            def full_rep(self, value, background):
                return [torch.ones((1, 2, 4)), None]

        model = _Task4Model()
        model.coch_gram = WrongBatchCoch()
        with _task4_attested_context(_Task4Evaluator(), model):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.trace_predict_batch(
                    model,
                    torch.ones((2, 2, 4)),
                    torch.ones((2, 2, 4)),
                    torch.tensor([1, 2]),
                    torch.tensor([3, 4]),
                    self.device,
                    autocast_enabled=False,
                    trial_ids=(1, 2),
                )

    def test_raw_normalized_or_feature_in_place_mutation_invalidates_trace(self):
        # Break caught: deterministic in-place mutation being mistaken for stable numerical evidence.
        cases = (
            (_Task4Evaluator(mutate_raw="scene"), _Task4Model(), "raw_scene"),
            (_Task4Evaluator(mutate_raw="cue"), _Task4Model(), "raw_cue"),
            (
                _Task4Evaluator(),
                _Task4Model(mutate_normalized="scene"),
                "normalized_scene",
            ),
            (_Task4Evaluator(), _Task4Model(mutate_normalized="cue"), "normalized_cue"),
            (_Task4Evaluator(), _Task4Model(mutate_feature="scene"), "scene_features"),
            (_Task4Evaluator(), _Task4Model(mutate_feature="cue"), "cue_features"),
        )
        for evaluator, model, boundary in cases:
            with self.subTest(boundary=boundary):
                with _task4_attested_context(evaluator, model):
                    with self.assertRaisesRegex(diagnose.DiagnosticError, "mutation"):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=False,
                            trial_ids=(1, 2),
                        )

    def test_scene_builder_shares_cache_snr_list_and_rejects_hash_before_prediction(
        self,
    ):
        # Break caught: regenerating a different scene or splitting raw/cue cache identity.
        scene_api = _Task4SceneAPI()
        cache = _Task4Cache(max_items=512)
        snr_errors = []
        raw, cue = diagnose._build_raw_batch(
            scene_api,
            self.bank.iloc[:2],
            clips_dir=pathlib.Path("/clips"),
            historical_scene_hashes=self.hashes,
            cache=cache,
            snr_errors=snr_errors,
        )
        self.assertEqual(raw.shape, cue.shape)
        self.assertEqual(scene_api.raw_calls[0][1], scene_api.cue_calls[0][1])
        self.assertEqual(scene_api.raw_calls[0][2], id(snr_errors))
        self.assertEqual(len(snr_errors), 2)
        with self.assertRaisesRegex(diagnose.DiagnosticError, "historical scene hash"):
            diagnose.build_raw_batch(
                _Task4SceneAPI(corrupt_trial=100),
                self.bank.iloc[:2],
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=self.hashes,
                cache=_Task4Cache(max_items=512),
            )

    def test_reference_pass_calls_frozen_predict_directly_with_one_pass_cache(self):
        # Break caught: reference execution accidentally traversing the new trace path.
        scene_api = _Task4SceneAPI()
        context = {
            "evaluator": self.evaluator,
            "model": self.model,
            "scene_api": scene_api,
            "bank": self.bank,
            "clips_dir": pathlib.Path("/clips"),
            "historical_scene_hashes": self.hashes,
            "device": self.device,
        }
        with mock.patch.object(
            diagnose, "trace_predict_batch", side_effect=AssertionError("trace called")
        ):
            got = diagnose.run_reference_pass(context, self.trials, "pass1", 2)
        self.assertEqual(got.trial_ids, tuple(range(100, 104)))
        self.assertEqual(len(self.evaluator.predict_calls), 2)
        self.assertEqual(len(_Task4Cache.instances), 1)
        self.assertEqual(_Task4Cache.instances[0].max_items, 512)
        self.assertEqual(
            {entry[1] for entry in scene_api.raw_calls + scene_api.cue_calls},
            {id(_Task4Cache.instances[0])},
        )

    def test_reference_guard_baseline_precedes_predict_mutation(self):
        scene_api = _Task4SceneAPI()
        self.evaluator.predict_mutate_raw = True
        context = {
            "evaluator": self.evaluator,
            "model": self.model,
            "scene_api": scene_api,
            "bank": self.bank,
            "clips_dir": pathlib.Path("/clips"),
            "historical_scene_hashes": self.hashes,
            "device": self.device,
        }
        with self.assertRaisesRegex(diagnose.DiagnosticError, "mutation"):
            diagnose.run_reference_pass(context, self.trials, "pass1", 2)

    def test_trace_pass_uses_one_cache_and_preserves_complete_task5_payload_inventory(
        self,
    ):
        # Break caught: rerunning inference in Task 5 because logits or child provenance were discarded.
        scene_api = _Task4SceneAPI()
        load_report = {"strict": "unchanged"}
        runtime = {"deterministic_algorithms": True}
        context = {
            "evaluator": self.evaluator,
            "model": self.model,
            "scene_api": scene_api,
            "bank": self.bank,
            "clips_dir": pathlib.Path("/clips"),
            "historical_scene_hashes": self.hashes,
            "device": self.device,
            "load_report": load_report,
            "runtime": runtime,
        }
        self.evaluator.model_to_load = self.model
        with _task4_hermetic_worker_context(
            self.evaluator, scene_api
        ) as worker_context:
            prepared = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
            context.update(
                {
                    "_formal40_worker_attestation": prepared[
                        "_formal40_worker_attestation"
                    ],
                    "worker_pid": prepared["worker_pid"],
                    "worker_nonce": prepared["worker_nonce"],
                    "model_nonce": prepared["model_nonce"],
                }
            )
            with mock.patch.object(
                diagnose, "trace_predict_batch", wraps=diagnose.trace_predict_batch
            ) as traced:
                got = diagnose.run_trace_pass(
                    context, self.trials, "pass1", 2, True, pathlib.Path("/scratch")
                )
        self.assertEqual(traced.call_count, 2)
        self.assertEqual(
            set(got.outputs), {"pred_label", "nll", "p_target", "p_probe_distractor"}
        )
        self.assertEqual(
            got.boundary_records["native_logits"]["tensor"].shape, (4, 800)
        )
        metadata = got.boundary_records["metadata"]
        self.assertEqual(metadata["bank_row_indices"], [20, 21, 22, 23])
        self.assertIs(metadata["load_report"], load_report)
        self.assertIs(metadata["runtime"], runtime)
        self.assertEqual(
            metadata["imported_source_records"], scene_api.imported_source_records
        )
        self.assertEqual(len(metadata["snr_errors"]), 4)
        self.assertEqual(len(_Task4Cache.instances), 1)

    def test_worker_preparation_configures_runtime_and_loads_only_formal40_once(self):
        # Break caught: loading extra models, repeated loading, or silently incomplete state mapping.
        evaluator = _Task4Evaluator(self.calls)
        with _task4_hermetic_worker_context(evaluator) as worker_context:
            got = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
        self.assertEqual(len(evaluator.load_calls), 1)
        self.assertEqual(evaluator.load_calls[0][1], "formal40")
        self.assertEqual(got["load_report"]["prefix_rule"], "exact")
        self.assertTrue(got["runtime"]["deterministic_algorithms"])
        self.assertTrue(got["runtime"]["cudnn_deterministic"])
        self.assertFalse(got["runtime"]["cudnn_benchmark"])
        self.assertEqual(got["runtime"]["float32_matmul_precision"], "medium")
        self.assertTrue(got["runtime"]["cuda_matmul_allow_tf32"])
        self.assertTrue(got["runtime"]["cudnn_allow_tf32"])

    def test_public_worker_issuer_rejects_structural_toy_provenance(self):
        # Break caught: compiled-in hash strings being stamped onto arbitrary objects.
        evaluator = _Task4Evaluator(model_to_load=_Task4Model())
        bad_contexts = (
            {"evaluator": evaluator, "manifest": {"frozen": True}},
            {"evaluator": evaluator, "manifest": {}},
            {
                "evaluator": evaluator,
                "manifest": {"frozen": True},
                "_frozen_context_capability": object(),
            },
        )
        for context in bad_contexts:
            with self.subTest(keys=tuple(context)):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "provenance|capability"
                ):
                    diagnose.prepare_formal40_worker(context, allow_cpu=True)

    def test_hermetic_capability_requires_real_verified_nonempty_records(self):
        # Break caught: empty/forged manifest, evaluator, pinned, or source records.
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            evaluator_path = root / "evaluator.py"
            manifest_path = root / "input_freeze.json"
            pinned_path = root / "pinned.bin"
            source_path = root / "source.py"
            evaluator_path.write_bytes(b"verified evaluator bytes\n")
            manifest_path.write_bytes(b'{"verified":true}\n')
            pinned_path.write_bytes(b"pinned\n")
            source_path.write_bytes(b"source\n")
            records = {
                "evaluator_record": trace.stable_file_record(
                    evaluator_path, allowed_root=root
                ),
                "manifest_record": trace.stable_file_record(
                    manifest_path, allowed_root=root
                ),
                "pinned_records": [
                    trace.stable_file_record(pinned_path, allowed_root=root)
                ],
                "source_records": [
                    trace.stable_file_record(source_path, allowed_root=root)
                ],
            }
            for key in records:
                broken = dict(records)
                broken[key] = [] if key.endswith("records") else {}
                with self.subTest(missing=key):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._issue_hermetic_frozen_capability(
                            evaluator=_Task4Evaluator(),
                            manifest={"verified": True},
                            root=root,
                            **broken,
                        )

    def test_worker_rejects_structurally_incomplete_strict_load_evidence(self):
        # Break caught: accepting a nominal 1.0 ratio without a valid full mapping report.
        for update in (
            {"key_count": 0},
            {"native_preprocessing": "wrong"},
            {"model_module": {}},
        ):
            with self.subTest(update=update):
                evaluator = _Task4Evaluator()
                original = evaluator.strict_load_model

                def bad_load(*args, **kwargs):
                    model, report = original(*args, **kwargs)
                    report.update(update)
                    return model, report

                evaluator.strict_load_model = bad_load
                with _task4_hermetic_worker_context(evaluator) as worker_context:
                    with self.assertRaisesRegex(
                        diagnose.DiagnosticError, "strict load report"
                    ):
                        diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)

    def test_capability_rejects_in_place_manifest_or_evaluator_mutation(self):
        # Break caught: mutable identity surviving a post-verification content change.
        for target in ("manifest", "evaluator"):
            evaluator = _Task4Evaluator(model_to_load=_Task4Model())
            with (
                self.subTest(target=target),
                _task4_hermetic_worker_context(evaluator) as worker_context,
            ):
                capability = worker_context["_frozen_context_capability"]
                self.assertIsInstance(capability.manifest_snapshot, bytes)
                with self.assertRaises(TypeError):
                    capability.manifest_snapshot[0] = 0
                if target == "manifest":
                    worker_context["manifest"]["models"] = {
                        "formal40": {"path": "/tampered/checkpoint.ckpt"}
                    }
                else:
                    original = evaluator.strict_load_model
                    evaluator.strict_load_model = lambda *args, **kwargs: original(
                        *args, **kwargs
                    )
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "capability|manifest|evaluator|changed"
                ):
                    diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)

    def test_verified_facade_rejects_rebound_reachable_module_globals(self):
        # Real verified-loader facade: function identity alone does not bind globals.
        source = """
import contextlib
def _frozen_import_context(*args, **kwargs): return contextlib.nullcontext()
def _load_torch_checkpoint(*args, **kwargs): return "checkpoint"
def strict_load_model(*args, **kwargs):
    _frozen_import_context()
    return _load_torch_checkpoint()
def singleton_native_preprocess(*args, **kwargs): return args[-1]
def predict_batch(*args, **kwargs): return singleton_native_preprocess(*args, **kwargs)
def _select_smoke_bank(*args, **kwargs): return None
def _configure_runtime(*args, **kwargs): return None
def _tensor_hashes(*args, **kwargs): return None
""".lstrip().encode()
        for function_name, global_name in (
            ("strict_load_model", "_frozen_import_context"),
            ("strict_load_model", "_load_torch_checkpoint"),
            ("predict_batch", "singleton_native_preprocess"),
        ):
            with (
                self.subTest(function=function_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = pathlib.Path(temporary).resolve()
                path = root / "locked_same_bank_eval.py"
                path.write_bytes(source)
                facade = diagnose.load_verified_v4_evaluator(
                    trace, path, len(source), hashlib.sha256(source).hexdigest()
                )
                manifest_path = root / "manifest.json"
                pinned_path = root / "pinned.bin"
                source_path = root / "source.py"
                for item, payload in (
                    (manifest_path, b"{}"),
                    (pinned_path, b"pinned"),
                    (source_path, b"source"),
                ):
                    item.write_bytes(payload)
                records = {
                    "evaluator": trace.stable_file_record(path, allowed_root=root),
                    "manifest": trace.stable_file_record(
                        manifest_path, allowed_root=root
                    ),
                    "pinned": trace.stable_file_record(pinned_path, allowed_root=root),
                    "source": trace.stable_file_record(source_path, allowed_root=root),
                }
                manifest = {}
                capability = diagnose._issue_hermetic_frozen_capability(
                    evaluator=facade,
                    manifest=manifest,
                    root=root,
                    evaluator_record=records["evaluator"],
                    manifest_record=records["manifest"],
                    pinned_records=[records["pinned"]],
                    source_records=[records["source"]],
                )
                diagnose._validate_frozen_capability_contents(capability)
                function = getattr(facade, function_name)
                function.__globals__[global_name] = lambda *args, **kwargs: "malicious"
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "capability|global|evaluator|changed"
                ):
                    diagnose._validate_frozen_capability_contents(capability)

    def test_throwing_capability_fingerprint_sticky_revokes_after_restore(self):
        evaluator = _Task4Evaluator(model_to_load=_Task4Model())
        evaluator.extra = []
        with _task4_hermetic_worker_context(evaluator) as context:
            capability = context["_frozen_context_capability"]
            evaluator.extra.append(collections.deque())
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "execution collection|capability|changed"
            ):
                diagnose._validate_frozen_capability_contents(capability)
            evaluator.extra.clear()
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "capability|revoked|changed"
            ):
                diagnose._validate_frozen_capability_contents(capability)

    def test_capability_cannot_rewrite_its_own_manifest_baseline(self):
        evaluator = _Task4Evaluator(model_to_load=_Task4Model())
        with _task4_hermetic_worker_context(evaluator) as context:
            capability = context["_frozen_context_capability"]
            capability.manifest["tampered"] = True
            replacement = trace.canonical_json_bytes(capability.manifest)
            object.__setattr__(capability, "manifest_snapshot", replacement)
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "capability|manifest|changed"
            ):
                diagnose._validate_frozen_capability_contents(capability)

    def test_actual_verified_v4_facade_rejects_rebound_reachable_helper(self):
        # Integration RED: seal the reviewed local v4 evaluator, not a toy facade.
        evaluator_path = (
            PACKAGE_ROOT.parent
            / "same_bank_eval_2026_08_29_v4"
            / "locked_same_bank_eval.py"
        ).resolve(strict=True)
        workspace = PACKAGE_ROOT.parent.resolve(strict=True)
        facade = diagnose.load_verified_v4_evaluator(
            trace,
            evaluator_path,
            154273,
            "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
        )
        with tempfile.TemporaryDirectory(dir=workspace) as temporary:
            root = pathlib.Path(temporary).resolve()
            manifest_path = root / "manifest.json"
            pinned_path = root / "pinned.bin"
            source_path = root / "source.py"
            for item, payload in (
                (manifest_path, b"{}"),
                (pinned_path, b"pinned"),
                (source_path, b"source"),
            ):
                item.write_bytes(payload)
            capability = diagnose._issue_hermetic_frozen_capability(
                evaluator=facade,
                manifest={},
                root=workspace,
                evaluator_record=trace.stable_file_record(
                    evaluator_path, allowed_root=workspace
                ),
                manifest_record=trace.stable_file_record(
                    manifest_path, allowed_root=workspace
                ),
                pinned_records=[
                    trace.stable_file_record(pinned_path, allowed_root=workspace)
                ],
                source_records=[
                    trace.stable_file_record(source_path, allowed_root=workspace)
                ],
            )
            function = facade.strict_load_model
            original = function.__globals__["_load_torch_checkpoint"]
            try:
                function.__globals__["_load_torch_checkpoint"] = (
                    lambda *args, **kwargs: "malicious"
                )
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "capability|global|evaluator|changed"
                ):
                    diagnose._validate_frozen_capability_contents(capability)
            finally:
                function.__globals__["_load_torch_checkpoint"] = original

    def test_callable_graph_seals_class_surface_and_contextmanager_wrapped_function(
        self,
    ):
        events = []

        class Cache:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, key):
                return key

        @contextlib.contextmanager
        def opened():
            yield "ok"

        anchors = diagnose._callable_graphs({"cache": Cache, "opened": opened})
        original_init = Cache.__init__
        Cache.__init__ = lambda self, *args, **kwargs: events.append("init")
        self.assertNotEqual(
            diagnose._callable_graph_fingerprint(Cache), anchors["cache"]
        )
        Cache.__init__ = original_init
        cell = next(cell for cell in opened.__closure__ if callable(cell.cell_contents))
        original_generator = cell.cell_contents

        def malicious_generator():
            events.append("wrapped")
            yield "bad"

        cell.cell_contents = malicious_generator
        try:
            self.assertNotEqual(
                diagnose._callable_graph_fingerprint(opened), anchors["opened"]
            )
        finally:
            cell.cell_contents = original_generator
        self.assertEqual(events, [])

    def test_actual_v4_contextmanager_and_dynamic_import_dependencies_are_sealed(self):
        evaluator_path = (
            PACKAGE_ROOT.parent
            / "same_bank_eval_2026_08_29_v4"
            / "locked_same_bank_eval.py"
        ).resolve(strict=True)
        facade = diagnose.load_verified_v4_evaluator(
            trace,
            evaluator_path,
            154273,
            "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4",
        )
        anchor = diagnose._callable_graph_fingerprint(facade.strict_load_model)
        wrapped = facade.strict_load_model.__globals__["open_pinned_file"]
        cell = next(
            cell for cell in wrapped.__closure__ if callable(cell.cell_contents)
        )
        original = cell.cell_contents

        def malicious(*args, **kwargs):
            yield None

        cell.cell_contents = malicious
        try:
            self.assertNotEqual(
                diagnose._callable_graph_fingerprint(facade.strict_load_model),
                anchor,
            )
        finally:
            cell.cell_contents = original

        module_name = "_task4_dynamic_import_dependency"
        dependency = types.ModuleType(module_name)
        dependency.crop_centered = lambda value: value
        sys.modules[module_name] = dependency
        namespace = {}
        exec(
            "def role(value):\n from %s import crop_centered\n return crop_centered(value)\n"
            % module_name,
            namespace,
        )
        role = namespace["role"]
        dynamic_anchor = diagnose._callable_graph_fingerprint(role)
        original_crop = dependency.crop_centered
        dependency.crop_centered = lambda value: value + 1
        try:
            self.assertNotEqual(
                diagnose._callable_graph_fingerprint(role), dynamic_anchor
            )
        finally:
            dependency.crop_centered = original_crop
            sys.modules.pop(module_name, None)

    def test_model_inner_forward_and_hook_registry_are_sealed_before_operator(self):
        for mutation in ("inner_forward", "forward_hook"):
            calls = []
            model = _Task4Model(calls)
            model.inner = torch.nn.Identity()
            original_forward = model.forward
            model.forward = lambda cue, scene, background: original_forward(
                model.inner(cue), scene, background
            )
            model.eval()
            evaluator = _Task4Evaluator(calls, model_to_load=model)
            with (
                self.subTest(mutation=mutation),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                malicious = []
                if mutation == "inner_forward":
                    model.inner.forward = lambda value: (
                        malicious.append("inner") or value
                    )
                else:
                    model.register_forward_hook(lambda *args: malicious.append("hook"))
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaisesRegex(
                        diagnose.DiagnosticError, "model|attestation|callable"
                    ):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertEqual(malicious, [])

    def test_model_training_flags_and_plain_audio_transform_list_are_sealed(self):
        class AudioCompose:
            def __init__(self):
                self.transforms = [lambda value: value]

            def __call__(self, value):
                for transform in self.transforms:
                    value = transform(value)
                return value

        for mutation in ("root_training", "inner_training", "audio_list"):
            model = _Task4Model([])
            model.inner = torch.nn.Identity()
            model.audio_transforms = AudioCompose()
            model.eval()
            evaluator = _Task4Evaluator(model_to_load=model)
            with (
                self.subTest(mutation=mutation),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                malicious = []
                if mutation == "root_training":
                    model.train()
                elif mutation == "inner_training":
                    model.inner.train()
                else:
                    model.audio_transforms.transforms[0] = lambda value: (
                        malicious.append("audio") or value
                    )
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertEqual(malicious, [])

    def test_callable_wrapper_descriptor_graph_is_bounded(self):
        """A builtin callable self-cycle must terminate without exhausting RAM."""
        script = (
            "import types, diagnose_batch_invariance as d; "
            "bound=types.MethodType(lambda self: None, object()); "
            "value=d._callable_graph_fingerprint(type(bound).__call__); "
            "assert 0 < len(value) <= 8"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=PACKAGE_ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(f"callable fingerprint did not terminate: {error}")
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout + completed.stderr)[-2000:],
        )

    def test_imported_target_and_existing_hook_transitive_globals_are_sealed(self):
        helper = {"value": lambda value: value}
        namespace = {"helper": helper}
        exec("def imported(value): return helper['value'](value)", namespace)
        imported = namespace["imported"]
        module_name = "_task4_import_target_graph"
        module = types.ModuleType(module_name)
        module.imported = imported
        sys.modules[module_name] = module
        outer_ns = {}
        exec(
            "def outer(value):\n from %s import imported\n return imported(value)"
            % module_name,
            outer_ns,
        )
        anchor = diagnose._callable_graph_fingerprint(outer_ns["outer"])
        helper["value"] = lambda value: value + 1
        try:
            self.assertNotEqual(
                diagnose._callable_graph_fingerprint(outer_ns["outer"]), anchor
            )
        finally:
            sys.modules.pop(module_name, None)

        model = _Task4Model([])
        hook_ns = {"helper": lambda *args: None}
        exec("def hook(*args): return helper(*args)", hook_ns)
        model.register_forward_hook(hook_ns["hook"])
        fingerprint = diagnose._model_execution_fingerprint(model)
        hook_ns["helper"] = lambda *args: (_ for _ in ()).throw(RuntimeError("bad"))
        self.assertNotEqual(diagnose._model_execution_fingerprint(model), fingerprint)

    def test_module_global_attribute_callable_rebinding_changes_graph(self):
        dependency = types.ModuleType("_task4_module_global_dependency")
        dependency.helper = lambda value: value
        namespace = {"dependency": dependency}
        exec("def outer(value): return dependency.helper(value)", namespace)
        outer = namespace["outer"]
        anchor = diagnose._callable_graph_fingerprint(outer)
        dependency.helper = lambda value: value + 1
        self.assertNotEqual(diagnose._callable_graph_fingerprint(outer), anchor)

    def test_every_named_module_mode_and_execution_configuration_are_sealed(self):
        class ConfiguredModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.enabled = True
                self.options = {"scale": 1.0, "order": ["left", "right"]}

            def forward(self, value):
                return value * self.options["scale"] if self.enabled else value

        mutations = {
            "batchnorm_eps": lambda model: setattr(model.batchnorm, "eps", 0.25),
            "dropout_p": lambda model: setattr(model.dropout, "p", 0.75),
            "custom_primitive": lambda model: setattr(
                model.configured, "enabled", False
            ),
            "custom_container": lambda model: model.configured.options.__setitem__(
                "scale", 2.0
            ),
        }
        for name, mutate in mutations.items():
            model = _Task4Model([])
            model.batchnorm = torch.nn.BatchNorm1d(4)
            model.dropout = torch.nn.Dropout(p=0.25)
            model.configured = ConfiguredModule()
            model.eval()
            for parameter in model.parameters():
                parameter.requires_grad_(False)
            evaluator = _Task4Evaluator(model_to_load=model)
            with (
                self.subTest(name=name),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                evaluator.calls.clear()
                mutate(model)
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertEqual(evaluator.calls, [])

        model = _Task4Model([])
        model.late_child = ConfiguredModule()  # Defaults to training=True.
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "eval|training|module"
            ):
                diagnose.prepare_formal40_worker(context, allow_cpu=True)

    def test_named_module_discovery_rebinding_is_rejected_without_invocation(self):
        model = _Task4Model([])
        model.inner = torch.nn.Identity()
        model.eval()
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            original_inventory = tuple(model.named_modules())
            invoked = []

            def malicious_named_modules(*args, **kwargs):
                invoked.append("named_modules")
                return iter(original_inventory)

            model.named_modules = malicious_named_modules
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertEqual(invoked, [])

    def test_trainable_parameter_check_bypasses_rebound_parameters_method(self):
        model = _Task4Model([])
        model.inner = torch.nn.Linear(4, 4)
        model.eval()
        invoked = []

        def malicious_parameters(*args, **kwargs):
            invoked.append("parameters")
            return iter(())

        model.parameters = malicious_parameters
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "trainable parameters"
            ):
                diagnose.prepare_formal40_worker(context, allow_cpu=True)
        self.assertEqual(invoked, [])

    def test_model_call_impl_rebinding_is_rejected_without_invocation(self):
        model = _Task4Model([])
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            invoked = []

            def malicious_call_impl(cue_features, scene_features, background):
                invoked.append("_call_impl")
                return torch.zeros(
                    (int(scene_features.shape[0]), 800),
                    dtype=scene_features.dtype,
                    device=scene_features.device,
                )

            model._call_impl = malicious_call_impl
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertEqual(invoked, [])

    def test_attestation_cannot_rewrite_its_own_model_fingerprint(self):
        model = _Task4Model([])
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            original = attestation.model_execution_fingerprint
            model.bad_logits_shape = True
            replacement = diagnose._model_execution_fingerprint(
                model, attestation.model_module_inventory
            )
            object.__setattr__(attestation, "model_execution_fingerprint", replacement)
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=attestation,
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|revoked|changed"
                ):
                    diagnose._live_inference_attestation(model, "mutated")
                model.bad_logits_shape = False
                object.__setattr__(attestation, "model_execution_fingerprint", original)
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|revoked|changed"
                ):
                    diagnose._live_inference_attestation(model, "restored")

    def test_audio_compose_order_child_graph_and_child_configuration_are_sealed(self):
        for mutation in ("order", "child_graph", "child_config"):
            invoked = []
            helper = {"apply": lambda value: value}

            class Transform:
                def __init__(self, scale):
                    self.scale = scale
                    self.flags = {"enabled": True, "axes": [0, 1]}

                def __call__(self, value):
                    if self.flags["enabled"]:
                        value = helper["apply"](value)
                    return value * self.scale

            class AudioCompose:
                def __init__(self, transforms):
                    self.transforms = list(transforms)

                def __call__(self, value):
                    for transform in self.transforms:
                        value = transform(value)
                    return value

            model = _Task4Model([])
            model.audio_transforms = AudioCompose((Transform(1.0), Transform(1.0)))
            evaluator = _Task4Evaluator(model_to_load=model)
            with (
                self.subTest(mutation=mutation),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                if mutation == "order":
                    model.audio_transforms.transforms.reverse()
                elif mutation == "child_graph":
                    helper["apply"] = lambda value: (invoked.append("child") or value)
                else:
                    model.audio_transforms.transforms[0].flags["enabled"] = False
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertEqual(invoked, [])

    def test_audio_child_class_helper_rebinding_is_rejected_before_invocation(self):
        invoked = []

        class Transform(torch.nn.Module):
            @staticmethod
            def helper(value):
                return value

            def forward(self, value):
                return self.helper(value)

        class AudioCompose:
            def __init__(self, transforms):
                self.transforms = list(transforms)

            def __call__(self, value):
                for transform in self.transforms:
                    value = transform(value)
                return value

        model = _Task4Model([])
        model.audio_transforms = AudioCompose((Transform().eval(),))
        evaluator = _Task4Evaluator(model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)

            def malicious_helper(value):
                invoked.append("class-helper")
                return value + 1

            Transform.helper = staticmethod(malicious_helper)
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
        self.assertEqual(invoked, [])

    def test_hook_closure_containers_and_dispatch_flags_are_sealed(self):
        for mutation in ("closure", "with_kwargs", "always_called"):
            invoked = []
            helper = {"callback": lambda *args: None}

            def hook(*args, **kwargs):
                return helper["callback"](*args, **kwargs)

            model = _Task4Model([])
            handle = model.register_forward_hook(
                hook,
                with_kwargs=True,
                always_call=True,
            )
            evaluator = _Task4Evaluator(model_to_load=model)
            with (
                self.subTest(mutation=mutation),
                _task4_hermetic_worker_context(evaluator) as context,
            ):
                prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
                if mutation == "closure":
                    helper["callback"] = lambda *args: invoked.append("hook")
                elif mutation == "with_kwargs":
                    model._forward_hooks_with_kwargs[handle.id] = False
                else:
                    model._forward_hooks_always_called.pop(handle.id)
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertEqual(invoked, [])

    def test_scene_api_callable_rebinding_is_rejected_before_reference_or_a2_raw_use(
        self,
    ):
        for path_name, field in itertools.product(
            ("reference", "a2"),
            ("waveform_cache_class", "raw_scene_batch", "correct_cue_batch"),
        ):
            calls = []
            evaluator = _Task4Evaluator(calls, model_to_load=self.model)
            backing = _Task4SceneAPI()
            api = diagnose.FrozenSceneAPI(
                _Task4Cache, backing.raw_scene_batch, backing.correct_cue_batch, ()
            )
            with (
                self.subTest(path=path_name, field=field),
                _task4_hermetic_worker_context(evaluator, api) as worker_context,
            ):
                prepared = diagnose.prepare_formal40_worker(
                    worker_context, allow_cpu=True
                )
                malicious_calls = []
                original = getattr(api, field)
                if field == "waveform_cache_class":

                    class MaliciousCache:
                        def __init__(self, *args, **kwargs):
                            malicious_calls.append("cache")
                            self.calls = []

                    replacement = MaliciousCache
                else:

                    def replacement(*args, **kwargs):
                        malicious_calls.append(field)
                        return original(*args, **kwargs)

                object.__setattr__(api, field, replacement)
                context = {
                    **prepared,
                    "evaluator": evaluator,
                    "scene_api": api,
                    "bank": self.bank,
                    "clips_dir": pathlib.Path("/clips"),
                    "historical_scene_hashes": self.hashes,
                    "_formal40_worker_attestation": prepared[
                        "_formal40_worker_attestation"
                    ],
                    "_frozen_context_capability": worker_context[
                        "_frozen_context_capability"
                    ],
                }
                runner = (
                    diagnose.run_reference_pass
                    if path_name == "reference"
                    else lambda value,
                    trials,
                    pass_id,
                    batch_size: diagnose.run_trace_pass(
                        value,
                        trials,
                        pass_id,
                        batch_size,
                        autocast_enabled=True,
                        scratch_root=value["_frozen_context_capability"].root,
                    )
                )
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|scene|callable|changed"
                ):
                    runner(context, self.trials, "pass1", 2)
                self.assertEqual(malicious_calls, [])

    def test_scene_wrapper_closure_rebinding_is_rejected_before_use(self):
        malicious_calls = []

        def make_wrapper(original):
            target = original

            def wrapper(*args, **kwargs):
                return target(*args, **kwargs)

            return wrapper

        backing = _Task4SceneAPI()
        wrapped = make_wrapper(backing.raw_scene_batch)
        api = diagnose.FrozenSceneAPI(
            _Task4Cache, wrapped, backing.correct_cue_batch, ()
        )
        evaluator = _Task4Evaluator(model_to_load=self.model)
        with _task4_hermetic_worker_context(evaluator, api) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)

            def malicious(*args, **kwargs):
                malicious_calls.append("closure")
                return backing.raw_scene_batch(*args, **kwargs)

            wrapped.__closure__[0].cell_contents = malicious
            run = {
                **prepared,
                **context,
                "bank": self.bank,
                "clips_dir": pathlib.Path("/clips"),
                "historical_scene_hashes": self.hashes,
            }
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "scene|callable|changed"
            ):
                diagnose.run_reference_pass(run, self.trials, "pass1", 2)
            self.assertEqual(malicious_calls, [])

    def test_source_record_alias_mutation_sticky_revokes_attestation(self):
        evaluator = _Task4Evaluator(model_to_load=self.model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            record = attestation.scene_api.imported_source_records[0]
            original = record["mode"]
            with self.assertRaises(TypeError):
                record["mode"] = int(original) ^ 0o111
            original_records = attestation.scene_api.imported_source_records
            tampered = dict(record)
            tampered["mode"] = int(original) ^ 0o111
            object.__setattr__(
                attestation.scene_api, "imported_source_records", (tampered,)
            )
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=self.model,
                attestation=attestation,
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._live_inference_attestation(self.model, "mutated")
                object.__setattr__(
                    attestation.scene_api, "imported_source_records", original_records
                )
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._live_inference_attestation(self.model, "restored")

    def test_audio_transform_rebinding_fails_before_malicious_transform_runs(self):
        calls = []
        model = _Task4Model(calls)
        evaluator = _Task4Evaluator(calls, model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            malicious = []
            model.audio_transforms = lambda value: (malicious.append("audio") or value)
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "model|callable|attestation"
                ):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertEqual(malicious, [])

    def test_configure_or_strict_load_mutation_is_rechecked_before_signing(self):
        for phase in ("configure", "strict_load"):
            evaluator = _Task4Evaluator(model_to_load=_Task4Model())
            with (
                self.subTest(phase=phase),
                _task4_hermetic_worker_context(evaluator) as context,
            ):

                def mutate():
                    context["manifest"].update(tampered=phase)

                if phase == "configure":
                    evaluator.configure_hook = mutate
                else:
                    evaluator.strict_load_hook = mutate
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "capability|changed"
                ):
                    diagnose.prepare_formal40_worker(context, allow_cpu=True)

    def test_post_issuance_manifest_or_callable_mutation_revokes_before_model(self):
        # Break caught: using a valid attestation after its mutable inputs changed.
        for target in ("manifest", "evaluator"):
            calls = []
            model = _Task4Model(calls)
            evaluator = _Task4Evaluator(calls, model_to_load=model)
            with (
                self.subTest(target=target),
                _task4_hermetic_worker_context(evaluator) as worker_context,
            ):
                prepared = diagnose.prepare_formal40_worker(
                    worker_context, allow_cpu=True
                )
                if target == "manifest":
                    worker_context["manifest"]["checkpoint_path"] = "/tampered.ckpt"
                else:
                    original = evaluator.singleton_native_preprocess
                    evaluator.singleton_native_preprocess = (
                        lambda *args, **kwargs: original(*args, **kwargs)
                    )
                calls.clear()
                with diagnose._prediction_evaluator_context(
                    evaluator,
                    model=model,
                    attestation=prepared["_formal40_worker_attestation"],
                ):
                    with self.assertRaisesRegex(
                        diagnose.DiagnosticError, "capability|attestation|changed"
                    ):
                        diagnose.trace_predict_batch(
                            model,
                            torch.ones((2, 2, 4)),
                            torch.ones((2, 2, 4)),
                            torch.tensor([1, 2]),
                            torch.tensor([3, 4]),
                            self.device,
                            autocast_enabled=True,
                            trial_ids=(1, 2),
                        )
                self.assertNotIn("model", calls)

    def test_production_capability_register_reverifies_pinned_and_source_records(self):
        # Break caught: production registration trusting caller-supplied record mappings.
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            paths = {
                name: root / name
                for name in ("evaluator", "manifest", "pinned", "source", "unrelated")
            }
            for name, path in paths.items():
                path.write_bytes(name.encode())
            records = {
                name: trace.stable_file_record(path, allowed_root=root)
                for name, path in paths.items()
            }
            source_record = {
                **records["source"],
                "type": "file",
                "observed_import": True,
            }
            evaluator = types.SimpleNamespace(
                **{
                    name: (lambda *args, **kwargs: None)
                    for name in diagnose.V4_EVALUATOR_WHITELIST
                }
            )
            manifest = {"verified": True}
            diagnose._VERIFIED_PRODUCTION_EVALUATORS[id(evaluator)] = (
                evaluator,
                records["evaluator"],
                {
                    name: diagnose._callable_anchor(getattr(evaluator, name))
                    for name in diagnose.V4_EVALUATOR_WHITELIST
                },
                diagnose._callable_graphs(
                    {
                        name: getattr(evaluator, name)
                        for name in diagnose.V4_EVALUATOR_WHITELIST
                    }
                ),
            )
            diagnose._VERIFIED_PRODUCTION_MANIFESTS[id(manifest)] = (
                manifest,
                records["manifest"],
            )
            if hasattr(diagnose, "_VERIFIED_PRODUCTION_INVENTORIES"):
                diagnose._VERIFIED_PRODUCTION_INVENTORIES[id(manifest)] = (
                    manifest,
                    (records["pinned"],),
                    (source_record,),
                    root.resolve(),
                )
            try:
                for field, replacement in (
                    ("pinned_records", "bad_sha"),
                    ("source_records", "bad_sha"),
                    ("pinned_records", "unrelated"),
                    ("source_records", "unrelated"),
                ):
                    arguments = {
                        "evaluator": evaluator,
                        "manifest": manifest,
                        "evaluator_record": records["evaluator"],
                        "manifest_record": records["manifest"],
                        "pinned_records": [records["pinned"]],
                        "source_records": [source_record],
                        "root": root,
                        "trust_domain": "production",
                    }
                    changed = dict(
                        records["unrelated"]
                        if replacement == "unrelated"
                        else arguments[field][0]
                    )
                    if replacement == "bad_sha":
                        changed["sha256"] = "0" * 64
                    arguments[field] = [changed]
                    with (
                        self.subTest(field=field, replacement=replacement),
                        self.assertRaises(diagnose.DiagnosticError),
                    ):
                        diagnose._register_frozen_context_capability(**arguments)
                if hasattr(diagnose, "_VERIFIED_PRODUCTION_INVENTORIES"):
                    valid = diagnose._register_frozen_context_capability(
                        evaluator=evaluator,
                        manifest=manifest,
                        evaluator_record=records["evaluator"],
                        manifest_record=records["manifest"],
                        pinned_records=[records["pinned"]],
                        source_records=[source_record],
                        root=root,
                        source_root=root,
                        trust_domain="production",
                    )
                    self.assertEqual(valid.trust_domain, "production")
            finally:
                diagnose._VERIFIED_PRODUCTION_EVALUATORS.pop(id(evaluator), None)
                diagnose._VERIFIED_PRODUCTION_MANIFESTS.pop(id(manifest), None)
                if hasattr(diagnose, "_VERIFIED_PRODUCTION_INVENTORIES"):
                    diagnose._VERIFIED_PRODUCTION_INVENTORIES.pop(id(manifest), None)

    def test_production_register_rejects_facade_changed_since_verified_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            paths = {
                name: root / name
                for name in ("evaluator", "manifest", "pinned", "source")
            }
            for name, path in paths.items():
                path.write_bytes(name.encode())
            records = {
                name: trace.stable_file_record(path, allowed_root=root)
                for name, path in paths.items()
            }
            evaluator = types.SimpleNamespace(
                **{
                    name: (lambda *args, **kwargs: None)
                    for name in diagnose.V4_EVALUATOR_WHITELIST
                }
            )
            manifest = {"verified": True}
            diagnose._VERIFIED_PRODUCTION_EVALUATORS[id(evaluator)] = (
                evaluator,
                records["evaluator"],
                {
                    name: diagnose._callable_anchor(getattr(evaluator, name))
                    for name in diagnose.V4_EVALUATOR_WHITELIST
                },
                diagnose._callable_graphs(
                    {
                        name: getattr(evaluator, name)
                        for name in diagnose.V4_EVALUATOR_WHITELIST
                    }
                ),
            )
            diagnose._VERIFIED_PRODUCTION_MANIFESTS[id(manifest)] = (
                manifest,
                records["manifest"],
            )
            diagnose._VERIFIED_PRODUCTION_INVENTORIES[id(manifest)] = (
                manifest,
                (records["pinned"],),
                (records["source"],),
                root,
            )
            original = evaluator.predict_batch
            evaluator.predict_batch = lambda *args, **kwargs: original(*args, **kwargs)
            try:
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "evaluator|loader|callable"
                ):
                    diagnose._register_frozen_context_capability(
                        evaluator=evaluator,
                        manifest=manifest,
                        evaluator_record=records["evaluator"],
                        manifest_record=records["manifest"],
                        pinned_records=[records["pinned"]],
                        source_records=[records["source"]],
                        root=root,
                        source_root=root,
                        trust_domain="production",
                    )
            finally:
                diagnose._VERIFIED_PRODUCTION_EVALUATORS.pop(id(evaluator), None)
                diagnose._VERIFIED_PRODUCTION_MANIFESTS.pop(id(manifest), None)
                diagnose._VERIFIED_PRODUCTION_INVENTORIES.pop(id(manifest), None)

    def test_strict_load_lazy_source_is_sealed_into_attestation(self):
        # Break caught: freezing imported sources before strict load performs lazy imports.
        calls = []
        model = _Task4Model(calls)
        holder = {}
        evaluator = _Task4Evaluator(
            calls,
            model_to_load=model,
            strict_load_hook=lambda: setattr(
                holder["scene_api"],
                "imported_source_records",
                tuple(
                    sorted(
                        holder["scene_api"].imported_source_records + (holder["lazy"],),
                        key=lambda item: item["relative_path"],
                    )
                ),
            ),
        )
        with _task4_lazy_source_worker_context(
            evaluator,
            before_issue=lambda scene_api, lazy: holder.update(
                scene_api=scene_api, lazy=lazy
            ),
        ) as (context, scene_api, lazy):
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            self.assertEqual(
                attestation.imported_source_records, scene_api.imported_source_records
            )
            calls.clear()
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=attestation,
            ):
                diagnose.trace_predict_batch(
                    model,
                    torch.ones((2, 2, 4)),
                    torch.ones((2, 2, 4)),
                    torch.tensor([1, 2]),
                    torch.tensor([3, 4]),
                    self.device,
                    autocast_enabled=True,
                    trial_ids=(1, 2),
                )
            self.assertIn("model", calls)

    def test_post_load_source_seal_requires_unique_sorted_full_identity(self):
        for case in ("duplicate", "reorder", "identity"):
            holder = {}

            def mutate():
                source, lazy = (
                    holder["scene_api"].imported_source_records[0],
                    holder["lazy"],
                )
                if case == "duplicate":
                    value = (source, source)
                elif case == "reorder":
                    value = tuple(
                        sorted(
                            (source, lazy),
                            key=lambda item: item["relative_path"],
                            reverse=True,
                        )
                    )
                else:
                    changed = dict(source)
                    changed["mode"] = int(changed["mode"]) ^ 0o111
                    value = (changed,)
                holder["scene_api"].imported_source_records = value

            evaluator = _Task4Evaluator(
                model_to_load=_Task4Model(), strict_load_hook=mutate
            )
            with (
                self.subTest(case=case),
                _task4_lazy_source_worker_context(
                    evaluator,
                    before_issue=lambda scene_api, lazy: holder.update(
                        scene_api=scene_api, lazy=lazy
                    ),
                ) as (context, scene_api, lazy),
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "source|provenance"
                ):
                    diagnose.prepare_formal40_worker(context, allow_cpu=True)

    def test_post_issuance_lazy_source_expansion_revokes_before_model(self):
        # Break caught: accepting a source set that expanded after worker issuance.
        calls = []
        model = _Task4Model(calls)
        evaluator = _Task4Evaluator(calls, model_to_load=model)
        with _task4_lazy_source_worker_context(evaluator) as (context, scene_api, lazy):
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            scene_api.imported_source_records += (lazy,)
            calls.clear()
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|source|scope"
                ):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertNotIn("model", calls)

    def test_lazy_source_expansion_during_first_operator_stops_before_next_operator(
        self,
    ):
        # Break caught: checking source liveness only at entry or after all model work.
        calls = []
        holder = {}
        model = _Task4Model(calls)
        evaluator = _Task4Evaluator(
            calls,
            model_to_load=model,
            preprocess_hook=lambda count: setattr(
                holder["scene_api"],
                "imported_source_records",
                holder["scene_api"].imported_source_records + (holder["lazy"],),
            )
            if count == 1
            else None,
        )
        with _task4_lazy_source_worker_context(
            evaluator,
            before_issue=lambda scene_api, lazy: holder.update(
                scene_api=scene_api, lazy=lazy
            ),
        ) as (context, scene_api, lazy):
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            calls.clear()
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=prepared["_formal40_worker_attestation"],
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|source|scope"
                ):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
            self.assertEqual(calls, ["scene_preprocess"])

    def test_operator_exception_still_checks_and_sticky_revokes_attestation(self):
        calls = []
        model = _Task4Model(calls)

        def mutate_then_raise(count):
            if count == 1:
                model.bad_logits_shape = True
                raise RuntimeError("operator failed after mutation")

        evaluator = _Task4Evaluator(
            calls,
            model_to_load=model,
            preprocess_hook=mutate_then_raise,
        )
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            calls.clear()
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=attestation,
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.trace_predict_batch(
                        model,
                        torch.ones((2, 2, 4)),
                        torch.ones((2, 2, 4)),
                        torch.tensor([1, 2]),
                        torch.tensor([3, 4]),
                        self.device,
                        autocast_enabled=True,
                        trial_ids=(1, 2),
                    )
                model.bad_logits_shape = False
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|revoked|callable"
                ):
                    diagnose._live_inference_attestation(model, "restored")
        self.assertEqual(calls, ["scene_preprocess"])

    def test_operator_lease_requires_the_exact_boundary_authority(self):
        calls = []
        model = _Task4Model(calls)
        evaluator = _Task4Evaluator(calls, model_to_load=model)
        with _task4_hermetic_worker_context(evaluator) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            attestation = prepared["_formal40_worker_attestation"]
            calls.clear()
            raw = torch.ones((2, 2, 4))
            labels = torch.tensor([1, 2])
            with diagnose._prediction_evaluator_context(
                evaluator,
                model=model,
                attestation=attestation,
            ):
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "operator|authority|boundary"
                ):
                    diagnose._invoke_attested_operator(
                        model,
                        "scene_preprocess",
                        attestation.evaluator_authority_callables["predict_batch"],
                        model,
                        raw,
                        raw,
                        labels,
                        labels,
                        self.device,
                    )
            self.assertEqual(evaluator.predict_calls, [])

    def test_formal_state_snapshot_ignores_instance_and_class_named_enumerators(self):
        # Break caught: executing holder-rebound discovery instead of direct registries.
        expected = [
            ("buffer", "offset", [1], "torch.float32", "cpu"),
            ("parameter", "weight", [2], "torch.float32", "cpu"),
        ]
        for scope in ("instance", "class"):
            with self.subTest(scope=scope):
                model = _StateFixture()
                invoked = []

                def poisoned_parameters(*args, **kwargs):
                    invoked.append("named_parameters")
                    return iter(())

                def poisoned_buffers(*args, **kwargs):
                    invoked.append("named_buffers")
                    return iter(())

                patches = contextlib.ExitStack()
                with patches:
                    if scope == "instance":
                        model.named_parameters = poisoned_parameters
                        model.named_buffers = poisoned_buffers
                    else:
                        patches.enter_context(
                            mock.patch.object(
                                _StateFixture, "named_parameters", poisoned_parameters
                            )
                        )
                        patches.enter_context(
                            mock.patch.object(
                                _StateFixture, "named_buffers", poisoned_buffers
                            )
                        )
                    entries = diagnose._snapshot_model_entries(model)
                observed = [
                    (
                        entry["kind"],
                        entry["name"],
                        entry["shape"],
                        entry["dtype"],
                        entry["device"],
                    )
                    for entry in entries
                ]
                self.assertEqual((invoked, observed), ([], expected))

    def test_attestation_issuance_binds_state_content_storage_and_keeps_digests_outside_leases(
        self,
    ):
        # Break caught: first-pass snapshots blessing mutations made after issuance.
        def caught(call):
            try:
                call()
            except BaseException as error:
                return error
            return None

        for mutation in ("data_copy", "storage_replace"):
            with self.subTest(mutation=mutation):
                calls = []
                model = _Task4Model(calls)
                model.register_parameter(
                    "sealed_weight",
                    torch.nn.Parameter(torch.tensor([1.0, 2.0]), requires_grad=False),
                )
                evaluator = _Task4Evaluator(calls, model_to_load=model)
                scene_api = _Task4SceneAPI()
                with _task4_hermetic_worker_context(
                    evaluator, scene_api_override=scene_api
                ) as worker_context:
                    prepared = diagnose.prepare_formal40_worker(
                        worker_context, allow_cpu=True
                    )
                    attestation = prepared["_formal40_worker_attestation"]
                    parameter = model.sealed_weight
                    original_data = parameter.data
                    original_values = parameter.detach().clone()
                    original_version = parameter._version
                    original_storage = parameter.untyped_storage().data_ptr()
                    if mutation == "data_copy":
                        parameter.data.copy_(original_values + 7.0)
                        self.assertEqual(
                            (
                                parameter._version,
                                parameter.untyped_storage().data_ptr(),
                            ),
                            (original_version, original_storage),
                        )
                    else:
                        parameter.data = original_values.clone()
                        self.assertEqual(parameter._version, original_version)
                        self.assertNotEqual(
                            parameter.untyped_storage().data_ptr(), original_storage
                        )
                        self.assertTrue(torch.equal(parameter, original_values))
                    calls.clear()
                    scene_api.raw_calls.clear()
                    scene_api.cue_calls.clear()
                    pass_context = {
                        **worker_context,
                        **prepared,
                        "scene_api": scene_api,
                        "bank": self.bank,
                        "clips_dir": pathlib.Path("/clips"),
                        "historical_scene_hashes": self.hashes,
                    }
                    first = caught(
                        lambda: diagnose.run_reference_pass(
                            pass_context, self.trials, "pass1", 2
                        )
                    )
                    if mutation == "data_copy":
                        parameter.data.copy_(original_values)
                    else:
                        parameter.data = original_data
                    with diagnose._prediction_evaluator_context(
                        evaluator,
                        model=model,
                        attestation=attestation,
                    ):
                        restored = caught(
                            lambda: diagnose._live_inference_attestation(
                                model, "restored_state"
                            )
                        )
                    self.assertEqual(
                        (
                            type(first),
                            scene_api.raw_calls,
                            scene_api.cue_calls,
                            evaluator.predict_calls,
                            type(restored),
                        ),
                        (
                            diagnose.DiagnosticError,
                            [],
                            [],
                            [],
                            diagnose.DiagnosticError,
                        ),
                    )

        events = []
        lease_depth = [0]
        phase = ["issue"]

        class TraceProxy:
            def __getattr__(proxy_self, name):
                return getattr(trace, name)

            def tensor_record(proxy_self, value, *, boundary):
                events.append((phase[0], "tensor_record", boundary, lease_depth[0]))
                return trace.tensor_record(value, boundary=boundary)

            def canonical_tensor_bytes(proxy_self, value):
                events.append((phase[0], "tensor_bytes", "", lease_depth[0]))
                return trace.canonical_tensor_bytes(value)

        original_invoke = diagnose._invoke_attested_operator

        def observed_invoke(*args, **kwargs):
            lease_depth[0] += 1
            try:
                return original_invoke(*args, **kwargs)
            finally:
                lease_depth[0] -= 1

        model = _Task4Model([])
        model.register_parameter(
            "sealed_weight",
            torch.nn.Parameter(torch.tensor([1.0, 2.0]), requires_grad=False),
        )
        evaluator = _Task4Evaluator(model_to_load=model)
        scene_api = _Task4SceneAPI()
        with (
            mock.patch.object(diagnose, "_get_trace", return_value=TraceProxy()),
            mock.patch.object(
                diagnose, "_invoke_attested_operator", side_effect=observed_invoke
            ),
            _task4_hermetic_worker_context(
                evaluator, scene_api_override=scene_api
            ) as worker_context,
        ):
            prepared = diagnose.prepare_formal40_worker(worker_context, allow_cpu=True)
            issuance_events = list(events)
            phase[0] = "pass"
            diagnose.run_reference_pass(
                {
                    **worker_context,
                    **prepared,
                    "scene_api": scene_api,
                    "bank": self.bank,
                    "clips_dir": pathlib.Path("/clips"),
                    "historical_scene_hashes": self.hashes,
                },
                self.trials,
                "pass1",
                2,
            )
        self.assertTrue(issuance_events, "attestation issuance made no tensor digest")
        self.assertTrue(all(event[3] == 0 for event in events), events)

    def test_exited_frozen_scene_context_fails_before_reference_prediction(self):
        # Break caught: retaining scene callbacks after the SHA-bound import context exits.
        scene_api = _Task4SceneAPI(exited=True)
        context = {
            "evaluator": self.evaluator,
            "model": self.model,
            "scene_api": scene_api,
            "bank": self.bank,
            "clips_dir": pathlib.Path("/clips"),
            "historical_scene_hashes": self.hashes,
            "device": self.device,
        }
        with self.assertRaisesRegex(diagnose.DiagnosticError, "context exit"):
            diagnose.run_reference_pass(context, self.trials, "pass1", 2)
        self.assertEqual(self.evaluator.predict_calls, [])


def _task4_metadata(
    role,
    trial_ids,
    *,
    worker_pid,
    worker_nonce,
    model_nonce,
    cache_nonce,
    scratch_root,
    cache_root,
    source_records=None,
    trust_domain="hermetic-test",
    scene_scope_nonce="scene-scope",
):
    load_report = {
        "key_count": 1,
        "missing_keys": [],
        "unexpected_keys": [],
        "shape_mismatches": {},
        "dtype_mismatches": {},
        "prefix_rule": "exact",
        "loaded_trainable_numel": 1,
        "trainable_numel": 1,
        "loaded_trainable_numel_ratio": 1.0,
        "native_preprocessing": "selftrain_singleton_per_example_leveling",
        "model_module": {"path": "/frozen/src/spatial_attn_lightning.py"},
    }
    load_report_sha = hashlib.sha256(
        trace.canonical_json_bytes(load_report)
    ).hexdigest()
    source_records = source_records or (
        {"relative_path": "frozen.py", "sha256": "b" * 64},
    )
    input_context_sha = hashlib.sha256(
        trace.canonical_json_bytes(
            {
                "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
                "v4_protocol": diagnose.V4_PROTOCOL,
                "evaluator_sha256": diagnose.V4_EVALUATOR_SHA256,
                "manifest_sha256": diagnose.V4_MANIFEST_SHA256,
                "load_report_sha256": load_report_sha,
                "imported_source_records": source_records,
            }
        )
    ).hexdigest()
    return {
        "role": role,
        "path": "frozen_predict_batch" if role == "REFERENCE_COLD" else "traced",
        "autocast_enabled": None if role == "REFERENCE_COLD" else True,
        "runtime": {
            "deterministic_algorithms": True,
            "cudnn_deterministic": True,
            "cudnn_benchmark": False,
            "float32_matmul_precision": "medium",
            "cuda_matmul_allow_tf32": True,
            "cudnn_allow_tf32": True,
        },
        "load_report": load_report,
        "load_report_sha256": load_report_sha,
        "imported_source_records": source_records,
        "trial_bank_rows": [
            {"trial_id": trial_id, "bank_row_index": 1000 + trial_id}
            for trial_id in trial_ids
        ],
        "worker_pid": worker_pid,
        "worker_nonce": worker_nonce,
        "model_nonce": model_nonce,
        "cache_nonce": cache_nonce,
        "scratch_root": scratch_root,
        "cache_roots": {
            "torchinductor": cache_root + "/torchinductor",
            "triton": cache_root + "/triton",
            "cuda": cache_root + "/cuda",
        },
        "attestation": {
            "basis": "static_formal40_worker_attestation",
            "limitation": "inference-disabled versions are not dynamic mutation detection",
            "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
            "v4_protocol": diagnose.V4_PROTOCOL,
            "evaluator_sha256": diagnose.V4_EVALUATOR_SHA256,
            "manifest_sha256": diagnose.V4_MANIFEST_SHA256,
            "model_id": "formal40",
            "worker_pid": worker_pid,
            "worker_nonce": worker_nonce,
            "model_nonce": model_nonce,
            "load_report_sha256": load_report_sha,
            "input_context_sha256": input_context_sha,
            "trust_domain": trust_domain,
            "scene_scope_nonce": scene_scope_nonce,
        },
    }


def _task4_pass(
    pass_id,
    trial_ids,
    raw,
    cue,
    outputs,
    *,
    model=None,
    rng=None,
    metadata=None,
    batch_size=None,
):
    model = model or _StateFixture()
    state = trace.snapshot_model_state(model)["entries"]
    rng = rng or trace.snapshot_rng_state()
    correct = np.asarray(outputs["pred_label"]) == np.asarray(
        [trial_id % 2 for trial_id in trial_ids]
    )
    return diagnose.PassResult(
        pass_id=pass_id,
        batch_size=len(trial_ids) if batch_size is None else batch_size,
        trial_ids=tuple(trial_ids),
        outputs=outputs,
        boundary_records={
            "raw_scene": {"tensor": raw},
            "raw_cue": {"tensor": cue},
            "derived": {"correct": {"tensor": correct}},
            "metadata": metadata or {},
        },
        model_snapshots={"before": state, "after": state},
        rng_snapshots={"before": rng, "after": rng},
    )


class ReferenceEquivalenceTests(unittest.TestCase):
    """Task 4 bitwise cold-reference equivalence and fail-closed boundaries."""

    def _pair(self, *, authenticated=False):
        capability_context = _task4_hermetic_worker_context(_Task4Evaluator())
        capability_values = capability_context.__enter__()
        self.addCleanup(capability_context.__exit__, None, None, None)
        root = capability_values["_frozen_context_capability"].root
        capability = capability_values["_frozen_context_capability"]
        scope_nonce = diagnose._ACTIVE_WORKER_SCENE_SCOPE.get()["nonce"]
        sealed_sources = tuple(dict(item) for item in capability.source_records)
        root_paths = {}
        for role in ("reference", "a2"):
            scratch = root / f"{role}-scratch"
            cache_root = root / f"{role}-cache"
            scratch.mkdir()
            cache_root.mkdir()
            for name in ("torchinductor", "triton", "cuda"):
                (cache_root / name).mkdir()
            root_paths[role] = (scratch, cache_root)
        trial_ids = (10, 11)
        raw = torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.float32)
        cue = torch.tensor([[0.5, 0.25], [0.75, 1.0]], dtype=torch.float32)
        outputs = {
            "pred_label": np.array([0, 1], dtype=np.int64),
            "nll": np.array([0.1, 0.2], dtype=np.float32),
            "p_target": np.array([0.9, 0.8], dtype=np.float32),
            "p_probe_distractor": np.array([0.05, 0.1], dtype=np.float32),
        }
        reference = _task4_pass(
            "pass1",
            trial_ids,
            raw,
            cue,
            outputs,
            metadata=_task4_metadata(
                "REFERENCE_COLD",
                trial_ids,
                worker_pid=1001,
                worker_nonce="worker-reference",
                model_nonce="model-reference",
                cache_nonce="cache-reference",
                scratch_root=str(root_paths["reference"][0]),
                cache_root=str(root_paths["reference"][1]),
                source_records=sealed_sources,
                scene_scope_nonce=scope_nonce,
            ),
        )
        order = [1, 0]
        traced = _task4_pass(
            "pass1",
            (11, 10),
            raw[order],
            cue[order],
            {key: np.asarray(value)[order] for key, value in outputs.items()},
            metadata=_task4_metadata(
                "A2",
                (11, 10),
                worker_pid=1002,
                worker_nonce="worker-a2",
                model_nonce="model-a2",
                cache_nonce="cache-a2",
                scratch_root=str(root_paths["a2"][0]),
                cache_root=str(root_paths["a2"][1]),
                source_records=sealed_sources,
                scene_scope_nonce=scope_nonce,
            ),
        )
        self._pair_capability = capability
        if not authenticated:
            return reference, traced
        return (
            diagnose._authenticate_hermetic_pass_result(capability, reference),
            diagnose._authenticate_hermetic_pass_result(capability, traced),
        )

    def test_equivalence_aligns_by_trial_id_and_requires_every_bitwise_boundary(self):
        # Break caught: comparing call order or skipping a frozen official output.
        reference, traced = self._pair()
        got = diagnose._compare_reference_equivalence_hermetic(
            diagnose._authenticate_hermetic_pass_result(
                self._pair_capability, reference
            ),
            diagnose._authenticate_hermetic_pass_result(self._pair_capability, traced),
        )
        self.assertEqual(got["status"], "REFERENCE_EQUIVALENCE_PASS")
        self.assertEqual(got["trial_ids"], [10, 11])
        self.assertTrue(
            all(item["bitwise_equal"] for item in got["comparisons"].values())
        )
        self.assertTrue(got["reference_model_state_unchanged"])
        self.assertTrue(got["trace_model_state_unchanged"])

    def test_authenticated_metadata_sources_bind_to_each_capability_inventory(self):
        # Break caught: two mutually consistent public source lists can disagree
        # with the sealed source inventory that authenticated each pass.
        reference, traced = self._pair(authenticated=False)
        capability = self._pair_capability
        rewritten = []
        forged_sources = ({"relative_path": "frozen.py", "sha256": "b" * 64},)
        for result in (reference, traced):
            records = dict(result.boundary_records)
            metadata = dict(records["metadata"])
            metadata["imported_source_records"] = forged_sources
            report_sha = metadata["load_report_sha256"]
            attestation = dict(metadata["attestation"])
            attestation["input_context_sha256"] = hashlib.sha256(
                trace.canonical_json_bytes(
                    {
                        "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
                        "v4_protocol": diagnose.V4_PROTOCOL,
                        "evaluator_sha256": diagnose.V4_EVALUATOR_SHA256,
                        "manifest_sha256": diagnose.V4_MANIFEST_SHA256,
                        "load_report_sha256": report_sha,
                        "imported_source_records": forged_sources,
                    }
                )
            ).hexdigest()
            metadata["attestation"] = attestation
            records["metadata"] = metadata
            rewritten.append(dataclasses.replace(result, boundary_records=records))
        with self.assertRaisesRegex(
            diagnose.DiagnosticError, "source|capability|authenticated"
        ):
            authenticated = tuple(
                diagnose._authenticate_hermetic_pass_result(capability, result)
                for result in rewritten
            )
            diagnose._compare_reference_equivalence_hermetic(*authenticated)

    def test_authenticated_public_attestation_binds_domain_and_scene_scope(self):
        # Break caught: public attestation fields must be checked against the
        # private authentication capability, not merely agree across passes.
        for field, value in (
            ("trust_domain", "production"),
            ("scene_scope_nonce", "forged-scope"),
        ):
            with self.subTest(field=field):
                reference, traced = self._pair(authenticated=False)
                capability = self._pair_capability
                rewritten = []
                for result in (reference, traced):
                    records = dict(result.boundary_records)
                    metadata = dict(records["metadata"])
                    attestation = dict(metadata["attestation"])
                    attestation[field] = value
                    metadata["attestation"] = attestation
                    records["metadata"] = metadata
                    rewritten.append(
                        dataclasses.replace(result, boundary_records=records)
                    )
                with self.assertRaisesRegex(
                    diagnose.DiagnosticError, "attestation|domain|scope|authentication"
                ):
                    authenticated = tuple(
                        diagnose._authenticate_hermetic_pass_result(capability, result)
                        for result in rewritten
                    )
                    diagnose._compare_reference_equivalence_hermetic(*authenticated)

    def test_authentication_and_unwrap_reject_mutated_or_revoked_capability(self):
        reference, traced = self._pair(authenticated=False)
        capability = self._pair_capability
        capability.manifest["tampered"] = True
        with self.assertRaisesRegex(diagnose.DiagnosticError, "capability|changed"):
            diagnose._authenticate_hermetic_pass_result(capability, reference)

        reference, traced = self._pair(authenticated=False)
        capability = self._pair_capability
        authenticated = (
            diagnose._authenticate_hermetic_pass_result(capability, reference),
            diagnose._authenticate_hermetic_pass_result(capability, traced),
        )
        diagnose._revoke_capability(capability)
        with self.assertRaisesRegex(
            diagnose.DiagnosticError, "capability|receipt|revoked"
        ):
            diagnose._compare_reference_equivalence_hermetic(*authenticated)

    def test_authenticated_receipt_is_deeply_immutable_and_sticky_after_failure(self):
        reference, traced = self._pair(authenticated=False)
        capability = self._pair_capability
        receipt = diagnose._authenticate_hermetic_pass_result(capability, reference)
        with self.assertRaises(TypeError):
            receipt.artifact_record["trust_domain"] = "production"
        with self.assertRaises(TypeError):
            receipt.artifact_record["imported_source_records"][0]["sha256"] = "f" * 64

        original_batch_size = reference.batch_size
        reference.batch_size = original_batch_size + 1
        with self.assertRaisesRegex(diagnose.DiagnosticError, "binding|receipt"):
            diagnose._unwrap_authenticated_pass(receipt, trust_domain="hermetic-test")
        reference.batch_size = original_batch_size
        with self.assertRaisesRegex(diagnose.DiagnosticError, "receipt|revoked"):
            diagnose._unwrap_authenticated_pass(receipt, trust_domain="hermetic-test")

        fresh = diagnose._authenticate_hermetic_pass_result(capability, traced)
        object.__setattr__(fresh, "nonce", "forged")
        with self.assertRaisesRegex(diagnose.DiagnosticError, "receipt|revoked"):
            diagnose._unwrap_authenticated_pass(fresh, trust_domain="hermetic-test")

    def test_all_receipts_reject_poison_without_eq_or_hash_and_sticky_revoke(self):
        # Break caught: holder fields choosing equality or escaping revocation via BaseException.
        class ReceiptHookExecuted(BaseException):
            pass

        class Poison:
            def __init__(self, raises):
                self.raises = raises
                self.calls = []

            def result(self, name, value):
                self.calls.append(name)
                if self.raises:
                    raise ReceiptHookExecuted(name)
                return value

            def __eq__(self, other):
                return self.result("__eq__", True)

            def __ne__(self, other):
                return self.result("__ne__", False)

            def __hash__(self):
                return self.result("__hash__", 0)

        def caught(call):
            try:
                call()
            except BaseException as error:
                return error
            return None

        for receipt_kind in ("capability", "attestation", "authenticated_pass"):
            for raises in (False, True):
                with self.subTest(receipt=receipt_kind, raises=raises):
                    poison = Poison(raises)
                    if receipt_kind == "authenticated_pass":
                        reference, _ = self._pair(authenticated=False)
                        capability = self._pair_capability
                        holder = diagnose._authenticate_hermetic_pass_result(
                            capability, reference
                        )
                        original = holder.nonce
                        object.__setattr__(holder, "nonce", poison)
                        first = caught(
                            lambda: diagnose._unwrap_authenticated_pass(
                                holder, trust_domain="hermetic-test"
                            )
                        )
                        object.__setattr__(holder, "nonce", original)
                        restored = caught(
                            lambda: diagnose._unwrap_authenticated_pass(
                                holder, trust_domain="hermetic-test"
                            )
                        )
                    else:
                        evaluator = _Task4Evaluator(model_to_load=_Task4Model())
                        with _task4_hermetic_worker_context(evaluator) as context:
                            capability = context["_frozen_context_capability"]
                            if receipt_kind == "capability":
                                holder = capability
                                original = holder.nonce
                                object.__setattr__(holder, "nonce", poison)
                                first = caught(
                                    lambda: diagnose._validate_frozen_capability_contents(
                                        holder
                                    )
                                )
                                object.__setattr__(holder, "nonce", original)
                                restored = caught(
                                    lambda: diagnose._validate_frozen_capability_contents(
                                        holder
                                    )
                                )
                            else:
                                prepared = diagnose.prepare_formal40_worker(
                                    context, allow_cpu=True
                                )
                                holder = prepared["_formal40_worker_attestation"]
                                original = holder.worker_nonce
                                object.__setattr__(holder, "worker_nonce", poison)
                                with diagnose._prediction_evaluator_context(
                                    evaluator,
                                    model=holder.model,
                                    attestation=holder,
                                ):
                                    first = caught(
                                        lambda: diagnose._live_inference_attestation(
                                            holder.model, "poisoned_receipt"
                                        )
                                    )
                                    object.__setattr__(holder, "worker_nonce", original)
                                    restored = caught(
                                        lambda: diagnose._live_inference_attestation(
                                            holder.model, "restored_receipt"
                                        )
                                    )
                    self.assertEqual(
                        (type(first), poison.calls, type(restored)),
                        (diagnose.DiagnosticError, [], diagnose.DiagnosticError),
                    )

    def test_hand_built_or_copied_provenance_never_authenticates(self):
        # Break caught: public dictionaries or copied private records posing as receipts.
        reference, traced = self._pair(authenticated=False)
        with self.assertRaisesRegex(diagnose.DiagnosticError, "receipt|authenticated"):
            diagnose.compare_reference_equivalence(reference, traced)
        fake = types.SimpleNamespace(binding_sha256="f" * 64)
        for value in (
            fake,
            dataclasses.replace(reference),
            dataclasses.replace(traced),
        ):
            records = dict(reference.boundary_records)
            records["provenance_receipt"] = value
            forged = dataclasses.replace(reference, boundary_records=records)
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.compare_reference_equivalence(forged, traced)

    def test_authenticated_binding_detects_every_pass_payload_tamper(self):
        # Break caught: authentic metadata surviving modified outputs/boundaries/provenance.
        reference, traced = self._pair(authenticated=False)
        capability = self._pair_capability
        reference_auth = diagnose._authenticate_hermetic_pass_result(
            capability, reference
        )
        traced_auth = diagnose._authenticate_hermetic_pass_result(capability, traced)
        clean = diagnose._compare_reference_equivalence_hermetic(
            reference_auth, traced_auth
        )
        self.assertEqual(clean["status"], "REFERENCE_EQUIVALENCE_PASS")
        changes = []
        outputs = dict(traced.outputs)
        outputs["nll"] = outputs["nll"].copy()
        outputs["nll"][0] += 1
        changes.append(dataclasses.replace(traced, outputs=outputs))
        boundaries = dict(traced.boundary_records)
        boundaries["raw_scene"] = {
            "tensor": torch.zeros_like(boundaries["raw_scene"]["tensor"])
        }
        changes.append(dataclasses.replace(traced, boundary_records=boundaries))
        metadata = dict(traced.boundary_records["metadata"])
        metadata["worker_nonce"] = "tampered"
        boundaries = dict(traced.boundary_records)
        boundaries["metadata"] = metadata
        changes.append(dataclasses.replace(traced, boundary_records=boundaries))
        changes.append(dataclasses.replace(traced, batch_size=1))
        self.assertIsNotNone(capability)
        for changed in changes:
            with self.assertRaisesRegex(diagnose.DiagnosticError, "binding|receipt"):
                diagnose._compare_reference_equivalence_hermetic(
                    reference_auth, changed
                )

    def test_scratch_and_cache_roots_are_canonical_real_and_pairwise_disjoint(self):
        # Break caught: unequal strings naming the same or overlapping directory tree.
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            paths = [
                root / name
                for name in (
                    "ref-s",
                    "ref-c1",
                    "ref-c2",
                    "ref-c3",
                    "a2-s",
                    "a2-c1",
                    "a2-c2",
                    "a2-c3",
                )
            ]
            for path in paths:
                path.mkdir()
            good = {
                "scratch": str(paths[0]),
                "torchinductor": str(paths[1]),
                "triton": str(paths[2]),
                "cuda": str(paths[3]),
            }
            other = {
                "scratch": str(paths[4]),
                "torchinductor": str(paths[5]),
                "triton": str(paths[6]),
                "cuda": str(paths[7]),
            }
            diagnose._validate_isolated_roots(good, other)
            alias = root / "alias"
            alias.symlink_to(paths[0], target_is_directory=True)
            child = paths[0] / "child"
            child.mkdir()
            bad_pairs = (
                (good, dict(other, scratch=good["scratch"])),
                (good, dict(other, scratch=str(alias))),
                (good, dict(other, scratch=str(child))),
                (dict(good, triton=good["scratch"]), other),
                (dict(good, cuda=str(paths[3] / ".." / paths[3].name)), other),
            )
            for left, right in bad_pairs:
                with self.subTest(left=left, right=right):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._validate_isolated_roots(left, right)

    def test_equivalence_proves_roles_runtime_load_sources_trials_and_cold_isolation(
        self,
    ):
        # Break caught: role-swapped or same-worker evidence being called a cold A2 replay.
        reference, traced = self._pair()
        ref_metadata = reference.boundary_records["metadata"]

        def changed(**updates):
            records = dict(traced.boundary_records)
            metadata = dict(records["metadata"])
            metadata.update(updates)
            records["metadata"] = metadata
            return dataclasses.replace(traced, boundary_records=records)

        cases = {
            "same_role": changed(role="REFERENCE_COLD", path="frozen_predict_batch"),
            "autocast_off": changed(autocast_enabled=False),
            "runtime_mismatch": changed(
                runtime={**ref_metadata["runtime"], "cudnn_benchmark": True}
            ),
            "runtime_missing": changed(runtime=None),
            "load_mismatch": changed(load_report={"formal40": "different"}),
            "load_missing": changed(load_report=None),
            "source_mismatch": changed(imported_source_records=()),
            "trial_mismatch": changed(trial_bank_rows=[]),
            "same_pid": changed(worker_pid=ref_metadata["worker_pid"]),
            "same_worker": changed(worker_nonce=ref_metadata["worker_nonce"]),
            "same_model": changed(model_nonce=ref_metadata["model_nonce"]),
            "same_cache": changed(cache_nonce=ref_metadata["cache_nonce"]),
            "same_scratch": changed(scratch_root=ref_metadata["scratch_root"]),
            "same_cache_roots": changed(cache_roots=ref_metadata["cache_roots"]),
            "batch_size_mismatch": dataclasses.replace(traced, batch_size=1),
        }
        for name, candidate in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._compare_reference_equivalence_hermetic(
                        diagnose._authenticate_hermetic_pass_result(
                            self._pair_capability, reference
                        ),
                        diagnose._authenticate_hermetic_pass_result(
                            self._pair_capability, candidate
                        ),
                    )

    def test_equivalence_rejects_output_identity_nonfinite_or_state_mutation(self):
        # Break caught: interpreting a trace after any schema, identity, finite, or state violation.
        mutations = []
        reference, traced = self._pair()
        bad_output = dict(traced.outputs)
        bad_output["nll"] = bad_output["nll"].copy()
        bad_output["nll"][0] += np.float32(0.01)
        mutations.append(dataclasses.replace(traced, outputs=bad_output))
        bad_nonfinite = dict(traced.outputs)
        bad_nonfinite["p_target"] = bad_nonfinite["p_target"].copy()
        bad_nonfinite["p_target"][0] = np.nan
        mutations.append(dataclasses.replace(traced, outputs=bad_nonfinite))
        bad_boundary = dict(traced.boundary_records)
        bad_boundary["raw_scene"] = {
            "tensor": traced.boundary_records["raw_scene"]["tensor"].double()
        }
        mutations.append(dataclasses.replace(traced, boundary_records=bad_boundary))
        model = _StateFixture()
        before = trace.snapshot_model_state(model)["entries"]
        with torch.no_grad():
            model.offset.add_(1.0)
        after = trace.snapshot_model_state(model)["entries"]
        mutations.append(
            dataclasses.replace(
                traced, model_snapshots={"before": before, "after": after}
            )
        )
        for index, bad in enumerate(mutations):
            with self.subTest(kind=index):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._compare_reference_equivalence_hermetic(
                        diagnose._authenticate_hermetic_pass_result(
                            self._pair_capability, reference
                        ),
                        diagnose._authenticate_hermetic_pass_result(
                            self._pair_capability, bad
                        ),
                    )

    def test_equivalence_requires_valid_rng_schema_but_rng_movement_is_context_only(
        self,
    ):
        # Break caught: accepting unauthenticated RNG evidence or treating ordinary RNG movement as trace inequivalence.
        reference, traced = self._pair()
        malformed = dataclasses.replace(
            traced,
            rng_snapshots={"before": {"families": {}}, "after": {"families": {}}},
        )
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.compare_reference_equivalence(reference, malformed)
        moved = trace.snapshot_rng_state()
        _ = torch.rand(1)
        later = trace.snapshot_rng_state()
        traced = dataclasses.replace(
            traced, rng_snapshots={"before": moved, "after": later}
        )
        got = diagnose._compare_reference_equivalence_hermetic(
            diagnose._authenticate_hermetic_pass_result(
                self._pair_capability, reference
            ),
            diagnose._authenticate_hermetic_pass_result(self._pair_capability, traced),
        )
        self.assertEqual(got["status"], "REFERENCE_EQUIVALENCE_PASS")
        self.assertTrue(got["trace_rng_changed"])


def _task5_refresh(result):
    """Refresh authentic post-output records after a deliberate numeric fixture edit."""
    for name in diagnose._TRACE_BOUNDARIES:
        record = result.boundary_records[name]
        value = record["tensor"]
        chunks = list(value.split(result.batch_size))
        guards = []
        for chunk in chunks:
            before = diagnose._tensor_guard(chunk, name)
            guards.append(diagnose._finish_tensor_guard(chunk, name, before))
        result.boundary_records[name] = diagnose._boundary_from_batches(
            name, chunks, result.trial_ids, guards
        )
    for name, record in list(result.boundary_records["derived"].items()):
        result.boundary_records["derived"][name] = diagnose._boundary_from_batches(
            name, [record["tensor"]], result.trial_ids, ()
        )
    diagnose._bind_pass_commitment(result)


def _task5_pair(cell="A2"):
    import copy

    ids = tuple(range(100, 132))
    state = trace.snapshot_model_state(_StateFixture())["entries"]
    rng = trace.snapshot_rng_state()
    values = []
    spec = diagnose.CELL_SPECS[cell]
    for pass_index, batch_size in enumerate(spec.pass_batch_sizes, 1):
        outputs = {
            "pred_label": np.zeros(32, dtype=np.int64),
            "nll": np.zeros(32, dtype=np.float64),
            "p_target": np.ones(32, dtype=np.float64),
            "p_probe_distractor": np.zeros(32, dtype=np.float64),
        }
        metadata = _task4_metadata(
            cell,
            ids,
            worker_pid=123,
            worker_nonce="worker",
            model_nonce="model",
            cache_nonce=f"pass-cache-{pass_index}",
            scratch_root="/scratch/A2",
            cache_root="/scratch/A2/cache",
        )
        metadata["autocast_enabled"] = spec.autocast_enabled
        result = diagnose.PassResult(
            pass_id=f"pass{pass_index}",
            batch_size=batch_size,
            trial_ids=ids,
            outputs=outputs,
            boundary_records={"metadata": metadata, "derived": {}},
            model_snapshots={
                "before": copy.deepcopy(state),
                "after": copy.deepcopy(state),
            },
            rng_snapshots={"before": copy.deepcopy(rng), "after": copy.deepcopy(rng)},
        )
        for name in diagnose._TRACE_BOUNDARIES:
            classes = 800 if name in {"native_logits", "log_probabilities"} else 3
            result.boundary_records[name] = {
                "tensor": torch.arange(32 * classes, dtype=torch.float32).reshape(
                    32, classes
                )
            }
        for name in ("target_logit", "logsumexp", "target_log_probability"):
            result.boundary_records["derived"][name] = {"tensor": torch.zeros(32)}
        for name, value in outputs.items():
            result.boundary_records["derived"][name] = {
                "tensor": torch.from_numpy(value.copy())
            }
        result.boundary_records["derived"]["correct"] = {
            "tensor": torch.ones(32, dtype=torch.bool)
        }
        _task5_refresh(result)
        values.append(result)
    return values


class CellSemanticsTests(unittest.TestCase):
    """Task 5a: numeric observation is not confused with invalid evidence."""

    def compare(self, pair, cell="A2"):
        return diagnose.compare_passes(*pair, spec=diagnose.CELL_SPECS[cell])

    def test_real_task4_pass_records_feed_cell_comparison_without_rewriting(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        trials = _task4_trials(bank)
        with _task4_hermetic_worker_context(evaluator, scene_api) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            run = {
                **context,
                **prepared,
                "bank": bank,
                "clips_dir": pathlib.Path("/clips"),
                "cell_id": "B1",
                "historical_scene_hashes": _task4_scene_hashes(bank),
                "scratch_root": "/scratch/B1",
                "cache_roots": {},
            }
            first = diagnose.run_trace_pass(
                run, trials, "pass1", 16, False, pathlib.Path("/scratch/B1")
            )
            second = diagnose.run_trace_pass(
                run, trials, "pass2", 16, False, pathlib.Path("/scratch/B1")
            )
            got = self.compare((first, second), "B1")
        self.assertEqual(got["errors"], [])
        self.assertEqual(got["cell_status"], "PASS")
        self.assertEqual(len(evaluator.load_calls), 1)

    def test_all_four_cells_accept_exact_replay(self):
        for cell in ("A1", "A2", "B1", "B2"):
            with self.subTest(cell=cell):
                got = self.compare(_task5_pair(cell), cell)
                self.assertEqual(got["cell_status"], "PASS")
                self.assertEqual(got["canary_status"], "PASS")
                self.assertIsNone(got["first_divergence"])
                self.assertEqual(
                    got["a2_replay_classification"],
                    "NOT_REPRODUCED" if cell == "A2" else None,
                )

    def test_historical_nll_difference_is_observation_not_exception(self):
        pair = _task5_pair()
        delta = 0.0077362060546875
        pair[1].outputs["nll"][5] = delta
        pair[1].boundary_records["derived"]["nll"]["tensor"][5] = delta
        _task5_refresh(pair[1])
        got = self.compare(pair)
        self.assertEqual((got["cell_status"], got["canary_status"]), ("DIFF", "DIFF"))
        self.assertEqual(got["a2_replay_classification"], "REPRODUCED")
        self.assertEqual(got["nll_max_abs"], delta)
        self.assertEqual(got["comparisons"]["nll"]["worst"]["trial_id"], 105)

    def test_exact_threshold_and_next_float_are_distinct(self):
        for value, classification in (
            (1e-6, "NOT_REPRODUCED"),
            (np.nextafter(1e-6, np.inf), "REPRODUCED"),
        ):
            pair = _task5_pair()
            pair[1].outputs["nll"][0] = value
            pair[1].boundary_records["derived"]["nll"]["tensor"][0] = value
            _task5_refresh(pair[1])
            got = self.compare(pair)
            self.assertEqual(got["a2_replay_classification"], classification)
            self.assertEqual(
                got["canary_status"],
                "PASS" if classification == "NOT_REPRODUCED" else "DIFF",
            )

    def test_below_threshold_boundary_difference_is_not_hidden(self):
        pair = _task5_pair()
        pair[1].boundary_records["normalized_scene"]["tensor"][0, 0] = 1e-8
        _task5_refresh(pair[1])
        got = self.compare(pair)
        self.assertEqual(got["cell_status"], "DIFF")
        self.assertEqual(got["canary_status"], "PASS")
        self.assertEqual(got["first_divergence"], "normalized_waveform")

    def test_trial_alignment_does_not_depend_on_batch_order(self):
        pair = _task5_pair()
        second = pair[1]
        order = list(reversed(range(32)))
        second.trial_ids = tuple(second.trial_ids[i] for i in order)
        second.outputs = {key: value[order] for key, value in second.outputs.items()}
        for name in diagnose._TRACE_BOUNDARIES:
            second.boundary_records[name]["tensor"] = second.boundary_records[name][
                "tensor"
            ][order]
        for record in second.boundary_records["derived"].values():
            record["tensor"] = record["tensor"][order]
        rows = second.boundary_records["metadata"]["trial_bank_rows"]
        second.boundary_records["metadata"]["trial_bank_rows"] = [
            rows[i] for i in order
        ]
        _task5_refresh(second)
        self.assertEqual(self.compare(pair)["cell_status"], "PASS")

    def test_every_identity_schema_and_runtime_break_is_invalid(self):
        mutations = (
            lambda p: setattr(p, "trial_ids", tuple([100] * 32)),
            lambda p: setattr(p, "batch_size", 16),
            lambda p: p.boundary_records["metadata"]["trial_bank_rows"][0].update(
                bank_row_index=999
            ),
            lambda p: p.boundary_records["metadata"].update(autocast_enabled=False),
            lambda p: p.boundary_records["metadata"].update(model_nonce="other"),
            lambda p: p.boundary_records["metadata"].update(cache_nonce="pass-cache-1"),
            lambda p: p.outputs.update(nll=p.outputs["nll"].astype(np.float32)),
            lambda p: p.boundary_records["native_logits"].update(
                tensor=torch.zeros(32, 799)
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutations.index(mutate)):
                pair = _task5_pair()
                mutate(pair[1])
                diagnose._bind_pass_commitment(pair[1])
                got = self.compare(pair)
                self.assertEqual(got["cell_status"], "INVALID")
                self.assertIsNone(got["canary_status"])
                self.assertIsNone(got["a2_replay_classification"])
                self.assertIsNone(got["first_divergence"])

    def test_raw_identity_mismatch_cannot_be_numeric_diff(self):
        for name in ("raw_scene", "raw_cue"):
            pair = _task5_pair()
            pair[1].boundary_records[name]["tensor"][0, 0] += 1
            _task5_refresh(pair[1])
            with mock.patch.object(
                diagnose, "classify_a2", side_effect=AssertionError("must not classify")
            ):
                self.assertEqual(self.compare(pair)["cell_status"], "INVALID")

    def test_mutation_guard_invalid_precedes_numeric_interpretation(self):
        pair = _task5_pair()
        guard = pair[1].boundary_records["scene_features"]["guards"][0]
        guard["after"]["version"] += 1
        diagnose._bind_pass_commitment(pair[1])
        with mock.patch.object(
            diagnose, "classify_a2", side_effect=AssertionError("must not classify")
        ):
            got = self.compare(pair)
        self.assertEqual(got["cell_status"], "INVALID")
        self.assertTrue(any("guard" in item for item in got["errors"]))

    def test_model_mutation_and_between_gap_are_invalid(self):
        for timepoint in ("before", "after"):
            pair = _task5_pair()
            pair[1].model_snapshots[timepoint][0]["sha256"] = "f" * 64
            diagnose._bind_pass_commitment(pair[1])
            self.assertEqual(self.compare(pair)["cell_status"], "INVALID")

    def test_legitimate_rng_movement_is_context_not_failure(self):
        import copy

        pair = _task5_pair()
        with mock.patch.object(
            random, "getstate", return_value=("changed RNG fixture",)
        ):
            changed = trace.snapshot_rng_state()
        pair[0].rng_snapshots["after"] = copy.deepcopy(changed)
        pair[1].rng_snapshots = {
            "before": copy.deepcopy(changed),
            "after": copy.deepcopy(changed),
        }
        for result in pair:
            diagnose._bind_pass_commitment(result)
        got = self.compare(pair)
        self.assertEqual(got["cell_status"], "PASS")
        self.assertTrue(got["rng"]["rng_changed"])

    def test_nonfinite_patterns_are_bounded_before_numeric_helper(self):
        pair = _task5_pair()
        pair[1].boundary_records["scene_features"]["tensor"] = torch.full(
            (32, 10000), float("nan")
        )
        pair[0].boundary_records["scene_features"]["tensor"] = torch.zeros(32, 10000)
        for result in pair:
            _task5_refresh(result)
        real_compare = trace.compare_aligned_tensor

        def finite_only(left, right, **kwargs):
            self.assertTrue(np.isfinite(np.asarray(left)).all())
            self.assertTrue(np.isfinite(np.asarray(right)).all())
            return real_compare(left, right, **kwargs)

        with mock.patch.object(
            diagnose._get_trace(), "compare_aligned_tensor", side_effect=finite_only
        ):
            got = self.compare(pair)
        bad = got["comparisons"]["scene_features"]
        self.assertEqual(got["cell_status"], "INVALID")
        self.assertEqual(bad["nonfinite_count"], 320000)
        self.assertLessEqual(len(bad["nonfinite_locations"]), 128)
        self.assertTrue(bad["nonfinite_truncated"])

    def test_prediction_difference_has_third_a2_classification(self):
        pair = _task5_pair()
        pair[1].outputs["pred_label"][0] = 1
        pair[1].boundary_records["derived"]["pred_label"]["tensor"][0] = 1
        pair[1].boundary_records["derived"]["correct"]["tensor"][0] = False
        _task5_refresh(pair[1])
        got = self.compare(pair)
        self.assertEqual(got["a2_replay_classification"], "DIFFERENT_NUMERIC_BEHAVIOR")
        self.assertEqual(got["canary_status"], "DIFF")

    def test_targeted_model_trace_only_after_equal_cochleagrams(self):
        pair = _task5_pair()
        pair[1].boundary_records["native_logits"]["tensor"][0, 0] += 1
        _task5_refresh(pair[1])
        got = self.compare(pair)
        self.assertEqual(got["first_divergence"], "logits")
        self.assertTrue(got["targeted_trace_required"])
        pair[1].boundary_records["cue_features"]["tensor"][0, 0] += 1
        _task5_refresh(pair[1])
        got = self.compare(pair)
        self.assertEqual(got["first_divergence"], "cochleagram")
        self.assertFalse(got["targeted_trace_required"])

    def test_commitment_tamper_is_invalid_without_resealing(self):
        pair = _task5_pair()
        pair[1].outputs["nll"][0] = 0.01
        self.assertEqual(self.compare(pair)["cell_status"], "INVALID")

    def test_non_tensor_boundary_schema_returns_invalid_instead_of_crashing(self):
        for value in (None, [], "not a tensor"):
            pair = _task5_pair()
            pair[1].boundary_records["scene_features"]["tensor"] = value
            diagnose._bind_pass_commitment(pair[1])
            self.assertEqual(self.compare(pair)["cell_status"], "INVALID")

    def test_matching_but_unfrozen_runtime_is_invalid(self):
        pair = _task5_pair()
        for result in pair:
            result.boundary_records["metadata"]["runtime"]["cuda_matmul_allow_tf32"] = (
                False
            )
            diagnose._bind_pass_commitment(result)
        self.assertEqual(self.compare(pair)["cell_status"], "INVALID")

    def test_derived_official_disagreement_and_guard_dtype_are_invalid(self):
        for alteration in ("derived", "guard", "scalar_shape", "correct_dtype"):
            with self.subTest(alteration=alteration):
                pair = _task5_pair()
                if alteration == "derived":
                    pair[1].boundary_records["derived"]["nll"]["tensor"][0] = 1
                    _task5_refresh(pair[1])
                elif alteration == "guard":
                    guard = pair[1].boundary_records["scene_features"]["guards"][0]
                    guard["before"]["dtype"] = guard["after"]["dtype"] = "torch.int8"
                elif alteration == "scalar_shape":
                    for result in pair:
                        result.boundary_records["derived"]["target_logit"]["tensor"] = (
                            torch.zeros(32, 1)
                        )
                        _task5_refresh(result)
                else:
                    for result in pair:
                        result.boundary_records["derived"]["correct"]["tensor"] = (
                            torch.ones(32, dtype=torch.int64)
                        )
                        _task5_refresh(result)
                for result in pair:
                    diagnose._bind_pass_commitment(result)
                self.assertEqual(self.compare(pair)["cell_status"], "INVALID")


class ArtifactContractTests(unittest.TestCase):
    """Task 5a exact output encoding; publication tests follow in Task 5b."""

    def test_official_output_encoding_roundtrip_preserves_every_bit_and_dtype(self):
        outputs = _task5_pair()[0].outputs
        outputs["nll"][0] = -0.0
        outputs["nll"][1] = np.nextafter(1.0, 2.0)
        outputs["p_target"] = outputs["p_target"].astype(">f4")
        encoded = diagnose.encode_official_outputs(outputs)
        wire = trace.canonical_json_bytes(encoded)
        decoded = diagnose.decode_official_outputs(json.loads(wire))
        for name, expected in outputs.items():
            self.assertEqual(decoded[name].dtype, expected.dtype)
            self.assertEqual(decoded[name].tobytes(), expected.tobytes())
            self.assertFalse(decoded[name].flags.writeable)

    def test_encoder_rejects_object_nonfinite_and_unexpected_field(self):
        for alteration in ("object", "nan", "extra"):
            outputs = _task5_pair()[0].outputs
            if alteration == "object":
                outputs["nll"] = outputs["nll"].astype(object)
            elif alteration == "nan":
                outputs["nll"][0] = np.nan
            else:
                outputs["extra"] = outputs["nll"]
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.encode_official_outputs(outputs)

    def test_decoder_rejects_corruption_noncanonical_hex_shape_and_dtype(self):
        for alteration in ("hash", "payload", "whitespace", "shape", "object", "extra"):
            with self.subTest(alteration=alteration):
                encoded = diagnose.encode_official_outputs(_task5_pair()[0].outputs)
                row = encoded["outputs"]["nll"]
                if alteration == "hash":
                    row["sha256"] = "f" * 64
                elif alteration == "payload":
                    row["bytes_hex"] = "f" + row["bytes_hex"][1:]
                elif alteration == "whitespace":
                    row["bytes_hex"] += " "
                elif alteration == "shape":
                    row["shape"] = [16, 2]
                elif alteration == "object":
                    row["dtype"] = "|O"
                else:
                    row["extra"] = "unreviewed"
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose.decode_official_outputs(encoded)

    def test_decoder_checks_bound_before_fromhex_or_numpy_allocation(self):
        encoded = diagnose.encode_official_outputs(_task5_pair()[0].outputs)
        encoded["outputs"]["nll"]["shape"] = [2**60]
        with mock.patch.object(
            np, "frombuffer", side_effect=AssertionError("allocation reached")
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.decode_official_outputs(encoded)


class ArtifactPublicationTests(unittest.TestCase):
    """Task 5b storage kernel; no worker or completion-marker claims."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.root = self.base / "attempts" / "slurm-123"
        self.root.mkdir(parents=True)
        self.rel = "cells/A2/LOGITS_PASS1.npy"

    def store(self):
        return diagnose._AttemptArtifactStore(self.root)

    def test_npy_fixed_header_native_bits_and_single_link(self):
        expected = np.arange(32 * 800, dtype=">f4").reshape(32, 800)
        expected[0, 0] = -0.0
        with self.store() as store:
            record = store.publish_npy(self.rel, expected)
            self.assertEqual(store.record(self.rel), record)
        path = self.root / self.rel
        self.assertEqual(path.read_bytes()[:8], b"\x93NUMPY\x01\x00")
        loaded = np.load(path, allow_pickle=False)
        self.assertEqual(loaded.dtype, expected.dtype)
        self.assertEqual(loaded.tobytes(), expected.tobytes())
        self.assertEqual(record["size"], path.stat().st_size)
        self.assertEqual(
            record["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(any(p.name.endswith(".partial") for p in self.root.rglob("*")))

    def test_noncontiguous_npy_is_c_order_and_projection_includes_header(self):
        value = np.arange(800 * 32, dtype=np.float64).reshape(800, 32).T
        with self.store() as store:
            record = store.publish_npy(self.rel, value)
        self.assertEqual(record["size"], diagnose._npy_projected_size(value))
        self.assertGreater(record["size"], value.nbytes)
        self.assertEqual(
            np.load(self.root / self.rel).tobytes(), value.tobytes(order="C")
        )

    def test_projection_does_not_materialize_large_broadcast_array(self):
        value = np.broadcast_to(np.array(1, dtype=np.uint8), (2**40,))
        with mock.patch.object(
            np, "ascontiguousarray", side_effect=AssertionError("copied")
        ):
            self.assertGreater(diagnose._npy_projected_size(value), 2**40)

    def test_reject_unsupported_dtype_and_wrong_logits_shape_before_writing(self):
        for value in (
            np.zeros((32, 800), dtype=object),
            np.zeros((32, 800), dtype="U1"),
            np.zeros((32, 800), dtype=[("x", "i4")]),
            np.zeros((1, 800)),
            np.zeros((32, 800), dtype=np.complex64),
        ):
            with (
                self.subTest(dtype=value.dtype, shape=value.shape),
                self.store() as store,
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.publish_npy(self.rel, value)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fixed_namespace_rejects_escapes_and_unknown_targets(self):
        with self.store() as store:
            for name in (
                "../escape",
                "/tmp/escape",
                "cells/A3/x.npy",
                "cells/A2/../A1/LOGITS_PASS1.npy",
                "cells/A2/extra.npy",
                "cells/A2/WORST_CASES/unknown.pass1.npy",
                "state/SMOKE_PASS.json",
            ):
                with (
                    self.subTest(name=name),
                    self.assertRaises(diagnose.DiagnosticError),
                ):
                    store.publish_bytes(name, b"unapproved")

    def test_existing_target_and_racing_target_are_never_overwritten(self):
        value = np.zeros((32, 800), dtype=np.float32)
        with self.store() as store:
            store.publish_npy(self.rel, value)
            with self.assertRaises((FileExistsError, diagnose.DiagnosticError)):
                store.publish_npy(self.rel, value + 1)
            target = self.root / "cells/A2/LOGITS_PASS2.npy"
            link = os.link

            def race(source, dest, **kwargs):
                target.write_bytes(b"race winner")
                return link(source, dest, **kwargs)

            with mock.patch.object(diagnose.os, "link", side_effect=race):
                with self.assertRaises((FileExistsError, diagnose.DiagnosticError)):
                    store.publish_npy("cells/A2/LOGITS_PASS2.npy", value)
            self.assertEqual(target.read_bytes(), b"race winner")
        self.assertFalse(any(p.name.endswith(".partial") for p in self.root.rglob("*")))

    def test_root_and_ancestor_symlink_are_rejected(self):
        link = self.base / "alias"
        link.symlink_to(self.base, target_is_directory=True)
        for path in (link / "attempts" / "slurm-123",):
            with self.assertRaises(diagnose.DiagnosticError):
                with diagnose._AttemptArtifactStore(path):
                    pass
        moved = self.root.with_name("old")
        self.root.rename(moved)
        self.root.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(diagnose.DiagnosticError):
            with self.store():
                pass

    def test_symlink_child_cannot_redirect_a_write(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "cells").symlink_to(outside, target_is_directory=True)
        with self.store() as store, self.assertRaises(diagnose.DiagnosticError):
            store.publish_npy(self.rel, np.zeros((32, 800), dtype=np.float32))
        self.assertEqual(list(outside.iterdir()), [])

    def test_namespace_replacement_during_link_fails_without_redirect(self):
        link = os.link
        outside = self.base / "outside"
        outside.mkdir()

        def replace(source, dest, **kwargs):
            cell = self.root / "cells/A2"
            cell.rename(cell.with_name("moved"))
            cell.symlink_to(outside, target_is_directory=True)
            return link(source, dest, **kwargs)

        with (
            self.store() as store,
            mock.patch.object(diagnose.os, "link", side_effect=replace),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                store.publish_npy(self.rel, np.zeros((32, 800), dtype=np.float32))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.root / "cells/moved/CELL_COMPLETE.json").exists())

    def test_same_bytes_replacement_after_link_is_not_accepted_as_own_publication(self):
        unlink = os.unlink

        def replace_after_unlink(name, *args, **kwargs):
            answer = unlink(name, *args, **kwargs)
            if str(name).endswith(".partial"):
                target = self.root / self.rel
                payload = target.read_bytes()
                replacement = target.with_name("swap")
                replacement.write_bytes(payload)
                replacement.chmod(0o600)
                os.replace(replacement, target)
            return answer

        with (
            self.store() as store,
            mock.patch.object(diagnose.os, "unlink", side_effect=replace_after_unlink),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                store.publish_npy(self.rel, np.zeros((32, 800), dtype=np.float32))

    def test_streamed_record_rejects_hardlink_mode_and_in_read_replacement(self):
        with self.store() as store:
            record = store.publish_bytes("reference_cold/RUNTIME.json", b"{}\n")
            path = self.root / "reference_cold/RUNTIME.json"
            alias = path.with_name("alias")
            os.link(path, alias)
            with self.assertRaises(diagnose.DiagnosticError):
                store.record("reference_cold/RUNTIME.json")
            alias.unlink()
            path.chmod(0o644)
            with self.assertRaises(diagnose.DiagnosticError):
                store.record("reference_cold/RUNTIME.json")
            path.chmod(0o600)
            read = os.read
            changed = False

            def replace(fd, count):
                nonlocal changed
                answer = read(fd, count)
                if not changed:
                    changed = True
                    alias.write_bytes(b"{}\n")
                    alias.chmod(0o600)
                    os.replace(alias, path)
                return answer

            with mock.patch.object(diagnose.os, "read", side_effect=replace):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.record("reference_cold/RUNTIME.json")
            portable = dict(record, st_dev=-1, st_ino=-1, st_mtime_ns=-1)
            self.assertEqual(store.verify_record(portable)["sha256"], record["sha256"])

    def test_streamed_hash_reads_bounded_chunks_without_read_bytes(self):
        read = os.read
        sizes = []

        def observe(fd, count):
            sizes.append(count)
            return read(fd, count)

        with (
            self.store() as store,
            mock.patch.object(
                pathlib.Path, "read_bytes", side_effect=AssertionError("whole file")
            ),
        ):
            with mock.patch.object(diagnose.os, "read", side_effect=observe):
                store.publish_npy(self.rel, np.zeros((32, 800), dtype=np.float64))
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 1 << 20)

    def test_failures_preserve_no_final_and_cleanup_own_private_file(self):
        for operation in ("write", "fsync", "link"):
            with self.subTest(operation=operation), self.store() as store:
                with mock.patch.object(
                    diagnose.os, operation, side_effect=OSError("injected")
                ):
                    with self.assertRaises((OSError, diagnose.DiagnosticError)):
                        store.publish_npy(
                            self.rel, np.zeros((32, 800), dtype=np.float32)
                        )
                self.assertFalse((self.root / self.rel).exists())
                self.assertFalse(
                    any(p.name.endswith(".partial") for p in self.root.rglob("*"))
                )

    def test_exact_inventory_rejects_extra_empty_directory_and_payload_corruption(self):
        with self.store() as store:
            record = store.publish_bytes("reference_cold/RUNTIME.json", b"{}\n")
            store.verify_inventory("reference_cold", [record], directories=())
            extra = self.root / "reference_cold/empty"
            extra.mkdir()
            with self.assertRaises(diagnose.DiagnosticError):
                store.verify_inventory("reference_cold", [record], directories=())
            extra.rmdir()
            (self.root / "reference_cold/RUNTIME.json").write_bytes(b"[]\n")
            with self.assertRaises(diagnose.DiagnosticError):
                store.verify_inventory("reference_cold", [record], directories=())

    def test_worst_global_count_includes_all_cells_and_all_npy_headers(self):
        trio = {
            f"scene_features.{suffix}.npy": np.zeros(3, dtype=dtype)
            for suffix, dtype in (
                ("pass1", np.float32),
                ("pass2", np.float32),
                ("difference", np.float64),
            )
        }
        with self.store() as store:
            first = store.publish_worst_cases("A1", trio)
            second = store.publish_worst_cases("B2", trio)
            self.assertEqual(
                store.worst_case_bytes(), sum(x["size"] for x in first + second)
            )
            self.assertGreater(
                store.worst_case_bytes(), 2 * sum(x.nbytes for x in trio.values())
            )

    def test_global_cap_exact_equality_and_one_byte_over_before_first_writer(self):
        trio = {
            f"cue_features.{suffix}.npy": np.zeros(3, dtype=dtype)
            for suffix, dtype in (
                ("pass1", np.float32),
                ("pass2", np.float32),
                ("difference", np.float64),
            )
        }
        projected = sum(diagnose._npy_projected_size(x) for x in trio.values())
        with self.store() as store:
            for extra in (0, 1):
                with mock.patch.object(
                    store,
                    "worst_case_bytes",
                    return_value=1073741824 - projected + extra,
                ):
                    with mock.patch.object(
                        store, "publish_npy", return_value={}
                    ) as writer:
                        if extra:
                            with self.assertRaises(diagnose.DiagnosticError):
                                store.publish_worst_cases("A2", trio)
                            writer.assert_not_called()
                        else:
                            store.publish_worst_cases("A2", trio)
                            self.assertEqual(writer.call_count, 3)

    def test_worst_case_rejects_incomplete_trio_and_wrong_difference_dtype(self):
        with self.store() as store:
            for arrays in (
                {"scene_features.pass1.npy": np.zeros(3)},
                {
                    f"cue_features.{s}.npy": np.zeros(3, dtype=np.float32)
                    for s in ("pass1", "pass2", "difference")
                },
            ):
                with mock.patch.object(store, "publish_npy") as writer:
                    with self.assertRaises(diagnose.DiagnosticError):
                        store.publish_worst_cases("A2", arrays)
                    writer.assert_not_called()

    def test_public_npy_entrypoint_is_fixed_to_diagnostic_attempt_namespace(self):
        with mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.base):
            record = diagnose.write_npy_create_once(
                self.root / self.rel, np.zeros((32, 800), dtype=np.float32)
            )
            self.assertEqual(record["relative_path"], self.rel)
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.write_npy_create_once(self.base / "outside.npy", np.zeros(3))

    def test_standalone_worst_writer_cannot_bypass_global_budget(self):
        target = "cells/A2/WORST_CASES/scene_features.pass1.npy"
        with self.store() as store:
            with self.assertRaises(diagnose.DiagnosticError):
                store.publish_npy(target, np.zeros(3))
            with self.assertRaises(diagnose.DiagnosticError):
                store.publish_bytes(target, b"not an NPY")
        with mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.base):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.write_npy_create_once(self.root / target, np.zeros(3))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fifo_replacement_cannot_block_record_open(self):
        with self.store() as store:
            store.publish_bytes("reference_cold/RUNTIME.json", b"{}\n")
            path = self.root / "reference_cold/RUNTIME.json"
            open_fd = os.open

            def replace(name, flags, *args, **kwargs):
                if name == "RUNTIME.json":
                    self.assertTrue(
                        flags & os.O_NONBLOCK, "FIFO replacement could block read"
                    )
                    path.unlink()
                    os.mkfifo(path, 0o600)
                return open_fd(name, flags, *args, **kwargs)

            with mock.patch.object(diagnose.os, "open", side_effect=replace):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.record("reference_cold/RUNTIME.json")

    def test_file_descriptor_closed_if_ancestor_fstat_fails(self):
        open_fd, fstat_fd = os.open, os.fstat
        descriptors = []

        def observe(*args, **kwargs):
            fd = open_fd(*args, **kwargs)
            descriptors.append(fd)
            return fd

        with mock.patch.object(diagnose.os, "open", side_effect=observe):
            with mock.patch.object(
                diagnose.os, "fstat", side_effect=OSError("injected fstat")
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    with self.store():
                        pass
        leaked = []
        for fd in descriptors:
            try:
                fstat_fd(fd)
                leaked.append(fd)
            except OSError:
                pass
        for fd in leaked:
            os.close(fd)
        self.assertEqual(leaked, [])

    def test_partial_os_writes_and_private_name_replacement(self):
        write = os.write
        with self.store() as store:
            with mock.patch.object(
                diagnose.os, "write", side_effect=lambda fd, data: write(fd, data[:7])
            ):
                result = store.publish_bytes("reference_cold/RUNTIME.json", b"x" * 100)
            self.assertEqual(result["size"], 100)
            fsync = os.fsync
            foreign = []

            def replace_private(fd):
                fsync(fd)
                pending = list((self.root / "cells/A2").glob("*.partial"))
                if pending:
                    pending[0].unlink()
                    pending[0].write_bytes(b"foreign replacement")
                    foreign.append(pending[0])

            with mock.patch.object(diagnose.os, "fsync", side_effect=replace_private):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.publish_npy(self.rel, np.zeros((32, 800)))
            self.assertEqual(len(foreign), 1)
            self.assertEqual(foreign[0].read_bytes(), b"foreign replacement")
            self.assertFalse((self.root / self.rel).exists())

    def test_inventory_detects_ancestor_swap_and_late_extra_directory(self):
        with self.store() as store:
            record = store.publish_bytes("reference_cold/RUNTIME.json", b"{}\n")
            verify = store.verify_record

            def extra(expected):
                actual = verify(expected)
                (self.root / "reference_cold/late").mkdir()
                return actual

            with mock.patch.object(store, "verify_record", side_effect=extra):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.verify_inventory("reference_cold", [record], directories=())
            moved = self.root.with_name("old-attempt")
            self.root.rename(moved)
            self.root.mkdir()
            with self.assertRaises(diagnose.DiagnosticError):
                store.verify_record(record)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_worst_budget_rejects_symlink_hardlink_and_extra_directory(self):
        worst = self.root / "cells/A1/WORST_CASES"
        worst.mkdir(parents=True)
        target = worst / "scene_features.pass1.npy"
        target.write_bytes(b"bytes counted even if from incomplete evidence")
        target.chmod(0o600)
        alias = self.base / "linked"
        with self.store() as store:
            os.link(target, alias)
            with self.assertRaises(diagnose.DiagnosticError):
                store.worst_case_bytes()
            alias.unlink()
            target.unlink()
            target.symlink_to(self.base / "missing")
            with self.assertRaises(diagnose.DiagnosticError):
                store.worst_case_bytes()
            target.unlink()
            (worst / "empty").mkdir()
            with self.assertRaises(diagnose.DiagnosticError):
                store.worst_case_bytes()


def _task5_artifact_result(cell="A2", *, reference=False):
    pair = _task5_pair(cell)
    if reference:
        for item in pair:
            item.boundary_records["metadata"].update(
                role="REFERENCE_COLD",
                path="frozen_predict_batch",
                autocast_enabled=None,
            )
            for name in tuple(diagnose._TRACE_BOUNDARIES):
                if name not in {"raw_scene", "raw_cue"}:
                    del item.boundary_records[name]
            item.boundary_records["derived"] = {
                "correct": item.boundary_records["derived"]["correct"]
            }
            diagnose._bind_pass_commitment(item)
    rows = pair[0].boundary_records["metadata"]["trial_bank_rows"]
    trials = tuple(
        diagnose.TrialSpec(
            i,
            row["trial_id"],
            row["bank_row_index"],
            {"trial_id": row["trial_id"], "target_label": 0},
        )
        for i, row in enumerate(rows)
    )
    return {
        "trials": trials,
        "passes": tuple(pair),
        "spec": None if reference else diagnose.CELL_SPECS[cell],
        "input_freeze_sha256": "d" * 64,
    }


class ChildArtifactTests(unittest.TestCase):
    """Task 5b: full child evidence, not subprocess-origin authentication."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.root = self.base / "attempts/slurm-123"
        self.root.mkdir(parents=True)
        patcher = mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.base)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, result):
        if result["spec"] is None:
            return diagnose.write_reference_artifacts(
                self.root / "reference_cold", result
            )
        return diagnose.write_cell_artifacts(
            self.root / "cells" / result["spec"].cell_id, result
        )

    def verify(self, receipt, *, reference=False):
        path = self.root / ("reference_cold" if reference else "cells/A2")
        function = (
            diagnose.verify_reference_artifacts
            if reference
            else diagnose.verify_cell_artifacts
        )
        return function(
            path,
            expected_marker=receipt["marker_record"],
            expected_input_freeze_sha256="d" * 64,
        )

    def test_pass_commitment_and_exact_outputs_roundtrip_without_fake_tensors(self):
        item = _task5_pair()[0]
        item.outputs["nll"][0] = -0.0
        item.boundary_records["derived"]["nll"]["tensor"][0] = -0.0
        _task5_refresh(item)
        encoded = diagnose.encode_pass_evidence(item)
        decoded = diagnose.decode_pass_evidence(
            json.loads(trace.canonical_json_bytes(encoded))
        )
        self.assertEqual(decoded["payload"], diagnose._pass_commitment_payload(item))
        self.assertEqual(
            decoded["outputs"]["nll"].tobytes(), item.outputs["nll"].tobytes()
        )
        self.assertFalse(decoded["outputs"]["nll"].flags.writeable)
        self.assertIsInstance(
            decoded["payload"]["boundaries"]["raw_scene"]["tensor"], dict
        )
        self.assertEqual(
            encoded["commitment"], dict(item.boundary_records["pass_commitment"])
        )

    def test_pass_codec_rejects_binding_and_output_corruption(self):
        import copy

        item = _task5_pair()[0]
        encoded = diagnose.encode_pass_evidence(item)
        for case in ("commitment", "output", "raw", "trial"):
            changed = copy.deepcopy(encoded)
            if case == "commitment":
                changed["commitment"]["binding_sha256"] = "e" * 64
            elif case == "output":
                changed["official_outputs"] = diagnose.encode_official_outputs(
                    {**item.outputs, "nll": np.ones(32)}
                )
            elif case == "raw":
                changed["payload"]["boundaries"]["raw_scene"]["per_trial"][0][
                    "sha256"
                ] = "e" * 64
            else:
                changed["payload"]["trial_ids"][1] = changed["payload"]["trial_ids"][0]
            with self.subTest(case=case), self.assertRaises(diagnose.DiagnosticError):
                diagnose.decode_pass_evidence(changed)
        item.outputs["nll"][0] = 1
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.encode_pass_evidence(item)

    def test_complete_cell_inventory_marker_last_and_self_excluded(self):
        events = []
        publish = diagnose._AttemptArtifactStore._publish

        def observe(store, relative, *args):
            events.append(relative)
            return publish(store, relative, *args)

        with mock.patch.object(diagnose._AttemptArtifactStore, "_publish", new=observe):
            receipt = self.write(_task5_artifact_result())
        self.assertEqual(events[-1], "cells/A2/CELL_COMPLETE.json")
        marker = json.loads((self.root / events[-1]).read_bytes())
        names = {x["relative_path"] for x in marker["artifacts"]}
        self.assertNotIn(events[-1], names)
        expected = {
            "cells/A2/" + x
            for x in diagnose._CELL_ARTIFACT_NAMES
            if x != "CELL_COMPLETE.json"
        }
        self.assertTrue(expected.issubset(names))
        self.assertEqual(marker["directories"], ["WORST_CASES"])
        self.assertEqual(marker["cell_status"], "PASS")
        verified = self.verify(receipt)
        self.assertEqual(verified["status"], "ARTIFACTS_VERIFIED")
        self.assertEqual(
            verified["marker_record"]["sha256"], receipt["marker_record"]["sha256"]
        )

    def test_reference_inventory_contains_exact_raw_and_official_evidence_only(self):
        data = _task5_artifact_result(reference=True)
        receipt = self.write(data)
        verified = self.verify(receipt, reference=True)
        root = self.root / "reference_cold"
        self.assertEqual(
            {p.name for p in root.iterdir()}, set(diagnose._REFERENCE_ARTIFACT_NAMES)
        )
        marker = json.loads((root / "REFERENCE_COMPLETE.json").read_bytes())
        for forbidden in ("cell_status", "canary_status", "a2_replay_classification"):
            self.assertNotIn(forbidden, marker)
        self.assertEqual(marker["directories"], [])
        first = verified["inputs"]["passes"][0]
        self.assertEqual(
            first["payload"]["boundaries"]["raw_scene"]["per_trial"],
            data["passes"][0].boundary_records["raw_scene"]["per_trial"],
        )
        self.assertNotIn("native_logits", first["payload"]["boundaries"])

    def test_diff_and_fully_recorded_invalid_are_distinct_complete_cells(self):
        for case in ("diff", "invalid"):
            data = _task5_artifact_result()
            second = data["passes"][1]
            if case == "diff":
                second.outputs["nll"][0] = 0.0077362060546875
                second.boundary_records["derived"]["nll"]["tensor"][0] = (
                    0.0077362060546875
                )
                _task5_refresh(second)
            else:
                guard = second.boundary_records["scene_features"]["guards"][0]
                guard["after"]["version"] += 1
                diagnose._bind_pass_commitment(second)
            with self.subTest(case=case):
                # Separate immutable attempt per case; do not overwrite a previous result.
                self.root = (
                    self.base / f"attempts/slurm-{124 if case == 'diff' else 125}"
                )
                self.root.mkdir()
                receipt = self.write(data)
                verified = self.verify(receipt)
                self.assertEqual(
                    verified["comparison"]["cell_status"],
                    "DIFF" if case == "diff" else "INVALID",
                )
                self.assertEqual(
                    verified["comparison"]["canary_status"],
                    "DIFF" if case == "diff" else None,
                )

    def test_between_discontinuity_preserves_both_observations(self):
        data = _task5_artifact_result()
        data["passes"][1].model_snapshots["before"][0]["sha256"] = "f" * 64
        diagnose._bind_pass_commitment(data["passes"][1])
        receipt = self.write(data)
        self.assertEqual(self.verify(receipt)["comparison"]["cell_status"], "INVALID")
        records = [
            json.loads(line)
            for line in (self.root / "cells/A2/STATE_BETWEEN.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual(
            {row["observation"] for row in records}, {"pass1_after", "pass2_before"}
        )

    def test_worst_selection_matches_frozen_trial_after_reverse_pass_order(self):
        data = _task5_artifact_result()
        second = data["passes"][1]
        second.boundary_records["scene_features"]["tensor"][7, 1] += 2
        order = list(reversed(range(32)))
        second.trial_ids = tuple(second.trial_ids[i] for i in order)
        second.outputs = {k: v[order].copy() for k, v in second.outputs.items()}
        for name in diagnose._TRACE_BOUNDARIES:
            second.boundary_records[name]["tensor"] = second.boundary_records[name][
                "tensor"
            ][order]
        for record in second.boundary_records["derived"].values():
            record["tensor"] = record["tensor"][order]
        metadata = second.boundary_records["metadata"]
        metadata["trial_bank_rows"] = [metadata["trial_bank_rows"][i] for i in order]
        metadata["bank_row_indices"] = [
            row["bank_row_index"] for row in metadata["trial_bank_rows"]
        ]
        _task5_refresh(second)
        receipt = self.write(data)
        selection = self.verify(receipt)["comparison"]["worst_cases"]["scene_features"]
        self.assertEqual(selection["trial_id"], 107)
        worst = self.root / "cells/A2/WORST_CASES"
        self.assertEqual(np.load(worst / "scene_features.difference.npy")[1], 2)

    def test_coch_trios_always_and_logits_trio_when_targeted(self):
        data = _task5_artifact_result()
        data["passes"][1].boundary_records["native_logits"]["tensor"][2, 4] += 1
        _task5_refresh(data["passes"][1])
        verified = self.verify(self.write(data))
        self.assertTrue(verified["comparison"]["targeted_trace_required"])
        files = {p.name for p in (self.root / "cells/A2/WORST_CASES").iterdir()}
        self.assertEqual(
            files,
            {
                f"{b}.{s}.npy"
                for b in ("scene_features", "cue_features", "native_logits")
                for s in ("pass1", "pass2", "difference")
            },
        )

    def test_partial_publication_never_creates_a_complete_marker(self):
        publish = diagnose._AttemptArtifactStore.publish_bytes

        def fail(store, relative, payload):
            if relative.endswith("RUNTIME.json"):
                raise OSError("injected payload write failure")
            return publish(store, relative, payload)

        with mock.patch.object(
            diagnose._AttemptArtifactStore, "publish_bytes", new=fail
        ):
            with self.assertRaises(OSError):
                self.write(_task5_artifact_result())
        self.assertFalse((self.root / "cells/A2/CELL_COMPLETE.json").exists())
        self.assertTrue((self.root / "cells/A2/CELL_INPUTS.json").exists())

    def test_corruption_between_publication_and_inventory_blocks_marker(self):
        publish = diagnose._AttemptArtifactStore.publish_bytes

        def corrupt(store, relative, payload):
            record = publish(store, relative, payload)
            if relative.endswith("RUNTIME.json"):
                (store.root / relative).write_bytes(b"{}\n")
            return record

        with mock.patch.object(
            diagnose._AttemptArtifactStore, "publish_bytes", new=corrupt
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                self.write(_task5_artifact_result())
        self.assertFalse((self.root / "cells/A2/CELL_COMPLETE.json").exists())

    def test_verifier_rejects_missing_extra_linked_or_corrupt_reference_file(self):
        for index, case in enumerate(
            ("missing", "extra_dir", "symlink", "hardlink", "corrupt"), 130
        ):
            self.root = self.base / f"attempts/slurm-{index}"
            self.root.mkdir()
            receipt = self.write(_task5_artifact_result(reference=True))
            path = self.root / "reference_cold/RUNTIME.json"
            if case == "missing":
                path.unlink()
            elif case == "extra_dir":
                (path.parent / "extra").mkdir()
            elif case == "symlink":
                path.rename(path.with_name("original"))
                path.symlink_to("original")
            elif case == "hardlink":
                os.link(path, self.root / "alias")
            else:
                path.write_bytes(b"{}\n")
            with self.subTest(case=case), self.assertRaises(diagnose.DiagnosticError):
                self.verify(receipt, reference=True)

    def test_verifier_rejects_wrong_out_of_band_marker_and_freeze(self):
        receipt = self.write(_task5_artifact_result())
        changed = {
            **receipt,
            "marker_record": {**receipt["marker_record"], "sha256": "e" * 64},
        }
        with self.assertRaises(diagnose.DiagnosticError):
            self.verify(changed)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.verify_cell_artifacts(
                self.root / "cells/A2",
                expected_marker=receipt["marker_record"],
                expected_input_freeze_sha256="e" * 64,
            )

    def test_full_verification_is_read_only(self):
        receipt = self.write(_task5_artifact_result())
        before = trace.fingerprint_tree(self.root)
        self.verify(receipt)
        self.assertEqual(trace.fingerprint_tree(self.root), before)

    def test_rerun_cannot_replace_previous_complete_artifacts(self):
        data = _task5_artifact_result()
        self.write(data)
        before = trace.fingerprint_tree(self.root)
        with self.assertRaises((diagnose.DiagnosticError, FileExistsError)):
            self.write(data)
        self.assertEqual(trace.fingerprint_tree(self.root), before)

    def test_same_byte_marker_swap_during_verification_is_rejected(self):
        receipt = self.write(_task5_artifact_result())
        original = diagnose._child_views
        swapped = False

        def swap(inputs):
            nonlocal swapped
            if not swapped:
                swapped = True
                marker = self.root / "cells/A2/CELL_COMPLETE.json"
                replacement = marker.with_name("swap")
                replacement.write_bytes(marker.read_bytes())
                replacement.chmod(0o600)
                os.replace(replacement, marker)
            return original(inputs)

        with mock.patch.object(diagnose, "_child_views", side_effect=swap):
            with self.assertRaises(diagnose.DiagnosticError):
                self.verify(receipt)

    def test_same_byte_payload_swap_before_marker_is_rejected(self):
        original = diagnose._AttemptArtifactStore.publish_bytes

        def swap(store, relative, payload):
            record = original(store, relative, payload)
            if relative.endswith("RUNTIME.json"):
                target = store.root / relative
                replacement = target.with_name("swap")
                replacement.write_bytes(target.read_bytes())
                replacement.chmod(0o600)
                os.replace(replacement, target)
            return record

        with mock.patch.object(
            diagnose._AttemptArtifactStore, "publish_bytes", new=swap
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                self.write(_task5_artifact_result())
        self.assertFalse((self.root / "cells/A2/CELL_COMPLETE.json").exists())

    def test_reference_real_task4_passes_persist_without_trace_or_reinference(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        trials = _task4_trials(bank)
        with _task4_hermetic_worker_context(evaluator, scene_api) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            run = {
                **context,
                **prepared,
                "bank": bank,
                "clips_dir": pathlib.Path("/clips"),
                "historical_scene_hashes": _task4_scene_hashes(bank),
                "scratch_root": "/scratch/reference",
                "cache_roots": {},
            }
            first = diagnose.run_reference_pass(run, trials, "pass1", 16)
            second = diagnose.run_reference_pass(run, trials, "pass2", 1)
        result = {
            "trials": trials,
            "passes": (first, second),
            "spec": None,
            "input_freeze_sha256": "d" * 64,
        }
        with mock.patch.object(
            diagnose, "run_reference_pass", side_effect=AssertionError("rerun")
        ):
            with mock.patch.object(
                diagnose, "run_trace_pass", side_effect=AssertionError("trace")
            ):
                receipt = self.write(result)
                self.assertEqual(
                    self.verify(receipt, reference=True)["status"], "ARTIFACTS_VERIFIED"
                )
        self.assertEqual(len(evaluator.load_calls), 1)

    def test_nonfinite_coch_evidence_persists_as_invalid_with_no_numeric_success(self):
        data = _task5_artifact_result()
        data["passes"][1].boundary_records["scene_features"]["tensor"][4, 0] = float(
            "nan"
        )
        _task5_refresh(data["passes"][1])
        verified = self.verify(self.write(data))
        self.assertEqual(verified["comparison"]["cell_status"], "INVALID")
        self.assertIsNone(verified["comparison"]["canary_status"])
        self.assertEqual(
            verified["comparison"]["worst_cases"]["scene_features"]["trial_id"], 104
        )

    def test_npy_header_cannot_trigger_unbounded_allocation_after_record_update(self):
        import io

        receipt = self.write(_task5_artifact_result())
        logits = self.root / "cells/A2/LOGITS_PASS1.npy"
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            header, {"descr": "<f4", "fortran_order": False, "shape": (2**60, 800)}
        )
        logits.write_bytes(header.getvalue())
        marker_path = self.root / "cells/A2/CELL_COMPLETE.json"
        marker = json.loads(marker_path.read_bytes())
        with diagnose._AttemptArtifactStore(self.root) as store:
            marker["artifacts"] = [
                store.record(r["relative_path"])
                if r["relative_path"].endswith("LOGITS_PASS1.npy")
                else r
                for r in marker["artifacts"]
            ]
            marker_path.write_bytes(trace.canonical_json_bytes(marker))
            receipt["marker_record"] = store.record("cells/A2/CELL_COMPLETE.json")
        with mock.patch.object(
            np, "load", side_effect=AssertionError("allocation reached")
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                self.verify(receipt)

    def test_canary_is_recomputed_from_lossless_outputs_not_just_marker_status(self):
        receipt = self.write(_task5_artifact_result())
        root = self.root / "cells/A2"
        comparison_path = root / "COMPARISON.json"
        comparison = json.loads(comparison_path.read_bytes())
        comparison.update(
            cell_status="DIFF",
            canary_status="DIFF",
            nll_max_abs=0.0077362060546875,
            a2_replay_classification="REPRODUCED",
        )
        comparison_path.write_bytes(trace.canonical_json_bytes(comparison))
        marker_path = root / "CELL_COMPLETE.json"
        marker = json.loads(marker_path.read_bytes())
        marker.update(
            {
                k: comparison[k]
                for k in ("cell_status", "canary_status", "a2_replay_classification")
            }
        )
        with diagnose._AttemptArtifactStore(self.root) as store:
            marker["artifacts"] = [
                store.record(r["relative_path"])
                if r["relative_path"].endswith("COMPARISON.json")
                else r
                for r in marker["artifacts"]
            ]
            marker_path.write_bytes(trace.canonical_json_bytes(marker))
            receipt["marker_record"] = store.record("cells/A2/CELL_COMPLETE.json")
        with self.assertRaises(diagnose.DiagnosticError):
            self.verify(receipt)

    def test_real_task4_trace_passes_persist_without_reinference(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        trials = _task4_trials(bank)
        with _task4_hermetic_worker_context(evaluator, scene_api) as context:
            prepared = diagnose.prepare_formal40_worker(context, allow_cpu=True)
            run = {
                **context,
                **prepared,
                "bank": bank,
                "cell_id": "B1",
                "clips_dir": pathlib.Path("/clips"),
                "historical_scene_hashes": _task4_scene_hashes(bank),
                "cache_roots": {},
                "scratch_root": "/scratch/B1",
            }
            first = diagnose.run_trace_pass(
                run, trials, "pass1", 16, False, pathlib.Path("/scratch/B1")
            )
            second = diagnose.run_trace_pass(
                run, trials, "pass2", 16, False, pathlib.Path("/scratch/B1")
            )
        result = {
            "trials": trials,
            "passes": (first, second),
            "spec": diagnose.CELL_SPECS["B1"],
            "input_freeze_sha256": "d" * 64,
        }
        with mock.patch.object(
            diagnose, "run_trace_pass", side_effect=AssertionError("reinference")
        ):
            receipt = self.write(result)
            got = diagnose.verify_cell_artifacts(
                self.root / "cells/B1",
                expected_marker=receipt["marker_record"],
                expected_input_freeze_sha256="d" * 64,
            )
        self.assertEqual(got["comparison"]["cell_status"], "PASS")
        self.assertEqual(len(evaluator.load_calls), 1)

    def test_legitimate_rng_movement_and_rng_gap_are_not_conflated(self):
        import copy

        with mock.patch.object(
            random, "getstate", return_value=("changed RNG fixture",)
        ):
            changed = trace.snapshot_rng_state()
        for index, gap in enumerate((False, True), 160):
            self.root = self.base / f"attempts/slurm-{index}"
            self.root.mkdir()
            data = _task5_artifact_result()
            data["passes"][0].rng_snapshots["after"] = copy.deepcopy(changed)
            if not gap:
                data["passes"][1].rng_snapshots = {
                    "before": copy.deepcopy(changed),
                    "after": copy.deepcopy(changed),
                }
            for item in data["passes"]:
                diagnose._bind_pass_commitment(item)
            got = self.verify(self.write(data))
            self.assertEqual(
                got["comparison"]["cell_status"], "INVALID" if gap else "PASS"
            )
            between = json.loads((self.root / "cells/A2/RNG_BETWEEN.json").read_bytes())
            self.assertEqual(len(between["observations"]), 2 if gap else 1)

    def test_selected_worst_tensor_must_reach_reported_boundary_maximum(self):
        data = _task5_artifact_result()
        data["passes"][1].boundary_records["scene_features"]["tensor"][7, 1] += 2
        _task5_refresh(data["passes"][1])
        select = diagnose._select_child_worst

        def wrong_trial(result, comparison):
            arrays, selections = select(result, comparison)
            selections["scene_features"].update(
                trial_id=100, ordinal=0, pass1_index=0, pass2_index=0
            )
            for index in (1, 2):
                arrays[f"scene_features.pass{index}.npy"] = (
                    result["passes"][index - 1]
                    .boundary_records["scene_features"]["tensor"][0]
                    .numpy()
                )
            arrays["scene_features.difference.npy"] = np.zeros(3, dtype=np.float64)
            return arrays, selections

        with mock.patch.object(
            diagnose, "_select_child_worst", side_effect=wrong_trial
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                self.write(data)
        self.assertFalse((self.root / "cells/A2/CELL_COMPLETE.json").exists())


class WorkerLifecycleTests(unittest.TestCase):
    """Task 5c worker seams; hermetic CPU is never a production fallback."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.diag_root = self.base / "diagnostic"
        self.attempt = self.diag_root / "attempts/slurm-123"
        self.attempt.mkdir(parents=True, mode=0o700)
        self.scratch_base = self.base / "audattn_v4_numdiag_123"
        self.scratch_base.mkdir(mode=0o700)
        self.args = types.SimpleNamespace(
            job_id="123", expected_input_freeze_sha256="d" * 64
        )
        patcher = mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.diag_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def environment(self, role="B1"):
        root = self.scratch_base / role
        env = {
            "SLURM_JOB_ID": "123",
            "DIAG_SCRATCH_ROOT": str(self.scratch_base),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
        }
        paths = {
            "HOME": "home",
            "XDG_CACHE_HOME": "xdg",
            "TORCH_HOME": "torch-home",
            "TMPDIR": "tmp",
            "TMP": "tmp",
            "TEMP": "tmp",
            "MPLCONFIGDIR": "mpl",
            "NUMBA_CACHE_DIR": "numba",
            "TORCHINDUCTOR_CACHE_DIR": "torchinductor",
            "TRITON_CACHE_DIR": "triton",
            "CUDA_CACHE_PATH": "cuda",
        }
        env.update({key: str(root / value) for key, value in paths.items()})
        return env

    @contextlib.contextmanager
    def scratch(self, role="B1", env=None):
        with (
            mock.patch.dict(os.environ, env or self.environment(role), clear=True),
            mock.patch.object(
                diagnose,
                "_require_local_scratch_mount",
                return_value={"filesystem": "tmpfs"},
            ),
        ):
            with diagnose._worker_scratch(self.args, role) as scratch:
                yield scratch

    def test_worker_scratch_is_exclusive_private_and_environment_bound(self):
        with self.scratch() as scratch:
            self.assertEqual(scratch.root, self.scratch_base / "B1")
            self.assertEqual(
                set(scratch.cache_roots), {"torchinductor", "triton", "cuda"}
            )
            for path in scratch.cache_roots.values():
                self.assertEqual(list(pathlib.Path(path).iterdir()), [])
                self.assertEqual(stat.S_IMODE(pathlib.Path(path).stat().st_mode), 0o700)
            scratch.check()
            self.assertTrue(scratch.record["caches_initially_empty"])
        with self.assertRaises((diagnose.DiagnosticError, FileExistsError)):
            with self.scratch():
                pass

    def test_wrong_environment_rejected_before_any_scratch_write(self):
        for key, value in (
            ("TORCHINDUCTOR_CACHE_DIR", "/tmp/shared"),
            ("HOME", "/home/s2510040"),
            ("PYTHONHASHSEED", "1"),
            ("SLURM_JOB_ID", "124"),
        ):
            with self.subTest(key=key):
                env = self.environment()
                env[key] = value
                with self.assertRaises(diagnose.DiagnosticError):
                    with self.scratch(env=env):
                        pass
                self.assertEqual(list(self.scratch_base.iterdir()), [])

    def test_scratch_parent_mode_symlink_and_namespace_replacement_fail(self):
        self.scratch_base.chmod(0o755)
        with self.assertRaises(diagnose.DiagnosticError):
            with self.scratch():
                pass
        self.scratch_base.chmod(0o700)
        with self.assertRaises(diagnose.DiagnosticError):
            with self.scratch() as scratch:
                scratch.root.rename(self.scratch_base / "moved")
                scratch.root.mkdir(mode=0o700)
                scratch.check()
        (self.scratch_base / "B1").rmdir()
        (self.scratch_base / "B1").symlink_to(self.scratch_base / "moved")
        with self.assertRaises((diagnose.DiagnosticError, FileExistsError)):
            with self.scratch():
                pass

    def test_scratch_rejects_unknown_role_and_bad_job_before_writes(self):
        for role, job in (
            ("../escape", "123"),
            ("B1", "01"),
            ("B1", "1/2"),
            ("B1", True),
        ):
            self.args.job_id = job
            with self.assertRaises(diagnose.DiagnosticError):
                with self.scratch(role):
                    pass
        self.assertEqual(list(self.scratch_base.iterdir()), [])

    def test_cold_process_claim_is_single_use_even_after_failure(self):
        with (
            mock.patch.object(diagnose, "_WORKER_PROCESS_CLAIMED", False),
            mock.patch.object(diagnose, "_require_cold_worker_interpreter") as cold,
        ):
            diagnose._claim_worker_process()
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._claim_worker_process()
            cold.assert_called_once_with()

    def test_public_entry_never_accepts_modified_matrix_or_cpu_fallback(self):
        with mock.patch.object(
            diagnose, "_run_child_worker", return_value={"sentinel": True}
        ) as run:
            for spec in diagnose.CELL_SPECS.values():
                self.assertEqual(diagnose.run_cell(spec, self.args), {"sentinel": True})
                self.assertEqual(run.call_args.args, (spec, self.args))
            diagnose.run_reference_cold(self.args)
            self.assertEqual(run.call_args.args, (None, self.args))
            run.reset_mock()
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.run_cell(diagnose.CellSpec("A2", False, (16, 1)), self.args)
            run.assert_not_called()

    def test_scratch_spill_retains_native_bytes_and_original_commitment(self):
        result = _task5_pair("B1")[0]
        commitment = dict(result.boundary_records["pass_commitment"])
        before = diagnose.encode_pass_evidence(result)
        with self.scratch() as scratch:
            scratch.spill(result)
            self.assertEqual(diagnose.encode_pass_evidence(result), before)
            self.assertEqual(
                dict(result.boundary_records["pass_commitment"]), commitment
            )
            for name in ("scene_features", "cue_features"):
                path = scratch.root / "intermediates" / f"pass1.{name}.npy"
                self.assertTrue(path.is_file())
                self.assertEqual(
                    np.load(path, allow_pickle=False).tobytes(),
                    result.boundary_records[name]["tensor"].numpy().tobytes(),
                )
            with self.assertRaises((diagnose.DiagnosticError, FileExistsError)):
                scratch.spill(result)
        self.assertFalse((self.attempt / "cells/B1/CELL_COMPLETE.json").exists())

    def test_real_cpu_cell_loads_once_keeps_scope_and_uses_two_fresh_caches(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        trials = _task4_trials(bank)
        _Task4Cache.instances.clear()
        with (
            self.scratch() as scratch,
            _task4_hermetic_worker_context(evaluator, scene_api) as context,
        ):
            context.update(
                bank=bank,
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=_task4_scene_hashes(bank),
            )
            checks = []

            def verify():
                self.assertIs(
                    diagnose._ACTIVE_WORKER_SCENE_SCOPE.get()["scene_api"], scene_api
                )
                checks.append("checked")

            receipt = diagnose._execute_worker_passes(
                context,
                trials,
                diagnose.CELL_SPECS["B1"],
                self.args,
                scratch,
                verify_inputs=verify,
                allow_cpu=True,
            )
            self.assertEqual(receipt["comparison"]["cell_status"], "PASS")
            self.assertEqual(len(checks), 2)
            self.assertEqual(len(evaluator.load_calls), 1)
            self.assertEqual(evaluator.load_calls[0][1], "formal40")
            self.assertEqual(evaluator.calls.count(("configure_runtime", True)), 1)
            self.assertEqual(len(_Task4Cache.instances), 2)
            self.assertNotEqual(
                id(_Task4Cache.instances[0]), id(_Task4Cache.instances[1])
            )
            metadata = receipt["inputs"]["passes"][0]["payload"]["boundaries"][
                "metadata"
            ]
            self.assertTrue(metadata["worker_environment"]["caches_initially_empty"])
            self.assertEqual(len(list((scratch.root / "intermediates").iterdir())), 4)

    def test_real_cpu_reference_uses_frozen_predict_16_then_1_without_trace(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        with (
            self.scratch("reference_cold") as scratch,
            _task4_hermetic_worker_context(evaluator, scene_api) as context,
        ):
            context.update(
                bank=bank,
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=_task4_scene_hashes(bank),
            )
            with mock.patch.object(
                diagnose, "run_trace_pass", side_effect=AssertionError("trace entered")
            ):
                got = diagnose._execute_worker_passes(
                    context,
                    _task4_trials(bank),
                    None,
                    self.args,
                    scratch,
                    verify_inputs=lambda: None,
                    allow_cpu=True,
                )
            self.assertEqual(
                [item[1] for item in evaluator.predict_calls], [16, 16] + [1] * 32
            )
            self.assertEqual(len(evaluator.load_calls), 1)
            self.assertIsNone(got["comparison"])
            self.assertEqual(list((scratch.root / "intermediates").iterdir()), [])

    def test_post_input_failure_blocks_complete_marker(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        with (
            self.scratch() as scratch,
            _task4_hermetic_worker_context(evaluator, scene_api) as context,
        ):
            context.update(
                bank=bank,
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=_task4_scene_hashes(bank),
            )
            with self.assertRaisesRegex(diagnose.DiagnosticError, "bound input"):
                diagnose._execute_worker_passes(
                    context,
                    _task4_trials(bank),
                    diagnose.CELL_SPECS["B1"],
                    self.args,
                    scratch,
                    verify_inputs=mock.Mock(
                        side_effect=diagnose.DiagnosticError("bound input changed")
                    ),
                    allow_cpu=True,
                )
        self.assertFalse((self.attempt / "cells/B1/CELL_COMPLETE.json").exists())

    def test_second_pass_error_never_retries_and_preserves_scratch(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        real = diagnose.run_trace_pass

        def failing(context, trials, pass_id, *args):
            if pass_id == "pass2":
                raise diagnose.DiagnosticError("pass2 failed")
            return real(context, trials, pass_id, *args)

        with (
            self.scratch() as scratch,
            _task4_hermetic_worker_context(evaluator, scene_api) as context,
        ):
            context.update(
                bank=bank,
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=_task4_scene_hashes(bank),
            )
            with mock.patch.object(
                diagnose, "run_trace_pass", side_effect=failing
            ) as predict:
                with self.assertRaisesRegex(diagnose.DiagnosticError, "pass2 failed"):
                    diagnose._execute_worker_passes(
                        context,
                        _task4_trials(bank),
                        diagnose.CELL_SPECS["B1"],
                        self.args,
                        scratch,
                        verify_inputs=lambda: None,
                        allow_cpu=True,
                    )
                self.assertEqual(predict.call_count, 2)
            self.assertTrue(
                (scratch.root / "intermediates/pass1.scene_features.npy").exists()
            )
        self.assertFalse((self.attempt / "cells/B1").exists())

    def test_freeze_audit_portability_is_limited_to_file_diagnostics(self):
        import copy

        left = {
            "clips": [
                {
                    "relative_path": "a",
                    "size": 4,
                    "sha256": "a" * 64,
                    "mode": 0o600,
                    "st_dev": 66,
                    "st_ino": 123,
                    "st_mtime_ns": 1,
                }
            ],
            "trials": [{"identity": {"st_dev": "must not be ignored"}}],
        }
        right = copy.deepcopy(left)
        right["clips"][0].update(st_dev=53, st_ino=321, st_mtime_ns=2)
        self.assertEqual(
            diagnose._portable_worker_audit(left),
            diagnose._portable_worker_audit(right),
        )
        for key, changed in (("size", 5), ("mode", 0o644), ("sha256", "b" * 64)):
            altered = copy.deepcopy(right)
            altered["clips"][0][key] = changed
            self.assertNotEqual(
                diagnose._portable_worker_audit(left),
                diagnose._portable_worker_audit(altered),
            )
        right["trials"][0]["identity"]["st_dev"] = "changed"
        self.assertNotEqual(
            diagnose._portable_worker_audit(left),
            diagnose._portable_worker_audit(right),
        )

    def test_created_cache_must_actually_be_empty_before_imports(self):
        real = os.mkdir

        def populated(path, *args, **kwargs):
            real(path, *args, **kwargs)
            if path == "cuda":
                (self.scratch_base / "B1/cuda/stale-cache").write_bytes(b"unexpected")

        with mock.patch.object(os, "mkdir", side_effect=populated):
            with self.assertRaises(diagnose.DiagnosticError):
                with self.scratch():
                    pass

    def test_same_bytes_scratch_replacement_cannot_become_new_baseline(self):
        real = diagnose._get_trace().stable_file_record

        def swap(path, **kwargs):
            path = pathlib.Path(path)
            if path.name == "pass1.scene_features.npy":
                payload = path.read_bytes()
                path.rename(path.with_suffix(".old"))
                path.write_bytes(payload)
            return real(path, **kwargs)

        with (
            self.scratch() as scratch,
            mock.patch.object(
                diagnose._get_trace(), "stable_file_record", side_effect=swap
            ),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                scratch.spill(_task5_pair("B1")[0])

    def test_production_entry_scope_order_and_no_cpu_override(self):
        events = []
        context = {"snapshot_files": self.base / "snapshot"}
        bundle = {
            "context": context,
            "trials": ("bound trials",),
            "audit": {
                "snapshot_files": [{"relative_path": "src/x.py", "sha256": "a" * 64}]
            },
        }

        @contextlib.contextmanager
        def scene(*args):
            events.append("scene-enter")
            try:
                yield "scene-api"
            finally:
                events.append("scene-exit")

        def load(digest):
            events.append("inputs")
            self.assertTrue((self.scratch_base / "B1/torchinductor").is_dir())
            return bundle

        def execute(ctx, trials, spec, args, scratch, *, verify_inputs, allow_cpu):
            events.append("execute")
            self.assertIs(allow_cpu, False)
            self.assertEqual(ctx["scene_api"], "scene-api")
            self.assertEqual(trials, ("bound trials",))
            verify_inputs()
            return {"status": "fixture-receipt"}

        with (
            mock.patch.dict(os.environ, self.environment(), clear=True),
            mock.patch.object(
                diagnose,
                "_claim_worker_process",
                side_effect=lambda: events.append("cold"),
            ),
            mock.patch.object(
                diagnose,
                "_require_local_scratch_mount",
                return_value={"filesystem": "tmpfs"},
            ),
            mock.patch.object(diagnose, "_load_worker_inputs", side_effect=load),
            mock.patch.object(diagnose, "frozen_scene_context", side_effect=scene),
            mock.patch.object(diagnose, "_execute_worker_passes", side_effect=execute),
            mock.patch.object(
                diagnose,
                "_revalidate_worker_inputs",
                side_effect=lambda item: events.append("recheck"),
            ),
        ):
            got = diagnose.run_cell(diagnose.CELL_SPECS["B1"], self.args)
        self.assertEqual(got, {"status": "fixture-receipt"})
        self.assertEqual(
            events,
            ["cold", "inputs", "scene-enter", "execute", "recheck", "scene-exit"],
        )

    def test_real_worker_records_runtime_versions_and_frozen_seed_authority(self):
        evaluator, scene_api = _Task4Evaluator(), _Task4SceneAPI()
        bank = _task4_bank(32)
        with (
            self.scratch("reference_cold") as scratch,
            _task4_hermetic_worker_context(evaluator, scene_api) as context,
        ):
            context.update(
                bank=bank,
                clips_dir=pathlib.Path("/clips"),
                historical_scene_hashes=_task4_scene_hashes(bank),
            )
            got = diagnose._execute_worker_passes(
                context,
                _task4_trials(bank),
                None,
                self.args,
                scratch,
                verify_inputs=lambda: None,
                allow_cpu=True,
            )
            env = got["inputs"]["passes"][0]["payload"]["boundaries"]["metadata"][
                "worker_environment"
            ]
            self.assertEqual(env["software"]["torch"], torch.__version__)
            self.assertEqual(env["software"]["device"], "cpu")
            self.assertEqual(
                env["runtime_configuration_policy"],
                "frozen_configurator_once_before_model_load__no_between_pass_reset",
            )

    def test_all_four_matrix_routes_use_exact_pass_arguments(self):
        for cell, enabled, sizes in (
            ("A1", True, (16, 16)),
            ("A2", True, (16, 1)),
            ("B1", False, (16, 16)),
            ("B2", False, (16, 1)),
        ):
            with self.subTest(cell=cell), self.scratch(cell) as scratch:
                results = _task5_artifact_result(cell)
                with (
                    mock.patch.object(
                        diagnose, "prepare_formal40_worker", return_value={}
                    ) as load,
                    mock.patch.object(
                        diagnose, "_worker_software_record", return_value={}
                    ),
                    mock.patch.object(
                        diagnose, "run_trace_pass", side_effect=results["passes"]
                    ) as run,
                    mock.patch.object(
                        diagnose, "write_cell_artifacts", return_value={"done": True}
                    ) as write,
                ):
                    got = diagnose._execute_worker_passes(
                        {},
                        results["trials"],
                        diagnose.CELL_SPECS[cell],
                        self.args,
                        scratch,
                        verify_inputs=lambda: None,
                    )
                    self.assertEqual(got, {"done": True})
                    load.assert_called_once_with({}, allow_cpu=False)
                    self.assertEqual(
                        [
                            (call.args[2], call.args[3], call.args[4])
                            for call in run.call_args_list
                        ],
                        [("pass1", sizes[0], enabled), ("pass2", sizes[1], enabled)],
                    )
                    self.assertEqual(
                        write.call_args.args[0], self.attempt / "cells" / cell
                    )

    def test_linux_mount_probe_rejects_network_same_device_and_unknown_fs(self):
        def info(device):
            return types.SimpleNamespace(st_dev=device)

        device = os.makedev(8, 1)
        local = f"5 1 8:1 / {self.scratch_base} rw - ext4 /dev/test rw\n"

        def fake_stat(path, **kwargs):
            return info(
                device if pathlib.Path(path) == self.scratch_base else os.makedev(0, 66)
            )

        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(os, "stat", side_effect=fake_stat),
        ):
            for fs in ("nfs", "nfs4", "cifs", "fuse.sshfs", "overlay", "unknown"):
                with mock.patch(
                    "builtins.open", mock.mock_open(read_data=local.replace("ext4", fs))
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose._require_local_scratch_mount(self.scratch_base)
            with mock.patch("builtins.open", mock.mock_open(read_data=local)):
                self.assertEqual(
                    diagnose._require_local_scratch_mount(self.scratch_base)[
                        "filesystem"
                    ],
                    "ext4",
                )
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(os, "stat", return_value=info(device)),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._require_local_scratch_mount(self.scratch_base)

    def test_cold_interpreter_does_not_import_torch_to_check_it(self):
        # Real isolated subprocess: source bootstrap + gate only, not a GPU run.
        tools = self.diag_root / "tools"
        tools.mkdir()
        script = tools / "diagnose_batch_invariance.py"
        script.write_bytes(DIAGNOSER.read_bytes())
        code = (
            "import importlib.util,sys,pathlib;"
            "p=pathlib.Path(sys.argv[1]);s=importlib.util.spec_from_file_location('d',p);"
            "d=importlib.util.module_from_spec(s);sys.modules['d']=d;s.loader.exec_module(d);"
            "d.PRODUCTION_PYTHON=pathlib.Path(sys.executable);d.DIAGNOSTIC_ROOT=p.parent.parent;"
            "d._require_cold_worker_interpreter();"
            "assert not any(x in sys.modules for x in ('torch','numpy','pandas','torchaudio'));"
            "d._claim_worker_process();print('COLD_STDLIB_ONLY=PASS')"
        )
        done = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("COLD_STDLIB_ONLY=PASS", done.stdout)

    def worker_bundle_fixture(self):
        self.root = self.diag_root
        tools = self.root / "tools"
        tools.mkdir()
        production = []
        for name in diagnose.PRODUCTION_FILES:
            path = tools / name
            path.write_bytes(b"fixture, not executed\n")
            production.append(trace.stable_file_record(path, allowed_root=tools))
        audit = FrozenContractTests.complete_audit(self, production)
        freeze = diagnose._freeze_document(audit)
        payload = trace.canonical_json_bytes(freeze)
        (self.root / "input_freeze.json").write_bytes(payload)
        context = {
            "_frozen_context_capability": types.SimpleNamespace(
                trust_domain="production"
            ),
            "roots": {"clips_dir": audit["roots"]["clips_dir"]},
            "manifest": {},
        }
        return audit, freeze, context, _sha256(payload)

    def test_worker_loader_uses_frozen_trials_and_accepts_only_portable_file_diagnostics(
        self,
    ):
        import copy

        audit, freeze, context, sha = self.worker_bundle_fixture()
        current = copy.deepcopy(audit)
        current["clips"][0].update(st_dev=53, st_ino=456, st_mtime_ns=999)
        with (
            mock.patch.object(diagnose, "read_frozen_context", return_value=context),
            mock.patch.object(diagnose, "audit_inputs", return_value=current),
            mock.patch.object(
                diagnose, "_worker_historical_hashes", return_value={0: "a" * 64}
            ),
        ):
            bundle = diagnose._load_worker_inputs(sha)
            self.assertEqual(
                [dataclasses.asdict(t) for t in bundle["trials"]], freeze["trials"]
            )
            current["clips"][0]["sha256"] = "b" * 64
            with self.assertRaisesRegex(
                diagnose.DiagnosticError, "reconstructed audit"
            ):
                diagnose._load_worker_inputs(sha)
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._load_worker_inputs("f" * 64)

    def test_worker_revalidation_detects_same_bytes_freeze_replacement(self):
        audit, freeze, context, sha = self.worker_bundle_fixture()
        bundle = {
            "context": context,
            "audit": audit,
            "freeze_record": trace.stable_file_record(
                self.root / "input_freeze.json", allowed_root=self.root
            ),
        }
        path = self.root / "input_freeze.json"
        payload = path.read_bytes()
        path.rename(self.root / "prior.json")
        path.write_bytes(payload)
        with self.assertRaises(Exception):
            diagnose._revalidate_worker_inputs(bundle)

    def test_worker_revalidation_rereads_pinned_and_complete_local_audit(self):
        import copy

        audit, freeze, context, sha = self.worker_bundle_fixture()
        bundle = {
            "context": context,
            "audit": audit,
            "freeze_record": trace.stable_file_record(
                self.root / "input_freeze.json", allowed_root=self.root
            ),
        }
        with (
            mock.patch.object(diagnose, "_validate_frozen_capability_contents"),
            mock.patch.object(
                diagnose,
                "_verify_v4_pinned_records",
                return_value=audit["v4"]["verified_pinned_files"],
            ) as pinned,
            mock.patch.object(
                diagnose, "audit_inputs", return_value=copy.deepcopy(audit)
            ) as fresh,
        ):
            diagnose._revalidate_worker_inputs(bundle)
            pinned.assert_called_once()
            fresh.assert_called_once()
            fresh.return_value["snapshot_files"][0]["st_ino"] += 1
            with self.assertRaisesRegex(diagnose.DiagnosticError, "within execution"):
                diagnose._revalidate_worker_inputs(bundle)

    def test_historical_hash_loader_binds_exact_frozen_file_and_sorted_vector(self):
        path = self.base / "per_trial_results.csv"
        hashes = {i: f"{i:064x}" for i in range(10000)}
        path.write_text(
            "trial_id,scene_sha256\n"
            + "".join(f"{i},{hashes[i]}\n" for i in reversed(range(10000)))
        )
        record = {
            **trace.stable_file_record(path, allowed_root=self.base),
            "path": str(path),
        }
        vector = _sha256(("\n".join(hashes[i] for i in range(10000)) + "\n").encode())
        context = {
            "manifest": {"historical_evidence": {"job584990_results": record}},
            "historical_scene_binding": {"scene_hash_vector_sha256": vector},
        }
        self.assertEqual(diagnose._worker_historical_hashes(context), hashes)
        context["historical_scene_binding"]["scene_hash_vector_sha256"] = "b" * 64
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._worker_historical_hashes(context)
        path.write_text("trial_id,scene_sha256\n0,bad\n")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._worker_historical_hashes(context)

    def test_invalid_cell_still_gets_complete_evidence_not_worker_retry(self):
        data = _task5_artifact_result("B1")
        data["passes"][1].boundary_records["scene_features"]["tensor"][0, 0] = float(
            "nan"
        )
        _task5_refresh(data["passes"][1])
        with (
            self.scratch() as scratch,
            mock.patch.object(diagnose, "prepare_formal40_worker", return_value={}),
            mock.patch.object(diagnose, "_worker_software_record", return_value={}),
            mock.patch.object(
                diagnose, "run_trace_pass", side_effect=data["passes"]
            ) as run,
        ):
            receipt = diagnose._execute_worker_passes(
                {},
                data["trials"],
                data["spec"],
                self.args,
                scratch,
                verify_inputs=lambda: None,
            )
            self.assertEqual(receipt["comparison"]["cell_status"], "INVALID")
            self.assertEqual(run.call_count, 2)
            self.assertTrue((self.attempt / "cells/B1/CELL_COMPLETE.json").is_file())

    def test_spill_corruption_detected_before_any_persistent_completion(self):
        with self.scratch() as scratch:
            scratch.spill(_task5_pair("B1")[0])
            path = scratch.root / "intermediates/pass1.scene_features.npy"
            with path.open("r+b") as stream:
                stream.seek(-1, 2)
                stream.write(b"\xff")
            with self.assertRaises(Exception):
                scratch.verify_spills()

    def test_missing_attempt_is_rejected_before_model_or_input_load(self):
        self.attempt.rmdir()
        with (
            mock.patch.dict(os.environ, self.environment(), clear=True),
            mock.patch.object(diagnose, "_claim_worker_process"),
            mock.patch.object(
                diagnose, "_require_local_scratch_mount", return_value={}
            ),
            mock.patch.object(
                diagnose,
                "_load_worker_inputs",
                side_effect=AssertionError("inputs reached"),
            ),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.run_cell(diagnose.CELL_SPECS["B1"], self.args)

    def test_cold_worker_rejects_unbound_source_location_before_imports(self):
        code = (
            "import importlib.util,sys,pathlib;"
            "p=pathlib.Path(sys.argv[1]);s=importlib.util.spec_from_file_location('d',p);"
            "d=importlib.util.module_from_spec(s);sys.modules['d']=d;s.loader.exec_module(d);"
            "d.PRODUCTION_PYTHON=pathlib.Path(sys.executable);"
            "d.DIAGNOSTIC_ROOT=pathlib.Path('/unrelated-root');\n"
            "try: d._require_cold_worker_interpreter()\n"
            "except d.DiagnosticError: print('REJECTED')\n"
            "else: raise SystemExit('unbound code location accepted')\n"
        )
        done = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(DIAGNOSER)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("REJECTED", done.stdout)

    def test_existing_or_insecure_attempt_never_loads_inputs(self):
        for problem in ("mode", "already-created"):
            with self.subTest(problem=problem):
                if problem == "mode":
                    self.attempt.chmod(0o755)
                else:
                    self.attempt.chmod(0o700)
                    (self.attempt / "cells/B1").mkdir(parents=True)
                with (
                    mock.patch.dict(os.environ, self.environment(), clear=True),
                    mock.patch.object(diagnose, "_claim_worker_process"),
                    mock.patch.object(
                        diagnose,
                        "_worker_scratch",
                        return_value=contextlib.nullcontext(),
                    ),
                    mock.patch.object(
                        diagnose,
                        "_load_worker_inputs",
                        side_effect=AssertionError("inputs reached"),
                    ),
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        diagnose.run_cell(diagnose.CELL_SPECS["B1"], self.args)


class ColdChildProcessTests(unittest.TestCase):
    """Task 6a launch transport, with real stdlib-only fixture processes."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.root = self.base / "diagnostic"
        self.attempt = self.root / "attempts/slurm-123"
        self.attempt.mkdir(parents=True, mode=0o700)
        self.scratch = self.base / "audattn_v4_numdiag_123"
        self.scratch.mkdir(mode=0o700)
        self.sha = "d" * 64
        self.env = {
            "SLURM_JOB_ID": "123",
            "CUDA_VISIBLE_DEVICES": "0",
            "SLURM_CPUS_PER_TASK": "8",
            "SLURM_JOB_NODELIST": "fixture-node",
            "SLURM_EXPORT_ENV": "ALL",
            "PYTHONPATH": "/untrusted",
            "LD_PRELOAD": "/untrusted.so",
            "CONDA_PREFIX": "/untrusted",
            "HOME": "/untrusted-home",
            "TASK6_SECRET": "not-forwarded",
        }
        for patcher in (
            mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.root),
            mock.patch.dict(os.environ, self.env, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.real_popen = subprocess.Popen

    def marker(self, cell="A2"):
        name = (
            "reference_cold/REFERENCE_COMPLETE.json"
            if cell is None
            else f"cells/{cell}/CELL_COMPLETE.json"
        )
        return {
            "path": str(self.attempt / name),
            "relative_path": name,
            "type": "file",
            "mode": 0o600,
            "size": 1024,
            "st_dev": 1,
            "st_ino": 200,
            "st_mtime_ns": 300,
            "sha256": "b" * 64,
        }

    def document(self, cell="A2"):
        return {
            "schema_version": 1,
            "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
            "evaluation_role": diagnose.EVALUATION_ROLE,
            "status": "CHILD_ARTIFACTS_READY",
            "job_id": "123",
            "input_freeze_sha256": self.sha,
            "worker_pid": 0,
            "mode": "_child-reference" if cell is None else "_child-cell",
            "cell": cell,
            "marker_record": self.marker(cell),
        }

    def child_source(
        self, cell="A2", *, document=None, prefix="", suffix="", exit_code=0
    ):
        document = self.document(cell) if document is None else document
        return (
            "import json,os,sys\n"
            f"v=json.loads({json.dumps(document)!r})\n"
            "if v['worker_pid'] == 0: v['worker_pid']=os.getpid()\n"
            f"sys.stdout.write({prefix!r})\n"
            "sys.stdout.write(json.dumps(v,sort_keys=True,separators=(',',':'),"
            "ensure_ascii=True,allow_nan=False)+'\\n')\n"
            f"sys.stdout.write({suffix!r})\n"
            "sys.stdout.flush()\n"
            f"sys.exit({exit_code})\n"
        )

    def launch_fixture(self, source, *, cell="A2", timeout=5.0, launcher=None):
        calls = []

        def spawn(argv, **kwargs):
            calls.append((argv, kwargs.copy()))
            return self.real_popen([sys.executable, "-I", "-B", "-c", source], **kwargs)

        launcher = launcher or diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=timeout
        )
        with mock.patch.object(diagnose.subprocess, "Popen", side_effect=spawn):
            result = launcher.run(
                "_child-reference" if cell is None else "_child-cell", cell
            )
        return result, calls

    def test_fixed_absolute_shell_free_argv_for_reference_and_all_cells(self):
        for cell in (None, "A2", "A1", "B1", "B2"):
            mode = "_child-reference" if cell is None else "_child-cell"
            got = diagnose.child_command(mode, "123", self.sha, cell, self.scratch)
            expected = [
                str(diagnose.PRODUCTION_PYTHON),
                "-I",
                "-B",
                str(self.root / "tools/diagnose_batch_invariance.py"),
                mode,
                "--job-id",
                "123",
                "--expected-input-freeze-sha256",
                self.sha,
            ]
            if cell:
                expected += ["--cell", cell]
            self.assertEqual(got, expected)
            self.assertNotIn(str(self.scratch), got)  # scratch is environment-only

    def test_invalid_job_sha_role_or_scratch_never_builds_a_command(self):
        bad = [
            ("_child-cell", job, self.sha, "A2", self.scratch)
            for job in ("", "0", "01", "１２３", "1;echo bad", True, 123)
        ]
        bad += [
            ("_child-cell", "123", sha, "A2", self.scratch)
            for sha in (None, "D" * 64, "d" * 63, "d" * 63 + "\0")
        ]
        bad += [
            (mode, "123", self.sha, cell, self.scratch)
            for mode, cell in (
                ("run-coordinator", "A2"),
                ("_child-cell", None),
                ("_child-reference", "A2"),
                ("_child-cell", "../A2"),
            )
        ]
        bad += [
            ("_child-cell", "123", self.sha, "A2", root)
            for root in (
                "relative",
                "/tmp/audattn_v4_numdiag_124",
                "/tmp/../audattn_v4_numdiag_123",
                "/tmp/audattn_v4_numdiag_123\0",
                str(self.root / self.scratch.name),
            )
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(diagnose.DiagnosticError):
                diagnose.child_command(*args)

    def test_child_environment_is_a_small_allowlist_with_disjoint_write_paths(self):
        seen = set()
        for cell in (None, "A2", "A1", "B1", "B2"):
            mode = "_child-reference" if cell is None else "_child-cell"
            env = diagnose.child_environment(mode, "123", cell, self.scratch, self.env)
            role = "reference_cold" if cell is None else cell
            self.assertEqual(env["SLURM_JOB_ID"], "123")
            self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
            self.assertEqual(env["SLURM_CPUS_PER_TASK"], "8")
            self.assertEqual(env["SLURM_JOB_NODELIST"], "fixture-node")
            self.assertEqual(env["DIAG_SCRATCH_ROOT"], str(self.scratch))
            self.assertEqual(env["PYTHONHASHSEED"], "0")
            self.assertEqual(env["PYTHONNOUSERSITE"], "1")
            self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(
                env["PATH"],
                f"{diagnose.PRODUCTION_PYTHON.parent}:/usr/local/bin:/usr/bin:/bin",
            )
            for forbidden in (
                "PYTHONPATH",
                "LD_PRELOAD",
                "CONDA_PREFIX",
                "TASK6_SECRET",
                "SLURM_EXPORT_ENV",
            ):
                self.assertNotIn(forbidden, env)
            current = set()
            for name, relative in diagnose._WORKER_WRITE_PATHS.items():
                self.assertEqual(env[name], str(self.scratch / role / relative))
                current.add(env[name])
            self.assertFalse(current & seen)
            seen.update(current)
        self.assertEqual(
            list(self.scratch.iterdir()), []
        )  # child creates its own cache

    def test_environment_refuses_wrong_slurm_job_and_missing_or_invalid_gpu(self):
        for patch in (
            {"SLURM_JOB_ID": "124"},
            {"CUDA_VISIBLE_DEVICES": ""},
            {"CUDA_VISIBLE_DEVICES": "0\0"},
            {"SLURM_CPUS_PER_TASK": 8},
        ):
            with self.subTest(patch=patch), self.assertRaises(diagnose.DiagnosticError):
                diagnose.child_environment(
                    "_child-cell", "123", "A2", self.scratch, {**self.env, **patch}
                )
        env = dict(self.env)
        del env["CUDA_VISIBLE_DEVICES"]
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.child_environment("_child-cell", "123", "A2", self.scratch, env)

    def test_real_process_exit_binds_pid_job_role_sha_and_marker(self):
        got, calls = self.launch_fixture(self.child_source())
        self.assertEqual(got["status"], "CHILD_EXIT_VERIFIED")
        self.assertEqual(got["returncode"], 0)
        self.assertNotEqual(got["pid"], os.getpid())
        self.assertEqual(got["completion"]["worker_pid"], got["pid"])
        self.assertEqual(got["completion"]["marker_record"], self.marker())
        self.assertEqual(got["argv"], calls[0][0])
        self.assertGreater(got["stdout_bytes"], 0)
        self.assertEqual(len(got["stdout_sha256"]), 64)
        self.assertEqual(len(calls), 1)
        kwargs = calls[0][1]
        self.assertIs(kwargs["shell"], False)
        self.assertIs(kwargs["start_new_session"], True)
        self.assertIs(kwargs["close_fds"], True)
        self.assertEqual(kwargs["pass_fds"], ())
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertIsNone(kwargs["stderr"])

    def test_reference_and_four_cells_use_distinct_real_processes(self):
        launcher = diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=5.0
        )
        pids = []
        for cell in (None, "A2", "A1", "B1", "B2"):
            got, _ = self.launch_fixture(
                self.child_source(cell), cell=cell, launcher=launcher
            )
            pids.append(got["pid"])
        self.assertEqual(len(set(pids)), 5)

    def test_stdin_is_eof_and_parent_descriptor_not_inherited(self):
        path = self.base / "parent.lock"
        with path.open("wb") as stream:
            fd = stream.fileno()
            os.set_inheritable(fd, True)
            source = (
                "import os,sys\nassert sys.stdin.read()==''\n"
                f"try:\n os.fstat({fd})\nexcept OSError:\n pass\nelse:\n raise RuntimeError('leaked fd')\n"
                + self.child_source()
            )
            self.launch_fixture(source)
            self.assertEqual(os.fstat(fd).st_ino, path.stat().st_ino)

    def test_nonzero_exit_rejected_even_with_complete_valid_envelope(self):
        with self.assertRaisesRegex(diagnose.DiagnosticError, "exit"):
            self.launch_fixture(self.child_source(exit_code=2))

    def test_empty_prefixed_trailing_duplicate_and_noncanonical_stdout_fail(self):
        sources = [
            "pass",
            self.child_source(prefix="Using explicit dim specification\n"),
            self.child_source(suffix="warning\n"),
            self.child_source(suffix="{}\n"),
            self.child_source().replace("sort_keys=True", "sort_keys=False"),
        ]
        for source in sources:
            with (
                self.subTest(source=source[:50]),
                self.assertRaises(diagnose.DiagnosticError),
            ):
                self.launch_fixture(source)

    def test_completion_rejects_forged_fields_or_out_of_attempt_marker(self):
        for key, value in (
            ("worker_pid", os.getpid()),
            ("job_id", "124"),
            ("input_freeze_sha256", "e" * 64),
            ("cell", "B1"),
            ("mode", "_child-reference"),
            ("status", "SMOKE_PASS"),
            ("evaluation_role", "INDEPENDENT_TEST"),
            ("schema_version", True),
        ):
            document = self.document()
            document[key] = value
            with self.subTest(key=key), self.assertRaises(diagnose.DiagnosticError):
                self.launch_fixture(self.child_source(document=document))
        for key, value in (
            ("path", str(self.base / "foreign.json")),
            ("relative_path", "../x"),
            ("sha256", "x" * 64),
            ("mode", 0o644),
            ("type", "symlink"),
            ("size", True),
            ("st_ino", -1),
        ):
            document = self.document()
            document["marker_record"][key] = value
            with (
                self.subTest(marker_key=key),
                self.assertRaises(diagnose.DiagnosticError),
            ):
                self.launch_fixture(self.child_source(document=document))

    def test_stream_limit_fails_before_accepting_large_stdout(self):
        with self.assertRaisesRegex(diagnose.DiagnosticError, "limit"):
            self.launch_fixture("import os\nos.write(1,b'x'*100000)\n")

    def test_timeout_terminates_and_reaps_process_group(self):
        children = []

        def spawn(argv, **kwargs):
            process = self.real_popen(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                **kwargs,
            )
            children.append(process)
            return process

        launcher = diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=0.15
        )
        with mock.patch.object(diagnose.subprocess, "Popen", side_effect=spawn):
            with self.assertRaisesRegex(diagnose.DiagnosticError, "timeout"):
                launcher.run("_child-cell", "A2")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertLess(children[0].returncode, 0)

    def test_interruption_terminates_active_group_without_retry(self):
        children = []

        def spawn(argv, **kwargs):
            process = self.real_popen(
                [sys.executable, "-I", "-B", "-c", "import time; time.sleep(30)"],
                **kwargs,
            )
            children.append(process)
            return process

        launcher = diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=5.0
        )
        with (
            mock.patch.object(diagnose.subprocess, "Popen", side_effect=spawn),
            mock.patch.object(
                diagnose, "_collect_child_stdout", side_effect=KeyboardInterrupt
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                launcher.run("_child-cell", "A2")
            with self.assertRaisesRegex(diagnose.DiagnosticError, "retry"):
                launcher.run("_child-cell", "A2")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)

    def test_same_role_not_relaunched_after_success_or_spawn_failure(self):
        launcher = diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=5.0
        )
        self.launch_fixture(self.child_source(), launcher=launcher)
        with mock.patch.object(diagnose.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(diagnose.DiagnosticError, "retry"):
                launcher.run("_child-cell", "A2")
            spawn.assert_not_called()
        other = diagnose._ColdChildLauncher(
            "123", self.sha, self.scratch, timeout_seconds=5.0
        )
        with mock.patch.object(
            diagnose.subprocess, "Popen", side_effect=OSError("launch failed")
        ) as spawn:
            with self.assertRaises((diagnose.DiagnosticError, OSError)):
                other.run("_child-cell", "A2")
            with self.assertRaisesRegex(diagnose.DiagnosticError, "retry"):
                other.run("_child-cell", "A2")
            self.assertEqual(spawn.call_count, 1)

    def test_missing_attempt_populated_scratch_or_wrong_mode_prevents_spawn(self):
        def attempt_absent():
            self.attempt.rmdir()

        def scratch_exists():
            (self.scratch / "A2").mkdir()

        def bad_mode():
            self.scratch.chmod(0o755)

        for change in (attempt_absent, scratch_exists, bad_mode):
            with self.subTest(change=change.__name__):
                change()
                with mock.patch.object(diagnose.subprocess, "Popen") as spawn:
                    with self.assertRaises((diagnose.DiagnosticError, FileExistsError)):
                        diagnose._ColdChildLauncher("123", self.sha, self.scratch).run(
                            "_child-cell", "A2"
                        )
                    spawn.assert_not_called()
                if not self.attempt.exists():
                    self.attempt.mkdir(mode=0o700)
                if (self.scratch / "A2").exists():
                    (self.scratch / "A2").rmdir()
                self.scratch.chmod(0o700)

    def test_completed_child_cannot_hide_parent_namespace_replacement(self):
        source = (
            "import pathlib\n"
            f"p=pathlib.Path({str(self.scratch)!r})\n"
            "p.rename(p.with_name('old-scratch'))\np.mkdir(mode=0o700)\n"
            + self.child_source()
        )
        with self.assertRaises(diagnose.DiagnosticError):
            self.launch_fixture(source)

    def test_completion_document_uses_actual_pid_and_preserves_finite_diff(self):
        args = types.SimpleNamespace(
            job_id="123", expected_input_freeze_sha256=self.sha
        )
        source = {
            "status": "ARTIFACTS_VERIFIED",
            "marker_record": self.marker(),
            "comparison": {"cell_status": "DIFF", "canary_status": "DIFF"},
        }
        document = diagnose._child_completion_document(
            source, args, "_child-cell", "A2"
        )
        expected = self.document()
        expected["worker_pid"] = os.getpid()
        self.assertEqual(document, expected)
        source["status"] = "ERROR"
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._child_completion_document(source, args, "_child-cell", "A2")

    def test_bootstrap_and_launch_planning_import_no_numerical_modules(self):
        code = (
            "import importlib.util,sys\n"
            f"s=importlib.util.spec_from_file_location('cold_diag',{str(DIAGNOSER)!r})\n"
            "m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)\n"
            f"m.child_command('_child-cell','123',{'d' * 64!r},'A2',{str(self.scratch)!r})\n"
            f"m.child_environment('_child-cell','123','A2',{str(self.scratch)!r},"
            "{'SLURM_JOB_ID':'123','CUDA_VISIBLE_DEVICES':'0'})\n"
            "bad=('torch','torchaudio','numpy','pandas','numeric_trace')\n"
            "assert not any(any(k==p or k.startswith(p+'.') for p in bad) for k in sys.modules)\n"
            "print('STDLIB_ONLY=PASS')\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "STDLIB_ONLY=PASS")

    def test_no_writable_scratch_anywhere_in_the_account_home(self):
        scratch = "/home/s2510040/arbitrary-cache/audattn_v4_numdiag_123"
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.child_command("_child-cell", "123", self.sha, "A2", scratch)

    def test_timeout_includes_alive_process_after_stdout_eof(self):
        with self.assertRaisesRegex(diagnose.DiagnosticError, "timeout"):
            self.launch_fixture(
                "import os,time\nos.close(1)\ntime.sleep(30)\n", timeout=0.15
            )

    def test_signal_exit_cannot_be_mistaken_for_a_valid_receipt(self):
        source = self.child_source().replace(
            "sys.exit(0)", f"os.kill(os.getpid(), {int(signal.SIGTERM)})"
        )
        with self.assertRaisesRegex(diagnose.DiagnosticError, "exit"):
            self.launch_fixture(source)

    def test_timeout_bounds_and_boolean_values_rejected(self):
        for value in (True, 0, -1, 3601, float("inf"), float("nan"), "30"):
            with self.subTest(value=value), self.assertRaises(diagnose.DiagnosticError):
                diagnose._ColdChildLauncher(
                    "123", self.sha, self.scratch, timeout_seconds=value
                )

    def test_canonical_envelope_rejects_duplicate_keys_nan_and_extra_fields(self):
        canonical = (
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")) + "\n"
        )
        duplicate = canonical.replace(
            '"schema_version":1', '"schema_version":1,"schema_version":1'
        )
        nan = canonical.replace('"worker_pid":0', '"worker_pid":NaN')
        extra = canonical.replace(
            '"schema_version":1', '"schema_version":1,"extra":true'
        )
        for payload in (duplicate, nan, extra, "[]\n", "null\n"):
            with (
                self.subTest(payload=payload[-60:]),
                self.assertRaises(diagnose.DiagnosticError),
            ):
                self.launch_fixture(f"import sys\nsys.stdout.write({payload!r})\n")

    def test_symlinked_scratch_ancestor_or_existing_evidence_prevents_spawn(self):
        link = self.base / "scratch-link"
        link.symlink_to(self.base, target_is_directory=True)
        with mock.patch.object(diagnose.subprocess, "Popen") as spawn:
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._ColdChildLauncher(
                    "123", self.sha, link / self.scratch.name
                ).run("_child-cell", "A2")
            (self.attempt / "cells/A2").mkdir(parents=True)
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._ColdChildLauncher("123", self.sha, self.scratch).run(
                    "_child-cell", "A2"
                )
            spawn.assert_not_called()

    def test_incomplete_execution_cli_arguments_never_start_workers(self):
        for command in ("_child-reference", "_child-cell", "run-coordinator"):
            with contextlib.redirect_stderr(__import__("io").StringIO()):
                with self.assertRaises(SystemExit) as error:
                    diagnose.main([command, "--job-id", "123"])
            self.assertEqual(error.exception.code, 2)


class PersistedMatrixTests(unittest.TestCase):
    """Parent evidence integration with CPU tensors and synthetic launch receipts.

    These fixtures do not certify an actual GPU launch. ColdChildProcessTests
    independently exercises the real subprocess transport used by the owner.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name).resolve()
        self.root = self.base / "diagnostic"
        self.attempt = self.root / "attempts/slurm-123"
        self.attempt.mkdir(parents=True, mode=0o700)
        self.scratch = self.base / "audattn_v4_numdiag_123"
        self.scratch.mkdir(mode=0o700)
        self.env = {
            "SLURM_JOB_ID": "123",
            "CUDA_VISIBLE_DEVICES": "0",
            "SLURM_JOB_NODELIST": "fixture-node",
        }
        patcher = mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = self.base / "frozen.py"
        source.write_text("# sealed fixture\n")
        self.sources = [trace.stable_file_record(source, allowed_root=self.base)]
        self.sha = "d" * 64
        sample = _task5_artifact_result()
        self.trials = diagnose._trial_documents(sample["trials"])
        self.history = {
            row["trial_id"]: row["sha256"]
            for row in sample["passes"][0].boundary_records["raw_scene"]["per_trial"]
        }
        self.events = []

    def data(self, cell=None, *, delta=0.0):
        result = _task5_artifact_result(cell or "A2")
        role = cell or "REFERENCE_COLD"
        worker_role = cell or "reference_cold"
        pid = 1001 + (0 if cell is None else ("A2", "A1", "B1", "B2").index(cell) + 1)
        for index, item in enumerate(result["passes"], 1):
            meta = _task4_metadata(
                role,
                item.trial_ids,
                worker_pid=pid,
                worker_nonce="worker-" + role,
                model_nonce="model-" + role,
                cache_nonce=f"cache-{role}-{index}",
                scratch_root=str(self.scratch / worker_role),
                cache_root=str(self.scratch / worker_role),
                source_records=self.sources,
                trust_domain="production",
                scene_scope_nonce="scope-" + role,
            )
            if cell:
                meta["autocast_enabled"] = diagnose.CELL_SPECS[cell].autocast_enabled
            env = diagnose.child_environment(
                "_child-cell" if cell else "_child-reference",
                "123",
                cell,
                self.scratch,
                self.env,
            )
            meta["worker_environment"] = {
                "schema_version": 1,
                "worker_role": worker_role,
                "scratch_root": str(self.scratch / worker_role),
                "caches_initially_empty": True,
                "write_paths": {k: env[k] for k in diagnose._WORKER_WRITE_PATHS},
                "software": {
                    "python": "3.11.5",
                    "torch": "2.1.1+cu118",
                    "cuda_runtime": "11.8",
                    "cudnn": 8700,
                    "device": "cuda:0",
                    "gpu_name": "NVIDIA A100-PCIE-40GB",
                    "hostname": "fixture-node",
                    "worker_pid": pid,
                    "slurm_job_id": "123",
                    "cuda_visible_devices": "0",
                },
            }
            item.boundary_records["metadata"] = meta
            if index == 2 and delta:
                item.outputs["nll"][0] = delta
                item.boundary_records["derived"]["nll"]["tensor"][0] = delta
            _task5_refresh(item)
            if cell is None:
                for name in diagnose._TRACE_BOUNDARIES:
                    if name not in ("raw_scene", "raw_cue"):
                        del item.boundary_records[name]
                item.boundary_records["derived"] = {
                    "correct": item.boundary_records["derived"]["correct"]
                }
                diagnose._bind_pass_commitment(item)
        result["spec"] = diagnose.CELL_SPECS[cell] if cell else None
        return result

    def publish(self, cell=None, *, delta=0.0, mutate=None):
        result = self.data(cell, delta=delta)
        if mutate:
            mutate(result)
            for p in result["passes"]:
                diagnose._bind_pass_commitment(p)
        writer = (
            diagnose.write_cell_artifacts
            if cell
            else diagnose.write_reference_artifacts
        )
        path = self.attempt / (f"cells/{cell}" if cell else "reference_cold")
        receipt = writer(path, result)
        pid = 1001 + (0 if cell is None else ("A2", "A1", "B1", "B2").index(cell) + 1)
        mode = "_child-cell" if cell else "_child-reference"
        completion = {
            "schema_version": 1,
            "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
            "evaluation_role": diagnose.EVALUATION_ROLE,
            "status": "CHILD_ARTIFACTS_READY",
            "job_id": "123",
            "input_freeze_sha256": self.sha,
            "worker_pid": pid,
            "mode": mode,
            "cell": cell,
            "marker_record": receipt["marker_record"],
        }
        raw = trace.canonical_json_bytes(completion)
        return {
            "status": "CHILD_EXIT_VERIFIED",
            "pid": pid,
            "returncode": 0,
            "argv": diagnose.child_command(mode, "123", self.sha, cell, self.scratch),
            "environment": diagnose.child_environment(
                mode, "123", cell, self.scratch, self.env
            ),
            "completion": completion,
            "stdout_bytes": len(raw),
            "stdout_sha256": _sha256(raw),
        }

    def reader(self, launch):
        return diagnose._read_bound_child_result(
            launch,
            job_id="123",
            freeze_sha=self.sha,
            trials=self.trials,
            source_records=self.sources,
            historical_scene_hashes=self.history,
        )

    def sequence(self, *, delta=0.0, mismatch=False, failure=None):
        def run(mode, cell=None):
            role = cell or "REFERENCE_COLD"
            self.events.append(role)
            if role == failure:
                raise diagnose.DiagnosticError("synthetic child crash")
            return self.publish(
                cell,
                delta=(
                    delta if cell == "A2" or (cell is None and not mismatch) else 0.0
                ),
            )

        return diagnose._run_matrix_sequence(
            types.SimpleNamespace(run=run),
            job_id="123",
            freeze_sha=self.sha,
            trials=self.trials,
            source_records=self.sources,
            historical_scene_hashes=self.history,
        )

    def test_reopens_payloads_and_binds_both_passes_to_observed_pid(self):
        launch = self.publish("A2")
        got = self.reader(launch)
        self.assertEqual(got["status"], "CHILD_ORIGIN_AND_ARTIFACTS_VERIFIED")
        self.assertEqual(got["worker_pid"], launch["pid"])
        self.assertEqual(len(got["pass_bindings"]), 2)
        self.assertEqual(got["inputs"]["trials"], self.trials)
        self.assertNotIn("tensor_payload", got)

    def test_rejects_self_consistent_passes_from_another_process(self):
        def mutate(result):
            for p in result["passes"]:
                m = p.boundary_records["metadata"]
                m["worker_pid"] = m["attestation"]["worker_pid"] = 5555
                m["worker_environment"]["software"]["worker_pid"] = 5555

        launch = self.publish("A2", mutate=mutate)
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(launch)

    def test_launch_receipt_tampering_is_rejected_before_artifact_acceptance(self):
        import copy

        launch = self.publish("A2")
        for field, value in (
            ("pid", 555),
            ("returncode", True),
            ("stdout_sha256", "e" * 64),
            ("stdout_bytes", 0),
            ("argv", ["/bin/true"]),
            ("status", "PASS"),
        ):
            bad = copy.deepcopy(launch)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(diagnose.DiagnosticError):
                self.reader(bad)

    def test_frozen_trial_and_source_inventories_are_parent_authorities(self):
        launch = self.publish("A2")
        for case in ("trial", "source", "history"):
            import copy

            trials, sources, history = copy.deepcopy(
                (self.trials, self.sources, self.history)
            )
            if case == "trial":
                trials[0]["identity"]["target_label"] = 7
            if case == "source":
                sources[0]["sha256"] = "a" * 64
            if case == "history":
                history[100] = "b" * 64
            with self.subTest(case=case), self.assertRaises(diagnose.DiagnosticError):
                diagnose._read_bound_child_result(
                    launch,
                    job_id="123",
                    freeze_sha=self.sha,
                    trials=trials,
                    source_records=sources,
                    historical_scene_hashes=history,
                )

    def test_changed_payload_is_not_masked_by_good_stdout(self):
        launch = self.publish("A2")
        (self.attempt / "cells/A2/TRIAL_OUTPUTS.csv").write_text("broken\n")
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(launch)

    def test_runtime_or_scratch_attestation_is_not_only_decorative(self):
        def mutate(result):
            for p in result["passes"]:
                p.boundary_records["metadata"]["worker_environment"][
                    "caches_initially_empty"
                ] = False

        launch = self.publish("A2", mutate=mutate)
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(launch)

    def test_finite_diff_runs_all_four_cells_and_is_not_scientific_success(self):
        delta = 0.0077362060546875
        result = self.sequence(delta=delta)
        self.assertEqual(self.events, ["REFERENCE_COLD", "A2", "A1", "B1", "B2"])
        self.assertEqual(result["status"], "MATRIX_EVIDENCE_VERIFIED")
        summary = result["summary"]
        self.assertEqual(summary["execution_order"], list(diagnose.EXECUTION_ORDER))
        self.assertEqual(summary["cells"]["A2"]["nll_max_abs"], delta)
        self.assertEqual(summary["a2_replay_classification"], "REPRODUCED")
        self.assertEqual(summary["cells"]["A2"]["canary_status"], "DIFF")
        self.assertEqual(summary["evaluation_role"], diagnose.EVALUATION_ROLE)
        self.assertEqual(set(summary["cells"]), set(diagnose.CELL_SPECS))
        for name in (
            "SMOKE_PASS.json",
            "SAME_BANK_AUDIT_PUBLISHED.json",
            "COMPLETE.json",
            "DIAGNOSTIC_COMPLETE.json",
            "DIAGNOSTIC_FAILED.json",
        ):
            self.assertEqual(list(self.root.rglob(name)), [])

    def test_no_reproduction_is_a_valid_complete_matrix(self):
        result = self.sequence()
        self.assertEqual(
            result["summary"]["a2_replay_classification"], "NOT_REPRODUCED"
        )
        self.assertEqual(len(self.events), 5)

    def test_equivalence_checks_second_pass_and_does_not_run_remaining_cells(self):
        with self.assertRaisesRegex(diagnose.DiagnosticError, "equivalence"):
            self.sequence(delta=0.0077362060546875, mismatch=True)
        self.assertEqual(self.events, ["REFERENCE_COLD", "A2"])
        marker = self.attempt / "INVALID_TRACE_PATH.json"
        self.assertTrue(marker.is_file())
        self.assertFalse((self.attempt / "MATRIX_SUMMARY.json").exists())
        self.assertTrue(
            (self.attempt / "reference_cold/REFERENCE_COMPLETE.json").exists()
        )

    def test_child_crash_does_not_produce_matrix_or_retry(self):
        with self.assertRaises(diagnose.DiagnosticError):
            self.sequence(failure="B1")
        self.assertEqual(self.events, ["REFERENCE_COLD", "A2", "A1", "B1"])
        self.assertFalse((self.attempt / "MATRIX_SUMMARY.json").exists())

    def test_durable_launch_receipts_are_reused_read_only_for_reverification(self):
        result = self.sequence()
        before = trace.fingerprint_tree(self.root)
        with mock.patch.object(
            diagnose._ColdChildLauncher,
            "run",
            side_effect=AssertionError("no process allowed"),
        ):
            verified = diagnose._reverify_matrix_sequence(
                result["launch_records"],
                job_id="123",
                freeze_sha=self.sha,
                trials=self.trials,
                source_records=self.sources,
                historical_scene_hashes=self.history,
            )
        self.assertEqual(verified, result["summary"])
        self.assertEqual(before, trace.fingerprint_tree(self.root))

    def test_reverification_rejects_missing_child_or_changed_launch_record(self):
        result = self.sequence()
        short = dict(result["launch_records"])
        del short["B2"]
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._reverify_matrix_sequence(
                short,
                job_id="123",
                freeze_sha=self.sha,
                trials=self.trials,
                source_records=self.sources,
                historical_scene_hashes=self.history,
            )
        path = pathlib.Path(result["launch_records"]["A2"]["path"])
        path.write_text("{}\n")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._reverify_matrix_sequence(
                result["launch_records"],
                job_id="123",
                freeze_sha=self.sha,
                trials=self.trials,
                source_records=self.sources,
                historical_scene_hashes=self.history,
            )

    def test_equivalence_verification_does_not_require_retained_node_local_cache(self):
        result = self.sequence()
        # Node-local caches are runtime evidence, not persistent result inputs.
        self.scratch.rmdir()
        verified = diagnose._reverify_matrix_sequence(
            result["launch_records"],
            job_id="123",
            freeze_sha=self.sha,
            trials=self.trials,
            source_records=self.sources,
            historical_scene_hashes=self.history,
        )
        self.assertEqual(verified, result["summary"])

    def test_sequence_refuses_existing_receipts_before_starting_any_child(self):
        self.sequence()
        self.events.clear()
        with self.assertRaises(diagnose.DiagnosticError):
            self.sequence()
        self.assertEqual(self.events, [])

    def test_owner_files_are_not_added_to_child_publication_namespace(self):
        for name in (
            "CHILD_EXIT_A2.json",
            "MATRIX_SUMMARY.json",
            "INVALID_TRACE_PATH.json",
        ):
            with (
                self.subTest(name=name),
                diagnose._AttemptArtifactStore(self.attempt) as store,
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    store.publish_bytes(name, b"{}\n")
        with diagnose._MatrixArtifactStore(self.attempt) as store:
            for name in (
                "../MATRIX_SUMMARY.json",
                "cells/A2/CELL_COMPLETE.json",
                "SMOKE_PASS.json",
                "DIAGNOSTIC_COMPLETE.json",
                "DIAGNOSTIC_FAILED.json",
                "arbitrary.json",
            ):
                with (
                    self.subTest(name=name),
                    self.assertRaises(diagnose.DiagnosticError),
                ):
                    store.publish_bytes(name, b"{}\n")

    def test_reference_pass_state_change_is_invalid_even_with_matching_outputs(self):
        def mutate(result):
            result["passes"][1].model_snapshots["after"][0]["sha256"] = "b" * 64

        launch = self.publish(mutate=mutate)
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(launch)

    def test_invalid_trace_cell_is_not_promoted_by_zero_child_exit(self):
        def mutate(result):
            for p in result["passes"]:
                p.boundary_records["metadata"]["runtime"]["cuda_matmul_allow_tf32"] = (
                    False
                )

        launch = self.publish("A2", mutate=mutate)
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(launch)

    def test_equivalence_checks_all_four_official_outputs(self):
        import copy

        left = self.reader(self.publish())
        right = self.reader(self.publish("A2"))
        for field in diagnose._OFFICIAL_OUTPUT_KEYS:
            other = copy.deepcopy(right)
            saved = other["inputs"]["passes"][1]
            decoded = diagnose.decode_official_outputs(saved["official_outputs"])
            changed = {k: v.copy() for k, v in decoded.items()}
            changed[field][0] = changed[field][0] + (
                1 if field == "pred_label" else 0.01
            )
            saved["official_outputs"] = diagnose.encode_official_outputs(changed)
            saved["payload"]["outputs"] = {
                k: {n: r[n] for n in ("boundary", "shape", "dtype", "sha256")}
                for k, v in changed.items()
                for r in [trace.tensor_record(v, boundary="output." + k)]
            }
            saved["commitment"]["binding_sha256"] = _sha256(
                trace.canonical_json_bytes(saved["payload"])
            )
            with self.subTest(field=field), self.assertRaises(diagnose.DiagnosticError):
                diagnose._compare_persisted_reference(left, other)

    def test_reference_comparison_rejects_shape_dtype_or_raw_digest_changes(self):
        import copy

        left = self.reader(self.publish())
        right = self.reader(self.publish("A2"))
        for key, value in (
            ("shape", [99]),
            ("dtype", "torch.float64"),
            ("sha256", "e" * 64),
        ):
            other = copy.deepcopy(right)
            saved = other["inputs"]["passes"][1]
            saved["payload"]["boundaries"]["raw_cue"]["per_trial"][0][key] = value
            saved["commitment"]["binding_sha256"] = _sha256(
                trace.canonical_json_bytes(saved["payload"])
            )
            with self.subTest(key=key), self.assertRaises(diagnose.DiagnosticError):
                diagnose._compare_persisted_reference(left, other)

    def test_final_reverification_rejects_corruption_by_later_worker(self):
        def run(mode, cell=None):
            self.events.append(cell or "REFERENCE_COLD")
            receipt = self.publish(cell)
            if cell == "B2":
                (self.attempt / "reference_cold/TRIAL_OUTPUTS.csv").write_text(
                    "late-corruption\n"
                )
            return receipt

        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._run_matrix_sequence(
                types.SimpleNamespace(run=run),
                job_id="123",
                freeze_sha=self.sha,
                trials=self.trials,
                source_records=self.sources,
                historical_scene_hashes=self.history,
            )
        self.assertEqual(len(self.events), 5)
        self.assertFalse((self.attempt / "MATRIX_SUMMARY.json").exists())

    def test_all_cold_workers_must_start_with_same_frozen_model_content(self):
        import copy

        observations = [self.reader(self.publish(cell)) for cell in (None, "A2")]
        bad = copy.deepcopy(observations)
        for p in bad[1]["inputs"]["passes"]:
            for records in p["payload"]["model_snapshots"].values():
                records[0]["sha256"] = "a" * 64
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._check_distinct_persisted_workers(bad)

    def test_matrix_checks_state_and_raw_inputs_without_equating_predictions_between_cells(
        self,
    ):
        # A finite autocast-related label change is an observation, not identity invalidity.
        def run(mode, cell=None):
            def mutate(result):
                p = result["passes"][1]
                p.outputs["pred_label"][0] = 1
                p.boundary_records["derived"]["pred_label"]["tensor"][0] = 1
                p.boundary_records["derived"]["correct"]["tensor"][0] = False
                _task5_refresh(p)

            return self.publish(cell, mutate=mutate if cell == "B2" else None)

        got = diagnose._run_matrix_sequence(
            types.SimpleNamespace(run=run),
            job_id="123",
            freeze_sha=self.sha,
            trials=self.trials,
            source_records=self.sources,
            historical_scene_hashes=self.history,
        )
        self.assertEqual(got["summary"]["cells"]["B2"]["canary_status"], "DIFF")

    def test_aggregate_cannot_bind_equivalence_to_another_a2_pair(self):
        observations = {
            cell: self.reader(self.publish(cell))
            for cell in (None, "A2", "A1", "B1", "B2")
        }
        equivalence = diagnose._compare_persisted_reference(
            observations[None], observations["A2"]
        )
        equivalence["a2_pass_bindings"] = ["0" * 64] * 2
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.aggregate_matrix(
                {k: observations[k] for k in diagnose.CELL_SPECS}, equivalence
            )

    def test_software_and_hidden_env_mismatch_are_rejected(self):
        import copy

        launch = self.publish("A2")
        bad = copy.deepcopy(launch)
        bad["environment"]["LD_PRELOAD"] = "/untrusted"
        with self.assertRaises(diagnose.DiagnosticError):
            self.reader(bad)
        observations = [self.reader(self.publish()), self.reader(launch)]
        observations[1]["inputs"]["passes"][0]["payload"]["boundaries"]["metadata"][
            "worker_environment"
        ]["software"]["hostname"] = "different-node"
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._check_distinct_persisted_workers(observations)


class CoordinatorLifecycleTests(unittest.TestCase):
    """Real owner lifecycle with injected observations, not a GPU experiment."""

    def setUp(self):
        self.events = []
        self.args = types.SimpleNamespace(
            job_id="123", intent_nonce="a" * 32, expected_input_freeze_sha256="b" * 64
        )
        self.failures = {}
        self.held = False
        self.writes = {}
        test = self

        class Owner:
            def call(self, event, result=None):
                test.events.append(event)
                failure = test.failures.get(event)
                if failure:
                    if callable(failure):
                        failure()
                    else:
                        raise failure
                return result

            def authorize(self):
                return self.call("authorize", {"binding": "fixture"})

            def claim(self):
                self.call("claim")

            @contextlib.contextmanager
            def lock(self):
                self.call("lock")
                test.held = True
                try:
                    yield 99
                finally:
                    self.call("unlock")
                    test.held = False

            def verify_lock(self, fd):
                test.assertTrue(test.held)
                test.assertEqual(fd, 99)
                self.call("lock_check")

            def fingerprint(self):
                key = "tree_post" if "tree_pre" in test.events else "tree_pre"
                return self.call(key, {"tree_sha256": "t", "content_sha256": "c"})

            def inputs(self):
                key = "inputs_post" if "inputs_pre" in test.events else "inputs_pre"
                return self.call(key, {"records": ["fixed"]})

            def publish(self, name, value):
                self.call(name)
                if name in test.writes:
                    raise FileExistsError(name)
                test.writes[name] = value
                if name == "DIAGNOSTIC_COMPLETE.json":
                    test.assertTrue(test.held)

            def matrix(self):
                test.assertTrue(test.held)
                return self.call(
                    "matrix",
                    {
                        "status": "MATRIX_EVIDENCE_VERIFIED",
                        "summary": {"finite_difference": True},
                        "summary_record": {"sha256": "x"},
                    },
                )

        self.owner = Owner()

    def run_owner(self):
        return diagnose._coordinate(self.args, self.owner)

    def test_order_holds_same_lock_through_post_and_terminal(self):
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_COMPLETE")
        self.assertEqual(
            self.events,
            [
                "authorize",
                "claim",
                "lock",
                "lock_check",
                "tree_pre",
                "inputs_pre",
                "PRECHECK.json",
                "RUNNING.json",
                "matrix",
                "inputs_post",
                "tree_post",
                "lock_check",
                "POSTCHECK.json",
                "DIAGNOSTIC_COMPLETE.json",
                "unlock",
            ],
        )
        self.assertEqual(result["evaluation_role"], diagnose.EVALUATION_ROLE)

    def test_authorization_failure_has_no_claim_lock_or_output(self):
        self.failures["authorize"] = ValueError("bad receipt")
        with self.assertRaises(ValueError):
            self.run_owner()
        self.assertEqual(self.events, ["authorize"])
        self.assertEqual(self.writes, {})

    def test_claim_failure_never_overwrites_another_owners_terminal(self):
        self.failures["claim"] = FileExistsError("attempt exists")
        with self.assertRaises(FileExistsError):
            self.run_owner()
        self.assertEqual(self.events, ["authorize", "claim"])

    def test_primary_and_both_post_failures_are_retained(self):
        self.failures["matrix"] = ValueError("child failed")
        self.failures["inputs_post"] = ValueError("checkpoint changed")
        self.failures["tree_post"] = ValueError("v4 log changed")
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertIn("child failed", result["primary_error"]["message"])
        self.assertEqual(len(result["post_errors"]), 2)
        self.assertNotIn("DIAGNOSTIC_COMPLETE.json", self.writes)
        self.assertLess(
            self.events.index("DIAGNOSTIC_FAILED.json"), self.events.index("unlock")
        )

    def test_post_mutation_overrides_finite_matrix_success(self):
        for method, code in (
            ("inputs", "INVALID_BOUND_INPUT_CHANGED"),
            ("fingerprint", "INVALID_FROZEN_ROOT_CHANGED"),
        ):
            with self.subTest(method=method):
                self.setUp()
                original = getattr(self.owner, method)
                count = [0]

                def changed():
                    count[0] += 1
                    value = original()
                    return value if count[0] == 1 else {"changed": True}

                setattr(self.owner, method, changed)
                result = self.run_owner()
                self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
                self.assertIn(code, [x["code"] for x in result["post_errors"]])

    def test_pre_failure_skips_matrix_but_attempts_both_post_checks(self):
        self.failures["inputs_pre"] = ValueError("bad clip")
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertNotIn("matrix", self.events)
        self.assertIn("inputs_post", self.events)
        self.assertIn("tree_post", self.events)

    def test_lock_contention_never_generates_pre_fingerprints(self):
        self.failures["lock"] = diagnose.DiagnosticError("held exclusively")
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertNotIn("tree_pre", self.events)
        self.assertNotIn("matrix", self.events)
        self.assertFalse(result["lock_acquired"])

    def test_caught_real_signals_restore_handlers_and_preserve_post_checks(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                self.setUp()
                before = signal.getsignal(sig)
                self.failures["matrix"] = lambda: os.kill(os.getpid(), sig)
                result = self.run_owner()
                self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
                self.assertEqual(result["primary_error"]["signal"], sig)
                self.assertIn("inputs_post", self.events)
                self.assertEqual(signal.getsignal(sig), before)

    def test_post_signal_is_failure_not_complete_and_other_check_still_runs(self):
        self.failures["inputs_post"] = lambda: os.kill(os.getpid(), signal.SIGTERM)
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertIn("tree_post", self.events)

    def test_terminal_write_failure_never_attempts_second_terminal(self):
        self.failures["DIAGNOSTIC_COMPLETE.json"] = OSError("fsync failure")
        with self.assertRaises(OSError):
            self.run_owner()
        self.assertNotIn("DIAGNOSTIC_FAILED.json", self.events)
        self.assertEqual(self.events[-1], "unlock")

    def test_unverified_matrix_return_cannot_publish_success(self):
        self.owner.matrix = lambda: {"status": "RUNNING"}
        result = self.run_owner()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")

    def test_actual_child_is_reaped_before_post_checks_after_signal(self):
        fixture = ColdChildProcessTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        processes = []
        original_popen = fixture.real_popen

        def observed_spawn(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        fixture.real_popen = observed_spawn
        self.owner.matrix = lambda: fixture.launch_fixture(
            "import os,signal,time\ntime.sleep(0.15)\n"
            "os.kill(os.getppid(),signal.SIGTERM)\ntime.sleep(30)\n"
        )
        original_inputs = self.owner.inputs

        def inputs():
            if processes:
                self.assertIsNotNone(
                    processes[-1].poll(), "child must be reaped before POST"
                )
            return original_inputs()

        self.owner.inputs = inputs
        result = self.run_owner()
        self.assertEqual(len(processes), 1)
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertEqual(result["primary_error"]["signal"], signal.SIGTERM)
        self.assertIn("inputs_post", self.events)


class CoordinatorBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        for name in diagnose.DIAGNOSTIC_LAYOUT:
            (self.root / name).mkdir(mode=0o700)
        self.patcher = mock.patch.object(diagnose, "DIAGNOSTIC_ROOT", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.nonce, self.freeze, self.runner = "a" * 32, "b" * 64, "c" * 64
        self.args = types.SimpleNamespace(
            job_id="123",
            intent_nonce=self.nonce,
            expected_input_freeze_sha256=self.freeze,
        )
        self.common = {
            "schema_version": 1,
            "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
            "intent_nonce": self.nonce,
            "input_freeze_sha256": self.freeze,
            "runner_sha256": self.runner,
        }
        argv = [
            "/usr/bin/sbatch",
            "--parsable",
            "--export=NONE",
            "--comment=audattn-v4-numdiag-" + self.nonce[:12],
            str(self.root / "tools/run_numeric_diag.sbatch"),
            self.freeze,
            self.nonce,
        ]
        self.intent = dict(self.common, status="SUBMISSION_INTENT", argv=argv)
        self.response = dict(
            self.common,
            status="SBATCH_RESPONSE",
            argv=argv,
            returncode=0,
            stdout_b64="MTIzCg==",
            stderr_b64="",
        )
        self.receipt = dict(
            self.common,
            status="SUBMITTED",
            job_id="123",
            intent_record_sha256=_sha256(trace.canonical_json_bytes(self.intent)),
            response_record_sha256=_sha256(trace.canonical_json_bytes(self.response)),
        )
        self.save("INTENT.json", self.intent)
        self.save("SBATCH_RESPONSE.json", self.response)

    def save(self, name, value):
        (self.root / "state" / name).write_bytes(trace.canonical_json_bytes(value))

    def wait(self, **kwargs):
        return diagnose._wait_submission_binding(self.args, self.runner, **kwargs)

    def test_fast_start_waits_only_for_absent_receipt(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds
            self.save("SUBMISSION_RECEIPT.json", self.receipt)

        got = self.wait(monotonic=lambda: clock[0], sleep=sleep)
        self.assertEqual(got["job_id"], "123")
        self.assertEqual(clock[0], 1.0)
        self.assertEqual(
            set(got["records"]),
            {"INTENT.json", "SBATCH_RESPONSE.json", "SUBMISSION_RECEIPT.json"},
        )

    def test_receipt_timeout_is_bounded_and_read_only(self):
        before = trace.fingerprint_tree(self.root)
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        with self.assertRaisesRegex(diagnose.DiagnosticError, "receipt.*timeout"):
            self.wait(monotonic=lambda: clock[0], sleep=sleep)
        self.assertEqual(clock[0], 120.0)
        self.assertEqual(before, trace.fingerprint_tree(self.root))

    def test_mismatched_receipt_fails_without_wait_or_writes(self):
        for key, bad in (
            ("job_id", "124"),
            ("intent_nonce", "d" * 32),
            ("input_freeze_sha256", "d" * 64),
            ("runner_sha256", "d" * 64),
            ("response_record_sha256", "d" * 64),
        ):
            with self.subTest(key=key):
                self.save("SUBMISSION_RECEIPT.json", dict(self.receipt, **{key: bad}))
                with mock.patch.object(diagnose.time, "sleep") as sleeper:
                    with self.assertRaises(diagnose.DiagnosticError):
                        self.wait()
                    sleeper.assert_not_called()

    def test_response_binding_does_not_accept_ambiguous_scheduler_result(self):
        for key, value in (
            ("stdout_b64", "MTIzO2NsdXN0ZXIK"),
            ("returncode", True),
            ("returncode", 1),
            ("stderr_b64", "ZXJyb3I="),
        ):
            with self.subTest(key=key):
                response = dict(self.response, **{key: value})
                self.save("SBATCH_RESPONSE.json", response)
                self.save(
                    "SUBMISSION_RECEIPT.json",
                    dict(
                        self.receipt,
                        response_record_sha256=_sha256(
                            trace.canonical_json_bytes(response)
                        ),
                    ),
                )
                with self.assertRaises(diagnose.DiagnosticError):
                    self.wait()

    def test_noncanonical_or_symlinked_receipt_is_not_retried(self):
        path = self.root / "state/SUBMISSION_RECEIPT.json"
        path.write_text(json.dumps(self.receipt))
        with self.assertRaises(diagnose.DiagnosticError):
            self.wait()
        path.unlink()
        path.symlink_to(self.root / "state/INTENT.json")
        with self.assertRaises(diagnose.DiagnosticError):
            self.wait()

    def test_spool_archive_exact_bytes_create_once_and_no_shell(self):
        spool = self.root / "fixture.sbatch"
        spool.write_bytes(b"#!/bin/bash\nexit 0\n")
        sha = _sha256(spool.read_bytes())
        got = diagnose.archive_spool_runner(spool, "123", sha)
        archived = self.root / "submitted_runners/123.sbatch"
        self.assertEqual(got["sha256"], sha)
        self.assertEqual(archived.read_bytes(), spool.read_bytes())
        self.assertEqual(archived.stat().st_nlink, 1)
        with self.assertRaises(FileExistsError):
            diagnose.archive_spool_runner(spool, "123", sha)

    def test_bad_spool_cannot_create_archive(self):
        spool = self.root / "fixture.sbatch"
        spool.write_bytes(b"wrong")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.archive_spool_runner(spool, "123", "0" * 64)
        self.assertFalse(any((self.root / "submitted_runners").iterdir()))

    def test_portable_bound_identity_ignores_inode_but_rejects_changed_bytes_and_links(
        self,
    ):
        path = self.root / "clip"
        path.write_bytes(b"audio")
        expected = {
            "path": str(path),
            "type": "file",
            "size": 5,
            "sha256": _sha256(b"audio"),
        }
        first = diagnose._check_bound_record(expected)
        path.unlink()
        path.write_bytes(b"audio")
        self.assertEqual(first, diagnose._check_bound_record(expected))
        path.write_bytes(b"Audio")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._check_bound_record(expected)
        path.unlink()
        path.symlink_to(self.root / "state/INTENT.json")
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._check_bound_record(expected)

    def test_status_classifier_never_interprets_missing_terminal_as_success(self):
        self.assertEqual(
            diagnose.classify_diagnostic_terminal(None, None, slurm_ended=True),
            "INCOMPLETE_UNTRAPPED_TERMINATION",
        )
        self.assertEqual(
            diagnose.classify_diagnostic_terminal(None, None, slurm_ended=False),
            "AWAITING_TERMINAL",
        )
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.classify_diagnostic_terminal({}, {}, slurm_ended=True)


class CoordinatorFileOwnerTests(unittest.TestCase):
    """Real filesystem/locks with explicit fake frozen data; no model launch."""

    def setUp(self):
        self.binding = CoordinatorBindingTests()
        self.binding.setUp()
        self.addCleanup(self.binding.doCleanups)
        self.root = self.binding.root
        self.args = self.binding.args
        self.v4 = self.root.parent / (self.root.name + "-v4")
        self.v4.mkdir(mode=0o700)
        self.addCleanup(__import__("shutil").rmtree, self.v4)
        for name in ("tools", "state"):
            (self.v4 / name).mkdir(mode=0o700)
        for name in (
            "tools/locked_same_bank_eval.py",
            "tools/run_locked_same_bank_eval.sbatch",
            "state/evaluation.lock",
            "formal-final.ckpt",
        ):
            (self.v4 / name).write_bytes(name.encode())
        self.contract = dataclasses.replace(
            diagnose.production_contract(),
            v4_root=self.v4,
            evaluator_sha256=_sha256(b"tools/locked_same_bank_eval.py"),
            runner_sha256=_sha256(b"tools/run_locked_same_bank_eval.sbatch"),
            lock_sha256=_sha256(b"state/evaluation.lock"),
            formal40_sha256=_sha256(b"formal-final.ckpt"),
        )
        pinned = []
        for i, name in enumerate(
            (
                "tools/locked_same_bank_eval.py",
                "tools/run_locked_same_bank_eval.sbatch",
                "formal-final.ckpt",
            )
            + tuple(f"pin-{i}" for i in range(21))
        ):
            path = self.v4 / name
            if not path.exists():
                path.write_bytes(name.encode())
            pinned.append(
                {
                    "role_ordinal": i,
                    "path": str(path),
                    "type": "file",
                    "size": path.stat().st_size,
                    "sha256": _sha256(path.read_bytes()),
                }
            )
        lock_path = self.v4 / "state/evaluation.lock"
        manifest = {
            "inputs": {f"{i:02d}": r for i, r in enumerate(pinned)},
            "historical_evidence": {},
            "completion": {},
            "models": {},
            "checkpoint_selection": {},
            "layout": {
                "evaluation_lock": {
                    "path": str(lock_path),
                    "size": lock_path.stat().st_size,
                    "sha256": _sha256(lock_path.read_bytes()),
                }
            },
        }
        raw = trace.canonical_json_bytes(manifest)
        (self.v4 / "input_freeze.json").write_bytes(raw)
        self.contract = dataclasses.replace(self.contract, manifest_sha256=_sha256(raw))
        patch = mock.patch.object(
            diagnose, "production_contract", return_value=self.contract
        )
        patch.start()
        self.addCleanup(patch.stop)
        tools = []
        for name in diagnose.PRODUCTION_FILES:
            (self.root / "tools" / name).write_bytes(name.encode())
            tools.append(
                trace.stable_file_record(
                    self.root / "tools" / name, allowed_root=self.root / "tools"
                )
            )
        fixture = FrozenContractTests()
        fixture.root = self.root
        self.freeze = fixture.complete_audit(tools)
        self.freeze["roots"]["v4_root"] = str(self.v4)
        self.freeze["status"] = "INPUTS_FROZEN"
        self.freeze["v4"]["verified_pinned_files"] = pinned
        raw = trace.canonical_json_bytes(self.freeze)
        (self.root / "input_freeze.json").write_bytes(raw)
        self.args.expected_input_freeze_sha256 = _sha256(raw)
        self.args.spool_runner = str(self.root / "tools/run_numeric_diag.sbatch")
        self.binding.freeze = self.args.expected_input_freeze_sha256
        self.binding.runner = _sha256(b"run_numeric_diag.sbatch")
        for value in (self.binding.intent, self.binding.response, self.binding.receipt):
            value["input_freeze_sha256"] = self.binding.freeze
            value["runner_sha256"] = self.binding.runner
            if "argv" in value:
                value["argv"][-2] = self.binding.freeze
        self.binding.receipt["intent_record_sha256"] = _sha256(
            trace.canonical_json_bytes(self.binding.intent)
        )
        self.binding.receipt["response_record_sha256"] = _sha256(
            trace.canonical_json_bytes(self.binding.response)
        )
        for name, value in (
            ("INTENT.json", self.binding.intent),
            ("SBATCH_RESPONSE.json", self.binding.response),
            ("SUBMISSION_RECEIPT.json", self.binding.receipt),
        ):
            self.binding.save(name, value)

    def owner(self):
        return diagnose._CoordinatorOwner(self.args)

    def test_authorize_then_claim_archives_spool_and_pre_inputs_cover_every_category(
        self,
    ):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        with owner.lock() as fd:
            owner.verify_lock(fd)
            records = owner.inputs()["records"]
        paths = {r["path"] for r in records}
        self.assertTrue(
            {r["path"] for r in self.freeze["v4"]["verified_pinned_files"]}.issubset(
                paths
            )
        )
        for path in (
            self.root / "input_freeze.json",
            self.root / "submitted_runners/123.sbatch",
            self.root / "tools/test-clips/a.wav",
            self.root / "tools/test-snapshot/x.py",
            self.root / "state/SUBMISSION_RECEIPT.json",
        ):
            self.assertIn(str(path), paths)
        with self.assertRaises(FileExistsError):
            owner.claim()

    def test_changed_external_input_is_detected_each_time(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        for path in (
            self.root / "tools/test-clips/a.wav",
            self.root / "tools/test-snapshot/x.py",
            self.v4 / "formal-final.ckpt",
            self.root / "tools/numeric_trace.py",
            self.root / "submitted_runners/123.sbatch",
            self.root / "input_freeze.json",
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(b"changed")
                with self.assertRaises(diagnose.DiagnosticError):
                    owner.inputs()
                path.write_bytes(original)

    def test_actual_lock_excludes_writer_until_terminal_fsync(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        lock = self.v4 / "state/evaluation.lock"
        with owner.lock() as fd:
            owner.verify_lock(fd)
            probe = os.open(lock, os.O_RDONLY)
            try:
                with self.assertRaises(BlockingIOError):
                    diagnose.fcntl.flock(
                        probe, diagnose.fcntl.LOCK_EX | diagnose.fcntl.LOCK_NB
                    )
                owner.publish("DIAGNOSTIC_FAILED.json", {"status": "DIAGNOSTIC_FAILED"})
                with self.assertRaises(BlockingIOError):
                    diagnose.fcntl.flock(
                        probe, diagnose.fcntl.LOCK_EX | diagnose.fcntl.LOCK_NB
                    )
            finally:
                os.close(probe)

    def test_same_content_lock_replacement_is_rejected_within_invocation(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        lock = self.v4 / "state/evaluation.lock"
        with self.assertRaises(diagnose.DiagnosticError):
            with owner.lock() as fd:
                owner.verify_lock(fd)
                data = lock.read_bytes()
                lock.unlink()
                lock.write_bytes(data)
                owner.verify_lock(fd)

    def test_owner_rejects_forbidden_marker_even_as_dangling_symlink(self):
        owner = self.owner()
        path = self.root / "state/SMOKE_PASS.json"
        path.symlink_to(self.root / "missing")
        with self.assertRaises(diagnose.DiagnosticError):
            owner.authorize()

    def test_no_second_owner_or_another_attempt_is_accepted(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        again = self.owner()
        again.authorize()
        with self.assertRaises(FileExistsError):
            again.claim()
        self.assertFalse((self.root / "state/DIAGNOSTIC_FAILED.json").exists())

    def test_owner_namespace_cannot_publish_science_or_arbitrary_file(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        for name in ("SMOKE_PASS.json", "../escape", "COMPLETE.json", "x.json"):
            with self.assertRaises(diagnose.DiagnosticError):
                owner.publish(name, {})

    def test_complete_then_write_failure_never_creates_opposite_marker(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        owner.publish("DIAGNOSTIC_FAILED.json", {"status": "DIAGNOSTIC_FAILED"})
        with self.assertRaises(FileExistsError):
            owner.publish("DIAGNOSTIC_COMPLETE.json", {"status": "DIAGNOSTIC_COMPLETE"})

    def test_attempt_replacement_cannot_redirect_owner_output(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        original = owner.attempt
        original.rename(original.with_name("preserved-original"))
        original.mkdir(mode=0o700)
        with self.assertRaises(diagnose.DiagnosticError):
            owner.publish("RUNNING.json", {})
        self.assertFalse((original / "RUNNING.json").exists())

    def test_pipeline_preserves_primary_and_real_v4_write_race(self):
        owner = self.owner()

        def failed_matrix():
            (self.v4 / "late-runner-log").write_bytes(b"official runner race")
            raise ValueError("child crash")

        owner.matrix = failed_matrix
        result = diagnose._coordinate(self.args, owner)
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertEqual(result["primary_error"]["message"], "child crash")
        self.assertIn(
            "INVALID_FROZEN_ROOT_CHANGED", [r["code"] for r in result["post_errors"]]
        )
        saved = json.loads((self.root / "state/DIAGNOSTIC_FAILED.json").read_text())
        self.assertEqual(saved, result)
        self.assertFalse((self.root / "state/DIAGNOSTIC_COMPLETE.json").exists())

    def test_matrix_uses_frozen_source_records_without_invented_path_fields(self):
        owner = self.owner()
        owner.authorize()
        owner.claim()
        result = {"summary": {"targeted_trace_cells": []}}
        with (
            mock.patch.object(diagnose, "_historical_scene_binding", return_value={}),
            mock.patch.object(diagnose, "_worker_historical_hashes", return_value={}),
            mock.patch.object(diagnose, "_ColdChildLauncher"),
            mock.patch.object(
                diagnose, "_run_matrix_sequence", return_value=result
            ) as run,
        ):
            owner.matrix()
        self.assertEqual(
            run.call_args.kwargs["source_records"], self.freeze["snapshot_files"]
        )


class ResultVerifierTests(unittest.TestCase):
    """Real persisted CPU matrix + real owner/journal; never a GPU result."""

    def setUp(self):
        self.matrix = PersistedMatrixTests()
        self.matrix.setUp()
        self.addCleanup(self.matrix.doCleanups)
        self.files = CoordinatorFileOwnerTests()
        self.files.setUp()
        self.addCleanup(self.files.doCleanups)
        self.root, self.args = self.files.root, self.files.args
        self.matrix.root = self.root
        self.matrix.attempt = self.root / "attempts/slurm-123"
        env_patch = mock.patch.dict(
            os.environ,
            {
                "SLURM_JOB_ID": "123",
                "CUDA_VISIBLE_DEVICES": "0",
                "DIAG_SCRATCH_ROOT": str(self.matrix.scratch),
            },
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.matrix.sources = self.files.freeze["snapshot_files"]
        for row in self.matrix.trials:
            row["identity"] = {
                key: row["identity"].get(key, row["trial_id"])
                for key in diagnose.TRIAL_IDENTITY_COLUMNS
            }
        original_data = self.matrix.data

        def complete_trial_schema(*args, **kwargs):
            result = original_data(*args, **kwargs)
            result["input_freeze_sha256"] = self.matrix.sha
            result["trials"] = tuple(
                dataclasses.replace(
                    t, identity=self.matrix.trials[t.ordinal]["identity"]
                )
                for t in result["trials"]
            )
            return result

        self.matrix.data = complete_trial_schema
        self.files.freeze["trials"] = self.matrix.trials
        self.files.freeze["clips"][0]["uses"][0]["trial_id"] = self.matrix.trials[0][
            "trial_id"
        ]
        raw = trace.canonical_json_bytes(self.files.freeze)
        (self.root / "input_freeze.json").write_bytes(raw)
        self.args.expected_input_freeze_sha256 = self.matrix.sha = _sha256(raw)
        b = self.files.binding
        for value in (b.intent, b.response, b.receipt):
            value["input_freeze_sha256"] = self.matrix.sha
            if "argv" in value:
                value["argv"][-2] = self.matrix.sha
        b.receipt["intent_record_sha256"] = _sha256(
            trace.canonical_json_bytes(b.intent)
        )
        b.receipt["response_record_sha256"] = _sha256(
            trace.canonical_json_bytes(b.response)
        )
        for name, value in (
            ("INTENT.json", b.intent),
            ("SBATCH_RESPONSE.json", b.response),
            ("SUBMISSION_RECEIPT.json", b.receipt),
        ):
            b.save(name, value)
        # The real history reader has its own tests. This fixture has no 10k CSV.
        for name, value in (
            ("_historical_scene_binding", {}),
            ("_worker_historical_hashes", self.matrix.history),
        ):
            patch = mock.patch.object(diagnose, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def complete(self):
        owner = self.files.owner()
        owner.matrix = lambda: self.matrix.sequence(delta=0.0077362060546875)
        self.report = diagnose._coordinate(self.args, owner)
        self.assertEqual(
            self.report["status"], "DIAGNOSTIC_COMPLETE", self.report["primary_error"]
        )
        return self.report

    def verify(self):
        return diagnose.verify_results(self.matrix.sha, "123")

    def rewrite_terminal(self, change, *, refresh_inventory=False):
        path = self.root / "state/DIAGNOSTIC_COMPLETE.json"
        value = json.loads(path.read_bytes())
        change(value)
        if refresh_inventory:
            value["artifact_inventory"] = diagnose._terminal_inventory(
                self.matrix.attempt
            )
        path.write_bytes(trace.canonical_json_bytes(value))

    def test_complete_finite_diff_recomputed_without_writes_or_inference(self):
        self.complete()
        before = trace.fingerprint_tree(self.root)
        with (
            mock.patch.object(
                diagnose, "_ColdChildLauncher", side_effect=AssertionError("no launch")
            ),
            mock.patch.object(
                diagnose, "atomic_create_bytes", side_effect=AssertionError("no writes")
            ),
            mock.patch.object(
                diagnose.subprocess, "Popen", side_effect=AssertionError("no process")
            ),
        ):
            result = self.verify()
        self.assertEqual(result["status"], "DIAGNOSTIC_RESULTS_VERIFIED")
        self.assertEqual(result["matrix"]["a2_replay_classification"], "REPRODUCED")
        self.assertEqual(result["evaluation_role"], diagnose.EVALUATION_ROLE)
        self.assertEqual(trace.fingerprint_tree(self.root), before)

    def test_terminal_inventory_binds_every_attempt_file(self):
        report = self.complete()
        inventory = report["artifact_inventory"]
        expected = {
            p.relative_to(self.matrix.attempt).as_posix()
            for p in self.matrix.attempt.rglob("*")
            if p.is_file()
        }
        self.assertEqual({r["relative_path"] for r in inventory["files"]}, expected)
        self.assertIn("ENVIRONMENT.json", expected)
        self.assertIn("cells/B2/CELL_COMPLETE.json", expected)

    def test_missing_terminal_is_incomplete_not_success_or_retry(self):
        result = self.verify()
        self.assertEqual(result["status"], "INCOMPLETE_NO_TERMINAL")
        self.assertFalse(result["results_verified"])
        self.assertFalse((self.root / "attempts/slurm-123").exists())

    def test_failed_marker_is_failure_evidence_not_matrix_success(self):
        owner = self.files.owner()
        owner.matrix = mock.Mock(side_effect=ValueError("synthetic crash"))
        diagnose._coordinate(self.args, owner)
        result = self.verify()
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILURE_RECORDED")
        self.assertFalse(result["results_verified"])
        self.assertEqual(result["primary_error"]["message"], "synthetic crash")

    def test_missing_receipt_does_not_wait_or_recreate(self):
        self.complete()
        (self.root / "state/SUBMISSION_RECEIPT.json").unlink()
        with mock.patch.object(
            diagnose.time, "sleep", side_effect=AssertionError("must not wait")
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                self.verify()

    def test_ephemeral_spool_and_scratch_not_required_after_completion(self):
        spool = self.matrix.base / "slurm-script"
        spool.write_bytes(b"run_numeric_diag.sbatch")
        self.args.spool_runner = str(spool)
        self.complete()
        spool.unlink()
        __import__("shutil").rmtree(self.matrix.scratch)
        self.assertEqual(self.verify()["status"], "DIAGNOSTIC_RESULTS_VERIFIED")

    def test_extra_missing_corrupt_and_aliased_artifacts_rejected(self):
        self.complete()
        path = self.matrix.attempt / "ENVIRONMENT.json"
        original = path.read_bytes()
        for case in ("extra", "missing", "corrupt", "symlink", "hardlink", "directory"):
            extra = self.matrix.attempt / "unexpected"
            with self.subTest(case=case):
                if case == "extra":
                    extra.write_bytes(b"x")
                if case == "directory":
                    extra.mkdir()
                if case in ("missing", "symlink"):
                    path.unlink()
                if case == "corrupt":
                    path.write_bytes(b"{}\n")
                if case == "symlink":
                    path.symlink_to(self.root / "input_freeze.json")
                if case == "hardlink":
                    os.link(path, extra)
                with self.assertRaises((diagnose.DiagnosticError, FileNotFoundError)):
                    self.verify()
                if extra.is_dir():
                    extra.rmdir()
                elif extra.exists():
                    extra.unlink()
                if path.is_symlink():
                    path.unlink()
                path.write_bytes(original)
                path.chmod(0o600)

    def test_rehashed_summary_cannot_replace_recomputation(self):
        self.complete()
        path = self.matrix.attempt / "MATRIX_SUMMARY.json"
        summary = json.loads(path.read_bytes())
        summary["a2_replay_classification"] = "NOT_REPRODUCED"
        path.write_bytes(trace.canonical_json_bytes(summary))
        with diagnose._MatrixArtifactStore(self.matrix.attempt) as store:
            record = store.record("MATRIX_SUMMARY.json")

        def change(value):
            value["matrix"]["summary"] = summary
            value["matrix"]["summary_record"] = record

        self.rewrite_terminal(change, refresh_inventory=True)
        with self.assertRaises(diagnose.DiagnosticError):
            self.verify()

    def test_terminal_identity_and_post_conditions_are_not_trusted(self):
        self.complete()
        path = self.root / "state/DIAGNOSTIC_COMPLETE.json"
        original = path.read_bytes()
        changes = [
            lambda v: v.update(job_id="999"),
            lambda v: v.update(lock_acquired=False),
            lambda v: v["post"].update(inputs={"records": []}),
            lambda v: v.update(primary_error={"message": "failed"}),
            lambda v: v.update(evaluation_role="INDEPENDENT_TEST"),
            lambda v: v["authorization"].update(intent_nonce="f" * 32),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                self.rewrite_terminal(change)
                with self.assertRaises(diagnose.DiagnosticError):
                    self.verify()
                path.write_bytes(original)

    def test_conflicting_and_forbidden_markers_rejected(self):
        self.complete()
        for name in ("DIAGNOSTIC_FAILED.json", *diagnose.FORBIDDEN_SCIENCE_MARKERS):
            path = self.root / "state" / name
            path.write_bytes(b"{}\n")
            with self.subTest(name=name), self.assertRaises(diagnose.DiagnosticError):
                self.verify()
            path.unlink()

    def test_changed_v4_unpinned_file_or_bound_external_input_rejected(self):
        self.complete()
        path = self.files.v4 / "late-log"
        path.write_bytes(b"late official runner")
        with self.assertRaises(diagnose.DiagnosticError):
            self.verify()
        path.unlink()
        # Restore directory mtime: the second rejection must be the clip itself.
        recorded = self.report["post"]["tree"]
        self.assertEqual(recorded, trace.fingerprint_tree(self.files.v4))
        (self.root / "tools/test-clips/a.wav").write_bytes(b"other audio")
        with self.assertRaises(diagnose.DiagnosticError):
            self.verify()

    def test_cross_node_device_inode_only_differences_are_diagnostic(self):
        self.complete()

        def change(value):
            for side in ("pre", "post"):
                tree = value[side]["tree"]
                for row in tree["entries"]:
                    row["st_dev"] += 17
                    row["st_ino"] += 19
                fields = (
                    "relative_path",
                    "type",
                    "mode",
                    "size",
                    "st_mtime_ns",
                    "st_dev",
                    "st_ino",
                    "symlink_target",
                )
                tree["tree_sha256"] = _sha256(
                    b"".join(_field(r[k]) for r in tree["entries"] for k in fields)
                )
                p = self.matrix.attempt / (
                    "PRECHECK.json" if side == "pre" else "POSTCHECK.json"
                )
                p.write_bytes(trace.canonical_json_bytes(value[side]))

        self.rewrite_terminal(change, refresh_inventory=True)
        self.assertEqual(self.verify()["status"], "DIAGNOSTIC_RESULTS_VERIFIED")

    def test_rehashed_owner_environment_cannot_claim_a_different_gpu_or_job(self):
        self.complete()
        path = self.matrix.attempt / "ENVIRONMENT.json"
        original = path.read_bytes()
        for key in ("SLURM_JOB_ID", "CUDA_VISIBLE_DEVICES", "DIAG_SCRATCH_ROOT"):
            with self.subTest(key=key):
                value = json.loads(original)
                value["environment"][key] = "999"
                path.write_bytes(trace.canonical_json_bytes(value))
                self.rewrite_terminal(lambda v: None, refresh_inventory=True)
                with self.assertRaises(diagnose.DiagnosticError):
                    self.verify()
                path.write_bytes(original)

    def test_read_only_cli_returns_nonzero_for_incomplete_or_failure(self):
        for status in (
            "INCOMPLETE_NO_TERMINAL",
            "DIAGNOSTIC_FAILURE_RECORDED",
            "DIAGNOSTIC_RESULTS_VERIFIED",
        ):
            with (
                self.subTest(status=status),
                mock.patch.object(
                    diagnose, "verify_results", return_value={"status": status}
                ),
                mock.patch.object(diagnose, "_emit") as emit,
            ):
                rc = diagnose.main(
                    [
                        "verify-results",
                        "--job-id",
                        "123",
                        "--expected-input-freeze-sha256",
                        self.matrix.sha,
                    ]
                )
                self.assertEqual(
                    rc, 0 if status == "DIAGNOSTIC_RESULTS_VERIFIED" else 2
                )
                emit.assert_called_once_with({"status": status})

    def test_owner_cannot_publish_completion_without_persisted_matrix(self):
        owner = self.files.owner()
        owner.authorize()
        owner.claim()
        fake = {
            "status": "DIAGNOSTIC_COMPLETE",
            "job_id": "123",
            "input_freeze_sha256": self.matrix.sha,
            "lock_acquired": True,
            "primary_error": None,
            "post_errors": [],
            "pre": {"tree": {}, "inputs": {}},
            "post": {"tree": {}, "inputs": {}},
            "matrix": {"status": "MATRIX_EVIDENCE_VERIFIED"},
        }
        with self.assertRaises((diagnose.DiagnosticError, FileNotFoundError)):
            owner.publish("DIAGNOSTIC_COMPLETE.json", fake)
        self.assertFalse((self.root / "state/DIAGNOSTIC_COMPLETE.json").exists())

    def test_targeted_trace_recommendation_binds_worst_trial_without_deep_root_cause(
        self,
    ):
        worst = {
            "trial_id": 117,
            "ordinal": 17,
            "pass1_index": 17,
            "pass2_index": 17,
            "selection_rule": "maximum_abs_difference__nonfinite_first__frozen_ordinal_tie",
        }
        matrix = {
            "summary": {
                "targeted_trace_cells": ["A2"],
                "cells": {"A2": {"worst_cases": {"native_logits": worst}}},
            },
            "summary_record": {
                "relative_path": "MATRIX_SUMMARY.json",
                "sha256": "a" * 64,
            },
        }
        result = diagnose._targeted_trace_document(matrix, "123")
        self.assertEqual(result["worst_trials"], {"A2": worst})
        self.assertEqual(result["matrix_summary_record"], matrix["summary_record"])
        self.assertEqual(
            result["first_subgraph"],
            "formal40 model forward (cochleagram inputs to native logits)",
        )
        self.assertNotIn("root_cause", result)


class ExecutionEntryTests(unittest.TestCase):
    """Entry contracts with fake frozen inputs; no production launch or GPU."""

    def setUp(self):
        self.fixture = CoordinatorFileOwnerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.args = self.fixture.root, self.fixture.args
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.scratch = pathlib.Path(self.temp.name) / "audattn_v4_numdiag_123"
        self.scratch.mkdir(mode=0o700)

    def coordinator_env(self):
        return diagnose.coordinator_environment(
            "123",
            str(self.scratch),
            {"SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"},
        )

    def prepare_scratch(self):
        env = self.coordinator_env()
        for name in set(diagnose._COORDINATOR_WRITE_PATHS.values()):
            (self.scratch / name).mkdir(mode=0o700)
        return env

    def test_coordinator_argv_has_no_shell_or_output_override(self):
        command = diagnose.coordinator_command(self.args)
        self.assertEqual(
            command[:4],
            [
                str(diagnose.PRODUCTION_PYTHON),
                "-I",
                "-B",
                str(self.root / "tools/diagnose_batch_invariance.py"),
            ],
        )
        self.assertEqual(
            command[4:],
            [
                "run-coordinator",
                "--job-id",
                "123",
                "--intent-nonce",
                self.args.intent_nonce,
                "--expected-input-freeze-sha256",
                self.args.expected_input_freeze_sha256,
                "--spool-runner",
                self.args.spool_runner,
            ],
        )
        self.args.spool_runner = "relative.sh"
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose.coordinator_command(self.args)

    def test_coordinator_write_locations_are_exclusive_and_allowlisted(self):
        env = self.coordinator_env()
        for key, relative in diagnose._COORDINATOR_WRITE_PATHS.items():
            self.assertEqual(env[key], str(self.scratch / relative))
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertEqual(env["PYTHONHASHSEED"], "0")

    def test_scratch_gate_validates_empty_owned_paths_and_restores_tempdir(self):
        env = self.prepare_scratch()
        previous = tempfile.tempdir
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                diagnose,
                "_require_local_scratch_mount",
                return_value={"filesystem": "fixture"},
            ),
        ):
            with diagnose._coordinator_scratch(self.args) as guard:
                guard()
                self.assertEqual(tempfile.tempdir, env["TMPDIR"])
                (self.scratch / "coordinator-cache" / "used").write_bytes(b"cache")
                guard()  # no requirement that caches remain empty after startup
        self.assertEqual(tempfile.tempdir, previous)

    def test_dirty_scratch_and_injected_environment_rejected(self):
        env = self.prepare_scratch()
        with mock.patch.object(
            diagnose, "_require_local_scratch_mount", return_value={}
        ):
            for key in ("PYTHONPATH", "LD_PRELOAD", "PYTHONSTARTUP"):
                with (
                    self.subTest(key=key),
                    mock.patch.dict(
                        os.environ, dict(env, **{key: "unreviewed"}), clear=True
                    ),
                ):
                    with self.assertRaises(diagnose.DiagnosticError):
                        with diagnose._coordinator_scratch(self.args):
                            pass
            (self.scratch / "coordinator-home" / "old").write_bytes(b"old")
            with (
                mock.patch.dict(os.environ, env, clear=True),
                self.assertRaises(diagnose.DiagnosticError),
            ):
                with diagnose._coordinator_scratch(self.args):
                    pass

    def test_coordinator_entry_gates_before_owner_and_uses_existing_lifecycle(self):
        events = []

        @contextlib.contextmanager
        def scratch(args):
            events.append("scratch")
            yield lambda: events.append("scratch_check")

        result = {"status": "DIAGNOSTIC_COMPLETE"}
        with (
            mock.patch.object(
                diagnose,
                "_claim_worker_process",
                side_effect=lambda: events.append("cold"),
            ),
            mock.patch.object(
                diagnose.sys, "argv", diagnose.coordinator_command(self.args)[3:]
            ),
            mock.patch.object(diagnose, "_worker_job_id", return_value="123"),
            mock.patch.object(diagnose, "_coordinator_scratch", side_effect=scratch),
            mock.patch.object(
                diagnose, "_CoordinatorOwner", return_value=types.SimpleNamespace()
            ),
            mock.patch.object(
                diagnose,
                "_coordinate",
                side_effect=lambda a, o: (events.append("coordinate") or result),
            ),
        ):
            self.assertEqual(diagnose.run_coordinator(self.args), result)
        self.assertEqual(events, ["cold", "scratch", "coordinate", "scratch_check"])

    def prepare_parent(self, cell=None):
        env = diagnose.child_environment(
            "_child-cell" if cell else "_child-reference",
            "123",
            cell,
            self.scratch,
            {"SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"},
        )
        parent_env = {
            "SLURM_JOB_ID": "123",
            "CUDA_VISIBLE_DEVICES": "0",
            "DIAG_SCRATCH_ROOT": str(self.scratch),
        }
        with mock.patch.dict(os.environ, parent_env):
            owner = self.fixture.owner()
            owner.authorize()
            owner.claim()
        owner.publish(
            "RUNNING.json",
            {
                "schema_version": 1,
                "status": "RUNNING",
                "diagnostic_protocol": diagnose.DIAGNOSTIC_PROTOCOL,
                "evaluation_role": diagnose.EVALUATION_ROLE,
                "job_id": "123",
                "input_freeze_sha256": self.args.expected_input_freeze_sha256,
            },
        )
        proc = {
            "pid": os.getpid(),
            "uid": os.getuid(),
            "start_time": "12345",
            "executable": str(diagnose.PRODUCTION_PYTHON.resolve()),
            "argv": diagnose.coordinator_command(self.args),
        }
        return env, proc

    def test_child_requires_live_parent_and_matching_job_receipt_without_numeric_import(
        self,
    ):
        env, proc = self.prepare_parent("A2")
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(diagnose.os, "getppid", return_value=proc["pid"]),
            mock.patch.object(diagnose, "_read_parent_process", return_value=proc),
            mock.patch.object(
                diagnose, "_get_trace", side_effect=AssertionError("premature import")
            ),
        ):
            diagnose._authorize_child_parent(self.args, "A2")

    def test_wrong_parent_command_pid_environment_or_completed_attempt_rejected(self):
        env, proc = self.prepare_parent()
        for key, bad in (
            ("argv", ["python", "unreviewed.py"]),
            ("pid", 42),
            ("uid", os.getuid() + 1),
            ("executable", "/bin/false"),
        ):
            with (
                self.subTest(key=key),
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(diagnose.os, "getppid", return_value=proc["pid"]),
                mock.patch.object(
                    diagnose,
                    "_read_parent_process",
                    return_value=dict(proc, **{key: bad}),
                ),
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._authorize_child_parent(self.args, None)
        (self.root / "state/DIAGNOSTIC_FAILED.json").write_bytes(b"{}\n")
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(diagnose.os, "getppid", return_value=proc["pid"]),
            mock.patch.object(diagnose, "_read_parent_process", return_value=proc),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._authorize_child_parent(self.args, None)

    def test_child_entry_does_not_enter_worker_when_parent_auth_fails(self):
        with (
            mock.patch.object(diagnose, "_require_cold_worker_interpreter"),
            mock.patch.object(
                diagnose,
                "_authorize_child_parent",
                side_effect=diagnose.DiagnosticError("not parent"),
            ),
            mock.patch.object(diagnose, "run_reference_cold") as worker,
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose._dispatch_child(self.args, None)
            worker.assert_not_called()

    def test_cli_dispatches_only_complete_fixed_execution_arguments(self):
        command = diagnose.coordinator_command(self.args)[4:]
        with (
            mock.patch.object(
                diagnose,
                "run_coordinator",
                return_value={"status": "DIAGNOSTIC_FAILED"},
            ),
            mock.patch.object(diagnose, "_emit"),
        ):
            self.assertEqual(diagnose.main(command), 2)
        for mode in ("_child-reference", "_child-cell"):
            args = [
                mode,
                "--job-id",
                "123",
                "--expected-input-freeze-sha256",
                self.args.expected_input_freeze_sha256,
            ]
            if mode == "_child-cell":
                args += ["--cell", "B2"]
            with (
                mock.patch.object(
                    diagnose,
                    "_dispatch_child",
                    return_value={"status": "CHILD_ARTIFACTS_READY"},
                ) as dispatch,
                mock.patch.object(diagnose, "_emit"),
            ):
                self.assertEqual(diagnose.main(args), 0)
                self.assertEqual(
                    dispatch.call_args.args[1], "B2" if mode == "_child-cell" else None
                )

    def test_scratch_guard_participates_in_post_failure_record(self):
        owner = self.fixture.owner()
        owner.execution_guard = mock.Mock(
            side_effect=[None, diagnose.DiagnosticError("scratch replaced")]
        )
        owner.matrix = mock.Mock(side_effect=ValueError("fixture child failure"))
        result = diagnose._coordinate(self.args, owner)
        self.assertEqual(result["status"], "DIAGNOSTIC_FAILED")
        self.assertTrue(
            any("scratch replaced" in r["message"] for r in result["post_errors"])
        )

    def test_preexisting_child_or_unknown_scratch_subtree_is_not_reused(self):
        env = self.prepare_scratch()
        (self.scratch / "reference_cold").mkdir(mode=0o700)
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                diagnose, "_require_local_scratch_mount", return_value={}
            ),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                with diagnose._coordinator_scratch(self.args):
                    pass

    def test_parent_proc_parser_handles_spaces_and_parentheses_and_bounds_bytes(self):
        proc = pathlib.Path(self.temp.name) / "proc"
        pid = 43210
        root = proc / str(pid)
        root.mkdir(parents=True)
        fields = ["S"] + ["0"] * 18 + ["87654"] + ["0"] * 8
        (root / "stat").write_bytes(
            f"{pid} (name ) with spaces) {' '.join(fields)}\n".encode()
        )
        (root / "cmdline").write_bytes(b"/python\0-I\0-B\0/script.py\0")
        (root / "exe").symlink_to("/python")
        value = diagnose._read_proc_parent_identity(proc, pid)
        self.assertEqual(value["start_time"], "87654")
        self.assertEqual(value["argv"], ["/python", "-I", "-B", "/script.py"])
        (root / "cmdline").write_bytes(b"x" * 65537)
        with self.assertRaises(diagnose.DiagnosticError):
            diagnose._read_proc_parent_identity(proc, pid)

    def test_parent_start_time_change_or_reparenting_rejected(self):
        env, proc = self.prepare_parent()
        for case in ("start", "ppid"):
            with (
                self.subTest(case=case),
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(
                    diagnose.os,
                    "getppid",
                    side_effect=[proc["pid"], 1 if case == "ppid" else proc["pid"]],
                ),
                mock.patch.object(
                    diagnose,
                    "_read_parent_process",
                    side_effect=[proc, dict(proc, start_time="other")],
                ),
            ):
                with self.assertRaises(diagnose.DiagnosticError):
                    diagnose._authorize_child_parent(self.args, None)

    def test_rejected_execution_cli_emits_pure_json_without_numerical_import(self):
        code = (
            "import importlib.util,sys,json;"
            f"s=importlib.util.spec_from_file_location('entry_test',{str(DIAGNOSER)!r});"
            "m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);"
            "rc=m.main(['_child-reference','--job-id','123','--expected-input-freeze-sha256','d'*64]);"
            "assert rc==2;assert m._TRACE is None;"
            "assert not any(n.split('.')[0] in ('torch','numpy','pandas','torchaudio') for n in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code], capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(json.loads(result.stdout)["status"], "ERROR")
        self.assertEqual(
            result.stdout, trace.canonical_json_bytes(json.loads(result.stdout))
        )

    def test_coordinator_rejects_noncanonical_actual_invocation_before_claim(self):
        with (
            mock.patch.object(diagnose, "_worker_job_id", return_value="123"),
            mock.patch.object(diagnose, "_claim_worker_process") as claim,
            mock.patch.object(
                diagnose, "_coordinator_scratch", side_effect=AssertionError("too late")
            ),
            mock.patch.object(diagnose.sys, "argv", ["-c", "unreviewed"]),
        ):
            with self.assertRaises(diagnose.DiagnosticError):
                diagnose.run_coordinator(self.args)
            claim.assert_not_called()


if __name__ == "__main__":
    unittest.main()
