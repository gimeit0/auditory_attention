"""Read-only post-result sensitivity audit; never changes the frozen P06 policy.

Run from any directory with Python + numpy + pandas. Prints JSON only.
Bounds are conditional on a uniform per-output perturbation envelope, not a
measurement of full-bank batch1 results or new confidence intervals.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs/superpowers/evidence"
ARCHIVE = EVIDENCE / "p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k"
LOGIT_EPS = 0.004
NLL_EPS = 0.002
MODELS = ("formal40", "author_external", "valbest33")


def near_tie_fraction(logits, epsilon):
    x = np.asarray(logits, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] == 0 or x.shape[1] < 2:
        raise ValueError("Expected nonempty samples x classes")
    if epsilon < 0 or not np.isfinite(epsilon) or not np.isfinite(x).all():
        raise ValueError("Expected finite logits and nonnegative epsilon")
    top = np.partition(x, -2, axis=1)[:, -2:]
    return float(np.mean(top[:, 1] - top[:, 0] <= 2 * epsilon))


def paired_bound(bound_a, bound_b):
    return bound_a + bound_b


def audit():
    manifest = EVIDENCE / "p10-delivery-20260919/SHA256SUMS.txt"
    checked = 0
    for line in manifest.read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Frozen source changed: {name}")
        checked += 1
    frame = pd.read_csv(ARCHIVE / "results.csv", low_memory=False)
    if frame.trial_id.tolist() != list(range(10000)):
        raise ValueError("Unexpected full-bank trial order")
    stats = json.loads((EVIDENCE / "p09-statistics-20260919/STATISTICS.json").read_text())
    original = stats["v4_summary"]["paired_model_differences"]["formal40_vs_author_external"]["strata"]
    strata = {}
    with np.load(ARCHIVE / "logits.npz", allow_pickle=False) as arrays:
        for model in MODELS:
            x = arrays[model + "__correct"]
            if x.shape != (10000, 800) or not np.array_equal(x.argmax(axis=1), frame[model + "_pred_label"]):
                raise ValueError(f"Logit/table mismatch: {model}")
        for name, mask in {
            "overall": np.ones(len(frame), dtype=bool),
            "mixed": (frame.scene_kind == "mixed").to_numpy(),
            "clean": (frame.scene_kind == "clean").to_numpy(),
        }.items():
            bounds = {m: near_tie_fraction(arrays[m + "__correct"][mask], LOGIT_EPS) for m in MODELS}
            accuracy = float((frame.formal40_correct - frame.author_external_correct)[mask].mean())
            nll = float((frame.author_external_nll - frame.formal40_nll)[mask].mean())
            metrics = original[name]
            if not np.isclose(accuracy, metrics["accuracy_difference_a_minus_b_positive_favors_a"]["mean"], atol=1e-12, rtol=0):
                raise ValueError("Accuracy summary mismatch")
            if not np.isclose(nll, metrics["cross_entropy_improvement_b_minus_a_positive_favors_a"]["mean"], atol=1e-12, rtol=0):
                raise ValueError("NLL summary mismatch")
            acc_bound = paired_bound(bounds["formal40"], bounds["author_external"])
            nll_bound = paired_bound(NLL_EPS, NLL_EPS)
            strata[name] = {
                "n": int(mask.sum()), "conditional_accuracy_bounds": bounds,
                "accuracy_difference": accuracy,
                "conditional_accuracy_point_range": [accuracy - acc_bound, accuracy + acc_bound],
                "nll_improvement": nll,
                "conditional_nll_point_range": [nll - nll_bound, nll + nll_bound],
                "original_accuracy_ci": metrics["accuracy_difference_a_minus_b_positive_favors_a"]["target_speaker_cluster_bootstrap_95ci"],
                "original_nll_ci": metrics["cross_entropy_improvement_b_minus_a_positive_favors_a"]["target_speaker_cluster_bootstrap_95ci"],
            }
    return {"status": "OFFLINE_SENSITIVITY_AUDIT_PASS", "frozen_files_verified": checked,
            "scope": "post-result mathematical erratum; conditional point ranges, not new 95% CIs",
            "uniform_envelope_proven_for_full_bank": False,
            "full_bank_batch1_measured": False, "jobs_submitted": 0, "strata": strata}


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, allow_nan=False))
