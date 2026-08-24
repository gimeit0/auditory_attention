"""
Dynamic diotic speech-mixture dataset for training from scratch.

The anchor catalog stores one row per aligned in-vocabulary word.  This dataset
uses those rows to construct batches online:

  cue        = same speaker, different recording and anchor word
  target     = 2.5-second crop centred on the labelled target word
  background = sum of 1..N crops from different distractor speakers

All returned waveforms are diotic (left == right).  Target/background SNR and
final RMS normalization remain in BinauralAttentionModule's audio transforms.
"""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
import torch
import torchaudio

from selftrain.data.anchor_index import cue_eligible_target_mask


SAMPLE_RATE = 44_100
CROP_SECONDS = 2.5
CROP_SAMPLES = int(SAMPLE_RATE * CROP_SECONDS)
HALF_CROP = CROP_SAMPLES // 2


class WaveformCache:
    """Small per-process LRU cache for decoded, resampled mono waveforms."""

    def __init__(self, max_items: int = 128):
        self.max_items = max_items
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()

    def get(self, path: Path) -> np.ndarray:
        key = path.as_posix()
        if key in self._items:
            waveform = self._items.pop(key)
            self._items[key] = waveform
            return waveform

        waveform, sample_rate = sf.read(path, dtype="float32")
        if waveform.ndim == 2:
            waveform = waveform.mean(axis=1)
        if sample_rate != SAMPLE_RATE:
            tensor = torch.from_numpy(waveform).unsqueeze(0)
            waveform = (
                torchaudio.functional.resample(
                    tensor, sample_rate, SAMPLE_RATE
                )
                .squeeze(0)
                .numpy()
            )
        waveform = np.asarray(waveform, dtype=np.float32)
        self._items[key] = waveform
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return waveform


def crop_centered(waveform: np.ndarray, center_s: float) -> np.ndarray:
    center = int(round(float(center_s) * SAMPLE_RATE))
    start = center - HALF_CROP
    end = start + CROP_SAMPLES
    if start < 0 or end > len(waveform):
        raise ValueError(
            f"2.5-second crop is out of bounds: center={center_s}, "
            f"duration={len(waveform) / SAMPLE_RATE:.3f}"
        )
    return np.array(waveform[start:end], dtype=np.float32, copy=True)


def rms(waveform: np.ndarray) -> float:
    demeaned = waveform - waveform.mean()
    return float(np.sqrt(np.mean(np.square(demeaned))) + 1e-12)


def sum_equal_rms(sources: list[np.ndarray]) -> np.ndarray:
    if not sources:
        return np.zeros(CROP_SAMPLES, dtype=np.float32)
    reference_rms = rms(sources[0])
    aligned = [
        source * (reference_rms / rms(source))
        for source in sources
    ]
    return np.sum(aligned, axis=0, dtype=np.float32)


