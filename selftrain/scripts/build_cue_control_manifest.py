"""Build a deterministic, prediction-independent cue-control trial bank.

The bank is intentionally generated before a model is loaded.  Every row fixes
one target, one distractor, a correct target-speaker cue, a constrained shuffled
cue drawn by permuting the complete correct-cue pool, and an independent
distractor-speaker cue.  Evaluation can therefore keep the target+distractor
scene byte-identical while changing only the cue.
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


MANIFEST_VERSION = 2
DEFAULT_BANK_SEED = 20260815

ROLE_COLUMNS = (
    "target",
    "correct_cue",
    "distractor",
    "distractor_cue",
    "shuffled_cue",
)
ROW_FIELDS = (
    "path",
    "speaker",
    "gender",
    "norm",
    "label",
    "anchor_center_s",
)
ROLE_SPEAKER_DTYPES = {
    f"{role}_speaker": str
    for role in ROLE_COLUMNS
}


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_config(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    corpus = config.get("corpus", {})
    if corpus.get("dataset_type") != "diotic_manifest":
        raise ValueError("Cue controls require corpus.dataset_type=diotic_manifest")
    if int(corpus.get("min_distractors", -1)) != 1 or int(
        corpus.get("max_distractors", -1)
    ) != 1:
        raise ValueError("Cue controls require exactly one distractor")
    if float(corpus.get("cue_free_percentage", -1.0)) != 0.0:
        raise ValueError("Cue controls require cue_free_percentage=0.0")
    noise = config.get("noise_kwargs", {})
    if float(noise.get("low_snr", 999.0)) != 0.0 or float(
        noise.get("high_snr", 999.0)
    ) != 0.0:
        raise ValueError("Cue controls require fixed 0 dB SNR")
    if config.get("hparas", {}).get("mask_cues", False):
        raise ValueError("Cue controls require hparas.mask_cues=false")
    return config


def _resolve_from_project(project_root: pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


class AnchorSampler:
    def __init__(self, anchors: pd.DataFrame):
        required = {
            "path",
            "speaker",
            "gender",
            "norm",
            "label",
            "anchor_center_s",
        }
        missing = sorted(required.difference(anchors.columns))
        if missing:
            raise ValueError(f"Anchor manifest is missing columns: {missing}")
        if anchors.empty:
            raise ValueError("Anchor manifest is empty")
        anchors = anchors.copy().reset_index(drop=True)
        anchors["speaker"] = anchors["speaker"].astype(str)
        if not anchors["label"].between(0, 799).all():
            raise ValueError("Anchor label outside [0, 799]")
        self.anchors = anchors
        self.rows = anchors.to_dict("records")

        eligible = cue_eligible_target_mask(anchors)
        self.eligible_indices = np.flatnonzero(eligible).astype(np.int64)
        if not len(self.eligible_indices):
            raise ValueError("No cue-eligible anchors")

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
                raise RuntimeError("Cue eligibility index is internally inconsistent")
            self.cue_candidates[int(index)] = candidates

        self.eligible_by_speaker: dict[str, np.ndarray] = {}
        for speaker in self.rows_by_speaker:
            speaker_indices = self.eligible_indices[
                anchors.iloc[self.eligible_indices]["speaker"].to_numpy()
                == speaker
            ]
            if len(speaker_indices):
                self.eligible_by_speaker[speaker] = speaker_indices
        self.eligible_speakers = tuple(self.eligible_by_speaker)
        if len(self.eligible_speakers) < 3:
            raise ValueError("At least three cue-eligible speakers are required")

        self.target_by_gender_label: dict[str, dict[int, np.ndarray]] = {}
        eligible_rows = anchors.iloc[self.eligible_indices]
        for gender in ("female", "male"):
            gender_indices = self.eligible_indices[
                eligible_rows["gender"].to_numpy() == gender
            ]
            if not len(gender_indices):
                continue
            labels = anchors.iloc[gender_indices]["label"].unique()
            self.target_by_gender_label[gender] = {
                int(label): gender_indices[
                    anchors.iloc[gender_indices]["label"].to_numpy() == label
                ]
                for label in labels
            }
        self.genders = tuple(self.target_by_gender_label)
        if not self.genders:
            raise ValueError("No eligible target genders")

    @staticmethod
    def _pick(rng: np.random.Generator, values) -> object:
        if not len(values):
            raise ValueError("Cannot sample from an empty collection")
        return values[int(rng.integers(0, len(values)))]

    def sample_target(self, rng: np.random.Generator) -> int:
        gender = str(self._pick(rng, self.genders))
        pools = self.target_by_gender_label[gender]
        label = int(self._pick(rng, tuple(pools)))
        return int(self._pick(rng, pools[label]))

    def sample_other_speaker(
        self,
        rng: np.random.Generator,
        excluded: set[str],
    ) -> str:
        candidates = [s for s in self.eligible_speakers if s not in excluded]
        return str(self._pick(rng, candidates))

    def sample_source_and_cue(
        self,
        rng: np.random.Generator,
        speaker: str,
        forbidden_source_words: set[str] | None = None,
        forbidden_cue_words: set[str] | None = None,
    ) -> tuple[int, int]:
        sources = np.array(self.eligible_by_speaker[speaker], copy=True)
        order = rng.permutation(len(sources))
        forbidden_sources = forbidden_source_words or set()
        forbidden = forbidden_cue_words or set()
        for position in order:
            source_index = int(sources[int(position)])
            if str(self.rows[source_index]["norm"]) in forbidden_sources:
                continue
            cues = np.array(self.cue_candidates[source_index], copy=True)
            cue_order = rng.permutation(len(cues))
            for cue_position in cue_order:
                cue_index = int(cues[int(cue_position)])
                if str(self.rows[cue_index]["norm"]) not in forbidden:
                    return source_index, cue_index
        raise ValueError(
            f"Speaker {speaker!r} has no cue outside forbidden words {forbidden}"
        )

    def serialize_role(self, output: dict, role: str, index: int) -> None:
        row = self.rows[index]
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


def validate_bank(frame: pd.DataFrame, expected_trials: int | None = None) -> dict:
    required = {
        "manifest_version",
        "trial_id",
        "bank_seed",
        "shuffled_source_trial_id",
    }
    for role in ROLE_COLUMNS:
        required.add(f"{role}_index")
        required.update(f"{role}_{field}" for field in ROW_FIELDS)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Cue-control bank is missing columns: {missing}")
    if frame.empty:
        raise ValueError("Cue-control bank is empty")
    if expected_trials is not None and len(frame) != expected_trials:
        raise ValueError(
            f"Expected {expected_trials} trials, found {len(frame)}"
        )
    if frame["trial_id"].duplicated().any():
        raise ValueError("Cue-control trial_id values are not unique")
    if sorted(frame["trial_id"].astype(int).tolist()) != list(range(len(frame))):
        raise ValueError("Cue-control trial_id values must be contiguous from zero")
    if set(frame["manifest_version"].astype(int)) != {MANIFEST_VERSION}:
        raise ValueError("Unexpected cue-control manifest version")

    def _require(mask, message):
        if not bool(np.asarray(mask).all()):
            bad = np.flatnonzero(~np.asarray(mask))[:5].tolist()
            raise ValueError(f"{message}; first bad rows={bad}")

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
    _require(
        frame["correct_cue_norm"] != frame["distractor_norm"],
        "Correct cue word must differ from distractor word",
    )
    _require(
        frame["correct_cue_label"].astype(int)
        != frame["distractor_label"].astype(int),
        "Correct cue label must differ from distractor label",
    )
    _require(
        frame["distractor_speaker"].astype(str)
        != frame["target_speaker"].astype(str),
        "Distractor speaker must differ from target speaker",
    )
    _require(
        frame["distractor_label"].astype(int)
        != frame["target_label"].astype(int),
        "Distractor word/label must differ from target label",
    )
    _require(
        frame["distractor_cue_speaker"].astype(str)
        == frame["distractor_speaker"].astype(str),
        "Distractor cue speaker must equal distractor speaker",
    )
    _require(
        frame["distractor_cue_path"] != frame["distractor_path"],
        "Distractor cue path must differ from distractor path",
    )
    _require(
        frame["distractor_cue_norm"] != frame["distractor_norm"],
        "Distractor cue word must differ from distractor word",
    )
    _require(
        frame["distractor_cue_norm"] != frame["target_norm"],
        "Distractor cue word must differ from target word",
    )
    _require(
        frame["distractor_cue_label"].astype(int)
        != frame["target_label"].astype(int),
        "Distractor cue label must differ from target label",
    )
    shuffled = frame["shuffled_cue_speaker"].astype(str)
    _require(
        shuffled != frame["target_speaker"].astype(str),
        "Shuffled cue speaker must differ from target speaker",
    )
    _require(
        shuffled != frame["distractor_speaker"].astype(str),
        "Shuffled cue speaker must differ from distractor speaker",
    )
    _require(
        frame["shuffled_cue_norm"] != frame["target_norm"],
        "Shuffled cue word must differ from target word",
    )
    _require(
        frame["shuffled_cue_norm"] != frame["distractor_norm"],
        "Shuffled cue word must differ from distractor word",
    )
    _require(
        frame["shuffled_cue_label"].astype(int)
        != frame["target_label"].astype(int),
        "Shuffled cue label must differ from target label",
    )
    _require(
        frame["shuffled_cue_label"].astype(int)
        != frame["distractor_label"].astype(int),
        "Shuffled cue label must differ from distractor label",
    )
    for role in ROLE_COLUMNS:
        labels = frame[f"{role}_label"].astype(int)
        _require(labels.between(0, 799), f"{role} label outside [0, 799]")

    scene_keys = list(
        zip(
            frame["target_index"].astype(int),
            frame["distractor_index"].astype(int),
        )
    )
    if len(scene_keys) != len(set(scene_keys)):
        raise ValueError("Duplicate target+distractor scenes in cue-control bank")

    shuffled_sources = frame["shuffled_source_trial_id"].astype(int)
    _require(
        shuffled_sources.between(0, len(frame) - 1),
        "Shuffled cue source trial is outside the bank",
    )
    _require(
        shuffled_sources.to_numpy() != frame["trial_id"].astype(int).to_numpy(),
        "Shuffled cue must not come from its own trial",
    )
    if sorted(shuffled_sources.tolist()) != sorted(
        frame["trial_id"].astype(int).tolist()
    ):
        raise ValueError("Shuffled cue source trials are not a permutation")
    if sorted(frame["shuffled_cue_index"].astype(int).tolist()) != sorted(
        frame["correct_cue_index"].astype(int).tolist()
    ):
        raise ValueError("Shuffled cue pool does not preserve correct-cue marginals")
    correct_by_trial = dict(
        zip(
            frame["trial_id"].astype(int),
            frame["correct_cue_index"].astype(int),
        )
    )
    expected_shuffled_indices = shuffled_sources.map(correct_by_trial).astype(int)
    _require(
        frame["shuffled_cue_index"].astype(int).to_numpy()
        == expected_shuffled_indices.to_numpy(),
        "Shuffled cue does not match its recorded donor trial",
    )

    return {
        "manifest_version": MANIFEST_VERSION,
        "trials": int(len(frame)),
        "target_speakers": int(frame["target_speaker"].nunique()),
        "distractor_speakers": int(frame["distractor_speaker"].nunique()),
        "target_labels": int(frame["target_label"].nunique()),
        "target_gender_counts": dict(
            Counter(frame.get("target_gender", pd.Series(dtype=str)))
        ),
    }


def _assign_shuffled_cues(
    rows: list[dict],
    sampler: AnchorSampler,
    bank_seed: int,
) -> None:
    """Assign an exact constrained permutation of the correct-cue pool."""

    def allowed(receiver: int, donor: int) -> bool:
        if receiver == donor:
            return False
        cue = sampler.rows[int(rows[donor]["correct_cue_index"])]
        return (
            str(cue["speaker"])
            not in {
                str(rows[receiver]["target_speaker"]),
                str(rows[receiver]["distractor_speaker"]),
            }
            and str(cue["norm"])
            not in {
                str(rows[receiver]["target_norm"]),
                str(rows[receiver]["distractor_norm"]),
            }
        )

    rng = np.random.default_rng(
        np.random.SeedSequence([int(bank_seed), MANIFEST_VERSION, 0x5A17F1ED])
    )
    size = len(rows)
    for _ in range(100):
        permutation = rng.permutation(size)
        for receiver in range(size):
            if allowed(receiver, int(permutation[receiver])):
                continue
            candidates = rng.permutation(size)
            repaired = False
            for other in candidates:
                other = int(other)
                if other == receiver:
                    continue
                donor = int(permutation[receiver])
                other_donor = int(permutation[other])
                if allowed(receiver, other_donor) and allowed(other, donor):
                    permutation[receiver], permutation[other] = other_donor, donor
                    repaired = True
                    break
            if not repaired:
                break
        if all(allowed(i, int(permutation[i])) for i in range(size)):
            for receiver, donor in enumerate(permutation):
                donor = int(donor)
                rows[receiver]["shuffled_source_trial_id"] = donor
                sampler.serialize_role(
                    rows[receiver],
                    "shuffled_cue",
                    int(rows[donor]["correct_cue_index"]),
                )
            return
    raise RuntimeError("Could not construct a constrained shuffled-cue permutation")


def validate_bank_artifacts(
    output_path: pathlib.Path,
    config_path: pathlib.Path,
    project_root: pathlib.Path,
    expected_trials: int,
    expected_bank_seed: int,
) -> dict:
    config = _load_config(config_path)
    anchor_path = _resolve_from_project(
        project_root,
        config["corpus"]["validation_anchor_manifest"],
    )
    anchors = pd.read_csv(anchor_path, sep="\t", dtype={"speaker": str})
    frame = pd.read_csv(output_path, sep="\t", dtype=ROLE_SPEAKER_DTYPES)
    stats = validate_bank(frame, expected_trials=expected_trials)
    if set(frame["bank_seed"].astype(int)) != {int(expected_bank_seed)}:
        raise ValueError("Cue-control bank seed does not match the expected seed")

    for role in ROLE_COLUMNS:
        indices = frame[f"{role}_index"].astype(int).to_numpy()
        if (indices < 0).any() or (indices >= len(anchors)).any():
            raise ValueError(f"{role} anchor index is outside the frozen manifest")
        source = anchors.iloc[indices].reset_index(drop=True)
        for field in ROW_FIELDS:
            bank_values = frame[f"{role}_{field}"]
            source_values = source[field]
            if field == "anchor_center_s":
                equal = np.isclose(
                    bank_values.astype(float),
                    source_values.astype(float),
                    rtol=0.0,
                    atol=1e-9,
                )
            elif field == "label":
                equal = (
                    bank_values.astype(int).to_numpy()
                    == source_values.astype(int).to_numpy()
                )
            else:
                equal = (
                    bank_values.astype(str).to_numpy()
                    == source_values.astype(str).to_numpy()
                )
            if not bool(np.asarray(equal).all()):
                raise ValueError(f"{role}_{field} does not match frozen anchors")

    manifest_sha = sha256_file(output_path)
    sha_path = output_path.with_suffix(output_path.suffix + ".sha256")
    metadata_path = output_path.with_suffix(output_path.suffix + ".json")
    if not sha_path.is_file() or not metadata_path.is_file():
        raise ValueError("Cue-control bank sidecars are missing")
    recorded_sha, recorded_name = sha_path.read_text(encoding="utf-8").split()
    if recorded_sha != manifest_sha or recorded_name != output_path.name:
        raise ValueError("Cue-control bank SHA sidecar is stale")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_metadata = {
        "manifest_version": MANIFEST_VERSION,
        "trials": int(expected_trials),
        "bank_seed": int(expected_bank_seed),
        "manifest_sha256": manifest_sha,
        "config_sha256": sha256_file(config_path),
        "anchor_manifest_sha256": sha256_file(anchor_path),
    }
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected_metadata.items()
        if metadata.get(key) != value
    }
    if mismatches:
        raise ValueError(f"Cue-control bank metadata mismatch: {mismatches}")
    return {**stats, **expected_metadata}


def build_bank(
    config_path: pathlib.Path,
    output_path: pathlib.Path,
    num_trials: int,
    bank_seed: int,
    project_root: pathlib.Path,
) -> dict:
    if num_trials <= 0:
        raise ValueError("num_trials must be positive")
    config = _load_config(config_path)
    manifest_path = _resolve_from_project(
        project_root,
        config["corpus"]["validation_anchor_manifest"],
    )
    anchors = pd.read_csv(manifest_path, sep="\t", dtype={"speaker": str})
    sampler = AnchorSampler(anchors)

    rows: list[dict] = []
    seen_scenes: set[tuple[int, int]] = set()
    for trial_id in range(num_trials):
        for attempt in range(1000):
            rng = np.random.default_rng(
                np.random.SeedSequence(
                    [int(bank_seed), int(trial_id), int(attempt), MANIFEST_VERSION]
                )
            )
            target_index = sampler.sample_target(rng)
            target = sampler.rows[target_index]
            correct_cue_index = int(
                sampler._pick(rng, sampler.cue_candidates[target_index])
            )
            correct_cue = sampler.rows[correct_cue_index]

            distractor_speaker = sampler.sample_other_speaker(
                rng, {str(target["speaker"])}
            )
            try:
                distractor_index, distractor_cue_index = (
                    sampler.sample_source_and_cue(
                        rng,
                        distractor_speaker,
                        forbidden_source_words={str(target["norm"])},
                        forbidden_cue_words={str(target["norm"])},
                    )
                )
            except ValueError:
                continue
            distractor = sampler.rows[distractor_index]
            if (
                str(correct_cue["norm"]) == str(distractor["norm"])
                or int(correct_cue["label"]) == int(distractor["label"])
            ):
                continue
            scene_key = (target_index, distractor_index)
            if scene_key in seen_scenes:
                continue

            row: dict[str, object] = {
                "manifest_version": MANIFEST_VERSION,
                "trial_id": trial_id,
                "bank_seed": int(bank_seed),
                "target_gender": str(target["gender"]),
            }
            sampler.serialize_role(row, "target", target_index)
            sampler.serialize_role(row, "correct_cue", correct_cue_index)
            sampler.serialize_role(row, "distractor", distractor_index)
            sampler.serialize_role(row, "distractor_cue", distractor_cue_index)
            rows.append(row)
            seen_scenes.add(scene_key)
            break
        else:
            raise RuntimeError(f"Could not build unique trial {trial_id}")

    _assign_shuffled_cues(rows, sampler, bank_seed)
    frame = pd.DataFrame(rows)
    stats = validate_bank(frame, expected_trials=num_trials)
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
    try:
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    manifest_sha = sha256_file(output_path)
    sha_path = output_path.with_suffix(output_path.suffix + ".sha256")
    sha_path.write_text(
        f"{manifest_sha}  {output_path.name}\n", encoding="utf-8"
    )
    metadata = {
        **stats,
        "bank_seed": int(bank_seed),
        "config_path": str(config_path.resolve()),
        "config_sha256": sha256_file(config_path),
        "anchor_manifest": str(manifest_path),
        "anchor_manifest_sha256": sha256_file(manifest_path),
        "manifest_path": str(output_path.resolve()),
        "manifest_sha256": manifest_sha,
    }
    output_path.with_suffix(output_path.suffix + ".json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--num-trials", type=int, default=10_000)
    parser.add_argument("--bank-seed", type=int, default=DEFAULT_BANK_SEED)
    parser.add_argument("--project-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    config = args.config.expanduser().resolve()
    project_root = args.project_root.expanduser().resolve()
    if args.validate_only:
        stats = validate_bank_artifacts(
            output_path=output,
            config_path=config,
            project_root=project_root,
            expected_trials=args.num_trials,
            expected_bank_seed=args.bank_seed,
        )
        print(json.dumps(stats, indent=2, sort_keys=True))
        return
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite cue-control bank: {output}")
    metadata = build_bank(
        config_path=config,
        output_path=output,
        num_trials=args.num_trials,
        bank_seed=args.bank_seed,
        project_root=project_root,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
