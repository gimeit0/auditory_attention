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
CANDIDATE = ROOT / "same_bank_compare_2026_09_19_confirm_v2/eager_compare.py"
CANDIDATE_SHA = "3fb3e57098861e4eef7ed0b92fcfe837be4613eefca72d775a7364146d2d2f5e"
V1_REVIEW = ROOT / "same_bank_compare_2026_09_18_layout_v1/review_layouts.py"
V1_REVIEW_SHA = "a2648549402e3e56b2b670078557ded09b1dbc1015fa00320073088cc65eed23"
V1_CANDIDATE_SHA = "8a191e7afc5a7e382b26039fb409041910bc250e7b9b84b8a483244d7c3042ed"
V1_PROTOCOL = "same_bank_eager_fp32_layout_20260918_v1"
# Declared comparison pairs: (left layout, right layout) per kind. Nothing else.
PAIRS = {
    "bridge": {("v1_bridge16", "bridge16")},
    "subset-repeat": {("conf256", "conf32rep16")},
    "subset-batch-size": {("conf256", "conf32b1"), ("conf32rep16", "conf32b1")},
}
# P06 (approved 2026-09-19): reporting envelope and margin strata; not pass thresholds.
ENVELOPE = {"nll_abs_diff_max": 2e-3, "logits_abs_diff_max": 4e-3}
MARGIN_EDGES = (4e-3, 4e-2)
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


def read_archive(candidate, base, path, receipt_sha, layout_sha):
    import numpy as np
    import pandas as pd

    path = Path(path)
    verified = candidate.verify_receipt(base, path, receipt_sha, layout_sha)
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


def read_baseline(path, receipt_sha, layout_sha):
    """Job 726428 artifacts must still pass their original pinned v1 reader."""
    require(
        hashlib.sha256(V1_REVIEW.read_bytes()).hexdigest() == V1_REVIEW_SHA,
        "Baseline reader changed",
    )
    spec = importlib.util.spec_from_file_location("baseline_reader_v1", V1_REVIEW)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    candidate, base = reader.load_core()
    require(candidate.PROTOCOL == V1_PROTOCOL, "Wrong baseline candidate")
    return reader.read_archive(candidate, base, path, receipt_sha, layout_sha)


def layout_name(candidate, archive):
    run = archive["run"]
    if run["protocol"] == V1_PROTOCOL:
        require(run["candidate_sha256"] == V1_CANDIDATE_SHA, "Unknown baseline source")
        require(
            run["layout_id"] == "bridge16"
            and tuple(run["trial_ids"]) == candidate.TRIAL_IDS
            and run["batch_size"] == 16,
            "Wrong baseline layout",
        )
        return "v1_bridge16"
    require(run["protocol"] == candidate.PROTOCOL, "Unknown protocol")
    require(run["candidate_sha256"] == CANDIDATE_SHA, "Unknown new source")
    spec = candidate.layout_spec(run["layout_id"])
    candidate.validate_layout(spec, run["layout_sha256"])
    require(
        run["trial_ids"] == spec["trial_ids"]
        and run["batch_size"] == spec["batch_size"]
        and run["batches"] == spec["batches"],
        "Wrong declared layout",
    )
    return run["layout_id"]


def project(candidate, archive, ids):
    """Align condition-specific logits without rewriting archived declarations."""
    import numpy as np

    bank, result = archive["bank"], archive["results"]
    declared = archive["run"]["trial_ids"]
    require(bank.trial_id.is_unique and result.trial_id.is_unique, "Duplicate trial")
    require(bank.trial_id.tolist() == declared, "Bank/layout order mismatch")
    require(
        set(result.trial_id) == set(declared) and len(result) == len(declared),
        "Missing or extra result identities",
    )
    require(set(ids).issubset(declared), "Requested comparison identity missing")
    projected = dict(archive)
    projected["bank"] = (
        bank.set_index("trial_id", drop=False).loc[ids].reset_index(drop=True)
    )
    projected["results"] = (
        result.set_index("trial_id", drop=False).loc[ids].reset_index(drop=True)
    )
    projected["arrays"] = {}
    cues = {}
    require(
        set(archive["pass"]["cue_hashes"]) == set(candidate.CONDITIONS),
        "Wrong cue inventory",
    )
    require(
        set(archive["arrays"])
        == {f"{m}__{c}" for m in candidate.MODEL_ORDER for c in candidate.CONDITIONS},
        "Wrong array inventory",
    )
    for condition in candidate.CONDITIONS:
        source_ids = bank.loc[
            np.ones(len(bank), dtype=bool)
            if condition == "correct"
            else bank.control_subset.to_numpy(dtype=int) == 1,
            "trial_id",
        ].tolist()
        target_bank = projected["bank"]
        target_ids = target_bank.loc[
            np.ones(len(target_bank), dtype=bool)
            if condition == "correct"
            else target_bank.control_subset.to_numpy(dtype=int) == 1,
            "trial_id",
        ].tolist()
        positions = {trial: i for i, trial in enumerate(source_ids)}
        indices = [positions[t] for t in target_ids]
        source_cues = archive["pass"]["cue_hashes"][condition]
        require(len(source_cues) == len(source_ids), "Missing cue identities")
        cues[condition] = [source_cues[i] for i in indices]
        for model in candidate.MODEL_ORDER:
            key = f"{model}__{condition}"
            values = archive["arrays"][key]
            require(
                values.shape == (len(source_ids), 800)
                and values.dtype == np.float32
                and np.isfinite(values).all(),
                "Invalid logits array",
            )
            projected["arrays"][key] = values[indices].copy()
    projected["pass"] = dict(archive["pass"], cue_hashes=cues)
    return projected


