"""Regression tests for per-trial-derived pilot GO records."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from selftrain.scripts import eval_full_pilot as evaluator_module
from selftrain.scripts.eval_full_pilot import recompute_pilot4_eval
from selftrain.scripts.pilot_release import create_release, validate_release
from selftrain.scripts.test_full_pilot_eval import synthetic_bank_and_results


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PilotReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bank_template, cls.results_template = synthetic_bank_and_results()
        cls.summary_template = recompute_pilot4_eval(
            cls.results_template, cls.bank_template
        )
        if cls.summary_template["decision"] != "GO":
            raise RuntimeError("Synthetic pilot-release fixture must pass")

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = (
            pathlib.Path(self.temporary_directory.name)
            / "project/selftrain/experiments/runs/pilot"
        )
        (self.root / "state").mkdir(parents=True)
        checkpoints = self.root / "full/checkpoints"
        checkpoints.mkdir(parents=True)
        self.stage0 = checkpoints / "stage-0.ckpt"
        self.stage0.write_bytes(b"stage zero")
        self.checkpoint = checkpoints / "pilot4-final.ckpt"
        self.checkpoint.write_bytes(b"pilot checkpoint")
        checkpoint_hash = _sha256(self.checkpoint)
        self.pilot_path = self.root / "state/PILOT4_COMPLETE.json"
        self.pilot_path.write_text(
            json.dumps(
                {
                    "status": "COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW",
                    "run_phase": "pilot4",
                    "run_id": "pilot",
                    "completed_epochs": 4,
                    "global_step": 6944,
                    "checkpoint": str(self.checkpoint),
                    "checkpoint_basename": self.checkpoint.name,
                    "checkpoint_sha256": checkpoint_hash,
                }
            ),
            encoding="utf-8",
        )
        self.cue_path = self.root / "state/cue_control_release.json"
        self.cue_path.write_text(
            json.dumps(
                {
                    "status": "RELEASED_FOR_FULL_DISTRIBUTION_PILOT",
                    "summary_sha256": "c" * 64,
                }
            ),
            encoding="utf-8",
        )
        self.review = self.root / "pilot_review.md"
        self.review.write_text(
            "GO after review of the per-trial evaluation\n", encoding="utf-8"
        )
        snapshot = self.root / "snapshot"
        scripts = snapshot / "files/selftrain/scripts"
        scripts.mkdir(parents=True)
        self.evaluator = scripts / "eval_full_pilot.py"
        self.evaluator.write_bytes(
            pathlib.Path(evaluator_module.__file__).resolve().read_bytes()
        )
        self.config = snapshot / "files/selftrain/configs/full.yaml"
        self.config.parent.mkdir(parents=True)
        self.config.write_text("frozen: config\n", encoding="utf-8")
        self.source_manifest = snapshot / "manifest.json"
        self.source_manifest.write_text(
            json.dumps({"semantic_combined_sha256": "s" * 64}),
            encoding="utf-8",
        )
        evaluation_root = self.root / "evaluation/pilot4"
        evaluation_root.mkdir(parents=True)
        self.bank = evaluation_root / "frozen_bank.tsv"
        self.results = evaluation_root / "jobs/1/per_trial_results.csv"
        self.results.parent.mkdir(parents=True)
        self.bank_template.to_csv(self.bank, sep="\t", index=False)
        self.results_template.to_csv(self.results, index=False)
        self.bank_freeze_state = self.root / "state/PILOT4_BANK_FROZEN.json"
        self.bank_freeze_state.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "FROZEN_BEFORE_PILOT_TRAINING",
                    "bank": str(self.bank.resolve()),
                    "bank_sha256": _sha256(self.bank),
                    "bank_seed": 20260816,
                    "config_sha256": _sha256(self.config),
                    "source_semantic_sha256": "s" * 64,
                    "evaluator_sha256": _sha256(self.evaluator),
                    "global_step_before_training": 0,
                }
            ),
            encoding="utf-8",
        )
        self.evaluation = self.results.parent / "PILOT4_EVAL.json"
        self._write_evaluation(copy.deepcopy(self.summary_template))
        self.bank_validation_patch = mock.patch(
            "selftrain.scripts.build_full_pilot_eval_bank.validate_bank_artifacts",
            return_value={},
        )
        self.bank_validation_patch.start()

    def tearDown(self) -> None:
        self.bank_validation_patch.stop()
        self.temporary_directory.cleanup()

    def _write_evaluation(self, summary: dict) -> None:
        summary["run_id"] = "pilot"
        summary["frozen_inputs"] = {
            "bank_sha256": _sha256(self.bank),
            "results_sha256": _sha256(self.results),
            "evaluator_sha256": _sha256(self.evaluator),
            "bank_freeze_state_sha256": _sha256(self.bank_freeze_state),
            "config_sha256": _sha256(self.config),
            "source_manifest_file_sha256": _sha256(self.source_manifest),
            "source_semantic_sha256": "s" * 64,
            "stage0_checkpoint": {
                "path": str(self.stage0.resolve()),
                "sha256": _sha256(self.stage0),
                "global_step": 0,
                "completed_epochs": 0,
            },
            "pilot_checkpoint": {
                "path": str(self.checkpoint.resolve()),
                "sha256": _sha256(self.checkpoint),
                "global_step": 6944,
                "completed_epochs": 4,
            },
        }
        self.evaluation.write_text(
            json.dumps(summary, allow_nan=False), encoding="utf-8"
        )

    def _create(self) -> dict:
        return create_release(
            self.root,
            self.review,
            self.evaluation,
            self.bank,
            self.results,
            self.evaluator,
            self.config,
            self.source_manifest,
            self.stage0,
        )

    def _publish(self) -> None:
        release = self._create()
        (self.root / "state/PILOT4_GO.json").write_text(
            json.dumps(release), encoding="utf-8"
        )

    def test_bound_go_record_is_accepted(self) -> None:
        self._publish()
        release = validate_release(self.root)
        self.assertEqual(release["pilot_global_step"], 6944)
        self.assertEqual(release["schema_version"], 2)

    def test_results_change_after_go_is_rejected(self) -> None:
        self._publish()
        with self.results.open("a", encoding="utf-8") as handle:
            handle.write("tamper\n")
        with self.assertRaises(ValueError):
            validate_release(self.root)

    def test_review_change_is_rejected(self) -> None:
        self._publish()
        self.review.write_text("changed decision\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_release(self.root)

    def test_handwritten_go_cannot_override_inconclusive_results(self) -> None:
        changed = self.results_template.copy()
        changed["pilot_pred_label"] = changed["stage0_pred_label"]
        changed["pilot_correct"] = 0
        changed["pilot_nll"] = changed["stage0_nll"]
        changed["pilot_p_target"] = changed["stage0_p_target"]
        changed.to_csv(self.results, index=False)
        # Keep a formally shaped GO summary and update only its result hash.
        # Release must discover that the rows do not reproduce that summary.
        self._write_evaluation(copy.deepcopy(self.summary_template))
        with self.assertRaises(ValueError):
            self._create()

    def test_nan_result_cannot_create_go(self) -> None:
        changed = self.results_template.copy()
        changed.loc[0, "pilot_nll"] = float("nan")
        changed.to_csv(self.results, index=False)
        self._write_evaluation(copy.deepcopy(self.summary_template))
        with self.assertRaises(ValueError):
            self._create()


if __name__ == "__main__":
    unittest.main(verbosity=2)
