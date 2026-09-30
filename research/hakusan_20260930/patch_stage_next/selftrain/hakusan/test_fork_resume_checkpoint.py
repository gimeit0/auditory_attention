"""Regression tests for the control-only fork-resume checkpoint importer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import random
import tempfile
import unittest

import numpy as np
import torch

from selftrain.hakusan.fork_resume_checkpoint import (
    _assert_checkpoint_equivalent,
    _load_checkpoint,
    prepare_fork,
)


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ForkResumeCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temporary_directory.name)
        self.source = root / "runs/parent"
        self.staging = root / "runs/child.preparing"
        self.logical = root / "runs/child"
        self.source_snapshot = self.source / "snapshot"
        self.target_snapshot = self.staging / "snapshot"
        for snapshot in (self.source_snapshot, self.target_snapshot):
            config = snapshot / "files/selftrain/configs/full.yaml"
            config.parent.mkdir(parents=True)
            config.write_text("model: identical\n", encoding="utf-8")

        self.source_semantic = "a" * 64
        self.target_semantic = "b" * 64
        paths = (
            "selftrain/configs/full.yaml",
            "selftrain/scripts/check_training_safety.py",
            "src/spatial_attn_lightning.py",
        )
        source_entries = [
            {"path": path, "sha256": "1" * 64, "size": 1}
            for path in paths
        ]
        target_entries = [dict(entry) for entry in source_entries]
        for entry in target_entries:
            if entry["path"] == "src/spatial_attn_lightning.py":
                entry["sha256"] = "2" * 64
            elif entry["path"] == "selftrain/scripts/check_training_safety.py":
                entry["sha256"] = "3" * 64
        self.source_manifest = self.source_snapshot / "manifest.json"
        self.target_manifest = self.target_snapshot / "manifest.json"
        self.source_manifest.write_text(
            json.dumps(
                {
                    "semantic_combined_sha256": self.source_semantic,
                    "semantic_files": source_entries,
                }
            ),
            encoding="utf-8",
        )
        self.target_manifest.write_text(
            json.dumps(
                {
                    "semantic_combined_sha256": self.target_semantic,
                    "semantic_files": target_entries,
                }
            ),
            encoding="utf-8",
        )

        self.numerics_pass = self.target_snapshot / "numerics_PASS.json"
        self._write_numerics_pass(self.target_semantic)
        config_sha256 = _sha256(
            self.source_snapshot / "files/selftrain/configs/full.yaml"
        )
        self.source_checkpoint = self.source / "full/checkpoints/last.ckpt"
        self.source_checkpoint.parent.mkdir(parents=True)
        torch.save(
            {
                "pytorch-lightning_version": importlib.metadata.version(
                    "pytorch-lightning"
                ),
                "state_dict": {"weight": torch.tensor([1.0])},
                "epoch": 0,
                "global_step": 7813,
                "loops": {"fit_loop": {"completed": 7813}},
                "optimizer_states": [
                    {
                        "state": {
                            0: {
                                "exp_avg": torch.tensor([0.1]),
                                "step": torch.tensor(7813.0),
                            }
                        },
                        "param_groups": [],
                    }
                ],
                "lr_schedulers": [],
                "callbacks": {"counter": 7813},
                "MixedPrecision": {
                    "scale": 65536.0,
                    "growth_factor": 2.0,
                    "backoff_factor": 0.5,
                    "growth_interval": 2000,
                    "_growth_tracker": 17,
                },
                "audattn_amp_state_v1": {
                    "consecutive_overflows": 0,
                    "total_overflows": 0,
                    "total_optimizer_attempts": 7813,
                    "successful_optimizer_steps": 7813,
                    "epoch_index": 0,
                    "epoch_overflows": 0,
                    "epoch_optimizer_attempts": 7813,
                    "epoch_successful_steps": 7813,
                    "overflow_window": [0, 0],
                },
                "audattn_rng_state_v1": {
                    "python": random.Random(7).getstate(),
                    "numpy": np.random.RandomState(7).get_state(),
                    "torch_cpu": torch.Generator().manual_seed(7).get_state(),
                    "torch_cuda": [
                        torch.Generator().manual_seed(8).get_state()
                    ],
                },
                "audattn_run_metadata_v1": {
                    "run_id": "parent",
                    "source_semantic_sha256": self.source_semantic,
                    "config_sha256": config_sha256,
                },
            },
            self.source_checkpoint,
        )
        self.target_checkpoint = self.staging / "full/checkpoints/last.ckpt"
        self.lineage = self.staging / "restart/fork_resume_lineage.json"
        self.args = argparse.Namespace(
            source_run_root=str(self.source),
            target_run_root=str(self.staging),
            target_logical_run_root=str(self.logical),
            source_run_id="parent",
            target_run_id="child",
            source_checkpoint=str(self.source_checkpoint),
            target_checkpoint=str(self.target_checkpoint),
            source_manifest=str(self.source_manifest),
            target_manifest=str(self.target_manifest),
            numerics_pass=str(self.numerics_pass),
            lineage=str(self.lineage),
            resume_kind="epoch",
            expected_global_step=7813,
            expected_amp_overflows=0,
            allowed_semantic_change=[
                "src/spatial_attn_lightning.py",
                "selftrain/scripts/check_training_safety.py",
            ],
            reason="regression test",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_numerics_pass(self, semantic_sha256: str) -> None:
        self.numerics_pass.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "status": "PASS",
                    "precision": "16-mixed",
                    "expected_train_examples": 864000,
                    "expected_train_batches": 27000,
                    "batch_size": 32,
                    "accumulate_grad_batches": 9,
                    "effective_batch_size": 288,
                    "expected_optimizer_attempts": 3000,
                    "global_step": 3000,
                    "successful_optimizer_steps": 3000,
                    "amp_overflows": 0,
                    "confirmed_amp_skip_backoffs": 0,
                    "source_semantic_sha256": semantic_sha256,
                    "base_config_relative_path": (
                        "selftrain/configs/full.yaml"
                    ),
                    "base_config_sha256": "1" * 64,
                    "environment": {
                        "python": platform.python_version(),
                        "torch_cuda": torch.version.cuda,
                        "gpu": {"name": "NVIDIA A100-PCIE-40GB"},
                        "packages": {
                            name: importlib.metadata.version(name)
                            for name in (
                                "torch",
                                "numpy",
                                "pytorch-lightning",
                            )
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_only_run_binding_changes_and_parent_is_immutable(self) -> None:
        source_sha256 = _sha256(self.source_checkpoint)
        source_mtime = self.source_checkpoint.stat().st_mtime_ns
        source_payload = _load_checkpoint(self.source_checkpoint)

        lineage = prepare_fork(self.args)

        self.assertEqual(_sha256(self.source_checkpoint), source_sha256)
        self.assertEqual(
            self.source_checkpoint.stat().st_mtime_ns, source_mtime
        )
        target_payload = _load_checkpoint(self.target_checkpoint)
        _assert_checkpoint_equivalent(source_payload, target_payload)
        self.assertNotIn("audattn_fork_provenance_v1", target_payload)
        self.assertEqual(
            target_payload["audattn_run_metadata_v1"],
            {
                "run_id": "child",
                "source_semantic_sha256": self.target_semantic,
                "config_sha256": source_payload[
                    "audattn_run_metadata_v1"
                ]["config_sha256"],
            },
        )
        self.assertEqual(lineage["global_step"], 7813)
        self.assertTrue(self.lineage.is_file())

    def test_wrong_pass_binding_is_rejected_without_partial_output(self) -> None:
        self._write_numerics_pass("f" * 64)
        with self.assertRaises(RuntimeError):
            prepare_fork(self.args)
        self.assertFalse(self.target_checkpoint.exists())
        self.assertFalse(self.lineage.exists())

    def test_versioned_epoch_source_imports_to_canonical_last(self) -> None:
        versioned = self.source_checkpoint.with_name("last-v1.ckpt")
        self.source_checkpoint.rename(versioned)
        self.source_checkpoint = versioned
        self.args.source_checkpoint = str(versioned)

        lineage = prepare_fork(self.args)

        self.assertEqual(self.target_checkpoint.name, "last.ckpt")
        self.assertTrue(self.target_checkpoint.is_file())
        self.assertEqual(
            pathlib.Path(lineage["source_checkpoint_path"]).name,
            "last-v1.ckpt",
        )

    def test_invalid_epoch_source_basename_is_rejected(self) -> None:
        invalid = self.source_checkpoint.with_name("epoch=3.ckpt")
        self.source_checkpoint.rename(invalid)
        self.args.source_checkpoint = str(invalid)
        with self.assertRaises(ValueError):
            prepare_fork(self.args)
        self.assertFalse(self.target_checkpoint.exists())

    def test_symbolic_link_source_is_rejected(self) -> None:
        link = self.source_checkpoint.with_name("last-v1.ckpt")
        link.symlink_to(self.source_checkpoint.name)
        self.args.source_checkpoint = str(link)
        with self.assertRaises(ValueError):
            prepare_fork(self.args)
        self.assertFalse(self.target_checkpoint.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
