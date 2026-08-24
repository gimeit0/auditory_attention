"""Validate the frozen 10k cue-control result before full-distribution work."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import tempfile

import numpy as np


EXPECTED = {
    "TRAIN_JOB": "551219",
    "CHECKPOINT_SHA256": (
        "5662840b2866355b0b27de3cf4e09eafec9f603de178c0177ba2acfa947d935c"
    ),
    "CONFIG_SHA256": (
        "1260fa688aad2cfc127c5051301c5b562443383383a288ccdc3e1b42cfd4e838"
    ),
    "MANIFEST_SHA256": (
        "972dd402b5ae7cff43208c2d32cf8754f12c2c1172dc28d3c85ab017aa88ffa8"
    ),
    "FORMAL_MANIFEST_SHA256": (
        "972dd402b5ae7cff43208c2d32cf8754f12c2c1172dc28d3c85ab017aa88ffa8"
    ),
    "EVAL_CODE_SHA256": (
        "8eec4ddc454a11d8b1193c83f4b77200ad6d6e210940b3fd5e2970966e3d63cf"
    ),
    "CUE_CONTROL_MODE": "full",
}

BOOTSTRAP_SEED = 20260816
BOOTSTRAP_REPETITIONS = 2000


def _finite_float(value: object, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Cue-control {name} is not numeric: {value!r}") from error
    if not math.isfinite(converted):
        raise ValueError(f"Cue-control {name} is not finite: {value!r}")
    return converted


def _cluster_bootstrap_delta(
    values: np.ndarray,
    speakers: np.ndarray,
    seed: int,
    repetitions: int,
) -> tuple[float, float]:
    unique, inverse = np.unique(speakers.astype(str), return_inverse=True)
    if len(unique) == 0:
        raise ValueError("Cue-control results contain no target speakers")
    sums = np.bincount(inverse, weights=values.astype(float))
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        sampled = rng.integers(0, len(unique), size=len(unique))
        draws[index] = sums[sampled].sum() / counts[sampled].sum()
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or key in values:
            raise ValueError(f"Invalid frozen-input line: {line!r}")
        values[key] = value
    return values


def validate(job_root: str | pathlib.Path) -> dict:
    root = pathlib.Path(job_root).expanduser().resolve()
    summary_path = root / "summary_full.json"
    frozen_path = root / "frozen_inputs.env"
    results_path = root / "results_full.csv"
    for path in (summary_path, frozen_path, results_path):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(
                f"Cue-control release artifact is invalid: {path}"
            )
    frozen = _read_env(frozen_path)
    mismatches = {
        key: (frozen.get(key), expected)
        for key, expected in EXPECTED.items()
        if frozen.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"Cue-control frozen inputs mismatch: {mismatches}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    criterion = summary.get("preregistered_primary_criterion") or {}
    if summary.get("analysis_kind") != "confirmatory":
        raise ValueError("Cue-control summary is not confirmatory")
    if int(summary.get("trials", -1)) != 10000:
        raise ValueError("Cue-control summary does not contain 10,000 trials")
    if criterion.get("pass") is not True:
        raise ValueError("Cue-control preregistered primary criterion did not pass")
    if criterion.get("status") != "CONFIRMATORY_PASS":
        raise ValueError("Cue-control status is not CONFIRMATORY_PASS")
    required_result_columns = {
        "trial_id",
        "target_speaker",
        "correct_correct",
        "shuffled_correct",
        "silent_correct",
        "distractor_correct",
    }
    counts = {name: 0 for name in ("correct", "shuffled", "silent", "distractor")}
    outcomes = {name: [] for name in counts}
    trial_ids: list[int] = []
    target_speakers: list[str] = []
    with results_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing_columns = sorted(
            required_result_columns.difference(reader.fieldnames or [])
        )
        if missing_columns:
            raise ValueError(
                f"Cue-control results are missing columns: {missing_columns}"
            )
        for row in reader:
            trial_ids.append(int(row["trial_id"]))
            target_speaker = str(row["target_speaker"]).strip()
            if not target_speaker:
                raise ValueError("Cue-control target_speaker cannot be empty")
            target_speakers.append(target_speaker)
            for condition in counts:
                value = int(row[f"{condition}_correct"])
                if value not in (0, 1):
                    raise ValueError(
                        f"Non-binary correctness value for {condition}: {value}"
                    )
                counts[condition] += value
                outcomes[condition].append(value)
    if len(trial_ids) != 10000 or sorted(trial_ids) != list(range(10000)):
        raise ValueError(
            "Cue-control results must contain trial_id 0..9999 exactly once"
        )
    accuracies = {name: value / 10000 for name, value in counts.items()}
    conditions = summary.get("conditions") or {}
    for condition, accuracy in accuracies.items():
        summary_accuracy = _finite_float(
            (conditions.get(condition) or {}).get("accuracy"),
            f"{condition} summary accuracy",
        )
        if abs(summary_accuracy - accuracy) > 1e-12:
            raise ValueError(
                f"Cue-control summary accuracy mismatch for {condition}"
            )
    comparisons = summary.get("paired_comparisons") or {}
    speakers = np.asarray(target_speakers, dtype=str)
    correct_values = np.asarray(outcomes["correct"], dtype=np.int8)
    recomputed_confidence_intervals: dict[str, list[float]] = {}
    for offset, control in enumerate(("shuffled", "silent")):
        comparison = comparisons.get(f"correct_minus_{control}") or {}
        delta = accuracies["correct"] - accuracies[control]
        summary_delta = _finite_float(
            comparison.get("accuracy_delta"),
            f"correct-minus-{control} summary delta",
        )
        if abs(summary_delta - delta) > 1e-12:
            raise ValueError(
                f"Cue-control paired accuracy delta mismatch for {control}"
            )
        confidence_interval = comparison.get("cluster_bootstrap_95ci") or []
        if len(confidence_interval) != 2:
            raise ValueError(
                f"Cue-control primary CI is malformed: {control}"
            )
        summary_ci = [
            _finite_float(value, f"correct-minus-{control} CI[{index}]")
            for index, value in enumerate(confidence_interval)
        ]
        control_values = np.asarray(outcomes[control], dtype=np.int8)
        recomputed_ci = list(
            _cluster_bootstrap_delta(
                correct_values - control_values,
                speakers,
                BOOTSTRAP_SEED + 100 + offset,
                BOOTSTRAP_REPETITIONS,
            )
        )
        if any(
            abs(summary_value - recomputed_value) > 1e-12
            for summary_value, recomputed_value in zip(summary_ci, recomputed_ci)
        ):
            raise ValueError(
                f"Cue-control cluster-bootstrap CI mismatch for {control}"
            )
        if recomputed_ci[0] <= 0:
            raise ValueError(
                f"Cue-control primary CI lower bound is not positive: {control}"
            )
        recomputed_confidence_intervals[control] = recomputed_ci
    primary_delta = accuracies["correct"] - max(
        accuracies["shuffled"], accuracies["silent"]
    )
    if primary_delta < 0.05:
        raise ValueError("Cue-control recomputed primary delta is below 5pp")
    if abs(
        _finite_float(
            criterion.get("correct_minus_max_shuffled_silent"),
            "primary delta",
        )
        - primary_delta
    ) > 1e-12:
        raise ValueError("Cue-control summary primary delta mismatch")
    if _finite_float(criterion.get("required_delta"), "required delta") != 0.05:
        raise ValueError("Cue-control summary required delta changed")
    if criterion.get("all_primary_ci_lower_bounds_positive") is not True:
        raise ValueError("Cue-control primary CI flag is not true")
    frozen_summary = summary.get("frozen_inputs") or {}
    for key, expected in (
        ("checkpoint_sha256", EXPECTED["CHECKPOINT_SHA256"]),
        ("config_sha256", EXPECTED["CONFIG_SHA256"]),
        ("manifest_sha256", EXPECTED["MANIFEST_SHA256"]),
        ("output_sha256", _sha256(results_path)),
    ):
        if frozen_summary.get(key) != expected:
            raise ValueError(f"Cue-control summary frozen hash mismatch: {key}")
    return {
        "schema_version": 1,
        "status": "RELEASED_FOR_FULL_DISTRIBUTION_PILOT",
        "validated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cue_control_job_root": str(root),
        "train_job": 551219,
        "trials": 10000,
        "summary_sha256": _sha256(summary_path),
        "results_sha256": _sha256(results_path),
        "formal_manifest_sha256": EXPECTED["FORMAL_MANIFEST_SHA256"],
        "eval_code_sha256": EXPECTED["EVAL_CODE_SHA256"],
        "primary": criterion,
        "recomputed_condition_accuracies": accuracies,
        "recomputed_primary_delta": primary_delta,
        "recomputed_primary_cluster_bootstrap_95ci": (
            recomputed_confidence_intervals
        ),
    }


def validate_release_record(path_argument: str | pathlib.Path) -> dict:
    path = pathlib.Path(path_argument).expanduser()
    if path.is_symlink():
        raise ValueError("Cue-control release record must not be a symlink")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Cue-control release record is missing: {path}")
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recomputed = validate(recorded.get("cue_control_job_root", ""))
    stable_fields = (
        "schema_version",
        "status",
        "cue_control_job_root",
        "train_job",
        "trials",
        "summary_sha256",
        "results_sha256",
        "formal_manifest_sha256",
        "eval_code_sha256",
        "primary",
        "recomputed_condition_accuracies",
        "recomputed_primary_delta",
        "recomputed_primary_cluster_bootstrap_95ci",
    )
    mismatches = {
        field: (recorded.get(field), recomputed.get(field))
        for field in stable_fields
        if recorded.get(field) != recomputed.get(field)
    }
    if mismatches:
        raise ValueError(f"Cue-control release record mismatch: {mismatches}")
    return recorded


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--job-root")
    source.add_argument("--release-record")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.release_record:
        if args.output is not None:
            raise SystemExit("--output is valid only with --job-root")
        result = validate_release_record(args.release_record)
    else:
        result = validate(args.job_root)
    if args.output is not None:
        if args.output.exists():
            raise FileExistsError(
                f"Cue release output already exists: {args.output}"
            )
        _atomic_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
