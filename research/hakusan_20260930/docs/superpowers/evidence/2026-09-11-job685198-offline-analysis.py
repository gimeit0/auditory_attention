"""Read-only archival checks and descriptive analysis, not a production canary.

Reads pinned Job685198 evidence. No torch import, model loading, GPU, network,
submission, file writes, or changed acceptance thresholds. JSON goes to stdout.
Float64 NLL below is a CPU cross-check of saved logits, not an official result.
"""

import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat

import numpy as np


TERMINAL_SHA = "4db7f8ba6c63bb58b354cc30486a0e839bb186e31c4845676baa26cd741b72c1"
FREEZE_SHA = "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178"
INVENTORY_SHA = "57e589dd8f679715f49ba65cf841ef26b9e099ccf437024f8d13741afebf228b"
SOURCE_SHAS = {
    "spatial_attn_architecture.py": "84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed",
    "custom_modules.py": "98f0d393ee7a1a5fe1a8a8bd1302b0d6b574a4ef846946e30cf176adf860adad",
    "full.yaml": "3efe0f455d7c902c772f5d1a6fb30cf0a4f13e46f0b72024ff5bfa7b9f3229b4",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    require(stat.S_ISREG(path.lstat().st_mode), f"not a regular file: {path}")
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path, expected_sha=None):
    digest = sha256(path)
    if expected_sha is not None:
        require(digest == expected_sha, f"SHA differs: {path}")
    return json.loads(path.read_bytes())


def wire_sha(value):
    wire = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"
    return hashlib.sha256(wire.encode("ascii")).hexdigest()


def safe_relative(value):
    path = PurePosixPath(value)
    require(bool(value) and not path.is_absolute() and ".." not in path.parts
            and str(path) == value and value != ".", "unsafe inventory path")
    return value


def verify_inventory(root, inventory):
    require(stat.S_ISDIR(root.lstat().st_mode), "attempt must be a real directory")
    payload = {k: v for k, v in inventory.items() if k != "sha256"}
    require(wire_sha(payload) == inventory["sha256"], "inventory digest differs")
    expected = {}
    for kind, rows in (("directory", inventory["directories"]),
                       ("file", inventory["files"])):
        for row in rows:
            name = safe_relative(row["relative_path"])
            require(name not in expected, "duplicate inventory path")
            expected[name] = (kind, row)
    actual = set()
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            require(relative in expected, f"unexpected artifact: {relative}")
            kind, row = expected[relative]
            info = path.lstat()
            matches = stat.S_ISDIR if kind == "directory" else stat.S_ISREG
            require(matches(info.st_mode), f"wrong type/link: {relative}")
            require(stat.S_IMODE(info.st_mode) == row["mode"],
                    f"permissions differ: {relative}")
            if kind == "file":
                require(info.st_size == row["size"], f"size differs: {relative}")
                require(sha256(path) == row["sha256"], f"SHA differs: {relative}")
            actual.add(relative)
    require(actual == set(expected), "missing artifacts")
    return {"status": "OFFLINE_ARTIFACT_BYTES_VERIFIED",
            "files": len(inventory["files"]),
            "directories": len(inventory["directories"]),
            "bytes": sum(row["size"] for row in inventory["files"]),
            "inventory_sha256": inventory["sha256"]}


def logsumexp64(logits):
    values = np.asarray(logits, dtype=np.float64)
    require(values.ndim == 2 and values.shape[0] > 0 and values.shape[1] > 1,
            "invalid logits shape")
    require(np.isfinite(values).all(), "nonfinite logits")
    maximum = values.max(axis=1)
    return maximum + np.log(np.exp(values - maximum[:, None]).sum(axis=1))


def nll64(logits, targets):
    lse = logsumexp64(logits)
    targets = np.asarray(targets)
    require(targets.shape == (len(lse),) and targets.dtype.kind in "iu"
            and (targets >= 0).all() and (targets < logits.shape[1]).all(),
            "invalid targets")
    return lse - logits.astype(np.float64)[np.arange(len(lse)), targets]


