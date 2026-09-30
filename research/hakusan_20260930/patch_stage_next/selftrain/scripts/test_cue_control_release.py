"""Regression tests for the confirmatory cue-control gate."""

from __future__ import annotations

import hashlib
import json
import pathlib
import tempfile
import unittest

from selftrain.scripts.check_cue_control_release import (
    EXPECTED,
    validate,
    validate_release_record,
)


class CueControlReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary_directory.name)
        self.results = self.root / "results_full.csv"
        with self.results.open("w", encoding="utf-8") as handle:
            handle.write(
                "trial_id,target_speaker,correct_correct,shuffled_correct,"
                "silent_correct,distractor_correct\n"
            )
            for trial_id in range(10000):
                handle.write(f"{trial_id},s{trial_id % 100},1,0,0,0\n")
        self.frozen = self.root / "frozen_inputs.env"
        self.frozen.write_text(
            "".join(f"{key}={value}\n" for key, value in EXPECTED.items()),
            encoding="utf-8",
        )
        output_hash = hashlib.sha256(self.results.read_bytes()).hexdigest()
        self.summary = {
            "analysis_kind": "confirmatory",
            "trials": 10000,
            "preregistered_primary_criterion": {
                "pass": True,
                "status": "CONFIRMATORY_PASS",
                "correct_minus_max_shuffled_silent": 1.0,
                "required_delta": 0.05,
                "all_primary_ci_lower_bounds_positive": True,
            },
            "conditions": {
                "correct": {"accuracy": 1.0},
                "shuffled": {"accuracy": 0.0},
                "silent": {"accuracy": 0.0},
                "distractor": {"accuracy": 0.0},
            },
            "paired_comparisons": {
                "correct_minus_shuffled": {
                    "accuracy_delta": 1.0,
                    "cluster_bootstrap_95ci": [1.0, 1.0],
                },
                "correct_minus_silent": {
                    "accuracy_delta": 1.0,
                    "cluster_bootstrap_95ci": [1.0, 1.0],
                },
            },
            "frozen_inputs": {
                "checkpoint_sha256": EXPECTED["CHECKPOINT_SHA256"],
                "config_sha256": EXPECTED["CONFIG_SHA256"],
                "manifest_sha256": EXPECTED["MANIFEST_SHA256"],
                "output_sha256": output_hash,
            },
        }
        self.summary_path = self.root / "summary_full.json"
        self._write_summary()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_summary(self) -> None:
        self.summary_path.write_text(
            json.dumps(self.summary), encoding="utf-8"
        )

    def test_confirmatory_pass_is_released(self) -> None:
        result = validate(self.root)
        self.assertEqual(result["trials"], 10000)

    def test_confirmatory_fail_is_rejected(self) -> None:
        self.summary["preregistered_primary_criterion"]["pass"] = False
        self.summary["preregistered_primary_criterion"][
            "status"
        ] = "CONFIRMATORY_FAIL"
        self._write_summary()
        with self.assertRaises(ValueError):
            validate(self.root)

    def test_smoke_is_rejected(self) -> None:
        self.summary["analysis_kind"] = "smoke"
        self.summary["trials"] = 32
        self._write_summary()
        with self.assertRaises(ValueError):
            validate(self.root)

    def test_truncated_results_are_rejected_even_if_summary_claims_pass(self) -> None:
        self.results.write_text(
            "trial_id,target_speaker,correct_correct,shuffled_correct,"
            "silent_correct,distractor_correct\n0,s0,1,0,0,0\n",
            encoding="utf-8",
        )
        output_hash = hashlib.sha256(self.results.read_bytes()).hexdigest()
        self.summary["frozen_inputs"]["output_sha256"] = output_hash
        self._write_summary()
        with self.assertRaises(ValueError):
            validate(self.root)

    def test_nan_summary_accuracy_is_rejected(self) -> None:
        self.summary["conditions"]["correct"]["accuracy"] = float("nan")
        self._write_summary()
        with self.assertRaises(ValueError):
            validate(self.root)

    def test_nan_cluster_interval_is_rejected(self) -> None:
        self.summary["paired_comparisons"]["correct_minus_silent"][
            "cluster_bootstrap_95ci"
        ][0] = float("nan")
        self._write_summary()
        with self.assertRaises(ValueError):
            validate(self.root)

    def test_frozen_release_record_is_revalidated(self) -> None:
        record = validate(self.root)
        record_path = self.root / "cue_control_release.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(validate_release_record(record_path)["trials"], 10000)
        record["results_sha256"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_release_record(record_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
