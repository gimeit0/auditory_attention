#!/usr/bin/env python3
"""Read-only comparison of two independently verified small-run archives.

No SSH, submission, execution of checkpoints, changed numeric thresholds or
automatic qualification. Report stdout may be saved by the workflow wrapper.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = ROOT / "same_bank_compare_2026_09_17_eager_v1/eager_compare.py"
CANDIDATE_SHA = "d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4"
V4 = ROOT / "same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py"
RUNTIME = {
    "deterministic_algorithms": True,
    "cudnn_deterministic": True,
    "cudnn_benchmark": False,
    "matmul_precision": "highest",
    "matmul_tf32": False,
    "cudnn_tf32": False,
}


def require(value, message):
    if not value:
        raise ValueError(message)


def load_core():
    require(
        hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() == CANDIDATE_SHA,
        "Candidate changed; review this reader against the new source",
    )
    spec = importlib.util.spec_from_file_location("small_candidate_reader", CANDIDATE)
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    return candidate, candidate.load_v4(V4)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_declaration(candidate, base, run, details, loads):
    """Explicit scientific fields only, not runtime object-graph attestation."""
    require(run["candidate_sha256"] == CANDIDATE_SHA, "Wrong executed candidate SHA")
    require(run["model_order"] == list(candidate.MODEL_ORDER), "Wrong model order")
    require(
        run["amp"] is False and run["compiled_forward"] is False,
        "Not eager FP32 execution",
    )
    require(
        run["runtime"] == details["runtime"] == RUNTIME, "Declared runtime mismatch"
    )
    require(
        type(run["batch_size"]) is int and run["batch_size"] in (1, 16),
        "Invalid batch size",
    )
    require(details["batch_size"] == run["batch_size"], "RUN/pass batch mismatch")
    require(run["tail_policy"] == "unmodified smaller final batch", "Wrong tail policy")
    for field in (
        "model_state_unchanged",
        "rng_state_unchanged",
        "bank_rows_unchanged",
    ):
        require(details[field] is True, f"Missing successful state check: {field}")
    require(
        str(run["job_id"]).isdigit() and int(run["job_id"]) > 0,
        "Missing actual job identity",
    )
    require(type(run["pid"]) is int and run["pid"] > 0, "Missing process identity")
    started = dt.datetime.fromisoformat(run["started_utc"])
    require(started.tzinfo is not None, "Process timestamp lacks timezone")
    environment = run["environment"]
    require(
        environment["python"] == "3.11.5" and environment["torch"] == "2.1.1+cu118",
        "Not the declared native Python/PyTorch environment",
    )
    require(
        environment["cuda"] == "11.8" and "A100" in environment["device"],
        "Not the declared CUDA/A100 run",
    )
    require(
        type(environment["cudnn"]) is int and environment["cudnn"] > 0,
        "Missing cuDNN version",
    )
    require(bool(environment["hostname"]), "Missing hostname")
    require(set(loads) == set(candidate.MODEL_ORDER), "Missing model load report")
    for model_id in candidate.MODEL_ORDER:
        require(
            run["models"][model_id]["role"] == base.MODEL_ROLES[model_id],
            "Wrong scientific model role",
        )
        load = loads[model_id]
        require(
            load["loaded_trainable_numel_ratio"] == 1.0
            and load["loaded_trainable_numel"] == load["trainable_numel"] > 0,
            f"Incomplete strict load: {model_id}",
        )
        unwrap = load["eager_unwrap"]
        require(
            type(unwrap["known_wrapper_removed"]) is bool
            and type(unwrap["state_bindings_preserved"]) is int
            and unwrap["state_bindings_preserved"] > 0,
            "Missing eager binding check",
        )
    for hashes in details["cue_hashes"].values():
        require(
            all(
                isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes
            ),
            "Noncanonical cue hashes",
        )


def read_archive(candidate, base, path, receipt_sha):
    import numpy as np
    import pandas as pd

    path = Path(path)
    verified = candidate.verify_receipt(base, path, receipt_sha)
    run = read_json(path / "RUN.json")
    details = read_json(path / "pass.json")
    loads = read_json(path / "LOAD_REPORTS.json")
    validate_declaration(candidate, base, run, details, loads)
    bank = pd.read_csv(
        path / "bank.csv", keep_default_na=False, dtype={"target_speaker": str}
    )
    bank["snr_db"] = pd.to_numeric(bank.snr_db.replace("", np.nan), errors="raise")
    result = pd.read_csv(
        path / "results.csv", keep_default_na=False, dtype={"target_speaker": str}
    )
    for name in result:
        if name == "snr_db" or name.startswith(
            tuple(m + "_" for m in candidate.MODEL_ORDER)
        ):
            result[name] = pd.to_numeric(
                result[name].replace("", np.nan), errors="raise"
            )
    with np.load(path / "logits.npz", allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    return {
        "run": run,
        "pass": details,
        "bank": bank,
        "results": result,
        "arrays": arrays,
        "receipt_sha256": receipt_sha,
        "verification": verified,
    }


def check_pair(left, right, kind):
    import pandas as pd

    a, b = left["run"], right["run"]
    for field in (
        "protocol",
        "role",
        "candidate_sha256",
        "v4_source_sha256",
        "v4_manifest_sha256",
        "models",
        "trial_ids",
        "model_order",
        "historical_scene_hashes",
        "runtime",
        "amp",
        "compiled_forward",
        "tail_policy",
    ):
        require(a[field] == b[field], f"Run declarations differ: {field}")
    for field in ("python", "torch", "cuda", "cudnn", "device"):
        require(
            a["environment"][field] == b["environment"][field],
            f"Environment differs: {field}",
        )
    require(
        left["receipt_sha256"] != right["receipt_sha256"],
        "Same receipt is not an independent run",
    )

    def process(run):
        return (
            run["job_id"],
            run["environment"]["hostname"],
            run["pid"],
            run["started_utc"],
        )

    require(
        process(a) != process(b), "Same process record is not an independent cold run"
    )
    if kind == "cold-repeat":
        require(
            a["batch_size"] == b["batch_size"],
            "Cold repeat requires the same batch size",
        )
    elif kind == "batch-size":
        require(
            (a["batch_size"], b["batch_size"]) == (16, 1),
            "Batch comparison requires left=16, right=1",
        )
    else:
        raise ValueError("Unknown comparison kind")
    pd.testing.assert_frame_equal(left["bank"], right["bank"], check_exact=True)
    for field in ("scene_sha256", "correct_cue_sha256"):
        require(
            left["results"][field].tolist() == right["results"][field].tolist(),
            f"Input identity differs: {field}",
        )
    require(
        left["pass"]["cue_hashes"] == right["pass"]["cue_hashes"],
        "Control/correct cue identities differ",
    )


def absolute_difference(left, right):
    import numpy as np

    delta = np.abs(
        np.asarray(right, dtype=np.float64) - np.asarray(left, dtype=np.float64)
    )
    require(bool(np.isfinite(delta).all()), "Nonfinite numeric comparison")
    if delta.size == 0:
        return {
            "count": 0,
            "maximum": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "p99": None,
        }
    return {
        "count": int(delta.size),
        "maximum": float(delta.max()),
        "mean": float(delta.mean()),
        **{
            name: float(np.quantile(delta, q, method="linear"))
            for name, q in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
        },
    }


def compare_archives(candidate, base, left, right, kind):
    import numpy as np

    check_pair(left, right, kind)
    bank = left["bank"]
    report = {
        "status": "NUMERIC_SENSITIVITY_RECORDED",
        "kind": kind,
        "input_scope": "original_32_diagnostic_trials_only",
        "role": candidate.ROLE,
        "scientific_qualification": "NOT_DECIDED",
        "full_run_authorized": False,
        "numpy_version": np.__version__,
        "direction": "right run minus left run; paired model gaps are model_a minus model_b",
        "left_receipt_sha256": left["receipt_sha256"],
        "right_receipt_sha256": right["receipt_sha256"],
        "by_model_condition": {},
        "paired_model_gap_changes": {},
    }
    try:
        report["legacy_v4_result_table_canary_1e_6"] = base.compare_smoke_passes(
            left["results"], right["results"]
        )
    except base.EvaluationError as error:
        report["legacy_v4_result_table_canary_1e_6"] = {
            "status": "DIFF",
            "reason": str(error),
        }
    metric_values = {}
    for condition in candidate.CONDITIONS:
        mask = (
            np.ones(len(bank), dtype=bool)
            if condition == "correct"
            else bank.control_subset.to_numpy(dtype=int) == 1
        )
        ids = bank.loc[mask, "trial_id"].to_numpy(dtype=int)
        labels = bank.loc[mask, "target_label"].to_numpy(dtype=int)
        for model_id in candidate.MODEL_ORDER:
            key = f"{model_id}__{condition}"
            a, b = left["arrays"][key], right["arrays"][key]
            prefix = model_id if condition == "correct" else f"{model_id}_{condition}"
            flipped = a.argmax(1) != b.argmax(1)
            values = {
                "trials": len(ids),
                "logits_abs_diff": absolute_difference(a, b),
                "logits_bitwise_equal": a.tobytes() == b.tobytes(),
                "prediction_flips": int(flipped.sum()),
                "flip_fraction": float(flipped.mean()) if len(ids) else None,
            }
            if len(ids):
                a_top = np.partition(a.astype(np.float64), -2, axis=1)[:, -2:]
                b_top = np.partition(b.astype(np.float64), -2, axis=1)[:, -2:]
                a_margin, b_margin = (
                    a_top[:, 1] - a_top[:, 0],
                    b_top[:, 1] - b_top[:, 0],
                )
                values["flips"] = [
                    {
                        "trial_id": int(ids[i]),
                        "left_margin": float(a_margin[i]),
                        "right_margin": float(b_margin[i]),
                    }
                    for i in np.flatnonzero(flipped)
                ]
                values["minimum_top1_top2_margin"] = {
                    "left": float(a_margin.min()),
                    "right": float(b_margin.min()),
                }
            metric_values[key] = {}
            for metric in ("nll", "p_target", "p_probe_distractor"):
                x = (
                    left["results"]
                    .loc[mask, f"{prefix}_{metric}"]
                    .to_numpy(dtype=float)
                )
                y = (
                    right["results"]
                    .loc[mask, f"{prefix}_{metric}"]
                    .to_numpy(dtype=float)
                )
                values[f"{metric}_abs_diff"] = absolute_difference(x, y)
                if metric == "nll":
                    metric_values[key]["nll"] = (x, y)
            accuracy = (
                (a.argmax(1) == labels).astype(float),
                (b.argmax(1) == labels).astype(float),
            )
            metric_values[key]["accuracy"] = accuracy
            values["accuracy_change"] = (
                float((accuracy[1] - accuracy[0]).mean()) if len(ids) else None
            )
            nll = metric_values[key]["nll"]
            values["mean_nll_change"] = (
                float((nll[1] - nll[0]).mean()) if len(ids) else None
            )
            report["by_model_condition"][key] = values
        for model_a, model_b in (
            ("formal40", "author_external"),
            ("formal40", "valbest33"),
            ("valbest33", "author_external"),
        ):
            values = {}
            for metric in ("accuracy", "nll"):
                a = metric_values[f"{model_a}__{condition}"][metric]
                b = metric_values[f"{model_b}__{condition}"][metric]
                values[metric] = {
                    "gap_left": float((a[0] - b[0]).mean()) if len(ids) else None,
                    "gap_right": float((a[1] - b[1]).mean()) if len(ids) else None,
                    "gap_change": float(((a[1] - b[1]) - (a[0] - b[0])).mean())
                    if len(ids)
                    else None,
                    "sample_only_absolute_change_bound": float(
                        np.abs(a[1] - a[0]).mean() + np.abs(b[1] - b[0]).mean()
                    )
                    if len(ids)
                    else None,
                }
            report["paired_model_gap_changes"][f"{model_a}__{model_b}__{condition}"] = (
                values
            )
    report["limitations"] = [
        "Not a full 10k checkpoint comparison; no bootstrap confidence interval is calculated here.",
        "Observed sample bounds cannot be extrapolated unconditionally to the full bank.",
        "A legacy canary PASS does not authorize full evaluation or certify all coverage tests.",
        "Archive declarations do not replace independent Slurm allocation/accounting review.",
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("cold-repeat", "batch-size"), required=True)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--left-receipt-sha256", required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--right-receipt-sha256", required=True)
    args = parser.parse_args()
    candidate, base = load_core()
    left = read_archive(candidate, base, args.left, args.left_receipt_sha256)
    right = read_archive(candidate, base, args.right, args.right_receipt_sha256)
    print(
        json.dumps(
            compare_archives(candidate, base, left, right, args.kind),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