def analyse_cell(root, cell, trials):
    folder = root / "cells" / cell
    inputs = read_json(folder / "CELL_INPUTS.json")
    require(inputs["trials"] == trials, f"trial binding differs: {cell}")
    comparison = read_json(folder / "COMPARISON.json")
    require(comparison["canary_threshold"] == 1e-6, "original threshold differs")
    with (folder / "TRIAL_OUTPUTS.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(len(rows) == 2 * len(trials), "unexpected CSV row count")
    targets = np.array([t["identity"]["target_label"] for t in trials])
    arrays, stored, recomputed, margins = [], [], [], []
    for pass_index in range(2):
        pass_id = f"pass{pass_index + 1}"
        part = [row for row in rows if row["pass_id"] == pass_id]
        require(len(part) == len(trials), "wrong pass row count")
        raw = np.load(folder / f"LOGITS_PASS{pass_index + 1}.npy", allow_pickle=False)
        require(raw.shape == (32, 800) and raw.dtype.name in ("float16", "float32"),
                "unexpected saved logits layout")
        require(np.isfinite(raw).all(), "nonfinite saved logits")
        predictions = raw.argmax(axis=1)
        for index, (row, trial) in enumerate(zip(part, trials)):
            for key in ("ordinal", "trial_id", "bank_row_index"):
                require(int(row[key]) == trial[key], f"CSV identity differs: {key}")
            require(int(row["batch_size"]) == inputs["cell_spec"]["pass_batch_sizes"][pass_index],
                    "CSV batch size differs")
            require(int(row["pred_label"]) == int(predictions[index]), "prediction differs")
            require(int(row["correct"]) == int(predictions[index] == targets[index]),
                    "correctness differs")
        native = raw.astype(np.float64)
        native_nll = np.array([float(row["nll"]) for row in part])
        require(np.isfinite(native_nll).all(), "nonfinite recorded NLL")
        top_two = np.sort(native, axis=1)[:, -2:]
        margins.append(top_two[:, 1] - top_two[:, 0])
        arrays.append(native)
        stored.append(native_nll)
        recomputed.append(nll64(raw, targets))
    diff = arrays[1] - arrays[0]
    nll_diff = stored[1] - stored[0]
    worst_logit = int(np.abs(diff).max(axis=1).argmax())
    worst_nll = int(np.abs(nll_diff).argmax())
    require(float(np.abs(nll_diff).max()) == comparison["nll_max_abs"],
            "recorded max NLL differs")
    native_worst = comparison["worst_cases"].get("native_logits")
    if native_worst is not None:
        require(native_worst["ordinal"] == worst_logit
                and native_worst["trial_id"] == trials[worst_logit]["trial_id"],
                "native-logit worst-case selection differs")
    # Repeating one sample sixteen times is NOT the original batch context.
    context = [t["trial_id"] for t in trials[(worst_logit // 16) * 16:
                                             (worst_logit // 16 + 1) * 16]]
    return {
        "cell": cell, "trials": len(trials),
        "pass_batch_sizes": inputs["cell_spec"]["pass_batch_sizes"],
        "saved_native_dtype": str(np.load(folder / "LOGITS_PASS1.npy", allow_pickle=False).dtype),
        "nll_max_abs_recorded": float(np.abs(nll_diff).max()),
        "nll_worst_trial_id": trials[worst_nll]["trial_id"],
        "nll_over_original_1e_minus_6_count": int((np.abs(nll_diff) > 1e-6).sum()),
        "native_logits_max_abs": float(np.abs(diff).max()),
        "native_logits_worst_trial_id": trials[worst_logit]["trial_id"],
        "native_logits_changed_rows": int(np.any(diff != 0, axis=1).sum()),
        "native_logits_changed_elements": int(np.count_nonzero(diff)),
        "predictions_equal": bool(np.array_equal(arrays[0].argmax(1), arrays[1].argmax(1))),
        "minimum_top1_top2_margin_by_pass": [float(x.min()) for x in margins],
        "float64_cpu_crosscheck_nll_max_abs": float(np.abs(recomputed[1] - recomputed[0]).max()),
        "float64_cpu_vs_recorded_nll_max_abs_by_pass": [
            float(np.abs(recomputed[i] - stored[i]).max()) for i in range(2)],
        "worst_native_logit_trial_nll_abs": float(abs(nll_diff[worst_logit])),
        "saved_feature_trial_ids": {k: comparison["worst_cases"][k]["trial_id"]
                                    for k in ("scene_features", "cue_features")},
        "required_original_batch_context_for_native_logit_target": context,
        "first_observed_boundary": comparison["first_divergence"],
    }


def main():
    evidence = Path(__file__).resolve().parent
    archive = evidence / "job-685198-v18"
    attempt = archive / "slurm-685198"
    terminal = read_json(archive / "DIAGNOSTIC_COMPLETE.json", TERMINAL_SHA)
    freeze = read_json(evidence / "v18-deployment-artifacts" / "input_freeze.json", FREEZE_SHA)
    require(terminal["status"] == "DIAGNOSTIC_COMPLETE" and terminal["job_id"] == "685198",
            "wrong terminal")
    require(terminal["artifact_inventory"]["sha256"] == INVENTORY_SHA, "wrong inventory")
    verified = verify_inventory(attempt, terminal["artifact_inventory"])
    require(verified["files"] == 114 and verified["bytes"] == 211343132, "wrong artifact count")
    sources = archive / "frozen-model-source"
    for name, digest in SOURCE_SHAS.items():
        require(sha256(sources / name) == digest, f"frozen source differs: {name}")
    cells = [analyse_cell(attempt, c, freeze["trials"]) for c in ("A1", "A2", "B1", "B2")]
    # Catch accidental edits while the analysis ran, rather than certify cached bytes.
    require(verify_inventory(attempt, terminal["artifact_inventory"]) == verified,
            "archive changed during analysis")
    print(json.dumps({"status": "OFFLINE_DESCRIPTIVE_ANALYSIS_COMPLETE", "job_id": "685198",
                      "analysis_environment": {"python": platform.python_version(),
                                               "numpy": np.__version__,
                                               "device": "CPU", "torch_imported": False},
                      "analysis_script_sha256": sha256(Path(__file__)),
                      "evaluation_role": "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
                      "archive": verified, "terminal_sha256": TERMINAL_SHA,
                      "input_freeze_sha256": FREEZE_SHA, "frozen_source_sha256": SOURCE_SHAS,
                      "cells": cells,
                      "limitations": ["formal40-only, 32 trials; no model ranking",
                                      "not a rerun of GPU inference or replacement for remote verify-results",
                                      "float64 CPU NLL is descriptive, not a changed production threshold",
                                      "no per-layer evidence is present; first boundary is not root cause"]},
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
