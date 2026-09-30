#!/usr/bin/env python3
"""Release-blocking unit tests for ``locked_same_bank_eval.py``.

These tests intentionally exercise fail-closed properties without loading the
large checkpoints or the audio corpus.  The real HAKUSAN smoke run remains a
separate integration test.
"""

from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import threading
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd


MODULE_PATH = pathlib.Path(__file__).with_name("locked_same_bank_eval.py")
SPEC = importlib.util.spec_from_file_location("locked_same_bank_eval_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


class FakeTensor:
    def __init__(self, shape: tuple[int, ...] = (1,), dtype: str = "float32") -> None:
        self.shape = shape
        self.dtype = dtype

    def numel(self) -> int:
        return int(np.prod(self.shape))

    def is_floating_point(self) -> bool:
        return self.dtype.startswith("float")

    def is_complex(self) -> bool:
        return self.dtype.startswith("complex")


def valid_role_manifest() -> dict:
    return {
        "schema_version": EVAL.SCHEMA_VERSION,
        "protocol_id": EVAL.PROTOCOL_ID,
        "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
        "role_confirmation": EVAL.EXPECTED_ROLE_CONFIRMATION,
        "evaluation_role": EVAL.EVALUATION_ROLE,
        "models": {
            model_id: {"role": EVAL.MODEL_ROLES[model_id]}
            for model_id in EVAL.MODEL_IDS
        },
    }


def valid_result_frame(*, control: bool = True) -> pd.DataFrame:
    row: dict[str, object] = {
        "trial_id": 0,
        "scene_kind": "mixed",
        "control_subset": int(control),
        "target_speaker": "speaker-001",
        "target_gender": "female",
        "target_norm": "about",
        "target_label": 3,
        "distractor_count": 1,
        "snr_bin": 0,
        "snr_db": -10.0,
        "probe_distractor_norm": "above",
        "probe_distractor_label": 4,
        "scene_sha256": "a" * 64,
        "correct_cue_sha256": "b" * 64,
    }
    for model_id in EVAL.MODEL_IDS:
        row.update(
            {
                f"{model_id}_pred_label": 3,
                f"{model_id}_correct": 1,
                f"{model_id}_nll": 0.25,
                f"{model_id}_p_target": 0.75,
                f"{model_id}_p_probe_distractor": 0.05,
            }
        )
        for condition in EVAL.CONTROL_CONDITIONS:
            prefix = f"{model_id}_{condition}"
            if control:
                row.update(
                    {
                        f"{prefix}_pred_label": 3,
                        f"{prefix}_correct": 1,
                        f"{prefix}_nll": 0.5,
                        f"{prefix}_p_target": 0.6,
                        f"{prefix}_probe_intrusion": 0,
                        f"{prefix}_p_probe_distractor": 0.1,
                    }
                )
            else:
                row.update(
                    {
                        f"{prefix}_pred_label": np.nan,
                        f"{prefix}_correct": np.nan,
                        f"{prefix}_nll": np.nan,
                        f"{prefix}_p_target": np.nan,
                        f"{prefix}_probe_intrusion": np.nan,
                        f"{prefix}_p_probe_distractor": np.nan,
                    }
                )
    return pd.DataFrame([row])


class RoleAndDigestTests(unittest.TestCase):
    def test_exact_locked_roles_pass(self) -> None:
        EVAL.validate_role_manifest(valid_role_manifest())

    def test_any_role_mutation_or_extra_model_fails(self) -> None:
        cases = []
        changed_confirmation = valid_role_manifest()
        changed_confirmation["role_confirmation"] = "author-primary"
        cases.append(changed_confirmation)
        changed_role = valid_role_manifest()
        changed_role["models"]["formal40"]["role"] = "secondary"
        cases.append(changed_role)
        extra_model = valid_role_manifest()
        extra_model["models"]["candidate_after_audit"] = {"role": "primary"}
        cases.append(extra_model)
        missing_model = valid_role_manifest()
        del missing_model["models"]["author_external"]
        cases.append(missing_model)
        for manifest in cases:
            with self.subTest(manifest=manifest), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_role_manifest(manifest)

    def test_sha_parser_requires_canonical_lowercase(self) -> None:
        digest = "ab" * 32
        self.assertEqual(EVAL._require_sha(digest, "test"), digest)
        for invalid in (digest.upper(), "a" * 63, "g" * 64, "", " " + digest):
            with self.subTest(invalid=invalid), self.assertRaises(EVAL.EvaluationError):
                EVAL._require_sha(invalid, "test")


class StateDictionaryTests(unittest.TestCase):
    def test_selftrain_requires_exact_keys(self) -> None:
        tensor = FakeTensor()
        mapped, rule = EVAL.canonicalize_state_dict_keys(
            {"model.layer": tensor, "coch_gram.window": tensor},
            ["model.layer", "coch_gram.window"],
            allow_compile_wrapper_rewrite=False,
        )
        self.assertEqual(set(mapped), {"model.layer", "coch_gram.window"})
        self.assertEqual(rule, "exact")
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.canonicalize_state_dict_keys(
                {"model._orig_mod.layer": tensor, "coch_gram.window": tensor},
                ["model.layer", "coch_gram.window"],
                allow_compile_wrapper_rewrite=False,
            )

    def test_author_allows_only_uniform_compile_wrapper_rewrite(self) -> None:
        tensor = FakeTensor()
        mapped, rule = EVAL.canonicalize_state_dict_keys(
            {
                "model._orig_mod.layer1": tensor,
                "model._orig_mod.layer2": tensor,
                "coch_gram.window": tensor,
            },
            ["model.layer1", "model.layer2", "coch_gram.window"],
            allow_compile_wrapper_rewrite=True,
        )
        self.assertEqual(set(mapped), {"model.layer1", "model.layer2", "coch_gram.window"})
        self.assertEqual(rule, "remove_model._orig_mod")

        # A partially wrapped checkpoint is not one whole-model compile-prefix
        # rewrite and therefore must not be silently normalized.
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.canonicalize_state_dict_keys(
                {
                    "model._orig_mod.layer1": tensor,
                    "model.layer2": tensor,
                    "coch_gram.window": tensor,
                },
                ["model.layer1", "model.layer2", "coch_gram.window"],
                allow_compile_wrapper_rewrite=True,
            )

    def test_state_compatibility_rejects_shape_and_dtype_mismatch(self) -> None:
        expected = {"model.weight": FakeTensor((2, 3), "float32")}
        for actual in (
            {"model.weight": FakeTensor((3, 2), "float32")},
            {"model.weight": FakeTensor((2, 3), "float16")},
        ):
            with self.subTest(actual=actual), self.assertRaises(EVAL.EvaluationError):
                EVAL.audit_state_dict_compatibility(
                    actual, expected, allow_compile_wrapper_rewrite=False
                )

    def test_valbest_checkpoint_raw_lightning_progress_is_hard_bound(self) -> None:
        expected_progress = copy.deepcopy(EVAL.EXPECTED_EPOCH_PROGRESS["valbest33"])
        checkpoint = {
            "epoch": 33,
            "global_step": 59024,
            "pytorch-lightning_version": "2.1.1",
            "state_dict": {"model.weight": FakeTensor()},
            "loops": {"fit_loop": {"epoch_progress": expected_progress}},
            "audattn_amp_state_v1": {
                "total_optimizer_attempts": 59024,
                "successful_optimizer_steps": 59001,
                "total_overflows": 23,
            },
            "audattn_run_metadata_v1": {
                "run_id": EVAL.RUN_ID,
                "source_semantic_sha256": EVAL.EXPECTED_HASHES["source_semantic"],
                "config_sha256": EVAL.EXPECTED_HASHES["full_config"],
            },
        }
        record = {
            "path": "/frozen/epoch=33-step=59024.ckpt",
            "basename": "epoch=33-step=59024.ckpt",
            "size": 1,
            "sha256": "a" * 64,
        }
        with mock.patch.object(EVAL, "_load_torch_checkpoint", return_value=checkpoint):
            inspected, _ = EVAL.inspect_checkpoint(
                record, "valbest33", EVAL.EXPECTED_HASHES["source_semantic"]
            )
        self.assertEqual(inspected["epoch_progress"], expected_progress)

        for section, field in (("total", "completed"), ("current", "completed")):
            changed = copy.deepcopy(checkpoint)
            changed["loops"]["fit_loop"]["epoch_progress"][section][field] += 1
            with mock.patch.object(EVAL, "_load_torch_checkpoint", return_value=changed):
                with self.subTest(section=section), self.assertRaises(EVAL.EvaluationError):
                    EVAL.inspect_checkpoint(
                        record,
                        "valbest33",
                        EVAL.EXPECTED_HASHES["source_semantic"],
                    )


class BootstrapTests(unittest.TestCase):
    def test_cluster_bootstrap_is_deterministic_and_paired(self) -> None:
        values = np.asarray([1.0, -1.0, 0.5, 0.5, 2.0])
        speakers = np.asarray(["a", "a", "b", "b", "c"])
        first = EVAL.cluster_bootstrap_ci(values, speakers, 1234, 500)
        second = EVAL.cluster_bootstrap_ci(values, speakers, 1234, 500)
        self.assertEqual(first, second)
        self.assertLessEqual(first[0], values.mean())
        self.assertGreaterEqual(first[1], values.mean())

    def test_cluster_bootstrap_constant_difference_is_degenerate(self) -> None:
        low, high = EVAL.cluster_bootstrap_ci(
            np.ones(6), np.asarray(["a", "a", "b", "b", "c", "c"]), 7, 100
        )
        self.assertEqual((low, high), (1.0, 1.0))

    def test_cluster_bootstrap_rejects_missing_or_empty_speaker_ids(self) -> None:
        invalid_speakers = (
            np.asarray(["a", ""]),
            np.asarray(["a", None], dtype=object),
            np.asarray(["a", np.nan], dtype=object),
        )
        for speakers in invalid_speakers:
            with self.subTest(speakers=speakers), self.assertRaises(EVAL.EvaluationError):
                EVAL.cluster_bootstrap_ci(np.asarray([0.0, 1.0]), speakers, 1, 10)

    def test_cluster_bootstrap_rejects_nonfinite_or_bad_alignment(self) -> None:
        cases = (
            (np.asarray([]), np.asarray([]), 10),
            (np.asarray([np.nan]), np.asarray(["a"]), 10),
            (np.asarray([1.0]), np.asarray(["a", "b"]), 10),
            (np.asarray([1.0]), np.asarray(["a"]), 0),
        )
        for values, speakers, repetitions in cases:
            with self.subTest(values=values, speakers=speakers), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.cluster_bootstrap_ci(values, speakers, 1, repetitions)


class SelectionEvidenceTests(unittest.TestCase):
    @staticmethod
    def _write_lineage(root: pathlib.Path, peak_epoch: int = 33) -> dict:
        jobs: dict[str, dict] = {}
        segments = {
            "575142": range(0, 4),
            "587802": range(4, 17),
            "614647": range(17, 30),
            "628071": range(30, 40),
        }
        for job_id, epochs in segments.items():
            lines = []
            for epoch in epochs:
                val_acc = 0.453 if epoch == peak_epoch else 0.400 + epoch / 10_000
                attempts = (epoch + 1) * EVAL.EXPECTED_ATTEMPTS_PER_EPOCH
                lines.append(
                    "Epoch {epoch}: 100%|##########| val_loss_epoch=2.800, "
                    "val_acc={val_acc:.3f}, train_loss_epoch=1.000, "
                    "train_acc=0.700]AMP epoch summary: epoch={epoch}, "
                    "epoch_overflows=0, epoch_attempts=1736, "
                    "epoch_successful_steps=1736, total_overflows=0, "
                    "total_attempts={attempts}, total_successful_steps={attempts}\n".format(
                        epoch=epoch,
                        val_acc=val_acc,
                        attempts=attempts,
                    )
                )
            payload = "".join(lines).encode("utf-8")
            path = root / f"{job_id}.log"
            path.write_bytes(payload)
            jobs[job_id] = {
                "log": {
                    "path": str(path),
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            }
        return {"lineage": {"jobs": jobs}}

    def test_log_selection_requires_unique_epoch33_maximum(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            audit = self._write_lineage(pathlib.Path(raw), peak_epoch=33)
            selected = EVAL._validate_valbest_selection(
                audit,
                {
                    "amp": {
                        "attempts": 59024,
                        "successful": 59024,
                        "overflows": 0,
                    }
                },
            )
            self.assertEqual(selected["selected_epoch"], 33)
            self.assertEqual(selected["selected_val_acc"], 0.453)
            self.assertEqual(selected["metric_rows"], 40)

    def test_log_selection_rejects_a_different_best_epoch(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            audit = self._write_lineage(pathlib.Path(raw), peak_epoch=32)
            with self.assertRaises(EVAL.EvaluationError):
                EVAL._validate_valbest_selection(
                    audit,
                    {
                        "amp": {
                            "attempts": 59024,
                            "successful": 59024,
                            "overflows": 0,
                        }
                    },
                )

    def test_callback_selection_rejects_wrong_monitor_or_path(self) -> None:
        selected_path = pathlib.Path("/frozen/epoch=33-step=59024.ckpt")
        callback_key = (
            "ModelCheckpoint{'monitor': 'val_acc', 'mode': 'max', "
            "'every_n_epochs': 1}"
        )
        state = {
            "best_model_path": str(selected_path),
            "best_model_score": 0.453,
            "best_k_models": {str(selected_path): 0.453},
        }
        checkpoint = {"callbacks": {callback_key: state}}
        valbest = {
            "basename": selected_path.name,
            "sha256": EVAL.EXPECTED_HASHES["valbest33"],
            "epoch": 33,
            "global_step": 59024,
            "amp": {"attempts": 59024, "successful": 59001, "overflows": 23},
        }
        report = EVAL._validate_valbest_callback(
            checkpoint, {"valbest33": selected_path}, valbest
        )
        self.assertEqual(report["monitor"], "val_acc")
        self.assertEqual(report["mode"], "max")

        wrong_monitor = {"callbacks": {callback_key.replace("val_acc", "val_loss"): state}}
        with self.assertRaises(EVAL.EvaluationError):
            EVAL._validate_valbest_callback(
                wrong_monitor, {"valbest33": selected_path}, valbest
            )
        wrong_state = copy.deepcopy(state)
        wrong_state["best_model_path"] = "/frozen/epoch=32-step=57288.ckpt"
        with self.assertRaises(EVAL.EvaluationError):
            EVAL._validate_valbest_callback(
                {"callbacks": {callback_key: wrong_state}},
                {"valbest33": selected_path},
                valbest,
            )


class FilesystemSafetyTests(unittest.TestCase):
    def test_atomic_create_never_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            target = root / "result.json"
            target.write_bytes(b"reviewed")
            with self.assertRaises(FileExistsError):
                EVAL.atomic_create_bytes(target, b"replacement")
            self.assertEqual(target.read_bytes(), b"reviewed")

    def test_atomic_create_never_follows_existing_target_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            victim = root / "victim"
            victim.write_bytes(b"safe")
            target = root / "result"
            target.symlink_to(victim)
            with self.assertRaises(FileExistsError):
                EVAL.atomic_create_bytes(target, b"replacement")
            self.assertEqual(victim.read_bytes(), b"safe")

    def test_atomic_create_has_one_winner_under_concurrency(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            target = pathlib.Path(raw) / "result"
            barrier = threading.Barrier(2)

            def contender(payload: bytes) -> str:
                barrier.wait()
                try:
                    EVAL.atomic_create_bytes(target, payload)
                    return "created"
                except FileExistsError:
                    return "exists"

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(contender, (b"one", b"two")))
            self.assertEqual(sorted(outcomes), ["created", "exists"])
            self.assertIn(target.read_bytes(), {b"one", b"two"})
            self.assertEqual(list(target.parent.glob(".*.partial")), [])

    def test_pinned_file_rejects_leaf_and_parent_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            real_parent = root / "real"
            real_parent.mkdir()
            real_file = real_parent / "input"
            real_file.write_bytes(b"frozen")
            leaf_link = root / "leaf-link"
            leaf_link.symlink_to(real_file)
            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            for candidate in (leaf_link, parent_link / "input"):
                with self.subTest(candidate=candidate), self.assertRaises(
                    EVAL.EvaluationError
                ):
                    EVAL.pinned_file(candidate, "input")

    def test_open_pinned_file_detects_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            target = root / "input"
            replacement = root / "replacement"
            target.write_bytes(b"reviewed-bytes")
            replacement.write_bytes(b"different-bytes")
            with self.assertRaises(EVAL.EvaluationError):
                with EVAL.open_pinned_file(target, "input") as pinned:
                    self.assertEqual(pinned["handle"].read(), b"reviewed-bytes")
                    replacement.replace(target)

    def test_atomic_create_fails_closed_if_parent_namespace_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            parent = root / "parent"
            moved = root / "moved-parent"
            victim = root / "victim"
            parent.mkdir()
            victim.mkdir()
            target = parent / "result"
            original_link = EVAL.os.link

            def swapping_link(*args, **kwargs):
                result = original_link(*args, **kwargs)
                parent.rename(moved)
                parent.symlink_to(victim, target_is_directory=True)
                return result

            with mock.patch.object(EVAL.os, "link", side_effect=swapping_link):
                with self.assertRaises((EVAL.EvaluationError, OSError)):
                    EVAL.atomic_create_bytes(target, b"payload")
            self.assertFalse((victim / "result").exists())
            self.assertFalse((moved / "result").exists())


class StateMachineTests(unittest.TestCase):
    def test_cross_node_dev_and_inode_are_diagnostic_only(self) -> None:
        path = "/private/tmp/frozen-input.bin"
        frozen = {
            "path": path,
            "basename": "frozen-input.bin",
            "size": 7,
            "sha256": "a" * 64,
            "device": 101,
            "inode": 202,
        }
        current = {
            **frozen,
            "device": 303,
            "inode": 404,
        }
        diagnostics = EVAL.validate_persistent_file_identity(
            frozen,
            current,
            "cross-node fixture",
        )
        self.assertFalse(diagnostics["device_match"])
        self.assertFalse(diagnostics["inode_match"])
        self.assertEqual(diagnostics["frozen_device"], 101)
        self.assertEqual(diagnostics["current_inode"], 404)

    def test_persistent_identity_rejects_any_stable_field_change(self) -> None:
        frozen = {
            "path": "/private/tmp/frozen-input.bin",
            "basename": "frozen-input.bin",
            "size": 7,
            "sha256": "a" * 64,
            "device": 101,
            "inode": 202,
        }
        mutations = (
            ("path", "/private/tmp/other-input.bin"),
            ("basename", "other-input.bin"),
            ("size", 8),
            ("sha256", "b" * 64),
        )
        for field, value in mutations:
            current = dict(frozen)
            current[field] = value
            with self.subTest(field=field), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_persistent_file_identity(
                    frozen,
                    current,
                    "stable fixture",
                )

    def test_protocol_and_identity_policy_are_hard_bound(self) -> None:
        valid = {
            "schema_version": EVAL.SCHEMA_VERSION,
            "protocol_id": EVAL.PROTOCOL_ID,
            "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
        }
        EVAL.validate_protocol_boundary(valid, "fixture")
        for field, value in (
            ("schema_version", 2),
            ("protocol_id", "wrong-protocol"),
            ("filesystem_identity_policy", "wrong-policy"),
        ):
            changed = dict(valid)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_protocol_boundary(changed, "fixture")

    def test_publication_artifact_uses_portable_persistent_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            path = pathlib.Path(raw) / "artifact.bin"
            path.write_bytes(b"frozen artifact")
            frozen = EVAL.pinned_file(path, "frozen artifact")
            frozen["device"] = int(frozen["device"]) + 1000
            frozen["inode"] = int(frozen["inode"]) + 1000
            verified = EVAL._artifact_record_is_current(frozen, "artifact")
            diagnostics = verified["filesystem_identity_diagnostics"]
            self.assertFalse(diagnostics["device_match"])
            self.assertFalse(diagnostics["inode_match"])

            for field, value in (
                ("path", str(path.with_name("other.bin"))),
                ("basename", "other.bin"),
                ("size", int(frozen["size"]) + 1),
                ("sha256", "c" * 64),
            ):
                changed = dict(frozen)
                changed[field] = value
                with self.subTest(field=field), self.assertRaises(
                    (EVAL.EvaluationError, FileNotFoundError)
                ):
                    EVAL._artifact_record_is_current(changed, "artifact")

    def test_lock_payload_requires_exact_canonical_json(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            payload = EVAL._new_lock_payload(root)
            canonical = EVAL.canonical_json_bytes(payload)
            cases = {
                "empty": b"",
                "noncanonical": json.dumps(payload).encode("utf-8"),
                "extra_field": EVAL.canonical_json_bytes({**payload, "extra": 1}),
                "short_nonce": EVAL.canonical_json_bytes(
                    {**payload, "lock_nonce": "a" * 63}
                ),
            }
            for name, value in cases.items():
                path = root / f"{name}.lock"
                path.write_bytes(value)
                with self.subTest(name=name), self.assertRaises(EVAL.EvaluationError):
                    EVAL.read_lock_payload(
                        path,
                        hashlib.sha256(value).hexdigest(),
                        root,
                    )

            path = root / "valid.lock"
            path.write_bytes(canonical)
            parsed, record = EVAL.read_lock_payload(
                path,
                hashlib.sha256(canonical).hexdigest(),
                root,
            )
            self.assertEqual(parsed, payload)
            self.assertEqual(record["size"], len(canonical))

    def test_freeze_layout_is_one_shot_and_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            (root / "tools").mkdir()
            manifest_path = root / "input_freeze.json"
            candidate = {
                "schema_version": EVAL.SCHEMA_VERSION,
                "protocol_id": EVAL.PROTOCOL_ID,
                "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
                "status": "FROZEN",
            }
            published = EVAL.initialize_freeze_layout(
                root, manifest_path, copy.deepcopy(candidate)
            )
            self.assertEqual(published["manifest"]["path"], str(manifest_path))
            frozen = EVAL.read_json(
                manifest_path,
                "manifest",
                published["manifest"]["sha256"],
            )
            layout = EVAL.validate_frozen_layout(root, frozen)
            lock_payload = layout["evaluation_lock_payload"]
            self.assertEqual(
                set(lock_payload),
                {
                    "schema_version",
                    "protocol_id",
                    "filesystem_identity_policy",
                    "purpose",
                    "lock_nonce",
                    "external_root",
                },
            )
            self.assertRegex(lock_payload["lock_nonce"], r"^[0-9a-f]{64}$")
            self.assertEqual(lock_payload["external_root"], str(root))
            lock_bytes = EVAL.canonical_json_bytes(lock_payload)
            self.assertEqual(
                layout["evaluation_lock"]["sha256"],
                hashlib.sha256(lock_bytes).hexdigest(),
            )
            self.assertGreater(layout["evaluation_lock"]["size"], 0)
            self.assertTrue(
                layout["filesystem_identity_diagnostics"]["device_match"]
            )
            self.assertTrue(
                layout["filesystem_identity_diagnostics"]["inode_match"]
            )
            original_manifest = manifest_path.read_bytes()
            with self.assertRaises(FileExistsError):
                EVAL.initialize_freeze_layout(
                    root, manifest_path, copy.deepcopy(candidate)
                )
            self.assertEqual(manifest_path.read_bytes(), original_manifest)

            with EVAL.evaluation_lock(root):
                with self.assertRaises(EVAL.EvaluationError):
                    with EVAL.evaluation_lock(root):
                        self.fail("second exclusive lock unexpectedly succeeded")

    def test_frozen_layout_accepts_cross_node_stat_ids_but_binds_lock_payload(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            (root / "tools").mkdir()
            manifest_path = root / "input_freeze.json"
            candidate = {
                "schema_version": EVAL.SCHEMA_VERSION,
                "protocol_id": EVAL.PROTOCOL_ID,
                "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
                "status": "FROZEN",
            }
            published = EVAL.initialize_freeze_layout(
                root,
                manifest_path,
                candidate,
            )
            frozen = EVAL.read_json(
                manifest_path,
                "manifest",
                published["manifest"]["sha256"],
            )
            lock = frozen["layout"]["evaluation_lock"]
            lock["device"] = int(lock["device"]) + 1000
            lock["inode"] = int(lock["inode"]) + 1000
            validated = EVAL.validate_frozen_layout(root, frozen)
            diagnostics = validated["filesystem_identity_diagnostics"]
            self.assertFalse(diagnostics["device_match"])
            self.assertFalse(diagnostics["inode_match"])

            tampered = copy.deepcopy(frozen)
            original_nonce = tampered["layout"]["evaluation_lock"]["payload"][
                "lock_nonce"
            ]
            tampered["layout"]["evaluation_lock"]["payload"]["lock_nonce"] = (
                ("0" if original_nonce[0] != "0" else "1") + original_nonce[1:]
            )
            with self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_frozen_layout(root, tampered)

    def test_check_only_has_no_filesystem_write_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            manifest_path = root / "input_freeze.json"
            manifest_path.write_bytes(b"{}\n")
            before = {
                path.relative_to(root): (path.is_dir(), None if path.is_dir() else path.read_bytes())
                for path in root.rglob("*")
            }
            args = types.SimpleNamespace(
                external_root=root,
                manifest=manifest_path,
                expected_manifest_sha256="a" * 64,
            )
            manifest = valid_role_manifest()
            with (
                mock.patch.object(
                    EVAL,
                    "_validate_manifest_hash",
                    return_value=(manifest, "a" * 64),
                ),
                mock.patch.object(EVAL, "validate_frozen_layout", return_value={}),
                mock.patch.object(EVAL, "verify_frozen_manifest", return_value={}),
                mock.patch.object(
                    EVAL,
                    "strict_load_model",
                    side_effect=[(object(), {"model": model_id}) for model_id in EVAL.MODEL_IDS],
                ),
            ):
                result = EVAL.check_only(args)
            self.assertEqual(result["status"], "CHECK_PASS")
            after = {
                path.relative_to(root): (path.is_dir(), None if path.is_dir() else path.read_bytes())
                for path in root.rglob("*")
            }
            self.assertEqual(after, before)

    def test_lock_namespace_replacement_is_detected_before_release(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            state = root / "state"
            state.mkdir()
            lock = state / "evaluation.lock"
            lock.write_bytes(b"")
            moved = state / "evaluation.lock.replaced"
            with self.assertRaises(EVAL.EvaluationError):
                with EVAL.evaluation_lock(root):
                    lock.rename(moved)
                    lock.write_bytes(b"")


class RuntimeProvenanceTests(unittest.TestCase):
    @staticmethod
    def _active_environment(job_id: str) -> tuple[dict[str, object], types.ModuleType]:
        fake_torch = types.ModuleType("torch")
        fake_torch.cuda = types.SimpleNamespace(
            is_available=lambda: False,
            get_device_name=lambda _index: None,
        )
        fake_torch.version = types.SimpleNamespace(cuda=None)
        fake_torch.backends = types.SimpleNamespace(
            cudnn=types.SimpleNamespace(version=lambda: None)
        )
        fake_torch.__version__ = "2.1.1-test"
        environment = {
            "cuda_available": False,
            "cuda_runtime": None,
            "cudnn": None,
            "device": None,
            "hostname": EVAL.platform.node(),
            "python": EVAL.platform.python_version(),
            "slurm_job_id": job_id,
            "torch": fake_torch.__version__,
        }
        return environment, fake_torch

    def test_runtime_provenance_binds_canonical_environment_preimage(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            submitted = root / "submitted_runners"
            submitted.mkdir()
            job_id = "12345"
            runner = submitted / f"{job_id}.sbatch"
            runner.write_bytes(b"#!/bin/bash\n")
            runner_sha = hashlib.sha256(runner.read_bytes()).hexdigest()
            environment, fake_torch = self._active_environment(job_id)
            environment_path = submitted / f"{job_id}.environment.json"
            environment_bytes = (
                json.dumps(environment, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            environment_path.write_bytes(environment_bytes)
            environment_sha = hashlib.sha256(environment_bytes).hexdigest()
            args = types.SimpleNamespace(
                job_id=job_id,
                attempt_id=f"slurm-{job_id}",
                submitted_runner=runner,
                submitted_runner_sha256=runner_sha,
                environment_fingerprint=environment_path,
                environment_fingerprint_sha256=environment_sha,
            )
            manifest = {
                "schema_version": EVAL.SCHEMA_VERSION,
                "protocol_id": EVAL.PROTOCOL_ID,
                "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
                "inputs": {"sbatch": {"sha256": runner_sha}},
            }
            with (
                mock.patch.dict(EVAL.os.environ, {"SLURM_JOB_ID": job_id}),
                mock.patch.dict(EVAL.sys.modules, {"torch": fake_torch}),
            ):
                report = EVAL.validate_runtime_provenance(args, manifest, root)
            self.assertEqual(report["environment"], environment)
            self.assertEqual(report["environment_fingerprint"]["sha256"], environment_sha)

            # Rehashing a syntactically valid but false preimage must not make it
            # acceptable: it must describe this exact process and Slurm job.
            false_environment = dict(environment)
            false_environment["hostname"] = "not-this-host"
            false_bytes = (
                json.dumps(false_environment, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            environment_path.write_bytes(false_bytes)
            args.environment_fingerprint_sha256 = hashlib.sha256(false_bytes).hexdigest()
            with (
                mock.patch.dict(EVAL.os.environ, {"SLURM_JOB_ID": job_id}),
                mock.patch.dict(EVAL.sys.modules, {"torch": fake_torch}),
                self.assertRaises(EVAL.EvaluationError),
            ):
                EVAL.validate_runtime_provenance(args, manifest, root)


class PublicationMarkerTests(unittest.TestCase):
    @staticmethod
    def _prepare_smoke(root: pathlib.Path, *, inconsistent_environment: bool = False):
        job_id = "12345"
        attempt_id = f"slurm-{job_id}"
        (root / "state").mkdir()
        attempt = root / "attempts" / "smoke" / attempt_id
        attempt.mkdir(parents=True)
        submitted = root / "submitted_runners"
        submitted.mkdir()

        runner = submitted / f"{job_id}.sbatch"
        runner.write_bytes(b"#!/bin/bash\n")
        runner_record = EVAL.pinned_file(runner, "runner")
        manifest_path = root / "input_freeze.json"
        EVAL.atomic_create_json(
            manifest_path,
            {
                "schema_version": EVAL.SCHEMA_VERSION,
                "protocol_id": EVAL.PROTOCOL_ID,
                "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
                "inputs": {"sbatch": {"sha256": runner_record["sha256"]}},
            },
        )
        manifest_sha = EVAL.sha256_file(manifest_path)

        environment = {
            "cuda_available": True,
            "cuda_runtime": "12.1",
            "cudnn": 8900,
            "device": "A100",
            "hostname": "node-a",
            "python": "3.11.0",
            "slurm_job_id": job_id,
            "torch": "2.1.1",
        }
        environment_path = submitted / f"{job_id}.environment.json"
        environment_path.write_bytes(
            (json.dumps(environment, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        environment_record = EVAL.pinned_file(environment_path, "environment")

        results_path = attempt / "per_trial_results.csv"
        long_path = attempt / "per_model_results_long.csv"
        summary_path = attempt / "SMOKE_AUDIT.json"
        results_path.write_bytes(b"trial_id\n0\n")
        long_path.write_bytes(b"trial_id,model_id\n0,formal40\n")
        EVAL.atomic_create_json(
            summary_path,
            {
                "schema_version": EVAL.RESULT_SCHEMA_VERSION,
                "protocol_id": EVAL.PROTOCOL_ID,
                "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
                "engineering_status": "PASS",
                "scientific_decision": "NOT_GATED_EXTERNAL_AUDIT",
                "mode": "smoke",
                "attempt_id": attempt_id,
                "evaluation_role": EVAL.EVALUATION_ROLE,
                "role_confirmation": EVAL.EXPECTED_ROLE_CONFIRMATION,
                "manifest": str(manifest_path),
                "manifest_sha256": manifest_sha,
            },
        )
        complete_environment = dict(environment)
        if inconsistent_environment:
            complete_environment["device"] = "different-device"
        completion_path = attempt / "COMPLETE.json"
        completion = {
            "schema_version": EVAL.RESULT_SCHEMA_VERSION,
            "protocol_id": EVAL.PROTOCOL_ID,
            "filesystem_identity_policy": EVAL.FILESYSTEM_IDENTITY_POLICY,
            "status": "SMOKE_PASS",
            "evaluation_role": EVAL.EVALUATION_ROLE,
            "role_confirmation": EVAL.EXPECTED_ROLE_CONFIRMATION,
            "attempt_id": attempt_id,
            "job_id": job_id,
            "manifest_sha256": manifest_sha,
            "environment_fingerprint_sha256": environment_record["sha256"],
            "environment_fingerprint": environment_record,
            "environment": complete_environment,
            "submitted_runner": runner_record,
            "results": EVAL.pinned_file(results_path, "results"),
            "long_results": EVAL.pinned_file(long_path, "long"),
            "summary": EVAL.pinned_file(summary_path, "summary"),
        }
        EVAL.atomic_create_json(completion_path, completion)
        completion["attempt_complete"] = EVAL.pinned_file(completion_path, "complete")
        return {
            "job_id": job_id,
            "manifest_path": manifest_path,
            "manifest_sha": manifest_sha,
            "runner_sha": runner_record["sha256"],
            "environment_sha": environment_record["sha256"],
            "completion": completion,
            "results_path": results_path,
        }

    @staticmethod
    def _publish(root: pathlib.Path, fixture: dict):
        return EVAL.publish_canonical_marker(
            root,
            smoke=True,
            completion=fixture["completion"],
            manifest_path=fixture["manifest_path"],
            manifest_sha256=fixture["manifest_sha"],
            submitted_runner_sha256=fixture["runner_sha"],
            frozen_runner_sha256=fixture["runner_sha"],
            slurm_job_id=fixture["job_id"],
            environment_fingerprint_sha256=fixture["environment_sha"],
        )

    def test_marker_is_verifiable_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            fixture = self._prepare_smoke(root)
            publication = self._publish(root, fixture)
            marker_path = root / "state" / "SMOKE_PASS.json"
            original = marker_path.read_bytes()
            self.assertEqual(publication["marker"]["status"], "SMOKE_PASS")
            with self.assertRaises(FileExistsError):
                self._publish(root, fixture)
            self.assertEqual(marker_path.read_bytes(), original)

    def test_marker_reverification_detects_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            fixture = self._prepare_smoke(root)
            self._publish(root, fixture)
            fixture["results_path"].write_bytes(b"trial_id\n999\n")
            with self.assertRaises(EVAL.EvaluationError):
                EVAL.verify_publication_marker(
                    root, "SMOKE_PASS.json", fixture["manifest_sha"]
                )

    def test_marker_rejects_complete_environment_not_matching_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as raw:
            root = pathlib.Path(raw)
            fixture = self._prepare_smoke(root, inconsistent_environment=True)
            with self.assertRaises(EVAL.EvaluationError):
                self._publish(root, fixture)


class SNRIdentityBoundaryTests(unittest.TestCase):
    def test_exact_tolerance_is_inclusive_and_next_float_is_rejected(self) -> None:
        report = EVAL.validate_snr_identity(
            [0.0],
            [EVAL.SNR_IDENTITY_ATOL_DB],
            ["mixed"],
            label="boundary",
            atol=EVAL.SNR_IDENTITY_ATOL_DB,
        )
        self.assertEqual(report["max_abs"], EVAL.SNR_IDENTITY_ATOL_DB)
        outside = np.nextafter(EVAL.SNR_IDENTITY_ATOL_DB, np.inf)
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_snr_identity(
                [0.0],
                [outside],
                ["mixed"],
                label="boundary",
                atol=EVAL.SNR_IDENTITY_ATOL_DB,
            )

    def test_either_mixed_side_must_be_finite_and_in_range(self) -> None:
        bad_pairs = []
        for value in (np.nan, np.inf, -np.inf):
            bad_pairs.extend(((value, 0.0), (0.0, value)))
        # These pairs are within the identity tolerance but outside the
        # scientific SNR domain, so range validation must remain independent.
        bad_pairs.extend(
            (
                (-10.0 - 5e-13, -10.0),
                (-10.0, -10.0 - 5e-13),
                (10.0 + 5e-13, 10.0),
                (10.0, 10.0 + 5e-13),
            )
        )
        for expected, actual in bad_pairs:
            with self.subTest(expected=expected, actual=actual), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_snr_identity(
                    [expected],
                    [actual],
                    ["mixed"],
                    label="mixed-domain",
                    atol=EVAL.SNR_IDENTITY_ATOL_DB,
                )

    def test_clean_requires_nan_on_both_sides(self) -> None:
        EVAL.validate_snr_identity(
            [np.nan],
            [np.nan],
            ["clean"],
            label="clean",
            atol=EVAL.SNR_IDENTITY_ATOL_DB,
        )
        for expected, actual in (
            (0.0, np.nan),
            (np.nan, 0.0),
            (np.inf, np.nan),
            (np.nan, -np.inf),
        ):
            with self.subTest(expected=expected, actual=actual), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_snr_identity(
                    [expected],
                    [actual],
                    ["clean"],
                    label="clean",
                    atol=EVAL.SNR_IDENTITY_ATOL_DB,
                )

    def test_unknown_kind_shape_and_invalid_tolerance_fail_closed(self) -> None:
        calls = (
            ([0.0], [0.0], ["unknown"], EVAL.SNR_IDENTITY_ATOL_DB),
            ([0.0, 1.0], [0.0], ["mixed"], EVAL.SNR_IDENTITY_ATOL_DB),
            ([0.0], [0.0], ["mixed"], -1.0),
            ([0.0], [0.0], ["mixed"], np.nan),
            ([0.0], [0.0], ["mixed"], np.inf),
        )
        for expected, actual, kinds, atol in calls:
            with self.subTest(kinds=kinds, atol=atol), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_snr_identity(
                    expected,
                    actual,
                    kinds,
                    label="invalid",
                    atol=atol,
                )


class ResultValidationTests(unittest.TestCase):
    @staticmethod
    def _single_mixed_bank() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trial_id": [0],
                "scene_kind": ["mixed"],
                "control_subset": [1],
                "target_speaker": ["speaker-001"],
                "target_gender": ["female"],
                "target_norm": ["about"],
                "target_label": [3],
                "distractor_count": [1],
                "snr_bin": [0],
                "snr_db": [-10.0],
                "distractor_1_norm": ["above"],
                "distractor_1_label": [4],
            }
        )

    def test_valid_control_and_noncontrol_rows_pass(self) -> None:
        EVAL.validate_results(valid_result_frame(control=True), full_run=False)
        EVAL.validate_results(valid_result_frame(control=False), full_run=False)

    def test_control_prediction_range_is_validated(self) -> None:
        for bad_prediction in (-1, 800):
            frame = valid_result_frame(control=True)
            frame.loc[0, "formal40_shuffled_pred_label"] = bad_prediction
            frame.loc[0, "formal40_shuffled_correct"] = 0
            frame.loc[0, "formal40_shuffled_probe_intrusion"] = 0
            with self.subTest(bad_prediction=bad_prediction), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_results(frame, full_run=False)

    def test_control_numeric_metrics_are_finite_and_in_range(self) -> None:
        mutations = (
            ("formal40_silent_nll", np.nan),
            ("formal40_silent_nll", -0.1),
            ("formal40_silent_p_target", 1.1),
            ("formal40_silent_p_probe_distractor", -0.1),
        )
        for column, value in mutations:
            frame = valid_result_frame(control=True)
            frame.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_results(frame, full_run=False)

    def test_correctness_and_probe_intrusion_are_derived(self) -> None:
        frame = valid_result_frame(control=True)
        frame.loc[0, "valbest33_correct"] = 0
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_results(frame, full_run=False)
        frame = valid_result_frame(control=True)
        frame.loc[0, "author_external_distractor_probe_intrusion"] = 1
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_results(frame, full_run=False)

    def test_result_hash_fields_must_be_canonical_sha256(self) -> None:
        for column, value in (
            ("scene_sha256", "not-a-sha"),
            ("correct_cue_sha256", "A" * 64),
        ):
            frame = valid_result_frame(control=True)
            frame.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_results(frame, full_run=False)

    def test_full_result_ids_must_be_exactly_unique_and_contiguous(self) -> None:
        # Length alone is insufficient: a duplicated trial can otherwise
        # silently replace another bank item while still reporting 10,000.
        duplicated = pd.concat(
            [valid_result_frame(control=True)] * EVAL.TOTAL_TRIALS,
            ignore_index=True,
        )
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_results(duplicated, full_run=True)

    def test_smoke_selection_exercises_clean_mixed_and_control_paths(self) -> None:
        bank = pd.DataFrame(
            {
                "trial_id": np.arange(10),
                "scene_kind": ["mixed"] * 9 + ["clean"],
                "control_subset": [0] * 8 + [1, 0],
            }
        )
        chosen = EVAL._select_smoke_bank(bank, 3)
        self.assertIn("clean", set(chosen["scene_kind"]))
        self.assertIn("mixed", set(chosen["scene_kind"]))
        self.assertIn(1, set(chosen["control_subset"]))

    def test_sparse_smoke_summary_does_not_require_two_speakers_per_stratum(self) -> None:
        """Engineering smoke must not run full-study inference on tiny cells."""
        rows = []
        specifications = (
            (0, "mixed", True, "speaker-a", 0, 1),
            (1, "mixed", True, "speaker-b", 0, 1),
            (2, "mixed", False, "speaker-c", 4, 4),
            (3, "clean", False, "speaker-d", -1, 0),
        )
        for trial_id, scene_kind, control, speaker, snr_bin, distractors in specifications:
            frame = valid_result_frame(control=control)
            frame.loc[0, "trial_id"] = trial_id
            frame.loc[0, "scene_kind"] = scene_kind
            frame.loc[0, "target_speaker"] = speaker
            frame.loc[0, "snr_bin"] = snr_bin
            frame.loc[0, "distractor_count"] = distractors
            if scene_kind == "clean":
                frame.loc[0, "snr_db"] = np.nan
                frame.loc[0, "probe_distractor_norm"] = ""
                frame.loc[0, "probe_distractor_label"] = 0
            rows.append(frame)
        smoke = pd.concat(rows, ignore_index=True)
        summary = EVAL.summarize_results(smoke, full_run=False)
        self.assertEqual(summary["engineering_status"], "PASS")
        self.assertEqual(summary["scientific_decision"], "NOT_GATED_EXTERNAL_AUDIT")

    def test_long_results_preserve_exact_model_roles_and_checkpoint_hashes(self) -> None:
        results = pd.concat(
            [valid_result_frame(control=True), valid_result_frame(control=False)],
            ignore_index=True,
        )
        results.loc[1, "trial_id"] = 1
        manifest = {
            "models": {
                model_id: {"sha256": hashlib.sha256(model_id.encode()).hexdigest()}
                for model_id in EVAL.MODEL_IDS
            }
        }
        long_results = EVAL.to_model_long_results(results, manifest)
        self.assertEqual(len(long_results), 2 * len(EVAL.MODEL_IDS))
        self.assertEqual(set(long_results["model_id"]), set(EVAL.MODEL_IDS))
        for model_id in EVAL.MODEL_IDS:
            rows = long_results.loc[long_results["model_id"] == model_id]
            self.assertEqual(len(rows), 2)
            self.assertEqual(set(rows["model_role"]), {EVAL.MODEL_ROLES[model_id]})
            self.assertEqual(
                set(rows["checkpoint_sha256"]),
                {manifest["models"][model_id]["sha256"]},
            )

    def test_result_identity_rejects_snr_and_probe_tampering(self) -> None:
        bank = self._single_mixed_bank()
        baseline = valid_result_frame(control=True)
        EVAL.validate_result_identity(baseline, bank)
        for column, value in (
            ("snr_db", 10.0),
            ("probe_distractor_norm", "tampered"),
            ("probe_distractor_label", 5),
        ):
            changed = baseline.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_result_identity(changed, bank)

    def test_result_csv_reload_uses_only_the_locked_snr_tolerance(self) -> None:
        bank = self._single_mixed_bank()
        generated = valid_result_frame(control=True)
        serialized = generated.copy()
        serialized.loc[0, "snr_db"] += 5e-13
        reloaded = pd.read_csv(io.StringIO(serialized.to_csv(index=False)))

        report = EVAL.validate_result_identity(
            reloaded,
            bank,
            expected_generated=generated,
        )["snr_identity"]
        self.assertEqual(report["exact_mismatch_count"], 1)
        self.assertLessEqual(report["max_abs"], EVAL.SNR_IDENTITY_ATOL_DB)
        self.assertEqual(report["rtol"], 0.0)
        self.assertEqual(report["atol"], EVAL.SNR_IDENTITY_ATOL_DB)

        # The tolerance is exclusive to the serialized reload boundary.
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_result_identity(reloaded, bank)

        outside = generated.copy()
        outside.loc[0, "snr_db"] += 2e-12
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_result_identity(
                outside,
                bank,
                expected_generated=generated,
            )

    def test_result_csv_reload_keeps_scene_and_cue_hashes_exact(self) -> None:
        bank = self._single_mixed_bank()
        generated = valid_result_frame(control=True)

        report = EVAL.validate_result_identity(
            generated.copy(),
            bank,
            expected_generated=generated,
        )
        self.assertEqual(
            report["generated_hash_binding"],
            "scene_and_correct_cue_sha256_exact",
        )

        for column in ("scene_sha256", "correct_cue_sha256"):
            changed = generated.copy()
            changed.loc[0, column] = "c" * 64
            with self.subTest(column=column), self.assertRaises(
                EVAL.EvaluationError
            ):
                EVAL.validate_result_identity(
                    changed,
                    bank,
                    expected_generated=generated,
                )


class HistoricalSceneBindingTests(unittest.TestCase):
    @staticmethod
    def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
        trial_ids = np.arange(EVAL.TOTAL_TRIALS)
        mixed = trial_ids < EVAL.MIXED_TRIALS
        bank = pd.DataFrame(
            {
                "trial_id": trial_ids,
                "scene_kind": np.where(mixed, "mixed", "clean"),
                "control_subset": (trial_ids % 5 == 0).astype(int),
                "target_speaker": [f"s-{index % 100:03d}" for index in trial_ids],
                "target_gender": np.where(trial_ids % 2, "male", "female"),
                "target_label": trial_ids % 800,
                "distractor_count": np.where(mixed, trial_ids % 4 + 1, 0),
                "snr_bin": np.where(mixed, trial_ids % 5, -1),
                "snr_db": np.where(mixed, (trial_ids % 5) * 5.0 - 10.0, np.nan),
                "distractor_1_label": (trial_ids + 1) % 800,
            }
        )
        historical = bank[
            [
                "trial_id",
                "scene_kind",
                "control_subset",
                "target_speaker",
                "target_gender",
                "target_label",
                "distractor_count",
                "snr_bin",
                "snr_db",
            ]
        ].copy()
        historical["probe_distractor_label"] = np.where(
            mixed, bank["distractor_1_label"], 0
        )
        historical["scene_sha256"] = [
            hashlib.sha256(f"scene-{trial_id}".encode()).hexdigest()
            for trial_id in trial_ids
        ]
        return bank, historical

    def test_historical_scene_binding_accepts_exact_trial_identity(self) -> None:
        bank, historical = self._frames()
        report = EVAL.validate_historical_scene_binding(bank, historical)
        self.assertEqual(report["trials"], EVAL.TOTAL_TRIALS)
        self.assertEqual(report["scene_hashes"], EVAL.TOTAL_TRIALS)
        self.assertRegex(report["scene_hash_vector_sha256"], r"^[0-9a-f]{64}$")

    def test_historical_snr_accepts_csv_ulp_drift_and_reports_it(self) -> None:
        bank, historical = self._frames()
        historical.loc[0, "snr_db"] += 5e-13
        report = EVAL.validate_historical_scene_binding(bank, historical)[
            "snr_identity"
        ]
        self.assertEqual(report["exact_mismatch_count"], 1)
        self.assertEqual(report["exact_mismatches"], 1)
        self.assertLessEqual(report["max_abs"], EVAL.SNR_IDENTITY_ATOL_DB)
        self.assertEqual(report["max_abs_diff"], report["max_abs"])
        self.assertEqual(report["rtol"], 0.0)
        self.assertEqual(report["atol"], EVAL.SNR_IDENTITY_ATOL_DB)
        self.assertEqual(
            report["compared_rows"],
            {"mixed": EVAL.MIXED_TRIALS, "clean": EVAL.CLEAN_TRIALS},
        )

    def test_historical_snr_rejects_drift_beyond_locked_tolerance(self) -> None:
        bank, historical = self._frames()
        historical.loc[0, "snr_db"] += 2e-12
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_historical_scene_binding(bank, historical)

    def test_historical_snr_rejects_nonfinite_mixed_values(self) -> None:
        bank, historical = self._frames()
        for value in (np.nan, np.inf, -np.inf):
            changed = historical.copy()
            changed.loc[0, "snr_db"] = value
            with self.subTest(value=value), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_historical_scene_binding(bank, changed)

    def test_historical_snr_rejects_finite_clean_values(self) -> None:
        bank, historical = self._frames()
        historical.loc[EVAL.MIXED_TRIALS, "snr_db"] = 0.0
        with self.assertRaises(EVAL.EvaluationError):
            EVAL.validate_historical_scene_binding(bank, historical)

    def test_historical_scene_binding_rejects_identity_or_hash_tampering(self) -> None:
        bank, historical = self._frames()
        mutations = (
            ("target_label", 0, 799),
            ("scene_sha256", 0, "not-a-sha"),
            ("trial_id", 1, 0),
        )
        for column, row, value in mutations:
            changed = historical.copy()
            changed.loc[row, column] = value
            with self.subTest(column=column), self.assertRaises(EVAL.EvaluationError):
                EVAL.validate_historical_scene_binding(bank, changed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