class DioticAttentionDataset(torch.utils.data.Dataset):
    """
    Return internally batched (cue, target, background, label) arrays.

    The existing Lightning module expects one DataLoader item to already contain
    its full training batch, so ``batch_size`` is handled inside this dataset.
    """

    def __init__(
        self,
        root=None,
        cue_type="voice",
        task="word",
        batch_size=1,
        mode="train",
        train_anchor_manifest=(
            "selftrain/artifacts/anchors/train_anchors.tsv.gz"
        ),
        validation_anchor_manifest=(
            "selftrain/artifacts/anchors/validation_anchors.tsv.gz"
        ),
        clips_dir=(
            "/Users/gigi/论文/计划书/"
            "cv-corpus-9.0-2022-04-27/en/clips"
        ),
        examples_per_epoch=2048,
        validation_examples=512,
        min_distractors=1,
        max_distractors=4,
        cue_free_percentage=0.1,
        balance_target_gender=True,
        balance_target_words=True,
        seed=20260721,
        epoch=0,
        cache_items=128,
        **kwargs,
    ):
        if task != "word":
            raise ValueError("DioticAttentionDataset currently supports word task only")
        if cue_type not in {"voice", "diotic"}:
            raise ValueError("cue_type must be 'voice' or 'diotic'")
        if not 0 <= cue_free_percentage <= 1:
            raise ValueError("cue_free_percentage must be between 0 and 1")
        if min_distractors < 1 or max_distractors < min_distractors:
            raise ValueError("Invalid distractor count range")

        self.mode = mode
        self.batch_size = int(batch_size)
        self.examples_per_epoch = int(
            examples_per_epoch if mode == "train" else validation_examples
        )
        self.min_distractors = int(min_distractors)
        self.max_distractors = int(max_distractors)
        self.cue_free_percentage = float(cue_free_percentage)
        self.balance_target_gender = bool(balance_target_gender)
        self.balance_target_words = bool(balance_target_words)
        self.seed = int(seed)
        self.epoch = int(epoch)
        if self.epoch < 0:
            raise ValueError("epoch must be non-negative")
        clips_dir = os.environ.get("CV_CLIPS", clips_dir)
        self.clips_dir = Path(os.path.expanduser(str(clips_dir)))
        self.cache = WaveformCache(max_items=int(cache_items))

        manifest = (
            Path(train_anchor_manifest)
            if mode == "train"
            else Path(validation_anchor_manifest)
        )
        self.anchors = pd.read_csv(
            manifest, sep="\t", dtype={"speaker": str}
        )
        self._validate_anchor_table(self.anchors, manifest)
        self.anchors = self.anchors.reset_index(drop=True)
        target_mask = cue_eligible_target_mask(self.anchors)
        if not target_mask.any():
            raise ValueError(
                f"No rows with a valid target/cue pair in {manifest}"
            )

        self.rows = self.anchors.to_dict("records")
        self.row_by_index = {index: row for index, row in enumerate(self.rows)}
        self.cue_candidates: dict[int, np.ndarray] = {}
        self.all_target_indices = np.flatnonzero(target_mask)

        # Build speaker-local indices once.  The previous implementation made
        # a full-table boolean mask for every target row and every speaker,
        # which is quadratic in the number of anchors and becomes unusable for
        # the full 90k-row catalog.
        speaker_row_indices = {
            str(speaker): group.index.to_numpy(dtype=np.int64, copy=True)
            for speaker, group in self.anchors.groupby(
                "speaker", sort=False
            )
        }
        self.speaker_names = tuple(speaker_row_indices)
        self.speaker_row_indices = tuple(
            speaker_row_indices[speaker]
            for speaker in self.speaker_names
        )
        self.speaker_position_by_name = {
            speaker: position
            for position, speaker in enumerate(self.speaker_names)
        }
        if len(self.speaker_names) <= self.max_distractors:
            raise ValueError(
                "Not enough distinct speakers for the requested distractors"
            )

        for target_index in self.all_target_indices:
            target = self.row_by_index[int(target_index)]
            same_speaker_indices = speaker_row_indices[
                str(target["speaker"])
            ]
            same_speaker_rows = self.anchors.iloc[same_speaker_indices]
            cue_mask = (
                (same_speaker_rows["path"].to_numpy() != target["path"])
                & (same_speaker_rows["norm"].to_numpy() != target["norm"])
            )
            self.cue_candidates[int(target_index)] = (
                same_speaker_indices[cue_mask]
            )
            if not len(self.cue_candidates[int(target_index)]):
                raise RuntimeError(
                    "Internal target/cue eligibility index mismatch"
                )

        self.target_indices_by_gender = {
            gender: np.flatnonzero(
                target_mask
                & (self.anchors["gender"] == gender).to_numpy()
            )
            for gender in ("female", "male")
        }
        self.available_genders = [
            gender
            for gender, indices in self.target_indices_by_gender.items()
            if len(indices)
        ]
        self.target_indices_by_gender_label = {}
        for gender in self.available_genders:
            gender_indices = self.target_indices_by_gender[gender]
            labels = self.anchors.iloc[gender_indices]["label"].unique()
            self.target_indices_by_gender_label[gender] = {
                int(label): gender_indices[
                    self.anchors.iloc[gender_indices]["label"].to_numpy()
                    == label
                ]
                for label in labels
            }
    @staticmethod
    def _validate_anchor_table(anchors: pd.DataFrame, manifest: Path) -> None:
        required = {
            "path",
            "speaker",
            "gender",
            "norm",
            "label",
            "anchor_center_s",
        }
        missing = sorted(required - set(anchors.columns))
        if missing:
            raise ValueError(f"{manifest} is missing columns: {missing}")
        if anchors.empty:
            raise ValueError(f"Anchor manifest is empty: {manifest}")
        if not anchors["gender"].isin(["female", "male"]).all():
            raise ValueError(f"Unexpected gender value in {manifest}")
        if not anchors["label"].between(0, 799).all():
            raise ValueError(f"Label outside [0, 799] in {manifest}")

    def class_map(self):
        import pickle

        with open("./cv_800_word_label_to_int_dict.pkl", "rb") as handle:
            return pickle.load(handle)

    def _rng(self, index: int) -> np.random.Generator:
        if self.mode == "train":
            # Derive every stochastic mixture from stable semantic coordinates,
            # not a worker-process seed. This makes an epoch reproducible after
            # an epoch-end checkpoint is resumed in a new Slurm process.
            seed = np.random.SeedSequence(
                [self.seed, self.epoch, int(index)]
            )
        else:
            seed = np.random.SeedSequence([self.seed, int(index)])
        return np.random.default_rng(seed)

    def _sample_target_index(self, rng: np.random.Generator) -> int:
        if self.balance_target_gender and len(self.available_genders) == 2:
            gender = self.available_genders[int(rng.integers(0, 2))]
            pool = self.target_indices_by_gender[gender]
        else:
            gender = None
            pool = self.all_target_indices
        if self.balance_target_words:
            if gender is not None:
                label_pools = self.target_indices_by_gender_label[gender]
            else:
                labels = self.anchors.iloc[pool]["label"].unique()
                label_pools = {
                    int(label): pool[
                        self.anchors.iloc[pool]["label"].to_numpy() == label
                    ]
                    for label in labels
                }
            label = int(rng.choice(list(label_pools)))
            pool = label_pools[label]
        return int(rng.choice(pool))

    def _load_crop(self, row: dict) -> np.ndarray:
        waveform = self.cache.get(self.clips_dir / row["path"])
        return crop_centered(waveform, row["anchor_center_s"])

    def sample_example(
        self, rng: np.random.Generator
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, dict]:
        target_index = self._sample_target_index(rng)
        target_row = self.row_by_index[target_index]
        cue_index = int(rng.choice(self.cue_candidates[target_index]))
        cue_row = self.row_by_index[cue_index]

        distractor_count = int(
            rng.integers(
                self.min_distractors, self.max_distractors + 1
            )
        )
        target_speaker_position = self.speaker_position_by_name[
            str(target_row["speaker"])
        ]
        # Sample from an integer range with the target speaker removed, then
        # map positions at or above the removed slot back to the full range.
        distractor_speaker_positions = np.asarray(
            rng.choice(
                len(self.speaker_names) - 1,
                size=distractor_count,
                replace=False,
            ),
            dtype=np.int64,
        )
        distractor_speaker_positions += (
            distractor_speaker_positions >= target_speaker_position
        )
        chosen = [
            int(rng.choice(self.speaker_row_indices[int(position)]))
            for position in distractor_speaker_positions
        ]

        target = self._load_crop(target_row)
        cue = self._load_crop(cue_row)
        distractors = [
            self._load_crop(self.row_by_index[index])
            for index in chosen
        ]
        background = sum_equal_rms(distractors)

        cue_free = bool(rng.random() < self.cue_free_percentage)
        if cue_free:
            cue = np.zeros_like(cue)
            background = np.zeros_like(background)

        def diotic(waveform: np.ndarray) -> np.ndarray:
            return np.stack((waveform, waveform), axis=0).astype(
                np.float32, copy=False
            )

        metadata = {
            "target_path": target_row["path"],
            "target_speaker": str(target_row["speaker"]),
            "target_word": target_row["norm"],
            "cue_path": cue_row["path"],
            "cue_speaker": str(cue_row["speaker"]),
            "cue_word": cue_row["norm"],
            "distractor_speakers": [
                str(self.row_by_index[index]["speaker"])
                for index in chosen
            ],
            "distractor_count": distractor_count,
            "cue_free": cue_free,
        }
        return (
            diotic(cue),
            diotic(target),
            diotic(background),
            int(target_row["label"]),
            metadata,
        )

    def __getitem__(self, index: int):
        rng = self._rng(index)
        cues = np.empty(
            (self.batch_size, 2, CROP_SAMPLES), dtype=np.float32
        )
        targets = np.empty_like(cues)
        backgrounds = np.empty_like(cues)
        labels = np.empty(self.batch_size, dtype=np.int64)
        for batch_index in range(self.batch_size):
            cue, target, background, label, _ = self.sample_example(rng)
            cues[batch_index] = cue
            targets[batch_index] = target
            backgrounds[batch_index] = background
            labels[batch_index] = label
        return cues, targets, backgrounds, labels

    def __len__(self) -> int:
        return math.ceil(self.examples_per_epoch / self.batch_size)
