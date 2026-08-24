"""Paired stage-zero/four-epoch evaluation on the frozen full bank."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import platform
import random
import tempfile
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from selftrain.scripts.build_full_pilot_eval_bank import (
    CONTROL_TRIALS,
    DEFAULT_BANK_SEED,
    ROLE_SPEAKER_DTYPES,
    TOTAL_TRIALS,
    sha256_file,
    validate_bank_artifacts,
)

if TYPE_CHECKING:
    import torch

    from selftrain.data.diotic_attention import WaveformCache
    from src.spatial_attn_lightning import BinauralAttentionModule


EVALUATOR_SCHEMA_VERSION = 2
BOOTSTRAP_SEED = 20260816
BOOTSTRAP_REPETITIONS = 10_000
CHANCE_ACCURACY = 1.0 / 800.0
CONTROL_CONDITIONS = ("shuffled", "silent", "distractor")


def _load_checkpoint(path: pathlib.Path) -> dict:
    import torch

    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        checkpoint = torch.load(path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise ValueError(f"Checkpoint payload is not a mapping: {path}")
    return checkpoint


def validate_checkpoint(
    path: pathlib.Path,
    expected_sha256: str,
    expected_run_id: str,
    expected_source_semantic_sha256: str,
    expected_config_sha256: str,
    expected_global_step: int,
    expected_completed_epochs: int,
) -> dict:
    argument = path.expanduser()
    if argument.is_symlink():
        raise ValueError(f"Checkpoint must not be a symlink: {argument}")
    path = argument.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Checkpoint is missing: {path}")
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha256:
        raise ValueError(
            f"Checkpoint SHA mismatch: expected={expected_sha256}, "
            f"actual={actual_sha}, path={path}"
        )
    checkpoint = _load_checkpoint(path)
    global_step = int(checkpoint.get("global_step", -1))
    completed = int(
        checkpoint.get("loops", {})
        .get("fit_loop", {})
        .get("epoch_progress", {})
        .get("total", {})
        .get("completed", -1)
    )
    if global_step != expected_global_step or completed != expected_completed_epochs:
        raise ValueError(
            "Checkpoint phase mismatch: "
            f"actual=(step={global_step}, completed={completed}), "
            f"expected=(step={expected_global_step}, "
            f"completed={expected_completed_epochs})"
        )
    expected_metadata = {
        "run_id": expected_run_id,
        "source_semantic_sha256": expected_source_semantic_sha256,
        "config_sha256": expected_config_sha256,
    }
    if checkpoint.get("audattn_run_metadata_v1") != expected_metadata:
        raise ValueError("Checkpoint run metadata does not match the frozen run")
    amp = checkpoint.get("audattn_amp_state_v1") or {}
    attempts = int(amp.get("total_optimizer_attempts", -1))
    successful = int(amp.get("successful_optimizer_steps", -1))
    overflows = int(amp.get("total_overflows", -1))
    if attempts != global_step or successful + overflows != attempts:
        raise ValueError("Checkpoint AMP accounting is inconsistent")
    del checkpoint
    return {
        "path": str(path),
        "sha256": actual_sha,
        "global_step": global_step,
        "completed_epochs": completed,
        "successful_optimizer_steps": successful,
        "amp_overflows": overflows,
    }


def validate_bank_freeze_state(
    path: pathlib.Path,
    bank: pathlib.Path,
    bank_sha256: str,
    config_sha256: str,
    source_semantic_sha256: str,
    evaluator_sha256: str,
) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Pilot bank freeze state is invalid: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_PILOT_TRAINING",
        "bank": str(bank.resolve()),
        "bank_sha256": bank_sha256,
        "bank_seed": DEFAULT_BANK_SEED,
        "config_sha256": config_sha256,
        "source_semantic_sha256": source_semantic_sha256,
        "evaluator_sha256": evaluator_sha256,
        "global_step_before_training": 0,
    }
    mismatches = {
        key: (record.get(key), value)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot bank freeze state mismatch: {mismatches}")
    return record


def _load_model(
    checkpoint_path: pathlib.Path,
    config: dict,
    device: torch.device,
) -> BinauralAttentionModule:
    import torch

    from src.spatial_attn_lightning import BinauralAttentionModule

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
    import torch

    from selftrain.data.diotic_attention import CROP_SAMPLES, crop_centered

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


def _mix_at_fixed_snr(
    target: np.ndarray,
    background: np.ndarray,
    snr_db: float,
) -> tuple[np.ndarray, float]:
    foreground = np.asarray(
        target - target.mean(dtype=np.float64), dtype=np.float32
    )
    centered_background = np.asarray(
        background - background.mean(dtype=np.float64), dtype=np.float32
    )
    foreground_rms = np.sqrt(
        np.mean(np.square(foreground), dtype=np.float64)
    )
    background_rms = np.sqrt(
        np.mean(np.square(centered_background), dtype=np.float64)
    )
    if foreground_rms <= 0 or background_rms <= 0:
        raise ValueError("Pilot mixed scene contains a silent source")
    ratio = 10.0 ** (float(snr_db) / 20.0)
    scale = foreground_rms / max(background_rms * ratio, 1e-12)
    scaled_background = np.asarray(
        centered_background * scale, dtype=np.float32
    )
    scaled_background_rms = np.sqrt(
        np.mean(np.square(scaled_background), dtype=np.float64)
    )
    measured_snr_db = 20.0 * np.log10(
        foreground_rms / max(scaled_background_rms, 1e-12)
    )
    error = abs(measured_snr_db - float(snr_db))
    if error >= 1e-4:
        raise RuntimeError(
            "Pilot scene SNR implementation mismatch: "
            f"requested={snr_db}, measured={measured_snr_db}, error={error}"
        )
    return np.asarray(foreground + scaled_background, dtype=np.float32), float(
        error
    )


def _raw_scene_batch(
    frame: pd.DataFrame,
    cache: WaveformCache,
    clips_dir: pathlib.Path,
    snr_errors: list[float] | None = None,
) -> torch.Tensor:
    import torch

    from selftrain.data.diotic_attention import crop_centered, sum_equal_rms

    scenes = []
    for row in frame.itertuples(index=False):
        target_mono = crop_centered(
            cache.get(clips_dir / str(row.target_path)),
            float(row.target_anchor_center_s),
        )
        target = np.stack((target_mono, target_mono), axis=0).astype(
            np.float32, copy=False
        )
        if str(row.scene_kind) == "clean":
            scene = target
        else:
            distractors = []
            for position in range(1, int(row.distractor_count) + 1):
                mono = crop_centered(
                    cache.get(
                        clips_dir
                        / str(getattr(row, f"distractor_{position}_path"))
                    ),
                    float(
                        getattr(row, f"distractor_{position}_anchor_center_s")
                    ),
                )
                distractors.append(mono)
            background_mono = sum_equal_rms(distractors)
            background = np.stack(
                (background_mono, background_mono), axis=0
            ).astype(np.float32, copy=False)
            scene, snr_error = _mix_at_fixed_snr(
                target, background, float(row.snr_db)
            )
            if snr_errors is not None:
                snr_errors.append(float(snr_error))
        scenes.append(np.asarray(scene, dtype=np.float32))
    return torch.from_numpy(np.stack(scenes))


def _correct_cue_batch(
    frame: pd.DataFrame,
    cache: WaveformCache,
    clips_dir: pathlib.Path,
) -> torch.Tensor:
    import torch

    cue = _role_batch(frame, "correct_cue", cache, clips_dir)
    clean = torch.as_tensor(
        (frame["scene_kind"].astype(str) == "clean").to_numpy(),
        dtype=torch.bool,
    )
    cue[clean] = 0.0
    return cue


def _scene_hashes(scene: torch.Tensor) -> list[str]:
    scene = scene.detach().cpu().contiguous()
    return [
        hashlib.sha256(item.numpy().tobytes()).hexdigest() for item in scene
    ]


def _predict(
    model: BinauralAttentionModule,
    raw_scene: torch.Tensor,
    raw_cue: torch.Tensor,
    labels: torch.Tensor,
    probe_labels: torch.Tensor,
    device: torch.device,
) -> dict[str, np.ndarray]:
    import torch

    normalized_scene, _ = model.audio_transforms(raw_scene, None)
    normalized_cue, _ = model.audio_transforms(raw_cue, None)
    labels_device = labels.to(device, non_blocking=True)
    probe_device = probe_labels.to(device, non_blocking=True)
    with torch.inference_mode():
        autocast_enabled = device.type == "cuda"
        with torch.autocast(
            device_type=device.type,
            dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
            enabled=autocast_enabled,
        ):
            scene_features, _ = model.coch_gram.full_rep(
                normalized_scene.to(device, non_blocking=True), None
            )
            cue_features, _ = model.coch_gram.full_rep(
                normalized_cue.to(device, non_blocking=True), None
            )
            logits = model(cue_features, scene_features, None)
            log_probabilities = logits.float().log_softmax(dim=-1)
            probabilities = log_probabilities.exp()
            predicted = probabilities.argmax(dim=-1)
            nll = -log_probabilities.gather(
                1, labels_device[:, None]
            ).squeeze(1)
            p_target = probabilities.gather(
                1, labels_device[:, None]
            ).squeeze(1)
            p_probe = probabilities.gather(
                1, probe_device[:, None]
            ).squeeze(1)
    finite = (
        torch.isfinite(logits).all()
        and torch.isfinite(nll).all()
        and torch.isfinite(p_target).all()
        and torch.isfinite(p_probe).all()
    )
    if not bool(finite):
        raise FloatingPointError("Non-finite full-pilot inference output")
    return {
        "pred_label": predicted.cpu().numpy(),
        "nll": nll.cpu().numpy(),
        "p_target": p_target.cpu().numpy(),
        "p_probe_distractor": p_probe.cpu().numpy(),
    }


def _cluster_bootstrap_ci(
    values: np.ndarray,
    speakers: np.ndarray,
    seed: int,
    repetitions: int,
) -> tuple[float, float]:
    if repetitions <= 0:
        raise ValueError("bootstrap repetitions must be positive")
    unique, inverse = np.unique(speakers.astype(str), return_inverse=True)
    if not len(unique):
        raise ValueError("Cannot bootstrap an empty target-speaker set")
    sums = np.bincount(inverse, weights=values.astype(float))
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    draws = np.empty(repetitions, dtype=np.float64)
    for index in range(repetitions):
        sampled = rng.integers(0, len(unique), size=len(unique))
        draws[index] = sums[sampled].sum() / counts[sampled].sum()
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def validate_results_against_bank(
    results: pd.DataFrame,
    bank: pd.DataFrame,
) -> None:
    bank_required = {
        "trial_id",
        "scene_kind",
        "control_subset",
        "target_speaker",
        "target_gender",
        "target_label",
        "distractor_count",
        "snr_bin",
        "snr_db",
        "distractor_1_label",
    }
    bank_missing = sorted(bank_required.difference(bank.columns))
    if bank_missing:
        raise ValueError(
            f"Pilot bank is missing result-binding columns: {bank_missing}"
        )
    required = {
        "trial_id",
        "scene_kind",
        "control_subset",
        "target_speaker",
        "target_gender",
        "target_label",
        "distractor_count",
        "snr_bin",
        "snr_db",
        "probe_distractor_label",
        "scene_sha256",
        "stage0_pred_label",
        "stage0_correct",
        "stage0_nll",
        "stage0_p_target",
        "pilot_pred_label",
        "pilot_correct",
        "pilot_nll",
        "pilot_p_target",
    }
    for condition in CONTROL_CONDITIONS:
        required.update(
            {
                f"pilot_{condition}_pred_label",
                f"pilot_{condition}_correct",
                f"pilot_{condition}_nll",
                f"pilot_{condition}_p_target",
                f"pilot_{condition}_probe_intrusion",
                f"pilot_{condition}_p_probe_distractor",
            }
        )
    missing = sorted(required.difference(results.columns))
    if missing:
        raise ValueError(f"Pilot results are missing columns: {missing}")
    if len(results) != TOTAL_TRIALS or len(bank) != TOTAL_TRIALS:
        raise ValueError("Pilot results/bank row count is not 10,000")
    if bank["trial_id"].duplicated().any() or sorted(
        bank["trial_id"].astype(int)
    ) != list(range(TOTAL_TRIALS)):
        raise ValueError("Pilot bank trial IDs are not unique/contiguous")
    bank_mixed = bank["scene_kind"].astype(str) == "mixed"
    bank_clean = bank["scene_kind"].astype(str) == "clean"
    if int(bank_mixed.sum()) != 9_000 or int(bank_clean.sum()) != 1_000:
        raise ValueError("Pilot bank mixed/clean totals are not 9,000/1,000")
    mixed_frame = bank.loc[bank_mixed]
    cell_counts = mixed_frame.groupby(["distractor_count", "snr_bin"]).size()
    gender_counts = mixed_frame.groupby(
        ["distractor_count", "snr_bin", "target_gender"]
    ).size()
    if len(cell_counts) != 20 or set(cell_counts.astype(int)) != {450}:
        raise ValueError("Pilot bank does not contain 450 trials per mixed cell")
    if len(gender_counts) != 40 or set(gender_counts.astype(int)) != {225}:
        raise ValueError("Pilot bank does not contain 225 targets/gender/cell")
    if bank.loc[bank_clean].groupby("target_gender").size().to_dict() != {
        "female": 500,
        "male": 500,
    }:
        raise ValueError("Pilot clean bank is not 500 targets per gender")
    bank_controls = bank["control_subset"].astype(int) == 1
    control_frame = bank.loc[bank_controls]
    control_cells = control_frame.groupby(
        ["distractor_count", "snr_bin"]
    ).size()
    control_genders = control_frame.groupby(
        ["distractor_count", "snr_bin", "target_gender"]
    ).size()
    if (
        int(bank_controls.sum()) != CONTROL_TRIALS
        or bool((bank_controls & bank_clean).any())
        or len(control_cells) != 20
        or set(control_cells.astype(int)) != {100}
        or len(control_genders) != 40
        or set(control_genders.astype(int)) != {50}
    ):
        raise ValueError(
            "Pilot cue-control bank is not the balanced 2,000 subset"
        )
    if results["trial_id"].duplicated().any():
        raise ValueError("Pilot results contain duplicate trial IDs")
    results = results.sort_values("trial_id").reset_index(drop=True)
    bank = bank.sort_values("trial_id").reset_index(drop=True)
    if not np.array_equal(
        results["trial_id"].astype(int), bank["trial_id"].astype(int)
    ):
        raise ValueError("Pilot results trial IDs do not match the bank")
    identity_fields = (
        "scene_kind",
        "control_subset",
        "target_speaker",
        "target_gender",
        "target_label",
        "distractor_count",
        "snr_bin",
    )
    for field in identity_fields:
        left = results[field].astype(str).to_numpy()
        right = bank[field].astype(str).to_numpy()
        if not np.array_equal(left, right):
            raise ValueError(f"Pilot result identity differs at {field}")
    mixed = bank["scene_kind"].astype(str) == "mixed"
    if not np.allclose(
        results.loc[mixed, "snr_db"].astype(float),
        bank.loc[mixed, "snr_db"].astype(float),
        rtol=0,
        atol=1e-12,
    ):
        raise ValueError("Pilot result SNR differs from the frozen bank")
    if not np.array_equal(
        results.loc[mixed, "probe_distractor_label"].astype(int).to_numpy(),
        bank.loc[mixed, "distractor_1_label"].astype(int).to_numpy(),
    ):
        raise ValueError("Pilot result probe labels differ from the bank")
    if not results["scene_sha256"].astype(str).str.fullmatch(
        r"[0-9a-f]{64}"
    ).all():
        raise ValueError("Pilot result contains an invalid scene SHA")
    labels = results["target_label"].astype(int).to_numpy()
    for prefix in ("stage0", "pilot"):
        predictions = results[f"{prefix}_pred_label"].astype(int).to_numpy()
        if ((predictions < 0) | (predictions > 799)).any():
            raise ValueError(f"{prefix} prediction outside [0, 799]")
        expected_correct = (predictions == labels).astype(int)
        if not np.array_equal(
            expected_correct, results[f"{prefix}_correct"].astype(int)
        ):
            raise ValueError(f"{prefix}_correct is not derivable from predictions")
        values = results[[f"{prefix}_nll", f"{prefix}_p_target"]].to_numpy(
            dtype=float
        )
        if not np.isfinite(values).all():
            raise ValueError(f"{prefix} contains a non-finite metric")
        if (values[:, 0] < 0).any() or (
            (values[:, 1] < 0) | (values[:, 1] > 1)
        ).any():
            raise ValueError(f"{prefix} contains an invalid NLL/probability")
    controls = results["control_subset"].astype(int) == 1
    if int(controls.sum()) != CONTROL_TRIALS:
        raise ValueError("Pilot result control subset is not 2,000 trials")
    probe_labels = results.loc[controls, "probe_distractor_label"].astype(int)
    for condition in CONTROL_CONDITIONS:
        predictions = results.loc[
            controls, f"pilot_{condition}_pred_label"
        ].astype(int)
        expected_correct = (
            predictions.to_numpy() == labels[controls]
        ).astype(int)
        expected_intrusion = (
            predictions.to_numpy() == probe_labels.to_numpy()
        ).astype(int)
        if not np.array_equal(
            expected_correct,
            results.loc[controls, f"pilot_{condition}_correct"].astype(int),
        ):
            raise ValueError(f"{condition} correctness is not derivable")
        if not np.array_equal(
            expected_intrusion,
            results.loc[
                controls, f"pilot_{condition}_probe_intrusion"
            ].astype(int),
        ):
            raise ValueError(f"{condition} probe intrusion is not derivable")
        numeric = results.loc[
            controls,
            [
                f"pilot_{condition}_nll",
                f"pilot_{condition}_p_target",
                f"pilot_{condition}_p_probe_distractor",
            ],
        ].to_numpy(dtype=float)
        if not np.isfinite(numeric).all():
            raise ValueError(f"{condition} contains a non-finite metric")
        if (numeric[:, 0] < 0).any() or (
            (numeric[:, 1:] < 0) | (numeric[:, 1:] > 1)
        ).any():
            raise ValueError(
                f"{condition} contains an invalid NLL/probability"
            )
        if results.loc[
            ~controls, f"pilot_{condition}_pred_label"
        ].notna().any():
            raise ValueError(f"{condition} was evaluated outside control subset")


def _paired_summary(
    values: np.ndarray,
    speakers: np.ndarray,
    seed: int,
    repetitions: int,
) -> dict:
    low, high = _cluster_bootstrap_ci(
        values, speakers, seed, repetitions
    )
    return {
        "mean": float(np.mean(values)),
        "target_speaker_cluster_bootstrap_95ci": [low, high],
    }


def recompute_pilot4_eval(
    results: pd.DataFrame,
    bank: pd.DataFrame,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_repetitions: int = BOOTSTRAP_REPETITIONS,
) -> dict:
    validate_results_against_bank(results, bank)
    results = results.sort_values("trial_id").reset_index(drop=True)
    bank = bank.sort_values("trial_id").reset_index(drop=True)
    speakers = results["target_speaker"].astype(str).to_numpy()
    mixed = results["scene_kind"].astype(str).to_numpy() == "mixed"
    clean = ~mixed
    controls = results["control_subset"].astype(int).to_numpy() == 1
    ce_improvement = (
        results["stage0_nll"].astype(float).to_numpy()
        - results["pilot_nll"].astype(float).to_numpy()
    )
    accuracy_improvement = (
        results["pilot_correct"].astype(float).to_numpy()
        - results["stage0_correct"].astype(float).to_numpy()
    )
    overall_ce = _paired_summary(
        ce_improvement, speakers, bootstrap_seed, bootstrap_repetitions
    )
    mixed_ce = _paired_summary(
        ce_improvement[mixed],
        speakers[mixed],
        bootstrap_seed + 1,
        bootstrap_repetitions,
    )
    overall_accuracy = _paired_summary(
        accuracy_improvement,
        speakers,
        bootstrap_seed + 2,
        bootstrap_repetitions,
    )
    mixed_accuracy = _paired_summary(
        accuracy_improvement[mixed],
        speakers[mixed],
        bootstrap_seed + 3,
        bootstrap_repetitions,
    )
    clean_accuracy_values = results.loc[clean, "pilot_correct"].to_numpy(
        dtype=float
    )
    clean_low, clean_high = _cluster_bootstrap_ci(
        clean_accuracy_values,
        speakers[clean],
        bootstrap_seed + 4,
        bootstrap_repetitions,
    )
    correct = results.loc[controls, "pilot_correct"].to_numpy(dtype=float)
    cue_comparisons = {}
    for offset, condition in enumerate(("shuffled", "silent")):
        comparison = correct - results.loc[
            controls, f"pilot_{condition}_correct"
        ].to_numpy(dtype=float)
        cue_comparisons[f"correct_minus_{condition}"] = _paired_summary(
            comparison,
            speakers[controls],
            bootstrap_seed + 10 + offset,
            bootstrap_repetitions,
        )
    correct_accuracy = float(correct.mean())
    shuffled_accuracy = float(
        results.loc[controls, "pilot_shuffled_correct"].mean()
    )
    silent_accuracy = float(
        results.loc[controls, "pilot_silent_correct"].mean()
    )
    cue_advantage = correct_accuracy - max(
        shuffled_accuracy, silent_accuracy
    )
    cue_ci_lower_min = min(
        cue_comparisons[name]["target_speaker_cluster_bootstrap_95ci"][0]
        for name in cue_comparisons
    )
    distractor_probability_delta = (
        results.loc[controls, "pilot_distractor_p_probe_distractor"].to_numpy(
            dtype=float
        )
        - results.loc[controls, "pilot_p_probe_distractor"].to_numpy(
            dtype=float
        )
    )
    distractor_effect = _paired_summary(
        distractor_probability_delta,
        speakers[controls],
        bootstrap_seed + 20,
        bootstrap_repetitions,
    )
    same_gender_sensitivity: dict[str, object] = {"status": "UNAVAILABLE"}
    if "shuffled_cue_gender" in bank.columns:
        control_bank = bank.loc[controls].reset_index(drop=True)
        same_gender = (
            control_bank["shuffled_cue_gender"].astype(str).to_numpy()
            == results.loc[controls, "target_gender"].astype(str).to_numpy()
        )
        same_gender_sensitivity = {"status": "REPORTED_NON_GATING"}
        for offset, (name, mask) in enumerate(
            (("same_gender", same_gender), ("different_gender", ~same_gender))
        ):
            if not bool(mask.any()):
                same_gender_sensitivity[name] = {"trials": 0}
                continue
            values = correct[mask] - results.loc[
                controls, "pilot_shuffled_correct"
            ].to_numpy(dtype=float)[mask]
            same_gender_sensitivity[name] = {
                "trials": int(mask.sum()),
                **_paired_summary(
                    values,
                    speakers[controls][mask],
                    bootstrap_seed + 30 + offset,
                    bootstrap_repetitions,
                ),
            }

    def point_metrics(mask: np.ndarray) -> dict:
        return {
            "trials": int(mask.sum()),
            "stage0_accuracy": float(
                results.loc[mask, "stage0_correct"].mean()
            ),
            "pilot_accuracy": float(
                results.loc[mask, "pilot_correct"].mean()
            ),
            "stage0_cross_entropy": float(
                results.loc[mask, "stage0_nll"].mean()
            ),
            "pilot_cross_entropy": float(
                results.loc[mask, "pilot_nll"].mean()
            ),
        }

    strata: dict[str, object] = {
        "overall": point_metrics(np.ones(len(results), dtype=bool)),
        "mixed": point_metrics(mixed),
        "clean": point_metrics(clean),
        "by_distractor_count": {},
        "by_snr_bin": {},
        "by_distractor_count_and_snr_bin": {},
        "by_target_gender": {},
    }
    for count in range(1, 5):
        mask = mixed & (
            results["distractor_count"].astype(int).to_numpy() == count
        )
        strata["by_distractor_count"][str(count)] = point_metrics(mask)
    for bin_index in range(5):
        mask = mixed & (results["snr_bin"].astype(int).to_numpy() == bin_index)
        strata["by_snr_bin"][str(bin_index)] = point_metrics(mask)
    for count in range(1, 5):
        for bin_index in range(5):
            mask = (
                mixed
                & (results["distractor_count"].astype(int).to_numpy() == count)
                & (results["snr_bin"].astype(int).to_numpy() == bin_index)
            )
            key = f"n{count}_snrbin{bin_index}"
            strata["by_distractor_count_and_snr_bin"][key] = point_metrics(mask)
    for gender in ("female", "male"):
        mask = results["target_gender"].astype(str).to_numpy() == gender
        strata["by_target_gender"][gender] = point_metrics(mask)

    gates = {
        "overall_ce_improvement_ci_lower_gt_zero": overall_ce[
            "target_speaker_cluster_bootstrap_95ci"
        ][0]
        > 0,
        "mixed_ce_improvement_ci_lower_gt_zero": mixed_ce[
            "target_speaker_cluster_bootstrap_95ci"
        ][0]
        > 0,
        "overall_accuracy_improvement_ci_lower_gt_zero": overall_accuracy[
            "target_speaker_cluster_bootstrap_95ci"
        ][0]
        > 0,
        "mixed_accuracy_improvement_ci_lower_gt_zero": mixed_accuracy[
            "target_speaker_cluster_bootstrap_95ci"
        ][0]
        > 0,
        "clean_accuracy_ci_lower_gt_chance": clean_low > CHANCE_ACCURACY,
        "cue_correct_minus_max_control_ge_0_05": cue_advantage >= 0.05,
        "cue_pairwise_ci_lower_min_gt_zero": cue_ci_lower_min > 0,
    }
    decision = "GO" if all(gates.values()) else "INCONCLUSIVE"
    return {
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "engineering_status": "PASS",
        "decision": decision,
        "bootstrap": {
            "unit": "target_speaker",
            "seed": int(bootstrap_seed),
            "repetitions": int(bootstrap_repetitions),
        },
        "thresholds": {
            "chance_accuracy": CHANCE_ACCURACY,
            "minimum_cue_advantage": 0.05,
        },
        "gates": gates,
        "paired_improvements": {
            "overall_cross_entropy": overall_ce,
            "mixed_cross_entropy": mixed_ce,
            "overall_accuracy": overall_accuracy,
            "mixed_accuracy": mixed_accuracy,
        },
        "clean_final_accuracy": {
            "mean": float(clean_accuracy_values.mean()),
            "target_speaker_cluster_bootstrap_95ci": [
                clean_low,
                clean_high,
            ],
        },
        "cue_controls": {
            "trials": int(controls.sum()),
            "correct_accuracy": correct_accuracy,
            "shuffled_accuracy": shuffled_accuracy,
            "silent_accuracy": silent_accuracy,
            "correct_minus_max_shuffled_silent": cue_advantage,
            "pairwise": cue_comparisons,
            "pairwise_ci_lower_min": cue_ci_lower_min,
            "distractor_cue_p_probe_delta": distractor_effect,
            "shuffled_cue_gender_sensitivity": same_gender_sensitivity,
        },
        "strata": strata,
    }


def _atomic_json(path: pathlib.Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation summary: {path}")
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
        json.dump(
            value, handle, indent=2, sort_keys=True, allow_nan=False
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def evaluate(args: argparse.Namespace) -> dict:
    import torch
    import yaml

    from selftrain.data.diotic_attention import WaveformCache

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
    if args.output.exists() or args.summary.exists():
        raise FileExistsError("Refusing to overwrite full-pilot evaluation")

    config_sha = sha256_file(args.config)
    if config_sha != args.expected_config_sha256:
        raise ValueError("Frozen full config SHA mismatch")
    source_manifest_sha = sha256_file(args.source_manifest)
    if source_manifest_sha != args.expected_source_manifest_sha256:
        raise ValueError("Frozen source manifest file SHA mismatch")
    source_manifest = json.loads(
        args.source_manifest.read_text(encoding="utf-8")
    )
    source_semantic_sha = source_manifest["semantic_combined_sha256"]
    if source_semantic_sha != args.expected_source_semantic_sha256:
        raise ValueError("Frozen source semantic SHA mismatch")
    evaluator_sha = sha256_file(pathlib.Path(__file__).resolve())
    with args.config.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    stage0_frozen = validate_checkpoint(
        args.stage0_checkpoint,
        args.expected_stage0_sha256,
        args.run_id,
        source_semantic_sha,
        config_sha,
        expected_global_step=0,
        expected_completed_epochs=0,
    )
    pilot_frozen = validate_checkpoint(
        args.pilot_checkpoint,
        args.expected_pilot_sha256,
        args.run_id,
        source_semantic_sha,
        config_sha,
        expected_global_step=6944,
        expected_completed_epochs=4,
    )
    validate_bank_artifacts(
        args.bank,
        args.config,
        args.project_root,
        args.expected_bank_seed,
    )
    bank_sha = sha256_file(args.bank)
    if bank_sha != args.expected_bank_sha256:
        raise ValueError("Frozen pilot bank SHA mismatch")
    validate_bank_freeze_state(
        args.bank_freeze_state,
        args.bank,
        bank_sha,
        config_sha,
        source_semantic_sha,
        evaluator_sha,
    )
    bank = pd.read_csv(args.bank, sep="\t", dtype=ROLE_SPEAKER_DTYPES)
    clips_dir = pathlib.Path(
        os.environ.get("CV_CLIPS", config["corpus"]["clips_dir"])
    ).expanduser().resolve()
    if not clips_dir.is_dir():
        raise FileNotFoundError(f"CV clips directory is missing: {clips_dir}")

    base = bank[
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
            "distractor_1_label",
        ]
    ].copy()
    base = base.rename(
        columns={"distractor_1_label": "probe_distractor_label"}
    )
    base.loc[base["scene_kind"] == "clean", "probe_distractor_label"] = 0
    for name in ("stage0", "pilot"):
        for metric in ("pred_label", "correct", "nll", "p_target"):
            base[f"{name}_{metric}"] = np.nan
    base["pilot_p_probe_distractor"] = np.nan
    for condition in CONTROL_CONDITIONS:
        for metric in (
            "pred_label",
            "correct",
            "nll",
            "p_target",
            "probe_intrusion",
            "p_probe_distractor",
        ):
            base[f"pilot_{condition}_{metric}"] = np.nan
    base["scene_sha256"] = ""
    cache = WaveformCache(max_items=args.cache_items)
    snr_errors: list[float] = []

    def run_checkpoint(prefix: str, checkpoint_path: pathlib.Path) -> None:
        model = _load_model(checkpoint_path, config, device)
        versions = tuple(parameter._version for parameter in model.parameters())
        try:
            for start in range(0, len(bank), args.batch_size):
                stop = min(start + args.batch_size, len(bank))
                batch = bank.iloc[start:stop]
                raw_scene = _raw_scene_batch(
                    batch, cache, clips_dir, snr_errors=snr_errors
                )
                raw_correct = _correct_cue_batch(batch, cache, clips_dir)
                labels = torch.as_tensor(
                    batch["target_label"].to_numpy(dtype=np.int64),
                    dtype=torch.long,
                )
                probes = torch.as_tensor(
                    np.where(
                        batch["scene_kind"].astype(str).to_numpy() == "mixed",
                        batch["distractor_1_label"].to_numpy(dtype=np.int64),
                        0,
                    ),
                    dtype=torch.long,
                )
                prediction = _predict(
                    model, raw_scene, raw_correct, labels, probes, device
                )
                positions = np.arange(start, stop)
                predicted = prediction["pred_label"].astype(int)
                base.loc[positions, f"{prefix}_pred_label"] = predicted
                base.loc[positions, f"{prefix}_correct"] = (
                    predicted == labels.numpy()
                ).astype(int)
                base.loc[positions, f"{prefix}_nll"] = prediction["nll"]
                base.loc[positions, f"{prefix}_p_target"] = prediction[
                    "p_target"
                ]
                if prefix == "stage0":
                    base.loc[positions, "scene_sha256"] = _scene_hashes(raw_scene)
                else:
                    current_hashes = np.asarray(_scene_hashes(raw_scene))
                    recorded = base.loc[positions, "scene_sha256"].to_numpy()
                    if not np.array_equal(current_hashes, recorded):
                        raise RuntimeError("Stage0/pilot scenes are not byte-identical")
                    base.loc[positions, "pilot_p_probe_distractor"] = prediction[
                        "p_probe_distractor"
                    ]
                    selected = batch["control_subset"].astype(int).to_numpy() == 1
                    if selected.any():
                        control_batch = batch.iloc[np.flatnonzero(selected)]
                        control_scene = raw_scene[selected]
                        control_labels = labels[selected]
                        control_probes = probes[selected]
                        cues = {
                            "shuffled": _role_batch(
                                control_batch,
                                "shuffled_cue",
                                cache,
                                clips_dir,
                            ),
                            "silent": torch.zeros_like(raw_correct[selected]),
                            "distractor": _role_batch(
                                control_batch,
                                "probe_distractor_cue",
                                cache,
                                clips_dir,
                            ),
                        }
                        control_positions = positions[selected]
                        for condition, cue in cues.items():
                            values = _predict(
                                model,
                                control_scene,
                                cue,
                                control_labels,
                                control_probes,
                                device,
                            )
                            pred = values["pred_label"].astype(int)
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_pred_label",
                            ] = pred
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_correct",
                            ] = (pred == control_labels.numpy()).astype(int)
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_nll",
                            ] = values["nll"]
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_p_target",
                            ] = values["p_target"]
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_probe_intrusion",
                            ] = (pred == control_probes.numpy()).astype(int)
                            base.loc[
                                control_positions,
                                f"pilot_{condition}_p_probe_distractor",
                            ] = values["p_probe_distractor"]
                print(
                    f"Full pilot {prefix}: {stop}/{len(bank)}",
                    flush=True,
                )
        finally:
            if versions != tuple(parameter._version for parameter in model.parameters()):
                raise RuntimeError("Model parameters changed during inference")
            del model
            if device.type == "cuda":
                torch.cuda.empty_cache()

    run_checkpoint("stage0", args.stage0_checkpoint)
    run_checkpoint("pilot", args.pilot_checkpoint)
    base["stage0_pred_label"] = base["stage0_pred_label"].astype(int)
    base["stage0_correct"] = base["stage0_correct"].astype(int)
    base["pilot_pred_label"] = base["pilot_pred_label"].astype(int)
    base["pilot_correct"] = base["pilot_correct"].astype(int)
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    if partial.exists():
        raise FileExistsError(f"Stale partial evaluation exists: {partial}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    base.to_csv(partial, index=False)
    check = pd.read_csv(partial, dtype={"target_speaker": str})
    validate_results_against_bank(check, bank)
    os.replace(partial, args.output)
    results = pd.read_csv(args.output, dtype={"target_speaker": str})
    summary = recompute_pilot4_eval(results, bank)
    summary["run_id"] = args.run_id
    summary["frozen_inputs"] = {
        "bank_sha256": bank_sha,
        "results_sha256": sha256_file(args.output),
        "evaluator_sha256": evaluator_sha,
        "bank_freeze_state_sha256": sha256_file(args.bank_freeze_state),
        "config_sha256": config_sha,
        "source_manifest_file_sha256": source_manifest_sha,
        "source_semantic_sha256": source_semantic_sha,
        "stage0_checkpoint": stage0_frozen,
        "pilot_checkpoint": pilot_frozen,
    }
    summary["runtime"] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "batch_size": int(args.batch_size),
        "seed": int(args.seed),
        "max_abs_measured_snr_error_db": (
            max(snr_errors) if snr_errors else 0.0
        ),
    }
    _atomic_json(args.summary, summary)
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    print(f"PILOT4_EVAL: {summary['decision']}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--project-root", required=True, type=pathlib.Path)
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--source-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--bank", required=True, type=pathlib.Path)
    parser.add_argument("--bank-freeze-state", required=True, type=pathlib.Path)
    parser.add_argument("--stage0-checkpoint", required=True, type=pathlib.Path)
    parser.add_argument("--pilot-checkpoint", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--summary", required=True, type=pathlib.Path)
    parser.add_argument("--expected-bank-sha256", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--expected-source-semantic-sha256", required=True)
    parser.add_argument("--expected-stage0-sha256", required=True)
    parser.add_argument("--expected-pilot-sha256", required=True)
    parser.add_argument(
        "--expected-bank-seed", type=int, default=DEFAULT_BANK_SEED
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--cache-items", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20260816)
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()
    for name in (
        "project_root",
        "config",
        "source_manifest",
        "bank",
        "bank_freeze_state",
        "stage0_checkpoint",
        "pilot_checkpoint",
        "output",
        "summary",
    ):
        setattr(args, name, getattr(args, name).expanduser().resolve())
    if args.batch_size <= 0 or args.cache_items <= 0:
        raise SystemExit("batch-size and cache-items must be positive")
    evaluate(args)


if __name__ == "__main__":
    main()
