"""Create and validate an auditable GO decision after the four-epoch pilot.

The structured evaluator JSON is useful for review, but is never trusted as
the source of the release decision.  Both ``create`` and ``validate`` reload
the frozen 10,000-trial bank and per-trial predictions and independently rerun
the fixed evaluator/cluster bootstrap before accepting GO.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import tempfile


RELEASE_SCHEMA_VERSION = 2


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: pathlib.Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(f"Pilot release artifact is invalid: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Pilot release JSON is not an object: {path}")
    return value


def _finite_float(value: object, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Pilot evaluation {name} is not numeric") from error
    if not math.isfinite(converted):
        raise ValueError(f"Pilot evaluation {name} is not finite")
    return converted


def _assert_finite_tree(value: object, name: str = "evaluation") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite_tree(item, f"{name}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite_tree(item, f"{name}[{index}]")
    elif isinstance(value, float):
        _finite_float(value, name)


def _safe_file(path_argument: str | pathlib.Path, name: str) -> pathlib.Path:
    argument = pathlib.Path(path_argument).expanduser()
    if argument.is_symlink():
        raise ValueError(f"{name} must not be a symlink: {argument}")
    path = argument.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{name} is missing: {path}")
    return path


def _require_path(path: pathlib.Path, expected: pathlib.Path, name: str) -> None:
    if path != expected.resolve():
        raise ValueError(f"{name} is not the frozen run artifact: {path}")


def _require_under(path: pathlib.Path, directory: pathlib.Path, name: str) -> None:
    try:
        path.relative_to(directory.resolve())
    except ValueError as error:
        raise ValueError(f"{name} escapes {directory}: {path}") from error


def _validated_inputs(run_root: pathlib.Path) -> tuple[dict, dict]:
    pilot = _json(run_root / "state/PILOT4_COMPLETE.json")
    cue = _json(run_root / "state/cue_control_release.json")
    if pilot.get("status") != "COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW":
        raise ValueError("Pilot computation is not awaiting scientific review")
    if pilot.get("run_phase") != "pilot4":
        raise ValueError("Pilot completion record has the wrong phase")
    if int(pilot.get("completed_epochs", -1)) != 4:
        raise ValueError("Pilot completion record is not at four epochs")
    if int(pilot.get("global_step", -1)) != 6944:
        raise ValueError("Pilot completion record is not at global_step 6944")
    checkpoint_argument = pathlib.Path(pilot.get("checkpoint", ""))
    if checkpoint_argument.is_symlink():
        raise ValueError("Pilot checkpoint must not be a symlink")
    checkpoint = checkpoint_argument.resolve()
    expected_directory = (run_root / "full/checkpoints").resolve()
    if checkpoint.parent != expected_directory:
        raise ValueError("Pilot checkpoint escapes the run checkpoint directory")
    if checkpoint.name != pilot.get("checkpoint_basename"):
        raise ValueError("Pilot checkpoint basename mismatch")
    if not checkpoint.is_file() or _sha256(checkpoint) != pilot.get(
        "checkpoint_sha256"
    ):
        raise ValueError("Pilot checkpoint hash no longer matches completion")
    if cue.get("status") != "RELEASED_FOR_FULL_DISTRIBUTION_PILOT":
        raise ValueError("Confirmatory cue-control release is missing")
    return pilot, cue


def _checkpoint_binding(
    recorded: object,
    path: pathlib.Path,
    expected_sha256: str,
    global_step: int,
    completed_epochs: int,
    name: str,
) -> None:
    if not isinstance(recorded, dict):
        raise ValueError(f"Pilot evaluation has no {name} binding")
    expected = {
        "path": str(path),
        "sha256": expected_sha256,
        "global_step": global_step,
        "completed_epochs": completed_epochs,
    }
    mismatches = {
        key: (recorded.get(key), value)
        for key, value in expected.items()
        if recorded.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot evaluation {name} mismatch: {mismatches}")


def _validated_evaluation(
    run_root: pathlib.Path,
    pilot: dict,
    pilot_evaluation: str | pathlib.Path,
    bank: str | pathlib.Path,
    results: str | pathlib.Path,
    evaluator: str | pathlib.Path,
    config: str | pathlib.Path,
    source_manifest: str | pathlib.Path,
    stage0_checkpoint: str | pathlib.Path,
) -> tuple[dict, dict]:
    # Import lazily so simple CLI argument errors do not import torch/model code.
    import pandas as pd

    from selftrain.scripts import eval_full_pilot as evaluator_module
    from selftrain.scripts.build_full_pilot_eval_bank import (
        DEFAULT_BANK_SEED,
        ROLE_SPEAKER_DTYPES,
        validate_bank_artifacts,
    )

    evaluation_path = _safe_file(pilot_evaluation, "Pilot evaluation")
    bank_path = _safe_file(bank, "Pilot bank")
    results_path = _safe_file(results, "Pilot per-trial results")
    evaluator_path = _safe_file(evaluator, "Frozen pilot evaluator")
    config_path = _safe_file(config, "Frozen full config")
    source_manifest_path = _safe_file(
        source_manifest, "Frozen source manifest"
    )
    stage0_path = _safe_file(stage0_checkpoint, "Stage-zero checkpoint")
    pilot_path = _safe_file(pilot["checkpoint"], "Pilot checkpoint")
    bank_freeze_state_path = _safe_file(
        run_root / "state/PILOT4_BANK_FROZEN.json",
        "Pilot bank freeze state",
    )

    evaluation_root = (run_root / "evaluation/pilot4").resolve()
    for path, name in (
        (evaluation_path, "Pilot evaluation"),
        (bank_path, "Pilot bank"),
        (results_path, "Pilot per-trial results"),
    ):
        _require_under(path, evaluation_root, name)
    _require_path(
        evaluator_path,
        run_root / "snapshot/files/selftrain/scripts/eval_full_pilot.py",
        "Frozen pilot evaluator",
    )
    _require_path(
        config_path,
        run_root / "snapshot/files/selftrain/configs/full.yaml",
        "Frozen full config",
    )
    _require_path(
        source_manifest_path,
        run_root / "snapshot/manifest.json",
        "Frozen source manifest",
    )
    _require_path(
        stage0_path,
        run_root / "full/checkpoints/stage-0.ckpt",
        "Stage-zero checkpoint",
    )
    _require_path(
        bank_freeze_state_path,
        run_root / "state/PILOT4_BANK_FROZEN.json",
        "Pilot bank freeze state",
    )
    if (
        run_root.parent.name != "runs"
        or run_root.parent.parent.name != "experiments"
        or run_root.parent.parent.parent.name != "selftrain"
    ):
        raise ValueError("Run root does not have the expected project layout")
    project_root = run_root.parents[3]
    # Revalidate sidecars, exact 10k role constraints, and every path/crop/label
    # against the frozen validation anchors.  A matching TSV hash alone is not
    # sufficient evidence that the bank was built from the declared catalog.
    validate_bank_artifacts(
        bank_path,
        config_path,
        project_root,
        DEFAULT_BANK_SEED,
    )

    hashes = {
        "bank_sha256": _sha256(bank_path),
        "results_sha256": _sha256(results_path),
        "evaluator_sha256": _sha256(evaluator_path),
        "config_sha256": _sha256(config_path),
        "source_manifest_file_sha256": _sha256(source_manifest_path),
        "stage0_checkpoint_sha256": _sha256(stage0_path),
        "pilot_checkpoint_sha256": _sha256(pilot_path),
        "pilot_evaluation_sha256": _sha256(evaluation_path),
        "bank_freeze_state_sha256": _sha256(bank_freeze_state_path),
    }
    executing_evaluator = pathlib.Path(evaluator_module.__file__).resolve()
    if _sha256(executing_evaluator) != hashes["evaluator_sha256"]:
        raise ValueError(
            "The evaluator recomputing release differs from the frozen "
            "evaluator used to create per-trial results"
        )
    source_manifest_value = _json(source_manifest_path)
    source_semantic_sha256 = source_manifest_value.get(
        "semantic_combined_sha256"
    )
    if not isinstance(source_semantic_sha256, str):
        raise ValueError("Frozen source manifest has no semantic digest")
    evaluator_module.validate_bank_freeze_state(
        bank_freeze_state_path,
        bank_path,
        hashes["bank_sha256"],
        hashes["config_sha256"],
        source_semantic_sha256,
        hashes["evaluator_sha256"],
    )

    evaluation = _json(evaluation_path)
    _assert_finite_tree(evaluation)
    expected_identity = {
        "schema_version": evaluator_module.EVALUATOR_SCHEMA_VERSION,
        "engineering_status": "PASS",
        "run_id": pilot["run_id"],
    }
    mismatches = {
        key: (evaluation.get(key), value)
        for key, value in expected_identity.items()
        if evaluation.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot evaluation identity mismatch: {mismatches}")
    frozen = evaluation.get("frozen_inputs")
    if not isinstance(frozen, dict):
        raise ValueError("Pilot evaluation has no frozen_inputs binding")
    expected_frozen = {
        "bank_sha256": hashes["bank_sha256"],
        "results_sha256": hashes["results_sha256"],
        "evaluator_sha256": hashes["evaluator_sha256"],
        "config_sha256": hashes["config_sha256"],
        "source_manifest_file_sha256": hashes[
            "source_manifest_file_sha256"
        ],
        "source_semantic_sha256": source_semantic_sha256,
        "bank_freeze_state_sha256": hashes[
            "bank_freeze_state_sha256"
        ],
    }
    frozen_mismatches = {
        key: (frozen.get(key), value)
        for key, value in expected_frozen.items()
        if frozen.get(key) != value
    }
    if frozen_mismatches:
        raise ValueError(
            f"Pilot evaluation frozen input mismatch: {frozen_mismatches}"
        )
    _checkpoint_binding(
        frozen.get("stage0_checkpoint"),
        stage0_path,
        hashes["stage0_checkpoint_sha256"],
        0,
        0,
        "stage-zero checkpoint",
    )
    _checkpoint_binding(
        frozen.get("pilot_checkpoint"),
        pilot_path,
        hashes["pilot_checkpoint_sha256"],
        6944,
        4,
        "pilot checkpoint",
    )
    if hashes["pilot_checkpoint_sha256"] != pilot["checkpoint_sha256"]:
        raise ValueError("Pilot evaluation checkpoint differs from completion")

    bank_frame = pd.read_csv(bank_path, sep="\t", dtype=ROLE_SPEAKER_DTYPES)
    result_frame = pd.read_csv(results_path, dtype={"target_speaker": str})
    # This validates row identities, balanced bank layout, derivable outcomes,
    # finite probabilities/NLLs, and that controls exist only on the fixed set.
    evaluator_module.validate_results_against_bank(result_frame, bank_frame)
    recomputed = evaluator_module.recompute_pilot4_eval(
        result_frame,
        bank_frame,
        bootstrap_seed=evaluator_module.BOOTSTRAP_SEED,
        bootstrap_repetitions=evaluator_module.BOOTSTRAP_REPETITIONS,
    )
    _assert_finite_tree(recomputed, "recomputed")
    recorded_core = {
        key: evaluation.get(key) for key in recomputed
    }
    if recorded_core != recomputed:
        raise ValueError(
            "Structured PILOT4_EVAL does not equal the independent "
            "per-trial recomputation"
        )
    if recomputed.get("decision") != "GO":
        raise ValueError(
            "Per-trial pilot recomputation is INCONCLUSIVE; GO is forbidden"
        )
    for path, key in (
        (bank_path, "bank_sha256"),
        (results_path, "results_sha256"),
        (evaluator_path, "evaluator_sha256"),
        (config_path, "config_sha256"),
        (source_manifest_path, "source_manifest_file_sha256"),
        (stage0_path, "stage0_checkpoint_sha256"),
        (pilot_path, "pilot_checkpoint_sha256"),
        (evaluation_path, "pilot_evaluation_sha256"),
        (bank_freeze_state_path, "bank_freeze_state_sha256"),
    ):
        if _sha256(path) != hashes[key]:
            raise RuntimeError(f"Pilot release input changed while reading: {path}")
    bindings = {
        "bank": {"path": str(bank_path), "sha256": hashes["bank_sha256"]},
        "results": {
            "path": str(results_path),
            "sha256": hashes["results_sha256"],
        },
        "evaluator": {
            "path": str(evaluator_path),
            "sha256": hashes["evaluator_sha256"],
        },
        "config": {
            "path": str(config_path),
            "sha256": hashes["config_sha256"],
        },
        "source_manifest": {
            "path": str(source_manifest_path),
            "sha256": hashes["source_manifest_file_sha256"],
            "semantic_sha256": source_semantic_sha256,
        },
        "stage0_checkpoint": {
            "path": str(stage0_path),
            "sha256": hashes["stage0_checkpoint_sha256"],
        },
        "pilot_checkpoint": {
            "path": str(pilot_path),
            "sha256": hashes["pilot_checkpoint_sha256"],
        },
        "pilot_evaluation": {
            "path": str(evaluation_path),
            "sha256": hashes["pilot_evaluation_sha256"],
        },
        "bank_freeze_state": {
            "path": str(bank_freeze_state_path),
            "sha256": hashes["bank_freeze_state_sha256"],
        },
    }
    return evaluation, bindings


def create_release(
    run_root: str | pathlib.Path,
    review_record: str | pathlib.Path,
    pilot_evaluation: str | pathlib.Path,
    bank: str | pathlib.Path,
    results: str | pathlib.Path,
    evaluator: str | pathlib.Path,
    config: str | pathlib.Path,
    source_manifest: str | pathlib.Path,
    stage0_checkpoint: str | pathlib.Path,
) -> dict:
    root = pathlib.Path(run_root).expanduser().resolve()
    pilot, cue = _validated_inputs(root)
    evaluation, bindings = _validated_evaluation(
        root,
        pilot,
        pilot_evaluation,
        bank,
        results,
        evaluator,
        config,
        source_manifest,
        stage0_checkpoint,
    )
    review = _safe_file(review_record, "Pilot review record")
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "status": "GO",
        "run_id": pilot["run_id"],
        "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pilot_checkpoint_basename": pilot["checkpoint_basename"],
        "pilot_checkpoint_sha256": pilot["checkpoint_sha256"],
        "pilot_global_step": int(pilot["global_step"]),
        "pilot_completion_sha256": _sha256(
            root / "state/PILOT4_COMPLETE.json"
        ),
        "cue_control_release_sha256": _sha256(
            root / "state/cue_control_release.json"
        ),
        "cue_control_summary_sha256": cue["summary_sha256"],
        "review_record": str(review),
        "review_record_sha256": _sha256(review),
        "pilot_evaluation_decision": evaluation["decision"],
        "frozen_inputs": bindings,
    }


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Pilot GO record already exists: {path}")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def validate_release(run_root: str | pathlib.Path) -> dict:
    root = pathlib.Path(run_root).expanduser().resolve()
    pilot, cue = _validated_inputs(root)
    release = _json(root / "state/PILOT4_GO.json")
    expected = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "status": "GO",
        "run_id": pilot["run_id"],
        "pilot_checkpoint_basename": pilot["checkpoint_basename"],
        "pilot_checkpoint_sha256": pilot["checkpoint_sha256"],
        "pilot_global_step": int(pilot["global_step"]),
        "pilot_completion_sha256": _sha256(
            root / "state/PILOT4_COMPLETE.json"
        ),
        "cue_control_release_sha256": _sha256(
            root / "state/cue_control_release.json"
        ),
        "cue_control_summary_sha256": cue["summary_sha256"],
    }
    mismatches = {
        key: (release.get(key), value)
        for key, value in expected.items()
        if release.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot GO record mismatch: {mismatches}")
    review = _safe_file(release.get("review_record", ""), "Pilot review record")
    if _sha256(review) != release.get("review_record_sha256"):
        raise ValueError("Pilot review record changed after GO")
    bindings = release.get("frozen_inputs")
    if not isinstance(bindings, dict):
        raise ValueError("Pilot GO record has no frozen_inputs binding")

    def bound_path(name: str) -> pathlib.Path:
        record = bindings.get(name)
        if not isinstance(record, dict):
            raise ValueError(f"Pilot GO record has no {name} binding")
        return pathlib.Path(record.get("path", ""))

    evaluation, current_bindings = _validated_evaluation(
        root,
        pilot,
        bound_path("pilot_evaluation"),
        bound_path("bank"),
        bound_path("results"),
        bound_path("evaluator"),
        bound_path("config"),
        bound_path("source_manifest"),
        bound_path("stage0_checkpoint"),
    )
    if bindings != current_bindings:
        raise ValueError("A frozen pilot evaluation input changed after GO")
    if release.get("pilot_evaluation_decision") != evaluation["decision"]:
        raise ValueError("Pilot evaluation decision mismatch")
    return release


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("create", "validate"))
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--review-record")
    parser.add_argument("--pilot-evaluation")
    parser.add_argument("--bank")
    parser.add_argument("--results")
    parser.add_argument("--evaluator")
    parser.add_argument("--config")
    parser.add_argument("--source-manifest")
    parser.add_argument("--stage0-checkpoint")
    args = parser.parse_args()
    root = pathlib.Path(args.run_root).expanduser().resolve()
    if args.command == "create":
        required = (
            "review_record",
            "pilot_evaluation",
            "bank",
            "results",
            "evaluator",
            "config",
            "source_manifest",
            "stage0_checkpoint",
        )
        missing = [name for name in required if not getattr(args, name)]
        if missing:
            raise SystemExit(f"create is missing arguments: {missing}")
        result = create_release(
            root,
            args.review_record,
            args.pilot_evaluation,
            args.bank,
            args.results,
            args.evaluator,
            args.config,
            args.source_manifest,
            args.stage0_checkpoint,
        )
        _atomic_json(root / "state/PILOT4_GO.json", result)
    else:
        result = validate_release(root)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
