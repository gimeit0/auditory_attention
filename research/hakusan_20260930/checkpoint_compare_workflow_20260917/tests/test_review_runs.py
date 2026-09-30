"""Synthetic archive tests. Native declarations below are TEST DATA, not evidence.

The production checkpoint/GPU is never loaded. Fixtures use the existing tiny
disk-checkpoint/strict-load/forward path and are deleted after every test.
"""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest

import torch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVIEW = load(
    "archive_review_tests", ROOT / "checkpoint_compare_workflow_20260917/review_runs.py"
)
FIXTURE = load(
    "candidate_fixture_tests",
    ROOT / "same_bank_compare_2026_09_17_eager_v1/tests/test_eager_compare.py",
)
E, BASE = FIXTURE.E, FIXTURE.BASE


class ReviewTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.fixture = FIXTURE.CandidateTests("test_exclusive_artifact_creation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.counter = 0

    def archive(self, batch=16, modify_run=None, modify_details=None, flip=False):
        self.counter += 1
        output = self.fixture.root / f"archive-{self.counter}"
        output.mkdir()
        results, arrays, details = self.fixture.run_pass(batch)
        if flip:
            key = "formal40__correct"
            row = arrays[key][0]
            row[(int(row.argmax()) + 1) % 800] = row.max() + 20
            logits = torch.from_numpy(arrays[key])
            logp = logits.log_softmax(-1)
            labels = torch.tensor(self.fixture.bank.target_label.to_numpy())
            probes = torch.tensor(
                BASE._prepare_result_frame(
                    self.fixture.bank
                ).probe_distractor_label.to_numpy(dtype=int)
            )
            rows = torch.arange(len(logits))
            results["formal40_pred_label"] = logits.argmax(1).numpy()
            results["formal40_correct"] = (logits.argmax(1) == labels).long().numpy()
            results["formal40_nll"] = (-logp[rows, labels]).numpy()
            results["formal40_p_target"] = logp[rows, labels].exp().numpy()
            results["formal40_p_probe_distractor"] = logp[rows, probes].exp().numpy()
        if modify_details:
            modify_details(details)
        E.save_pass(output, self.fixture.bank, results, arrays, details)
        run = {
            "scope": "SYNTHETIC_TEST_NATIVE_DECLARATIONS_ARE_FIXTURES",
            "protocol": E.PROTOCOL,
            "role": E.ROLE,
            "candidate_sha256": REVIEW.CANDIDATE_SHA,
            "v4_source_sha256": E.V4_SHA,
            "v4_manifest_sha256": E.MANIFEST_SHA,
            "models": {
                m: {"sha256": BASE.EXPECTED_HASHES[m], "role": BASE.MODEL_ROLES[m]}
                for m in E.MODEL_ORDER
            },
            "model_order": list(E.MODEL_ORDER),
            "trial_ids": list(E.TRIAL_IDS),
            "historical_scene_hashes": {
                str(i): self.fixture.hashes[i] for i in E.TRIAL_IDS
            },
            "runtime": copy.deepcopy(REVIEW.RUNTIME),
            "amp": False,
            "compiled_forward": False,
            "batch_size": batch,
            "tail_policy": "unmodified smaller final batch",
            "job_id": "123456",
            "pid": 1000 + self.counter,
            "started_utc": "2026-09-17T12:00:00+00:00",
            "environment": {
                "python": "3.11.5",
                "torch": "2.1.1+cu118",
                "cuda": "11.8",
                "cudnn": 8700,
                "hostname": "synthetic-test-only",
                "device": "NVIDIA A100-PCIE-40GB",
            },
        }
        if modify_run:
            modify_run(run)
        E.create_json(output / "RUN.json", run)
        loads = {}
        for model_id, model in self.fixture.models.items():
            size = sum(p.numel() for p in model.parameters())
            loads[model_id] = {
                "scope": "synthetic fixture load report",
                "loaded_trainable_numel_ratio": 1.0,
                "loaded_trainable_numel": size,
                "trainable_numel": size,
                "eager_unwrap": {
                    "known_wrapper_removed": True,
                    "state_bindings_preserved": len(list(model.named_parameters()))
                    + len(list(model.named_buffers())),
                },
            }
        E.create_json(output / "LOAD_REPORTS.json", loads)
        E.create_json(
            output / "RECEIPT.json",
            {
                "protocol": E.PROTOCOL,
                "status": "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
                "files": {p.name: E.sha256(p) for p in output.iterdir()},
            },
        )
        return output, E.sha256(output / "RECEIPT.json")

    def read(self, artifact):
        return REVIEW.read_archive(E, BASE, *artifact)

    def test_pinned_core_load(self):
        candidate, base = REVIEW.load_core()
        self.assertEqual(candidate.PROTOCOL, E.PROTOCOL)
        self.assertEqual(base.PROTOCOL_ID, BASE.PROTOCOL_ID)

    def test_independent_same_batch_archive_comparison_no_auto_qualification(self):
        a, b = self.read(self.archive()), self.read(self.archive())
        result = REVIEW.compare_archives(E, BASE, a, b, "cold-repeat")
        self.assertEqual(result["status"], "NUMERIC_SENSITIVITY_RECORDED")
        self.assertEqual(result["scientific_qualification"], "NOT_DECIDED")
        self.assertFalse(result["full_run_authorized"])
        self.assertEqual(result["legacy_v4_result_table_canary_1e_6"]["status"], "PASS")
        for value in result["by_model_condition"].values():
            self.assertTrue(value["logits_bitwise_equal"])
            self.assertEqual(value["prediction_flips"], 0)
        json.dumps(result, allow_nan=False)

    def test_batch_size_report_and_paired_bounds(self):
        a, b = self.read(self.archive(16)), self.read(self.archive(1))
        result = REVIEW.compare_archives(E, BASE, a, b, "batch-size")
        self.assertEqual(len(result["by_model_condition"]), 12)
        for condition in result["paired_model_gap_changes"].values():
            for metric in condition.values():
                self.assertLessEqual(
                    abs(metric["gap_change"]),
                    metric["sample_only_absolute_change_bound"] + 1e-12,
                )

    def test_valid_semantic_logit_change_reports_diff_and_flip(self):
        a, b = self.read(self.archive()), self.read(self.archive(flip=True))
        result = REVIEW.compare_archives(E, BASE, a, b, "cold-repeat")
        self.assertEqual(result["legacy_v4_result_table_canary_1e_6"]["status"], "DIFF")
        self.assertEqual(
            result["by_model_condition"]["formal40__correct"]["prediction_flips"], 1
        )
        self.assertFalse(result["full_run_authorized"])

    def test_same_receipt_not_a_cold_repeat(self):
        a = self.read(self.archive())
        with self.assertRaisesRegex(ValueError, "Same receipt"):
            REVIEW.compare_archives(E, BASE, a, a, "cold-repeat")

    def test_same_process_copy_not_a_cold_repeat(self):
        a = self.read(self.archive())

        def same(run):
            run["pid"] = a["run"]["pid"]
            run["different_annotation"] = "Does not make a new process"

        b = self.read(self.archive(modify_run=same))
        with self.assertRaisesRegex(ValueError, "Same process"):
            REVIEW.compare_archives(E, BASE, a, b, "cold-repeat")

    def test_changed_control_cue_identity_not_numeric_noise(self):
        a = self.read(self.archive())

        def changed(details):
            details["cue_hashes"]["silent"][0] = "a" * 64

        b = self.read(self.archive(modify_details=changed))
        with self.assertRaisesRegex(ValueError, "cue identities differ"):
            REVIEW.compare_archives(E, BASE, a, b, "cold-repeat")

    def test_batch_change_cannot_be_called_cold_repeat(self):
        a, b = self.read(self.archive(16)), self.read(self.archive(1))
        with self.assertRaisesRegex(ValueError, "same batch"):
            REVIEW.compare_archives(E, BASE, a, b, "cold-repeat")

    def test_wrong_amp_configuration_rejected(self):
        artifact = self.archive(modify_run=lambda run: run.update(amp=True))
        with self.assertRaisesRegex(ValueError, "eager FP32"):
            self.read(artifact)

    def test_wrong_native_version_rejected(self):
        artifact = self.archive(
            modify_run=lambda run: run["environment"].update(torch="2.12.1")
        )
        with self.assertRaisesRegex(ValueError, "native Python"):
            self.read(artifact)

    def test_missing_state_check_rejected(self):
        artifact = self.archive(
            modify_details=lambda details: details.update(model_state_unchanged=False)
        )
        with self.assertRaisesRegex(ValueError, "state check"):
            self.read(artifact)

    def test_hash_corruption_rejected_before_metric_comparison(self):
        output, digest = self.archive()
        # Intentional damage of a TEMPORARY test artifact, never a real result.
        with (output / "results.csv").open("ab") as handle:
            handle.write(b"\n")
        with self.assertRaisesRegex(RuntimeError, "Artifact changed"):
            self.read((output, digest))


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
