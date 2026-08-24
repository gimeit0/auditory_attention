"""Regression tests for the full-continuation lower boundary."""

from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from selftrain.scripts.full_started import create_record, validate_record


class FullStartedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary_directory.name) / "run"
        (self.root / "state").mkdir(parents=True)
        checkpoint = self.root / "full/checkpoints/pilot4-final.ckpt"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"pilot checkpoint")
        self.pilot_path = self.root / "state/PILOT4_COMPLETE.json"
        self.pilot_path.write_text(
            json.dumps(
                {
                    "status": "COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW",
                    "run_phase": "pilot4",
                    "run_id": "pilot-run",
                    "completed_epochs": 4,
                    "global_step": 6944,
                    "checkpoint_basename": checkpoint.name,
                    "checkpoint_sha256": hashlib.sha256(
                        checkpoint.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _publish(self) -> None:
        record = create_record(self.root, "123")
        (self.root / "state/FULL_STARTED.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    def test_bound_record_and_forward_checkpoint_are_accepted(self) -> None:
        self._publish()
        result = validate_record(self.root, checkpoint_global_step=7000)
        self.assertEqual(result["initial_checkpoint_global_step"], 6944)

    def test_checkpoint_before_pilot_boundary_is_rejected(self) -> None:
        self._publish()
        with self.assertRaises(ValueError):
            validate_record(self.root, checkpoint_global_step=6000)

    def test_empty_record_is_rejected(self) -> None:
        (self.root / "state/FULL_STARTED.json").touch()
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            validate_record(self.root)

    def test_changed_pilot_completion_is_rejected(self) -> None:
        self._publish()
        pilot = json.loads(self.pilot_path.read_text(encoding="utf-8"))
        pilot["checkpoint_sha256"] = "0" * 64
        self.pilot_path.write_text(json.dumps(pilot), encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_record(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
