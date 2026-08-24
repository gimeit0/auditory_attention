"""Build the frozen, prediction-independent full-pilot evaluation bank.

The 10,000 trials are fixed before either checkpoint is loaded:

* 9,000 cued mixtures = 4 distractor counts x 5 equal-width SNR bins x 450;
* every mixture cell has exactly 225 female and 225 male targets;
* 2,000 mixtures (100/cell, 50/gender) form the paired cue-control subset;
* 1,000 target-only/zero-cue trials have 500 targets of each gender.

Every path, crop centre, SNR, distractor and cue donor is written to the TSV.
The shuffled cue is an exact constrained permutation of the correct-cue pool,
so its marginal cue distribution cannot be selected after seeing predictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import tempfile
from collections import Counter

import numpy as np
import pandas as pd
import yaml

from selftrain.data.anchor_index import cue_eligible_target_mask


MANIFEST_VERSION = 1
DEFAULT_BANK_SEED = 20260816
SNR_EDGES = (-10.0, -6.0, -2.0, 2.0, 6.0, 10.0)
DISTRACTOR_COUNTS = (1, 2, 3, 4)
MIXED_PER_CELL = 450
MIXED_PER_CELL_GENDER = 225
CONTROL_PER_CELL_GENDER = 50
MIXED_TRIALS = 9_000
CLEAN_TRIALS = 1_000
TOTAL_TRIALS = 10_000
CONTROL_TRIALS = 2_000
MAX_DISTRACTORS = 4
GENDERS = ("female", "male")
ROW_FIELDS = (
    "path",
    "speaker",
    "gender",
    "norm",
    "label",
    "anchor_center_s",
)
ROLE_NAMES = (
    "target",
    "correct_cue",
    "distractor_1",
    "distractor_2",
    "distractor_3",
    "distractor_4",
    "probe_distractor_cue",
    "shuffled_cue",
)
ROLE_SPEAKER_DTYPES = {
    f"{role}_speaker": str for role in ROLE_NAMES
}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(project_root: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _load_config(path: pathlib.Path) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    corpus = config.get("corpus", {})
    expected = {
        "dataset_type": "diotic_manifest",
        "min_distractors": 1,
        "max_distractors": 4,
        "cue_free_percentage": 0.1,
        "balance_target_gender": True,
        "balance_target_words": True,
    }
    mismatches = {
        key: (corpus.get(key), value)
        for key, value in expected.items()
        if corpus.get(key) != value
    }
    noise = config.get("noise_kwargs", {})
    if float(noise.get("low_snr", 999)) != -10.0:
        mismatches["noise_kwargs.low_snr"] = (
            noise.get("low_snr"),
            -10,
        )
    if float(noise.get("high_snr", 999)) != 10.0:
        mismatches["noise_kwargs.high_snr"] = (
            noise.get("high_snr"),
            10,
        )
    if config.get("hparas", {}).get("mask_cues", False):
        mismatches["hparas.mask_cues"] = (True, False)
    if mismatches:
        raise ValueError(f"Full-pilot evaluation config mismatch: {mismatches}")
    return config


class AnchorSampler:
    """Prediction-independent sampler over the frozen validation anchors."""

    def __init__(self, anchors: pd.DataFrame):
        required = set(ROW_FIELDS)
        missing = sorted(required.difference(anchors.columns))
        if missing or anchors.empty:
            raise ValueError(
                f"Invalid validation anchors: missing={missing}, "
                f"empty={anchors.empty}"
            )
        anchors = anchors.copy().reset_index(drop=True)
        anchors["speaker"] = anchors["speaker"].astype(str)
        if not anchors["gender"].isin(GENDERS).all():
            raise ValueError("Validation anchors contain an unsupported gender")
        if not anchors["label"].between(0, 799).all():
            raise ValueError("Validation anchor label outside [0, 799]")
        self.anchors = anchors
        self.rows = anchors.to_dict("records")
        eligible_mask = cue_eligible_target_mask(anchors)
        self.eligible_indices = np.flatnonzero(eligible_mask).astype(np.int64)
        if not len(self.eligible_indices):
            raise ValueError("Validation anchors contain no cue-eligible target")

        self.rows_by_speaker = {
            str(speaker): group.index.to_numpy(dtype=np.int64, copy=True)
            for speaker, group in anchors.groupby("speaker", sort=False)
        }
        self.cue_candidates: dict[int, np.ndarray] = {}
        for index in self.eligible_indices:
            row = self.rows[int(index)]
            same = self.rows_by_speaker[str(row["speaker"])]
            same_rows = anchors.iloc[same]
            keep = (
                (same_rows["path"].to_numpy() != row["path"])
                & (same_rows["norm"].to_numpy() != row["norm"])
            )
            candidates = same[keep]
            if not len(candidates):
                raise RuntimeError("Cue eligibility index is inconsistent")
            self.cue_candidates[int(index)] = candidates

        self.eligible_by_speaker: dict[str, np.ndarray] = {}
        eligible_speakers = anchors.iloc[self.eligible_indices][
            "speaker"
        ].astype(str).to_numpy()
        for speaker in self.rows_by_speaker:
            indices = self.eligible_indices[eligible_speakers == speaker]
            if len(indices):
                self.eligible_by_speaker[speaker] = indices
        self.eligible_speakers = tuple(self.eligible_by_speaker)
        if len(self.eligible_speakers) < 6:
            raise ValueError("At least six cue-eligible speakers are required")

        self.targets_by_gender_label: dict[str, dict[int, np.ndarray]] = {}
        eligible = anchors.iloc[self.eligible_indices]
        for gender in GENDERS:
            gender_indices = self.eligible_indices[
                eligible["gender"].to_numpy() == gender
            ]
            labels = anchors.iloc[gender_indices]["label"].unique()
            pools = {
                int(label): gender_indices[
                    anchors.iloc[gender_indices]["label"].to_numpy()
                    == label
                ]
                for label in labels
            }
            if not pools:
                raise ValueError(f"No cue-eligible {gender} targets")
            self.targets_by_gender_label[gender] = pools

    @staticmethod
    def pick(rng: np.random.Generator, values):
        if not len(values):
            raise ValueError("Cannot sample an empty collection")
        return values[int(rng.integers(0, len(values)))]

    def target(self, rng: np.random.Generator, gender: str) -> int:
        pools = self.targets_by_gender_label[gender]
        label = int(self.pick(rng, tuple(pools)))
        return int(self.pick(rng, pools[label]))

    def source_and_cue(
        self,
        rng: np.random.Generator,
        speaker: str,
        forbidden_words: set[str],
        forbidden_labels: set[int],
    ) -> tuple[int, int]:
        sources = np.array(self.eligible_by_speaker[speaker], copy=True)
        for source_position in rng.permutation(len(sources)):
            source = int(sources[int(source_position)])
            source_row = self.rows[source]
            if (
                str(source_row["norm"]) in forbidden_words
                or int(source_row["label"]) in forbidden_labels
            ):
                continue
            cues = np.array(self.cue_candidates[source], copy=True)
            for cue_position in rng.permutation(len(cues)):
                cue = int(cues[int(cue_position)])
                cue_row = self.rows[cue]
                if (
                    str(cue_row["norm"]) not in forbidden_words
                    and int(cue_row["label"]) not in forbidden_labels
                ):
                    return source, cue
        raise ValueError(f"No constrained source/cue for speaker {speaker}")

    def serialize(self, output: dict, role: str, index: int) -> None:
        row = self.rows[int(index)]
        output[f"{role}_index"] = int(index)
        for field in ROW_FIELDS:
            value = row[field]
            if field == "label":
                value = int(value)
            elif field == "anchor_center_s":
                value = float(value)
            else:
                value = str(value)
            output[f"{role}_{field}"] = value


def _empty_role(output: dict, role: str) -> None:
    output[f"{role}_index"] = -1
    for field in ROW_FIELDS:
        output[f"{role}_{field}"] = (
            -1 if field == "label" else np.nan if field == "anchor_center_s" else ""
        )


def _sample_mixed(
    sampler: AnchorSampler,
    trial_id: int,
    bank_seed: int,
    distractor_count: int,
    snr_bin: int,
    gender: str,
    control_subset: bool,
    seen_scenes: set[tuple[int, tuple[int, ...]]],
) -> dict:
    for attempt in range(2000):
        rng = np.random.default_rng(
            np.random.SeedSequence(
                [bank_seed, MANIFEST_VERSION, trial_id, attempt]
            )
        )
        target_index = sampler.target(rng, gender)
        target = sampler.rows[target_index]
        correct_cue_index = int(
            sampler.pick(rng, sampler.cue_candidates[target_index])
        )
        correct_cue = sampler.rows[correct_cue_index]
        available = [
            speaker
            for speaker in sampler.eligible_speakers
            if speaker != str(target["speaker"])
        ]
        positions = rng.choice(
            len(available), size=distractor_count, replace=False
        )
        speakers = [available[int(position)] for position in positions]
        distractor_indices: list[int] = []
        distractor_cues: list[int] = []
        forbidden_words = {str(target["norm"])}
        forbidden_labels = {int(target["label"])}
        try:
            for speaker in speakers:
                source, cue = sampler.source_and_cue(
                    rng,
                    speaker,
                    forbidden_words,
                    forbidden_labels,
                )
                distractor_indices.append(source)
                distractor_cues.append(cue)
                source_row = sampler.rows[source]
                forbidden_words.add(str(source_row["norm"]))
                forbidden_labels.add(int(source_row["label"]))
        except ValueError:
            continue
        if (
            str(correct_cue["norm"]) in forbidden_words - {str(target["norm"])}
            or int(correct_cue["label"])
            in forbidden_labels - {int(target["label"])}
        ):
            continue
        # Distractor addition is commutative, so exchanging role positions does
        # not create a new acoustic scene.  Canonicalise the set here and in
        # validation to prevent such pseudo-replicates entering the bank.
        scene_key = (target_index, tuple(sorted(distractor_indices)))
        if scene_key in seen_scenes:
            continue
        low, high = SNR_EDGES[snr_bin : snr_bin + 2]
        snr_db = float(rng.uniform(low, high))
        row: dict[str, object] = {
            "manifest_version": MANIFEST_VERSION,
            "trial_id": trial_id,
            "bank_seed": bank_seed,
            "scene_kind": "mixed",
            "control_subset": int(control_subset),
            "target_gender": gender,
            "distractor_count": distractor_count,
            "snr_bin": snr_bin,
            "snr_bin_low": low,
            "snr_bin_high": high,
            "snr_db": snr_db,
            "probe_distractor_position": 1,
            "shuffled_source_trial_id": -1,
        }
        sampler.serialize(row, "target", target_index)
        sampler.serialize(row, "correct_cue", correct_cue_index)
        for position in range(1, MAX_DISTRACTORS + 1):
            if position <= distractor_count:
                sampler.serialize(
                    row,
                    f"distractor_{position}",
                    distractor_indices[position - 1],
                )
            else:
                _empty_role(row, f"distractor_{position}")
        sampler.serialize(
            row, "probe_distractor_cue", distractor_cues[0]
        )
        _empty_role(row, "shuffled_cue")
        seen_scenes.add(scene_key)
        return row
    raise RuntimeError(f"Could not construct mixed trial {trial_id}")


def _sample_clean(
    sampler: AnchorSampler,
    trial_id: int,
    bank_seed: int,
    gender: str,
) -> dict:
    # The frozen validation catalog has fewer than 500 cue-eligible female
    # anchors.  Sampling with replacement mirrors DioticAttentionDataset and
    # still gives 500 independently specified trials without pretending that
    # more unique speech clips exist than the catalog contains.
    rng = np.random.default_rng(
        np.random.SeedSequence([bank_seed, MANIFEST_VERSION, trial_id])
    )
    target_index = sampler.target(rng, gender)
    cue_index = int(sampler.pick(rng, sampler.cue_candidates[target_index]))
    row: dict[str, object] = {
            "manifest_version": MANIFEST_VERSION,
            "trial_id": trial_id,
            "bank_seed": bank_seed,
            "scene_kind": "clean",
            "control_subset": 0,
            "target_gender": gender,
            "distractor_count": 0,
            "snr_bin": -1,
            "snr_bin_low": np.nan,
            "snr_bin_high": np.nan,
            "snr_db": np.nan,
            "probe_distractor_position": -1,
            "shuffled_source_trial_id": -1,
        }
    sampler.serialize(row, "target", target_index)
    sampler.serialize(row, "correct_cue", cue_index)
    for role in ROLE_NAMES[2:]:
        _empty_role(row, role)
    return row


def _assign_shuffled(rows: list[dict], sampler: AnchorSampler, seed: int) -> None:
    controls = [index for index, row in enumerate(rows) if row["control_subset"]]
    if len(controls) != CONTROL_TRIALS:
        raise RuntimeError("Internal control subset size mismatch")

    def allowed(receiver_index: int, donor_index: int) -> bool:
        if receiver_index == donor_index:
            return False
        receiver = rows[receiver_index]
        donor = rows[donor_index]
        cue = sampler.rows[int(donor["correct_cue_index"])]
        excluded_speakers = {str(receiver["target_speaker"])}
        excluded_words = {str(receiver["target_norm"])}
        excluded_labels = {int(receiver["target_label"])}
        for position in range(1, int(receiver["distractor_count"]) + 1):
            excluded_speakers.add(str(receiver[f"distractor_{position}_speaker"]))
            excluded_words.add(str(receiver[f"distractor_{position}_norm"]))
            excluded_labels.add(int(receiver[f"distractor_{position}_label"]))
        return (
            str(cue["speaker"]) not in excluded_speakers
            and str(cue["norm"]) not in excluded_words
            and int(cue["label"]) not in excluded_labels
        )

    rng = np.random.default_rng(
        np.random.SeedSequence([seed, MANIFEST_VERSION, 0xF011C0DE])
    )
    size = len(controls)
    for _ in range(100):
        permutation = rng.permutation(size)
        for receiver_position in range(size):
            receiver = controls[receiver_position]
            donor = controls[int(permutation[receiver_position])]
            if allowed(receiver, donor):
                continue
            for other_position in rng.permutation(size):
                other_position = int(other_position)
                if other_position == receiver_position:
                    continue
                other = controls[other_position]
                other_donor = controls[int(permutation[other_position])]
                if allowed(receiver, other_donor) and allowed(other, donor):
                    permutation[receiver_position], permutation[other_position] = (
                        permutation[other_position],
                        permutation[receiver_position],
                    )
                    break
            else:
                break
        if all(
            allowed(controls[position], controls[int(permutation[position])])
            for position in range(size)
        ):
            for receiver_position, receiver in enumerate(controls):
                donor = controls[int(permutation[receiver_position])]
                rows[receiver]["shuffled_source_trial_id"] = int(
                    rows[donor]["trial_id"]
                )
                sampler.serialize(
                    rows[receiver],
                    "shuffled_cue",
                    int(rows[donor]["correct_cue_index"]),
                )
            return
    raise RuntimeError("Could not construct constrained shuffled-cue permutation")


def _require(mask, message: str) -> None:
    values = np.asarray(mask)
    if not bool(values.all()):
        bad = np.flatnonzero(~values)[:5].tolist()
        raise ValueError(f"{message}; first bad rows={bad}")


def validate_bank(frame: pd.DataFrame) -> dict:
    required = {
        "manifest_version",
        "trial_id",
        "bank_seed",
        "scene_kind",
        "control_subset",
        "target_gender",
        "distractor_count",
        "snr_bin",
        "snr_bin_low",
        "snr_bin_high",
        "snr_db",
        "shuffled_source_trial_id",
    }
    for role in ROLE_NAMES:
        required.add(f"{role}_index")
        required.update(f"{role}_{field}" for field in ROW_FIELDS)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Pilot bank is missing columns: {missing}")
    if len(frame) != TOTAL_TRIALS:
        raise ValueError(f"Expected {TOTAL_TRIALS} trials, found {len(frame)}")
    if frame["trial_id"].duplicated().any() or sorted(
        frame["trial_id"].astype(int)
    ) != list(range(TOTAL_TRIALS)):
        raise ValueError("trial_id must be unique and contiguous from zero")
    if set(frame["manifest_version"].astype(int)) != {MANIFEST_VERSION}:
        raise ValueError("Unexpected pilot-bank manifest version")
    mixed = frame[frame["scene_kind"] == "mixed"]
    clean = frame[frame["scene_kind"] == "clean"]
    if len(mixed) != MIXED_TRIALS or len(clean) != CLEAN_TRIALS:
        raise ValueError("Pilot bank mixed/clean totals are not 9000/1000")
    counts = mixed.groupby(["distractor_count", "snr_bin"]).size()
    if len(counts) != 20 or set(counts.astype(int)) != {MIXED_PER_CELL}:
        raise ValueError("Every distractor-count/SNR cell must contain 450 trials")
    genders = mixed.groupby(
        ["distractor_count", "snr_bin", "target_gender"]
    ).size()
    if len(genders) != 40 or set(genders.astype(int)) != {
        MIXED_PER_CELL_GENDER
    }:
        raise ValueError("Every mixed cell must contain 225 targets per gender")
    clean_genders = clean.groupby("target_gender").size().to_dict()
    if clean_genders != {"female": 500, "male": 500}:
        raise ValueError("Clean trials must contain 500 targets per gender")
    controls = mixed[mixed["control_subset"].astype(int) == 1]
    control_cells = controls.groupby(["distractor_count", "snr_bin"]).size()
    control_genders = controls.groupby(
        ["distractor_count", "snr_bin", "target_gender"]
    ).size()
    if (
        len(controls) != CONTROL_TRIALS
        or len(control_cells) != 20
        or set(control_cells.astype(int)) != {100}
        or len(control_genders) != 40
        or set(control_genders.astype(int)) != {50}
    ):
        raise ValueError("Cue-control subset is not balanced 100/cell, 50/gender")
    if clean["control_subset"].astype(int).any():
        raise ValueError("Clean trials cannot enter the cue-control subset")
    for bin_index, (low, high) in enumerate(zip(SNR_EDGES[:-1], SNR_EDGES[1:])):
        cell = mixed[mixed["snr_bin"].astype(int) == bin_index]
        _require(
            (cell["snr_db"].astype(float) >= low)
            & (cell["snr_db"].astype(float) < high),
            f"SNR values escaped bin {bin_index}",
        )
    _require(
        frame["correct_cue_speaker"].astype(str)
        == frame["target_speaker"].astype(str),
        "Correct cue speaker must equal target speaker",
    )
    _require(
        frame["correct_cue_path"] != frame["target_path"],
        "Correct cue path must differ from target path",
    )
    _require(
        frame["correct_cue_norm"] != frame["target_norm"],
        "Correct cue word must differ from target word",
    )
    mixed_scene_keys = []
    for row in frame.itertuples(index=False):
        count = int(row.distractor_count)
        distractor_indices = []
        distractor_speakers = []
        for position in range(1, MAX_DISTRACTORS + 1):
            index = int(getattr(row, f"distractor_{position}_index"))
            if position <= count:
                if index < 0:
                    raise ValueError("Active distractor has an empty index")
                distractor_indices.append(index)
                distractor_speakers.append(
                    str(getattr(row, f"distractor_{position}_speaker"))
                )
                if int(getattr(row, f"distractor_{position}_label")) == int(
                    row.target_label
                ):
                    raise ValueError("Distractor label equals target label")
            elif index != -1:
                raise ValueError("Inactive distractor role is not empty")
        if len(set(distractor_speakers)) != count or str(
            row.target_speaker
        ) in distractor_speakers:
            raise ValueError("Scene speakers are not distinct")
        if count:
            mixed_scene_keys.append(
                (int(row.target_index), tuple(sorted(distractor_indices)))
            )
    if len(mixed_scene_keys) != len(set(mixed_scene_keys)):
        raise ValueError("Pilot bank contains a duplicate mixed scene")
    _require(
        controls["probe_distractor_cue_speaker"].astype(str)
        == controls["distractor_1_speaker"].astype(str),
        "Probe distractor cue speaker must match distractor 1",
    )
    _require(
        controls["probe_distractor_cue_path"]
        != controls["distractor_1_path"],
        "Probe distractor cue path must differ from its source",
    )
    _require(
        controls["probe_distractor_cue_norm"]
        != controls["distractor_1_norm"],
        "Probe distractor cue word must differ from its source",
    )
    _require(
        controls["probe_distractor_cue_label"].astype(int)
        != controls["target_label"].astype(int),
        "Probe distractor cue label must differ from target label",
    )
    donors = controls["shuffled_source_trial_id"].astype(int)
    if sorted(donors) != sorted(controls["trial_id"].astype(int)):
        raise ValueError("Shuffled cue donors are not a control-pool permutation")
    _require(
        donors.to_numpy() != controls["trial_id"].astype(int).to_numpy(),
        "A shuffled cue cannot come from its own trial",
    )
    donor_map = dict(
        zip(
            controls["trial_id"].astype(int),
            controls["correct_cue_index"].astype(int),
        )
    )
    expected = donors.map(donor_map).astype(int)
    _require(
        expected.to_numpy() == controls["shuffled_cue_index"].astype(int).to_numpy(),
        "Shuffled cue index does not match its donor trial",
    )
    # Re-derive every exclusion used by the constrained assignment.  Checking
    # only the donor/index permutation would allow a corrupted cue that names a
    # target or distractor already present in the receiving scene.
    for row in controls.itertuples(index=False):
        excluded_speakers = {str(row.target_speaker)}
        excluded_norms = {str(row.target_norm)}
        excluded_labels = {int(row.target_label)}
        for position in range(1, int(row.distractor_count) + 1):
            excluded_speakers.add(
                str(getattr(row, f"distractor_{position}_speaker"))
            )
            excluded_norms.add(
                str(getattr(row, f"distractor_{position}_norm"))
            )
            excluded_labels.add(
                int(getattr(row, f"distractor_{position}_label"))
            )
        if (
            str(row.shuffled_cue_speaker) in excluded_speakers
            or str(row.shuffled_cue_norm) in excluded_norms
            or int(row.shuffled_cue_label) in excluded_labels
        ):
            raise ValueError(
                "Shuffled cue overlaps the receiving target/distractors: "
                f"trial_id={int(row.trial_id)}"
            )
    return {
        "manifest_version": MANIFEST_VERSION,
        "trials": TOTAL_TRIALS,
        "mixed_trials": MIXED_TRIALS,
        "clean_trials": CLEAN_TRIALS,
        "control_trials": CONTROL_TRIALS,
        "target_speakers": int(frame["target_speaker"].nunique()),
        "target_labels": int(frame["target_label"].nunique()),
        "target_gender_counts": dict(Counter(frame["target_gender"])),
    }


def validate_bank_artifacts(
    output_path: pathlib.Path,
    config_path: pathlib.Path,
    project_root: pathlib.Path,
    expected_seed: int,
) -> dict:
    config = _load_config(config_path)
    anchor_path = _resolve(
        project_root, config["corpus"]["validation_anchor_manifest"]
    )
    anchors = pd.read_csv(anchor_path, sep="\t", dtype={"speaker": str})
    frame = pd.read_csv(output_path, sep="\t", dtype=ROLE_SPEAKER_DTYPES)
    stats = validate_bank(frame)
    if set(frame["bank_seed"].astype(int)) != {int(expected_seed)}:
        raise ValueError("Pilot bank seed mismatch")
    for role in ROLE_NAMES:
        active = frame[f"{role}_index"].astype(int) >= 0
        indices = frame.loc[active, f"{role}_index"].astype(int).to_numpy()
        if (indices >= len(anchors)).any():
            raise ValueError(f"{role} index outside validation anchors")
        source = anchors.iloc[indices].reset_index(drop=True)
        bank = frame.loc[active].reset_index(drop=True)
        for field in ROW_FIELDS:
            left = bank[f"{role}_{field}"]
            right = source[field]
            if field == "anchor_center_s":
                equal = np.isclose(
                    left.astype(float), right.astype(float), rtol=0, atol=1e-9
                )
            elif field in {"label"}:
                equal = left.astype(int).to_numpy() == right.astype(int).to_numpy()
            else:
                equal = left.astype(str).to_numpy() == right.astype(str).to_numpy()
            if not bool(np.asarray(equal).all()):
                raise ValueError(f"{role}_{field} differs from frozen anchors")
    manifest_sha = sha256_file(output_path)
    sha_path = output_path.with_suffix(output_path.suffix + ".sha256")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    if (
        not sha_path.is_file()
        or not metadata_path.is_file()
        or sha_path.is_symlink()
        or metadata_path.is_symlink()
    ):
        raise ValueError("Pilot bank sidecars are missing")
    recorded_sha, recorded_name = sha_path.read_text(encoding="utf-8").split()
    if recorded_sha != manifest_sha or recorded_name != output_path.name:
        raise ValueError("Pilot bank SHA sidecar is stale")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "manifest_version": MANIFEST_VERSION,
        "bank_seed": int(expected_seed),
        "manifest_sha256": manifest_sha,
        "config_sha256": sha256_file(config_path),
        "anchor_manifest_sha256": sha256_file(anchor_path),
        "trials": TOTAL_TRIALS,
        "mixed_trials": MIXED_TRIALS,
        "clean_trials": CLEAN_TRIALS,
        "control_trials": CONTROL_TRIALS,
    }
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Pilot bank metadata mismatch: {mismatches}")
    return {**stats, **expected}


def _atomic_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite pilot-bank artifact: {path}")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_bank(
    config_path: pathlib.Path,
    output_path: pathlib.Path,
    bank_seed: int,
    project_root: pathlib.Path,
) -> dict:
    config = _load_config(config_path)
    anchors_path = _resolve(
        project_root, config["corpus"]["validation_anchor_manifest"]
    )
    anchors = pd.read_csv(anchors_path, sep="\t", dtype={"speaker": str})
    sampler = AnchorSampler(anchors)
    rows: list[dict] = []
    seen_scenes: set[tuple[int, tuple[int, ...]]] = set()
    trial_id = 0
    for distractor_count in DISTRACTOR_COUNTS:
        for snr_bin in range(len(SNR_EDGES) - 1):
            for gender in GENDERS:
                for within_gender in range(MIXED_PER_CELL_GENDER):
                    rows.append(
                        _sample_mixed(
                            sampler,
                            trial_id,
                            bank_seed,
                            distractor_count,
                            snr_bin,
                            gender,
                            within_gender < CONTROL_PER_CELL_GENDER,
                            seen_scenes,
                        )
                    )
                    trial_id += 1
    for gender in GENDERS:
        for _ in range(500):
            rows.append(
                _sample_clean(
                    sampler,
                    trial_id,
                    bank_seed,
                    gender,
                )
            )
            trial_id += 1
    _assign_shuffled(rows, sampler, bank_seed)
    frame = pd.DataFrame(rows)
    stats = validate_bank(frame)
    if output_path.exists() or any(
        sidecar.exists()
        for sidecar in (
            output_path.with_suffix(output_path.suffix + ".sha256"),
            output_path.with_suffix(output_path.suffix + ".json"),
        )
    ):
        raise FileExistsError("Refusing to overwrite an existing pilot bank")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        frame.to_csv(handle, sep="\t", index=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output_path)
    manifest_sha = sha256_file(output_path)
    metadata = {
        **stats,
        "bank_seed": int(bank_seed),
        "manifest_sha256": manifest_sha,
        "config_sha256": sha256_file(config_path),
        "anchor_manifest": str(anchors_path),
        "anchor_manifest_sha256": sha256_file(anchors_path),
        "snr_edges": list(SNR_EDGES),
        "mixed_per_cell": MIXED_PER_CELL,
        "mixed_per_cell_gender": MIXED_PER_CELL_GENDER,
        "control_per_cell_gender": CONTROL_PER_CELL_GENDER,
    }
    _atomic_text(
        output_path.with_suffix(output_path.suffix + ".sha256"),
        f"{manifest_sha}  {output_path.name}\n",
    )
    _atomic_text(
        output_path.with_suffix(output_path.suffix + ".json"),
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--project-root", default=".", type=pathlib.Path)
    parser.add_argument("--bank-seed", type=int, default=DEFAULT_BANK_SEED)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    config = args.config.expanduser().resolve()
    output = args.output.expanduser().resolve()
    root = args.project_root.expanduser().resolve()
    if args.validate_only:
        result = validate_bank_artifacts(
            output, config, root, args.bank_seed
        )
    else:
        result = build_bank(config, output, args.bank_seed, root)
        result = validate_bank_artifacts(
            output, config, root, args.bank_seed
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
