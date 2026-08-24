"""Regression tests for the numerical-PASS contract."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from selftrain.scripts.run_integrity import validate_numerics_pass


class NumericsPassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temporary_directory.name)
        self.pass_path = root / "PASS.json"
        self.manifest_path = root / "manifest.json"
        self.semantic_sha256 = "a" * 64
        self.config_sha256 = "b" * 64
        self.manifest_path.write_text(
            json.dumps(
                {
                    "semantic_combined_sha256": self.semantic_sha256,
                    "semantic_files": [
                        {
                            "path": "selftrain/configs/full.yaml",
                            "sha256": self.config_sha256,
                            "size": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.result = {
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
            "successful_optimizer_steps": 2998,
            "amp_overflows": 2,
            "confirmed_amp_skip_backoffs": 2,
            "source_semantic_sha256": self.semantic_sha256,
            "base_config_relative_path": "selftrain/configs/full.yaml",
            "base_config_sha256": self.config_sha256,
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write(self) -> None:
        self.pass_path.write_text(
            json.dumps(self.result), encoding="utf-8"
        )

    def test_valid_schema_three_pass_is_accepted(self) -> None:
        self._write()
        validated = validate_numerics_pass(
            self.pass_path, self.manifest_path
        )
        self.assertEqual(validated["accumulate_grad_batches"], 9)

    def test_old_schema_is_rejected(self) -> None:
        self.result["schema_version"] = 2
        self._write()
        with self.assertRaises(RuntimeError):
            validate_numerics_pass(self.pass_path, self.manifest_path)

    def test_accumulation_arithmetic_mismatch_is_rejected(self) -> None:
        self.result["accumulate_grad_batches"] = 2
        self._write()
        with self.assertRaises(RuntimeError):
            validate_numerics_pass(self.pass_path, self.manifest_path)

    def test_base_config_hash_mismatch_is_rejected(self) -> None:
        self.result["base_config_sha256"] = "f" * 64
        self._write()
        with self.assertRaises(RuntimeError):
            validate_numerics_pass(self.pass_path, self.manifest_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
