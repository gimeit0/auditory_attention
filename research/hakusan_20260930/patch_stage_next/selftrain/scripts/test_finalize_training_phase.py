"""Regression tests for guarded phase completion."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import torch
import yaml

from selftrain.scripts.finalize_training_phase import validate_checkpoint


class FinalizeTrainingPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary_directory.name)
        self.config = self.root / "full.yaml"
        self.config.write_text(
            yaml.safe_dump(
                {
                    "corpus": {
                        "examples_per_epoch": 499968,
                        "validation_examples": 10000,
                        "min_distractors": 1,
                        "max_distractors": 4,
                        "cue_free_percentage": 0.1,
                    },
                    "noise_kwargs": {"low_snr": -10, "high_snr": 10},
                    "hparas": {
                        "epochs": 40,
                        "batch_size": 32,
                        "accumulate_grad_batches": 9,
                        "valid_step": 1.0,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.checkpoint = self.root / "pilot4-final.ckpt"
        self.payload = {
            "epoch": 4,
            "global_step": 6944,
            "loops": {
                "fit_loop": {
                    "epoch_progress": {"total": {"completed": 4}}
                }
            },
            "audattn_amp_state_v1": {
                "total_optimizer_attempts": 6944,
                "successful_optimizer_steps": 6942,
                "total_overflows": 2,
            },
            "audattn_run_metadata_v1": {
                "run_id": "pilot",
                "source_semantic_sha256": "a" * 64,
                "config_sha256": "b" * 64,
            },
        }
        self._write()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write(self) -> None:
        torch.save(self.payload, self.checkpoint)

    def _validate(self):
        return validate_checkpoint(
            self.checkpoint,
            self.config,
            "pilot4",
            "pilot",
            "123",
            "a" * 64,
            "b" * 64,
        )

    def test_post_fit_epoch_value_is_accepted(self) -> None:
        result = self._validate()
        self.assertEqual(result["completed_epochs"], 4)
        self.assertEqual(result["last_completed_epoch_index"], 3)

    def test_callback_style_epoch_value_is_also_accepted(self) -> None:
        self.payload["epoch"] = 3
        self._write()
        self.assertEqual(self._validate()["completed_epochs"], 4)

    def test_incomplete_loop_is_rejected(self) -> None:
        self.payload["loops"]["fit_loop"]["epoch_progress"]["total"][
            "completed"
        ] = 3
        self._write()
        with self.assertRaises(ValueError):
            self._validate()

    def test_wrong_global_step_is_rejected(self) -> None:
        self.payload["global_step"] = 6943
        self._write()
        with self.assertRaises(ValueError):
            self._validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
