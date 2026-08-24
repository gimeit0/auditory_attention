"""Regression tests for the staged full-training schedule guard."""

from __future__ import annotations

import copy
import pathlib
import tempfile
import unittest

import yaml

from selftrain.scripts.check_training_phase import validate


class TrainingPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temporary_directory.name) / "full.yaml"
        self.config = {
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

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write(self, config=None) -> None:
        self.path.write_text(
            yaml.safe_dump(config or self.config), encoding="utf-8"
        )

    def test_pilot_and_full_boundaries(self) -> None:
        self._write()
        pilot = validate(self.path, "pilot4")
        full = validate(self.path, "full")
        self.assertEqual(pilot["last_completed_epoch_index"], 3)
        self.assertEqual(pilot["expected_completed_epochs"], 4)
        self.assertEqual(pilot["expected_final_global_step"], 6944)
        self.assertEqual(full["last_completed_epoch_index"], 39)
        self.assertEqual(full["expected_completed_epochs"], 40)
        self.assertEqual(full["expected_final_global_step"], 69440)

    def test_partial_accumulation_epoch_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["corpus"]["examples_per_epoch"] = 500000
        self._write(config)
        with self.assertRaises(ValueError):
            validate(self.path, "pilot4")

    def test_early_stopping_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        config["hparas"]["early_stopping"] = {"patience": 2}
        self._write(config)
        with self.assertRaises(ValueError):
            validate(self.path, "pilot4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
