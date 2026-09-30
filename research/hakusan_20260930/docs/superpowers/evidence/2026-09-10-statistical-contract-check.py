#!/usr/bin/env python3
"""Synthetic-only checks of the pinned, unchanged v4 statistical implementation.

No remote access, model inference, data downloads, or scientific result output.
These checks do not replace publication/provenance verification of real results.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py"
SOURCE_SHA = "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
    raise RuntimeError("fixed scientific implementation changed")
SPEC = importlib.util.spec_from_file_location("fixed_statistical_contract", SOURCE)
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


def synthetic_frame():
    rows = []
    correct = {
        "formal40": [1, 1, 0, 1, 0, 1],
        "valbest33": [0, 1, 0, 0, 0, 1],
        "author_external": [0, 0, 0, 0, 0, 1],
    }
    losses = {
        "formal40": [1, 2, 3, 4, 5, 6],
        "valbest33": [2, 4, 4, 7, 5, 8],
        "author_external": [3, 4, 6, 7, 8, 9],
    }
    for i in range(6):
        control = i < 4
        row = dict(
            trial_id=i, scene_kind="mixed" if control else "clean",
            control_subset=int(control), target_speaker=["a", "a", "b", "c", "a", "d"][i],
            target_gender="female" if i % 2 else "male", target_norm="word",
            target_label=7, distractor_count=1 if control else 0,
            snr_bin=0 if control else -1, snr_db=-8.0 if control else np.nan,
            probe_distractor_norm="probe" if control else "",
            probe_distractor_label=8 if control else 0,
            scene_sha256=f"{i:064x}", correct_cue_sha256=f"{i+10:064x}",
        )
        for model in EVAL.MODEL_IDS:
            row.update({
                f"{model}_pred_label": 7 if correct[model][i] else 8,
                f"{model}_correct": correct[model][i],
                f"{model}_nll": losses[model][i],
                f"{model}_p_target": np.exp(-losses[model][i]),
                f"{model}_p_probe_distractor": 0.1,
            })
            for condition in EVAL.CONTROL_CONDITIONS:
                values = (8, 0, 4.0, np.exp(-4.0), 1, 0.3)
                names = ("pred_label", "correct", "nll", "p_target", "probe_intrusion", "p_probe_distractor")
                row.update({f"{model}_{condition}_{key}": value if control else np.nan
                            for key, value in zip(names, values)})
        rows.append(row)
    return pd.DataFrame(rows)


class StatisticalContractTests(unittest.TestCase):
    def test_frozen_constants_and_roles(self):
        self.assertEqual(EVAL.BOOTSTRAP_SEED, 20260829)
        self.assertEqual(EVAL.BOOTSTRAP_REPETITIONS, 10000)
        self.assertEqual(EVAL.MODEL_IDS, ("formal40", "valbest33", "author_external"))
        self.assertEqual(EVAL.MODEL_ROLES["formal40"], "primary_fixed_40_epoch")
        self.assertEqual(EVAL.EVALUATION_ROLE, "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST")

    def test_unequal_cluster_ci_matches_explicit_trial_resampling(self):
        sizes = [1, 2, 3, 5, 7, 11, 13, 17]
        means = [-5, -2, -1, 0, 1, 2, 4, 8]
        clusters = [np.full(n, value, dtype=float) for n, value in zip(sizes, means)]
        values = np.concatenate(clusters)
        speakers = np.concatenate([np.full(n, str(i)) for i, n in enumerate(sizes)])
        seed, reps = EVAL.BOOTSTRAP_SEED, EVAL.BOOTSTRAP_REPETITIONS
        rng = np.random.default_rng(seed)
        expanded = []
        unweighted = []
        for _ in range(reps):
            draw = rng.integers(0, len(clusters), size=len(clusters))
            expanded.append(np.concatenate([clusters[i] for i in draw]).mean())
            unweighted.append(np.asarray(means)[draw].mean())
        expected = np.quantile(expanded, [0.025, 0.975], method="linear")
        actual = EVAL.cluster_bootstrap_ci(values, speakers, seed, reps)
        np.testing.assert_array_equal(actual, expected)
        self.assertFalse(np.allclose(actual, np.quantile(unweighted, [0.025, 0.975])))

    def test_paired_signs_counts_and_speaker_clusters(self):
        frame = synthetic_frame()
        summary = EVAL.summarize_results(frame, full_run=False)
        for pair in summary["paired_model_differences"].values():
            a, b = pair["model_a"], pair["model_b"]
            overall = pair["strata"]["overall"]
            accuracy = overall["accuracy_difference_a_minus_b_positive_favors_a"]
            ce = overall["cross_entropy_improvement_b_minus_a_positive_favors_a"]
            self.assertEqual(accuracy["mean"], float((frame[a+"_correct"]-frame[b+"_correct"]).mean()))
            self.assertEqual(ce["mean"], float((frame[b+"_nll"]-frame[a+"_nll"]).mean()))
            self.assertGreater(accuracy["mean"], 0)
            self.assertGreater(ce["mean"], 0)
            self.assertEqual(overall["trials"], 6)
            self.assertEqual(accuracy["unique_target_speakers"], 4)

    def test_controls_are_subset_paired_and_probability_delta_has_correct_sign(self):
        frame = synthetic_frame()
        summary = EVAL.summarize_results(frame, full_run=False)
        for model in EVAL.MODEL_IDS:
            controls = summary["models"][model]["cue_controls"]
            expected = float(frame.loc[frame.control_subset == 1, model+"_correct"].mean())
            self.assertEqual(controls["trials"], 4)
            self.assertEqual(controls["correct_minus_silent"]["mean"], expected)
            self.assertAlmostEqual(controls["distractor_cue_p_probe_delta"]["mean"], 0.2)

    def test_smoke_has_no_inferential_ci(self):
        summary = EVAL.summarize_results(synthetic_frame(), full_run=False)
        self.assertIs(summary["bootstrap"]["performed"], False)
        for pair in summary["paired_model_differences"].values():
            for stratum in pair["strata"].values():
                for metric in stratum.values():
                    if isinstance(metric, dict):
                        self.assertEqual(metric["bootstrap_status"], "NOT_RUN_ENGINEERING_SMOKE")
                        self.assertIsNone(metric["target_speaker_cluster_bootstrap_95ci"])

    def test_full_run_rejects_synthetic_short_bank(self):
        with self.assertRaisesRegex(EVAL.EvaluationError, "10,000"):
            EVAL.summarize_results(synthetic_frame(), full_run=True)

    def test_point_strata_partition_and_units(self):
        summary = EVAL.summarize_results(synthetic_frame(), full_run=False)
        strata = summary["models"]["formal40"]["strata"]
        self.assertEqual(strata["mixed"]["trials"], 4)
        self.assertEqual(strata["clean"]["trials"], 2)
        self.assertEqual(strata["overall"]["accuracy"], 4/6)
        self.assertEqual(strata["overall"]["cross_entropy"], 3.5)
        self.assertEqual(strata["distractors_1__snr_bin_0"]["trials"], 4)


if __name__ == "__main__":
    outcome = unittest.main(exit=False, verbosity=2).result
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError("source changed during checks")
    print("SCOPE=SYNTHETIC_STATISTICS_ONLY_NO_SCIENTIFIC_RESULTS", flush=True)
    print("PINNED_EVALUATOR_UNCHANGED=" + SOURCE_SHA, flush=True)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