def align_pair(candidate, left, right, kind):
    import pandas as pd

    names = (layout_name(candidate, left), layout_name(candidate, right))
    require(kind in PAIRS and names in PAIRS[kind], "Undeclared comparison pair")
    a, b = left["run"], right["run"]
    for field in (
        "role",
        "v4_source_sha256",
        "v4_manifest_sha256",
        "models",
        "model_order",
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
    require(left["receipt_sha256"] != right["receipt_sha256"], "Same receipt")

    def process(run):
        return (
            run["job_id"],
            run["environment"]["hostname"],
            run["pid"],
            run["started_utc"],
        )

    require(process(a) != process(b), "Same process record")
    # Compared identities are the right layout's declared trials; they must be a
    # subset of the left layout (checked by project) and matched by trial ID.
    ids = list(b["trial_ids"])
    require(len(ids) == len(set(ids)), "Duplicate declared identity")
    for trial in ids:
        require(
            a["historical_scene_hashes"][str(trial)]
            == b["historical_scene_hashes"][str(trial)],
            "Historical scene differs",
        )
    left, right = project(candidate, left, ids), project(candidate, right, ids)
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
    return left, right


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

    left, right = align_pair(candidate, left, right, kind)
    bank = left["bank"]
    report = {
        "status": "NUMERIC_SENSITIVITY_RECORDED",
        "kind": kind,
        "input_scope": "frozen_layouts_confirmation_set_not_full_bank",
        "compared_trial_ids": bank.trial_id.tolist(),
        "left_layout": layout_name(candidate, left),
        "right_layout": layout_name(candidate, right),
        "paired_nll_rows": [],
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
            diff = nll[0] - nll[1]
            values["nll_signed_left_minus_right"] = {
                "mean": float(diff.mean()) if len(ids) else None,
                "std_ddof0": float(diff.std(ddof=0)) if len(ids) else None,
                "max_abs": float(np.abs(diff).max()) if len(ids) else None,
            }
            report["paired_nll_rows"].extend(
                {
                    "trial_id": int(t),
                    "model": model_id,
                    "condition": condition,
                    "left_nll": float(x),
                    "right_nll": float(y),
                    "diff": float(d),
                }
                for t, x, y, d in zip(ids, nll[0], nll[1], diff)
            )
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


def margin_strata(candidate, archive):
    """P06-4: top1-top2 logit margin strata per model/condition; reporting only."""
    import numpy as np

    low, high = MARGIN_EDGES
    result = {"edges": [low, high], "by_model_condition": {}}
    for condition in candidate.CONDITIONS:
        for model_id in candidate.MODEL_ORDER:
            key = f"{model_id}__{condition}"
            x = archive["arrays"][key]
            require(
                x.dtype == np.float32 and x.ndim == 2 and bool(np.isfinite(x).all()),
                "Invalid logits array",
            )
            if not len(x):
                result["by_model_condition"][key] = {"trials": 0}
                continue
            top = np.partition(x.astype(np.float64), -2, axis=1)[:, -2:]
            margin = top[:, 1] - top[:, 0]
            result["by_model_condition"][key] = {
                "trials": int(len(margin)),
                "minimum_margin": float(margin.min()),
                "within_envelope_le_low": int((margin <= low).sum()),
                "between_low_and_high": int(((margin > low) & (margin <= high)).sum()),
                "above_high": int((margin > high).sum()),
                "within_envelope_fraction": float((margin <= low).mean()),
            }
    return result


def envelope_check(report):
    """P06-3 envelope on a comparison report; records exceedance, never widens."""
    exceeded, worst_nll, worst_logits = [], 0.0, 0.0
    for key, value in report["by_model_condition"].items():
        nll = value["nll_abs_diff"]["maximum"]
        logits = value["logits_abs_diff"]["maximum"]
        if nll is None or logits is None:
            continue
        worst_nll, worst_logits = max(worst_nll, nll), max(worst_logits, logits)
        if nll > ENVELOPE["nll_abs_diff_max"] or logits > ENVELOPE["logits_abs_diff_max"]:
            exceeded.append(key)
    return {
        "envelope": dict(ENVELOPE),
        "max_nll_abs_diff": worst_nll,
        "max_logits_abs_diff": worst_logits,
        "exceeded": exceeded,
        "within_envelope": not exceeded,
        "policy": "P06 approved 2026-09-19; exceedance is recorded for review, not repaired",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=tuple(PAIRS),
        required=True,
    )
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--left-receipt-sha256", required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--right-receipt-sha256", required=True)
    parser.add_argument("--left-layout-sha256", required=True)
    parser.add_argument("--right-layout-sha256", required=True)
    parser.add_argument("--left-baseline", action="store_true")
    args = parser.parse_args()
    candidate, base = load_core()
    if args.left_baseline:
        left = read_baseline(
            args.left, args.left_receipt_sha256, args.left_layout_sha256
        )
    else:
        left = read_archive(
            candidate,
            base,
            args.left,
            args.left_receipt_sha256,
            args.left_layout_sha256,
        )
    right = read_archive(
        candidate, base, args.right, args.right_receipt_sha256, args.right_layout_sha256
    )
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
