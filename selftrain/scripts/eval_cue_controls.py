"""Evaluate a frozen checkpoint under paired cue counterfactuals.

Every trial uses one immutable target+distractor scene.  Only the cue changes:
correct target-speaker cue, a constrained permutation of the correct-cue pool,
all-zero cue, or an independent distractor-speaker cue.  This script deliberately avoids
``Trainer.test()`` because the repository's legacy test loop is incompatible
with the self-training dataset and does not preserve paired scenes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import random
import tempfile

import numpy as np
import pandas as pd
import torch
import yaml

from selftrain.data.diotic_attention import (
    CROP_SAMPLES,
    WaveformCache,
    crop_centered,
)
try:
    from selftrain.scripts.build_cue_control_manifest import (
        sha256_file,
        validate_bank_artifacts,
    )
except ModuleNotFoundError:  # Direct-file invocation during local review.
    from build_cue_control_manifest import sha256_file, validate_bank_artifacts
from src.spatial_attn_lightning import BinauralAttentionModule


CONDITIONS = ("correct", "shuffled", "silent", "distractor")


def _load_torch_checkpoint(path: pathlib.Path) -> dict:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise ValueError(f"Invalid metadata line in {path}: {line!r}")
        values[key] = value
    return values


def validate_frozen_inputs(
    checkpoint_path: pathlib.Path,
    config_path: pathlib.Path,
    metadata_path: pathlib.Path,
    source_manifest_path: pathlib.Path,
    expected_checkpoint_sha256: str,
    expected_config_sha256: str,
) -> dict:
    checkpoint_sha = sha256_file(checkpoint_path)
    config_sha = sha256_file(config_path)
    source_manifest_sha = sha256_file(source_manifest_path)
    if checkpoint_sha != expected_checkpoint_sha256:
        raise ValueError(
            "Checkpoint SHA-256 mismatch: "
            f"expected={expected_checkpoint_sha256}, actual={checkpoint_sha}"
        )
    if config_sha != expected_config_sha256:
        raise ValueError(
            "Config SHA-256 mismatch: "
            f"expected={expected_config_sha256}, actual={config_sha}"
        )

    expected_environment = _parse_env_file(metadata_path)
    required_environment = {
        "AUDATTN_RUN_ID",
        "AUDATTN_CONFIG_SHA256",
        "AUDATTN_SOURCE_SHA256",
    }
    missing = sorted(required_environment.difference(expected_environment))
    if missing:
        raise ValueError(f"Run metadata file is missing keys: {missing}")
    if expected_environment["AUDATTN_CONFIG_SHA256"] != config_sha:
        raise ValueError("Run metadata config SHA does not match frozen config")
    if expected_environment["AUDATTN_SOURCE_SHA256"] != source_manifest_sha:
        raise ValueError("Run metadata source SHA does not match source.sha256")

    checkpoint = _load_torch_checkpoint(checkpoint_path)
    if int(checkpoint.get("epoch", -1)) != 19:
        raise ValueError(
            f"Expected final epoch=19, got {checkpoint.get('epoch')!r}"
        )
    if int(checkpoint.get("global_step", -1)) != 93_760:
        raise ValueError(
            "Expected final global_step=93760, got "
            f"{checkpoint.get('global_step')!r}"
        )
    run_metadata = checkpoint.get("audattn_run_metadata_v1")
    if not isinstance(run_metadata, dict):
        raise ValueError("Checkpoint has no audattn_run_metadata_v1 mapping")
    expected_checkpoint_metadata = {
        "run_id": expected_environment["AUDATTN_RUN_ID"],
        "config_sha256": expected_environment["AUDATTN_CONFIG_SHA256"],
        "source_semantic_sha256": expected_environment[
            "AUDATTN_SOURCE_SHA256"
        ],
    }
    mismatches = {
        key: (run_metadata.get(key), value)
        for key, value in expected_checkpoint_metadata.items()
        if run_metadata.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Checkpoint run metadata mismatch: {mismatches}")
    amp = checkpoint.get("audattn_amp_state_v1", {})
    if int(amp.get("total_optimizer_attempts", -1)) != 93_760:
        raise ValueError("Checkpoint AMP attempt count is not 93760")
    if int(amp.get("successful_optimizer_steps", -1)) != 93_719:
        raise ValueError("Checkpoint successful optimizer count is not 93719")
    if int(amp.get("total_overflows", -1)) != 41:
        raise ValueError("Checkpoint AMP overflow count is not 41")
    del checkpoint
    return {
        "checkpoint_sha256": checkpoint_sha,
        "config_sha256": config_sha,
        "source_manifest_sha256": source_manifest_sha,
        "run_metadata": expected_checkpoint_metadata,
    }


def _load_model(
    checkpoint_path: pathlib.Path,
    config: dict,
    device: torch.device,
) -> BinauralAttentionModule:
    original_load = torch.load

    def load_full(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = load_full
    try:
        model = BinauralAttentionModule.load_from_checkpoint(
            checkpoint_path=str(checkpoint_path),
            config=config,
            strict=True,
            map_location="cpu",
        )
    finally:
        torch.load = original_load
    model.eval().to(device)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model


def _role_batch(
    frame: pd.DataFrame,
    role: str,
    cache: WaveformCache,
    clips_dir: pathlib.Path,
) -> torch.Tensor:
    waveforms = []
    for row in frame.itertuples(index=False):
        path = clips_dir / str(getattr(row, f"{role}_path"))
        center = float(getattr(row, f"{role}_anchor_center_s"))
        mono = crop_centered(cache.get(path), center)
        waveforms.append(np.stack((mono, mono), axis=0))
    array = np.stack(waveforms).astype(np.float32, copy=False)
    if array.shape[1:] != (2, CROP_SAMPLES):
        raise ValueError(f"Unexpected {role} batch shape: {array.shape}")
    return torch.from_numpy(array)


def _scene_hashes(scene: torch.Tensor) -> list[str]:
    scene = scene.detach().cpu().contiguous()
    return [
        hashlib.sha256(item.numpy().tobytes()).hexdigest() for item in scene
    ]


def _cluster_bootstrap_delta(
    values: np.ndarray,
    speakers: np.ndarray,
    seed: int,
    repetitions: int,
) -> tuple[float, float]:
    unique, inverse = np.unique(speakers.astype(str), return_inverse=True)
    sums = np.bincount(inverse, weights=values.astype(float))
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        sampled = rng.integers(0, len(unique), size=len(unique))
        draws[index] = sums[sampled].sum() / counts[sampled].sum()
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def summarize(
    frame: pd.DataFrame,
    bootstrap_seed: int,
    bootstrap_repetitions: int,
    analysis_kind: str,
) -> dict:
    summary: dict[str, object] = {
        "trials": int(len(frame)),
        "target_speakers": int(frame["target_speaker"].nunique()),
        "analysis_kind": analysis_kind,
        "conditions": {},
        "paired_comparisons": {},
    }
    speakers = frame["target_speaker"].astype(str).to_numpy()
    for offset, condition in enumerate(CONDITIONS):
        correct = frame[f"{condition}_correct"].astype(float).to_numpy()
        low, high = _cluster_bootstrap_delta(
            correct,
            speakers,
            bootstrap_seed + offset,
            bootstrap_repetitions,
        )
        summary["conditions"][condition] = {
            "accuracy": float(correct.mean()),
            "accuracy_cluster_bootstrap_95ci": [low, high],
            "cross_entropy": float(frame[f"{condition}_nll"].mean()),
            "mean_p_target": float(frame[f"{condition}_p_target"].mean()),
            "distractor_intrusion_rate": float(
                frame[f"{condition}_distractor_intrusion"].mean()
            ),
            "mean_p_distractor": float(
                frame[f"{condition}_p_distractor"].mean()
            ),
        }

    correct_values = frame["correct_correct"].astype(int).to_numpy()
    for offset, control in enumerate(("shuffled", "silent", "distractor")):
        control_values = frame[f"{control}_correct"].astype(int).to_numpy()
        delta = correct_values - control_values
        low, high = _cluster_bootstrap_delta(
            delta,
            speakers,
            bootstrap_seed + 100 + offset,
            bootstrap_repetitions,
        )
        summary["paired_comparisons"][f"correct_minus_{control}"] = {
            "accuracy_delta": float(delta.mean()),
            "cluster_bootstrap_95ci": [low, high],
            "mcnemar_correct_only": int(
                ((correct_values == 1) & (control_values == 0)).sum()
            ),
            "mcnemar_control_only": int(
                ((correct_values == 0) & (control_values == 1)).sum()
            ),
        }

    primary_controls = [
        float(summary["conditions"][name]["accuracy"])
        for name in ("shuffled", "silent")
    ]
    correct_accuracy = float(summary["conditions"]["correct"]["accuracy"])
    primary_delta = correct_accuracy - max(primary_controls)
    primary_ci_lows = [
        float(
            summary["paired_comparisons"][f"correct_minus_{name}"][
                "cluster_bootstrap_95ci"
            ][0]
        )
        for name in ("shuffled", "silent")
    ]
    primary_pass = bool(
        primary_delta >= 0.05 and all(value > 0 for value in primary_ci_lows)
    )
    summary["preregistered_primary_criterion"] = {
        "correct_minus_max_shuffled_silent": primary_delta,
        "required_delta": 0.05,
        "all_primary_ci_lower_bounds_positive": all(
            value > 0 for value in primary_ci_lows
        ),
        "pass": primary_pass if analysis_kind == "confirmatory" else None,
        "status": (
            "CONFIRMATORY_PASS" if primary_pass else "CONFIRMATORY_FAIL"
        ) if analysis_kind == "confirmatory" else "SMOKE_ONLY_NOT_INFERENTIAL",
    }
    p_delta = (
        frame["distractor_p_distractor"].astype(float).to_numpy()
        - frame["correct_p_distractor"].astype(float).to_numpy()
    )
    intrusion_delta = (
        frame["distractor_distractor_intrusion"].astype(float).to_numpy()
        - frame["correct_distractor_intrusion"].astype(float).to_numpy()
    )
    p_ci = _cluster_bootstrap_delta(
        p_delta, speakers, bootstrap_seed + 300, bootstrap_repetitions
    )
    intrusion_ci = _cluster_bootstrap_delta(
        intrusion_delta, speakers, bootstrap_seed + 301, bootstrap_repetitions
    )
    summary["preregistered_secondary_distractor_cue_effect"] = {
        "p_distractor_delta_vs_correct": float(p_delta.mean()),
        "p_distractor_delta_cluster_bootstrap_95ci": list(p_ci),
        "intrusion_delta_vs_correct": float(intrusion_delta.mean()),
        "intrusion_delta_cluster_bootstrap_95ci": list(intrusion_ci),
        "directional_support": bool(p_ci[0] > 0 and intrusion_ci[0] > 0)
        if analysis_kind == "confirmatory"
        else None,
    }
    return summary


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
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def evaluate(args) -> dict:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("medium")
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    if not torch.cuda.is_available() and not args.allow_cpu:
        raise RuntimeError("CUDA is required unless --allow-cpu is provided")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    frozen = validate_frozen_inputs(
        args.checkpoint,
        args.config,
        args.run_metadata,
        args.source_manifest,
        args.expected_checkpoint_sha256,
        args.expected_config_sha256,
    )
    with args.config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if config.get("hparas", {}).get("mask_cues", False):
        raise ValueError("Evaluation requires mask_cues=false")
    if float(config["noise_kwargs"]["low_snr"]) != 0.0 or float(
        config["noise_kwargs"]["high_snr"]
    ) != 0.0:
        raise ValueError("Evaluation requires fixed 0 dB config")

    dtype_map = {
        f"{role}_speaker": str
        for role in (
            "target",
            "correct_cue",
            "distractor",
            "distractor_cue",
            "shuffled_cue",
        )
    }
    bank = pd.read_csv(args.manifest, sep="\t", dtype=dtype_map)
    validate_bank_artifacts(
        output_path=args.manifest,
        config_path=args.config,
        project_root=args.project_root,
        expected_trials=args.expected_trials,
        expected_bank_seed=args.expected_bank_seed,
    )
    manifest_sha = sha256_file(args.manifest)
    if manifest_sha != args.expected_manifest_sha256:
        raise ValueError(
            "Manifest SHA-256 mismatch: "
            f"expected={args.expected_manifest_sha256}, actual={manifest_sha}"
        )
    if args.limit:
        bank = bank.iloc[: args.limit].copy()
    if bank.empty:
        raise ValueError("No trials selected")
    if args.output.exists() or args.summary.exists():
        raise FileExistsError("Refusing to overwrite cue-control output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)

    clips_dir = pathlib.Path(
        os.environ.get("CV_CLIPS", config["corpus"]["clips_dir"])
    ).expanduser().resolve()
    if not clips_dir.is_dir():
        raise FileNotFoundError(f"CV clips directory not found: {clips_dir}")

    model = _load_model(args.checkpoint, config, device)
    parameter_versions = tuple(parameter._version for parameter in model.parameters())
    cache = WaveformCache(max_items=args.cache_items)
    records: list[dict] = []
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    if partial.exists():
        raise FileExistsError(f"Refusing stale partial output: {partial}")

    try:
        for start in range(0, len(bank), args.batch_size):
            stop = min(start + args.batch_size, len(bank))
            batch = bank.iloc[start:stop]
            target = _role_batch(batch, "target", cache, clips_dir)
            background = _role_batch(batch, "distractor", cache, clips_dir)
            raw_cues = {
                "correct": _role_batch(batch, "correct_cue", cache, clips_dir),
                "shuffled": _role_batch(batch, "shuffled_cue", cache, clips_dir),
                "distractor": _role_batch(
                    batch, "distractor_cue", cache, clips_dir
                ),
            }
            raw_cues["silent"] = torch.zeros_like(raw_cues["correct"])

            scene, _ = model.audio_transforms(target, background)
            scene_hashes = _scene_hashes(scene)
            normalized_cues = {
                name: model.audio_transforms(waveform, None)[0]
                for name, waveform in raw_cues.items()
            }
            target_labels = torch.as_tensor(
                batch["target_label"].to_numpy(dtype=np.int64),
                dtype=torch.long,
                device=device,
            )
            distractor_labels = torch.as_tensor(
                batch["distractor_label"].to_numpy(dtype=np.int64),
                dtype=torch.long,
                device=device,
            )

            predictions: dict[str, dict[str, np.ndarray]] = {}
            with torch.inference_mode():
                scene_device = scene.to(device, non_blocking=True)
                autocast_enabled = device.type == "cuda"
                with torch.autocast(
                    device_type=device.type,
                    dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
                    enabled=autocast_enabled,
                ):
                    scene_features, _ = model.coch_gram.full_rep(
                        scene_device, None
                    )
                    for name in CONDITIONS:
                        cue_device = normalized_cues[name].to(
                            device, non_blocking=True
                        )
                        cue_features, _ = model.coch_gram.full_rep(
                            cue_device, None
                        )
                        logits = model(cue_features, scene_features, None)
                        log_probabilities = logits.float().log_softmax(dim=-1)
                        probabilities = log_probabilities.exp()
                        predicted = probabilities.argmax(dim=-1)
                        nll = -log_probabilities.gather(
                            1, target_labels[:, None]
                        ).squeeze(1)
                        p_target = probabilities.gather(
                            1, target_labels[:, None]
                        ).squeeze(1)
                        p_distractor = probabilities.gather(
                            1, distractor_labels[:, None]
                        ).squeeze(1)
                        finite = (
                            torch.isfinite(logits).all()
                            and torch.isfinite(nll).all()
                            and torch.isfinite(p_target).all()
                            and torch.isfinite(p_distractor).all()
                        )
                        if not bool(finite):
                            raise FloatingPointError(
                                f"Non-finite inference output in {name}"
                            )
                        predictions[name] = {
                            "pred": predicted.cpu().numpy(),
                            "nll": nll.cpu().numpy(),
                            "p_target": p_target.cpu().numpy(),
                            "p_distractor": p_distractor.cpu().numpy(),
                        }

            for position, row in enumerate(batch.itertuples(index=False)):
                record = {
                    "trial_id": int(row.trial_id),
                    "target_speaker": str(row.target_speaker),
                    "target_gender": str(row.target_gender),
                    "target_label": int(row.target_label),
                    "distractor_speaker": str(row.distractor_speaker),
                    "distractor_gender": str(row.distractor_gender),
                    "distractor_label": int(row.distractor_label),
                    "correct_cue_gender": str(row.correct_cue_gender),
                    "shuffled_cue_gender": str(row.shuffled_cue_gender),
                    "distractor_cue_gender": str(row.distractor_cue_gender),
                    "scene_sha256": scene_hashes[position],
                }
                for name in CONDITIONS:
                    predicted = int(predictions[name]["pred"][position])
                    record[f"{name}_pred_label"] = predicted
                    record[f"{name}_correct"] = int(
                        predicted == int(row.target_label)
                    )
                    record[f"{name}_distractor_intrusion"] = int(
                        predicted == int(row.distractor_label)
                    )
                    record[f"{name}_nll"] = float(
                        predictions[name]["nll"][position]
                    )
                    record[f"{name}_p_target"] = float(
                        predictions[name]["p_target"][position]
                    )
                    record[f"{name}_p_distractor"] = float(
                        predictions[name]["p_distractor"][position]
                    )
                records.append(record)

            pd.DataFrame(records[-len(batch) :]).to_csv(
                partial,
                mode="a",
                header=not partial.exists(),
                index=False,
            )
            print(f"Cue controls: {stop}/{len(bank)} trials", flush=True)

        result = pd.read_csv(partial, dtype={"target_speaker": str})
        if len(result) != len(bank):
            raise RuntimeError(
                f"Output row count mismatch: {len(result)} != {len(bank)}"
            )
        if result["trial_id"].duplicated().any():
            raise RuntimeError("Duplicate trial IDs in cue-control output")
        if parameter_versions != tuple(
            parameter._version for parameter in model.parameters()
        ):
            raise RuntimeError("Model parameter version changed during inference")
        os.replace(partial, args.output)
    finally:
        if partial.exists() and not args.output.exists():
            print(f"Partial output retained for audit: {partial}")

    result = pd.read_csv(args.output, dtype={"target_speaker": str})
    summary = summarize(
        result,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_repetitions=args.bootstrap_repetitions,
        analysis_kind=args.analysis_kind,
    )
    summary["frozen_inputs"] = {
        **frozen,
        "manifest_sha256": manifest_sha,
        "output_sha256": sha256_file(args.output),
    }
    summary["runtime"] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "seed": int(args.seed),
        "batch_size": int(args.batch_size),
    }
    _atomic_json(args.summary, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--run-metadata", required=True, type=pathlib.Path)
    parser.add_argument("--source-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--summary", required=True, type=pathlib.Path)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-trials", required=True, type=int)
    parser.add_argument("--expected-bank-seed", required=True, type=int)
    parser.add_argument(
        "--analysis-kind",
        required=True,
        choices=("smoke", "confirmatory"),
    )
    parser.add_argument(
        "--project-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--cache-items", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--bootstrap-seed", type=int, default=20260816)
    parser.add_argument("--bootstrap-repetitions", type=int, default=2000)
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()
    for name in (
        "checkpoint",
        "config",
        "run_metadata",
        "source_manifest",
        "manifest",
    ):
        value = getattr(args, name).expanduser().resolve()
        if not value.is_file():
            raise FileNotFoundError(f"Missing {name}: {value}")
        setattr(args, name, value)
    args.output = args.output.expanduser().resolve()
    args.summary = args.summary.expanduser().resolve()
    args.project_root = args.project_root.expanduser().resolve()
    if args.batch_size <= 0:
        raise ValueError("batch-size must be positive")
    if args.limit < 0:
        raise ValueError("limit cannot be negative")
    expected_by_kind = {"smoke": 32, "confirmatory": 10_000}
    if args.expected_trials != expected_by_kind[args.analysis_kind]:
        raise ValueError(
            f"{args.analysis_kind} requires expected-trials="
            f"{expected_by_kind[args.analysis_kind]}"
        )
    if args.limit != 0:
        raise ValueError("Partial-bank inference is forbidden; use a separate smoke bank")
    if args.bootstrap_repetitions < 100:
        raise ValueError("bootstrap-repetitions must be at least 100")
    if args.expected_trials <= 0:
        raise ValueError("expected-trials must be positive")
    evaluate(args)


if __name__ == "__main__":
    main()
