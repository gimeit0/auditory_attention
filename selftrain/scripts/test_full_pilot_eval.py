"""Unit tests for per-trial pilot evaluation and release recomputation."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from selftrain.scripts.eval_full_pilot import (
    _mix_at_fixed_snr,
    recompute_pilot4_eval,
    validate_results_against_bank,
)


def synthetic_bank_and_results() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a compact-column but structurally exact 10k pilot fixture."""
    bank_rows: list[dict] = []
    trial_id = 0
    for distractor_count in range(1, 5):
        for snr_bin in range(5):
            for gender in ("female", "male"):
                for within_gender in range(225):
                    label = trial_id % 800
                    bank_rows.append(
                        {
                            "trial_id": trial_id,
                            "scene_kind": "mixed",
                            "control_subset": int(within_gender < 50),
                            "target_speaker": f"{gender[0]}{trial_id % 200:03d}",
                            "target_gender": gender,
                            "target_label": label,
                            "distractor_count": distractor_count,
                            "snr_bin": snr_bin,
                            "snr_db": -9.0 + 4.0 * snr_bin,
                            "distractor_1_label": (label + 1) % 800,
                        }
                    )
                    trial_id += 1
    for gender in ("female", "male"):
        for _ in range(500):
            label = trial_id % 800
            bank_rows.append(
                {
                    "trial_id": trial_id,
                    "scene_kind": "clean",
                    "control_subset": 0,
                    "target_speaker": f"{gender[0]}{trial_id % 200:03d}",
                    "target_gender": gender,
                    "target_label": label,
                    "distractor_count": 0,
                    "snr_bin": -1,
                    "snr_db": np.nan,
                    "distractor_1_label": -1,
                }
            )
            trial_id += 1
    bank = pd.DataFrame(bank_rows)
    labels = bank["target_label"].to_numpy(dtype=int)
    controls = bank["control_subset"].to_numpy(dtype=int) == 1
    probe = np.where(
        bank["scene_kind"].to_numpy() == "mixed",
        bank["distractor_1_label"].to_numpy(dtype=int),
        0,
    )
    results = bank[
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
    results["probe_distractor_label"] = probe
    results["scene_sha256"] = [f"{index:064x}" for index in range(len(bank))]
    results["stage0_pred_label"] = (labels + 2) % 800
    results["stage0_correct"] = 0
    results["stage0_nll"] = 7.0
    results["stage0_p_target"] = 0.001
    results["pilot_pred_label"] = labels
    results["pilot_correct"] = 1
    results["pilot_nll"] = 1.0
    results["pilot_p_target"] = 0.5
    results["pilot_p_probe_distractor"] = 0.01
    for condition in ("shuffled", "silent", "distractor"):
        results[f"pilot_{condition}_pred_label"] = np.nan
        results[f"pilot_{condition}_correct"] = np.nan
        results[f"pilot_{condition}_nll"] = np.nan
        results[f"pilot_{condition}_p_target"] = np.nan
        results[f"pilot_{condition}_probe_intrusion"] = np.nan
        results[f"pilot_{condition}_p_probe_distractor"] = np.nan
    wrong = (labels[controls] + 3) % 800
    for condition in ("shuffled", "silent"):
        results.loc[controls, f"pilot_{condition}_pred_label"] = wrong
        results.loc[controls, f"pilot_{condition}_correct"] = 0
        results.loc[controls, f"pilot_{condition}_nll"] = 7.0
        results.loc[controls, f"pilot_{condition}_p_target"] = 0.001
        results.loc[controls, f"pilot_{condition}_probe_intrusion"] = 0
        results.loc[controls, f"pilot_{condition}_p_probe_distractor"] = 0.01
    results.loc[controls, "pilot_distractor_pred_label"] = probe[controls]
    results.loc[controls, "pilot_distractor_correct"] = 0
    results.loc[controls, "pilot_distractor_nll"] = 7.0
    results.loc[controls, "pilot_distractor_p_target"] = 0.001
    results.loc[controls, "pilot_distractor_probe_intrusion"] = 1
    results.loc[controls, "pilot_distractor_p_probe_distractor"] = 0.8
    return bank, results


class FullPilotEvalTests(unittest.TestCase):
    def test_fixed_snr_mixer_has_correct_sign_and_level(self) -> None:
        phase = np.linspace(0, 16 * np.pi, 25_000, dtype=np.float32)
        target = np.stack((np.sin(phase), np.sin(phase)))
        background = np.stack((np.cos(phase), np.cos(phase)))
        positive, positive_error = _mix_at_fixed_snr(
            target, background, 10.0
        )
        negative, negative_error = _mix_at_fixed_snr(
            target, background, -10.0
        )
        self.assertEqual(positive.shape, target.shape)
        self.assertEqual(negative.shape, target.shape)
        self.assertLess(positive_error, 1e-4)
        self.assertLess(negative_error, 1e-4)
        # At -10 dB the background dominates, so the mixture RMS is larger.
        self.assertGreater(np.sqrt(np.mean(negative**2)), np.sqrt(np.mean(positive**2)))

    def test_structured_fixture_recomputes_go(self) -> None:
        bank, results = synthetic_bank_and_results()
        summary = recompute_pilot4_eval(
            results, bank, bootstrap_seed=17, bootstrap_repetitions=100
        )
        self.assertEqual(summary["decision"], "GO")
        self.assertEqual(summary["strata"]["mixed"]["trials"], 9000)
        self.assertEqual(summary["cue_controls"]["trials"], 2000)

    def test_tampered_derived_correctness_is_rejected(self) -> None:
        bank, results = synthetic_bank_and_results()
        results.loc[0, "pilot_correct"] = 0
        with self.assertRaises(ValueError):
            validate_results_against_bank(results, bank)

    def test_unbalanced_bank_is_rejected(self) -> None:
        bank, results = synthetic_bank_and_results()
        bank.loc[0, "target_gender"] = "male"
        results.loc[0, "target_gender"] = "male"
        with self.assertRaises(ValueError):
            validate_results_against_bank(results, bank)

    def test_nonfinite_prediction_metric_is_rejected(self) -> None:
        bank, results = synthetic_bank_and_results()
        results.loc[0, "stage0_nll"] = np.nan
        with self.assertRaises(ValueError):
            validate_results_against_bank(results, bank)


if __name__ == "__main__":
    unittest.main(verbosity=2)
