"""
Build resumable forced-alignment anchor catalogs for self-training.

Inputs come from prepare_splits.py.  Each output anchor is a word in
the fixed 800-word vocabulary with enough audio on both sides to support a
2.5-second crop centred on that word.

This script is intentionally incremental.  Every processed clip is appended to
JSONL, including clips with no valid anchor or clips that failed.  Re-running
the same command skips completed paths and adds more clips.
"""

from __future__ import annotations

import argparse
import json
import pickle
import random
from pathlib import Path
from typing import Iterable

import pandas as pd
import torch
import torchaudio

from align_words import (
    DEVICE,
    load_audio_16k,
    normalize_sentence,
    process_clip,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cv-dir",
        type=Path,
        default=Path(
            "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en"
        ),
    )
    parser.add_argument(
        "--train-manifest",
        type=Path,
        default=Path(
            "selftrain/artifacts/splits/train_candidates.tsv.gz"
        ),
    )
    parser.add_argument(
        "--validation-manifest",
        type=Path,
        default=Path(
            "selftrain/artifacts/splits/validation_candidates.tsv.gz"
        ),
    )
    parser.add_argument(
        "--word-table",
        type=Path,
        default=Path("cv_800_word_label_to_int_dict.pkl"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("selftrain/artifacts/anchors"),
    )
    parser.add_argument(
        "--train-max-clips",
        type=int,
        default=24,
        help="New training clips to align in this invocation.",
    )
    parser.add_argument(
        "--validation-max-clips",
        type=int,
        default=12,
        help="New validation clips to align in this invocation.",
    )
    parser.add_argument(
        "--max-clips-per-speaker",
        type=int,
        default=4,
        help="Limit per speaker per invocation to retain speaker diversity.",
    )
    parser.add_argument("--seed", type=int, default=20260721)
    return parser.parse_args()


def transcript_vocab_words(sentence: str, vocabulary: set[str]) -> set[str]:
    normalized, _, _ = normalize_sentence(str(sentence))
    return {item["norm"] for item in normalized if item["norm"] in vocabulary}


def read_processed(jsonl_path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not jsonl_path.exists():
        return records
    with jsonl_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSONL at {jsonl_path}:{line_number}: {error}"
                ) from error
            records[record["path"]] = record
    return records


def alternating_speakers(
    data: pd.DataFrame, rng: random.Random
) -> list[str]:
    speaker_gender = data.groupby("client_id")["gender"].first().to_dict()
    by_gender = {
        gender: [
            speaker
            for speaker, value in speaker_gender.items()
            if value == gender
        ]
        for gender in ("female", "male")
    }
    rng.shuffle(by_gender["female"])
    rng.shuffle(by_gender["male"])
    order: list[str] = []
    for index in range(max(map(len, by_gender.values()), default=0)):
        for gender in ("female", "male"):
            if index < len(by_gender[gender]):
                order.append(by_gender[gender][index])
    return order


def select_new_clips(
    manifest: Path,
    vocabulary: set[str],
    covered_words: set[str],
    processed_paths: set[str],
    limit: int,
    max_per_speaker: int,
    seed: int,
) -> tuple[list[dict], dict]:
    data = pd.read_csv(
        manifest, sep="\t", dtype=str, keep_default_na=False
    )
    required = {"client_id", "path", "sentence", "gender"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"{manifest} is missing columns: {missing}")

    data = data[~data["path"].isin(processed_paths)].copy()
    raw_counts = data["client_id"].value_counts()
    data = data[data["client_id"].isin(raw_counts[raw_counts >= 2].index)]
    data["vocab_words"] = data["sentence"].map(
        lambda sentence: transcript_vocab_words(sentence, vocabulary)
    )
    data = data[data["vocab_words"].map(bool)].copy()
    missing_words = vocabulary - covered_words
    remaining_frequency: dict[str, int] = {}
    for words in data["vocab_words"]:
        for word in words:
            remaining_frequency[word] = remaining_frequency.get(word, 0) + 1

    rng = random.Random(seed)
    rows_by_speaker = {
        speaker: group.to_dict("records")
        for speaker, group in data.groupby("client_id", sort=False)
    }
    selected: list[dict] = []
    for speaker in alternating_speakers(data, rng):
        rows = rows_by_speaker[speaker]
        rng.shuffle(rows)
        # Prioritize uncovered and rare vocabulary while retaining multiple
        # clips per speaker so that valid target/cue pairs can be formed.
        rows.sort(
            key=lambda row: (
                len(row["vocab_words"] & missing_words),
                sum(
                    1.0 / remaining_frequency[word]
                    for word in row["vocab_words"] & missing_words
                ),
                len(row["vocab_words"]),
            ),
            reverse=True,
        )
        selected.extend(rows[:max_per_speaker])
        if len(selected) >= limit:
            selected = selected[:limit]
            break

    summary = {
        "manifest_rows_remaining": int(len(data)),
        "speakers_remaining": int(data["client_id"].nunique()),
        "selected_clips": len(selected),
        "selected_speakers": len(
            {row["client_id"] for row in selected}
        ),
        "covered_words_before_run": len(covered_words),
        "missing_words_before_run": len(missing_words),
    }
    return selected, summary


def append_alignment_records(
    split: str,
    selected: Iterable[dict],
    jsonl_path: Path,
    clips_dir: Path,
    model,
    tokenizer,
    aligner,
    word2ix: dict[str, int],
) -> None:
    selected = list(selected)
    with jsonl_path.open("a", encoding="utf-8") as handle:
        for index, row in enumerate(selected, start=1):
            record = {
                "split": split,
                "path": row["path"],
                "speaker": row["client_id"],
                "gender": row["gender"],
                "sentence": row["sentence"],
            }
            try:
                wav16, duration = load_audio_16k(
                    clips_dir / row["path"]
                )
                words, anchors, unaligned, modified = process_clip(
                    model,
                    tokenizer,
                    aligner,
                    wav16,
                    duration,
                    row["sentence"],
                    word2ix,
                )
                record.update(
                    {
                        "status": "ok",
                        "duration_s": round(duration, 3),
                        "words": words,
                        "anchors": anchors,
                        "unaligned_tokens": unaligned,
                        "modified_tokens": modified,
                    }
                )
            except Exception as error:
                record.update(
                    {
                        "status": "error",
                        "error": f"{type(error).__name__}: {error}",
                        "anchors": [],
                    }
                )
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            print(
                f"  {split}: {index}/{len(selected)} "
                f"{row['path']} anchors={len(record['anchors'])} "
                f"status={record['status']}"
            )


def build_anchor_table(
    split: str,
    records: dict[str, dict],
    word2ix: dict[str, int],
) -> pd.DataFrame:
    rows: list[dict] = []
    for record in records.values():
        if record.get("status") != "ok":
            continue
        for anchor in record.get("anchors", []):
            rows.append(
                {
                    "split": split,
                    "path": record["path"],
                    "speaker": record["speaker"],
                    "gender": record["gender"],
                    "sentence": record["sentence"],
                    "duration_s": record["duration_s"],
                    "word": anchor["word"],
                    "norm": anchor["norm"],
                    "label": int(anchor["label"]),
                    "start_s": anchor["start_s"],
                    "end_s": anchor["end_s"],
                    "anchor_center_s": anchor["anchor_center_s"],
                }
            )

    columns = [
        "split",
        "path",
        "speaker",
        "gender",
        "sentence",
        "duration_s",
        "word",
        "norm",
        "label",
        "start_s",
        "end_s",
        "anchor_center_s",
    ]
    anchors = pd.DataFrame(rows, columns=columns)
    if anchors.empty:
        return anchors

    anchors = anchors.drop_duplicates(
        ["path", "norm", "start_s", "end_s"]
    ).sort_values(["speaker", "path", "start_s"])
    anchors = anchors.reset_index(drop=True)

    expected_labels = anchors["norm"].map(word2ix)
    if expected_labels.isna().any():
        raise RuntimeError("Anchor table contains words outside the vocabulary")
    if not (expected_labels.astype(int) == anchors["label"]).all():
        raise RuntimeError("Anchor word-to-label mapping mismatch")
    if not (anchors["start_s"] >= 1.25).all():
        raise RuntimeError("Anchor violates the 1.25-second leading margin")
    if not (
        anchors["end_s"] + 1.25 <= anchors["duration_s"] + 1e-6
    ).all():
        raise RuntimeError("Anchor violates the 1.25-second trailing margin")
    return anchors


def audit_catalog(
    split: str,
    records: dict[str, dict],
    anchors: pd.DataFrame,
    selection_summary: dict,
) -> dict:
    ok_records = [
        record for record in records.values()
        if record.get("status") == "ok"
    ]
    error_records = [
        record for record in records.values()
        if record.get("status") == "error"
    ]
    if anchors.empty:
        pairable_speakers = 0
    else:
        clip_word_counts = (
            anchors.groupby("speaker")
            .agg(unique_clips=("path", "nunique"), unique_words=("norm", "nunique"))
        )
        pairable_speakers = int(
            (
                (clip_word_counts["unique_clips"] >= 2)
                & (clip_word_counts["unique_words"] >= 2)
            ).sum()
        )
    return {
        "split": split,
        "selection_this_run": selection_summary,
        "processed_clips_total": len(records),
        "successful_clips_total": len(ok_records),
        "error_clips_total": len(error_records),
        "clips_with_anchor": int(
            len({path for path in anchors["path"]})
            if not anchors.empty
            else 0
        ),
        "anchors_total": int(len(anchors)),
        "unique_anchor_words": int(
            anchors["norm"].nunique() if not anchors.empty else 0
        ),
        "anchor_speakers": int(
            anchors["speaker"].nunique() if not anchors.empty else 0
        ),
        "pairable_speakers": pairable_speakers,
        "gender_counts": (
            anchors["gender"].value_counts().sort_index().to_dict()
            if not anchors.empty
            else {}
        ),
    }


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = args.cv_dir / "clips"
    with args.word_table.open("rb") as handle:
        word2ix = pickle.load(handle)
    if len(word2ix) != 800:
        raise ValueError(f"Expected 800 vocabulary words, found {len(word2ix)}")
    vocabulary = set(word2ix)

    split_specs = {
        "train": (args.train_manifest, args.train_max_clips),
        "validation": (
            args.validation_manifest,
            args.validation_max_clips,
        ),
    }
    selections: dict[str, tuple[list[dict], dict]] = {}
    for offset, (split, (manifest, limit)) in enumerate(split_specs.items()):
        jsonl_path = args.out_dir / f"{split}_alignments.jsonl"
        processed = read_processed(jsonl_path)
        existing_anchors = build_anchor_table(split, processed, word2ix)
        if existing_anchors.empty:
            covered_words: set[str] = set()
        else:
            speaker_stats = existing_anchors.groupby("speaker").agg(
                unique_clips=("path", "nunique"),
                unique_words=("norm", "nunique"),
            )
            pairable = set(
                speaker_stats.index[
                    (speaker_stats["unique_clips"] >= 2)
                    & (speaker_stats["unique_words"] >= 2)
                ]
            )
            covered_words = set(
                existing_anchors.loc[
                    existing_anchors["speaker"].isin(pairable), "norm"
                ]
            )
        selections[split] = select_new_clips(
            manifest=manifest,
            vocabulary=vocabulary,
            covered_words=covered_words,
            processed_paths=set(processed),
            limit=limit,
            max_per_speaker=args.max_clips_per_speaker,
            seed=args.seed + offset,
        )

    total_selected = sum(len(items) for items, _ in selections.values())
    if total_selected:
        print(
            "Loading MMS_FA forced-alignment model "
            f"on {DEVICE} ({total_selected} new clips)..."
        )
        bundle = torchaudio.pipelines.MMS_FA
        model = bundle.get_model().to(DEVICE).eval()
        tokenizer = bundle.get_tokenizer()
        aligner = bundle.get_aligner()
        for split, (selected, _) in selections.items():
            append_alignment_records(
                split=split,
                selected=selected,
                jsonl_path=args.out_dir / f"{split}_alignments.jsonl",
                clips_dir=clips_dir,
                model=model,
                tokenizer=tokenizer,
                aligner=aligner,
                word2ix=word2ix,
            )
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    else:
        print("No new clips selected; rebuilding catalogs from existing JSONL.")

    audits = {}
    for split, (_, selection_summary) in selections.items():
        records = read_processed(
            args.out_dir / f"{split}_alignments.jsonl"
        )
        anchors = build_anchor_table(split, records, word2ix)
        anchors.to_csv(
            args.out_dir / f"{split}_anchors.tsv.gz",
            sep="\t",
            index=False,
            compression="gzip",
        )
        audits[split] = audit_catalog(
            split, records, anchors, selection_summary
        )

    train_anchor_speakers = set(
        pd.read_csv(
            args.out_dir / "train_anchors.tsv.gz", sep="\t"
        ).get("speaker", pd.Series(dtype=str)).astype(str)
    )
    validation_anchor_speakers = set(
        pd.read_csv(
            args.out_dir / "validation_anchors.tsv.gz", sep="\t"
        ).get("speaker", pd.Series(dtype=str)).astype(str)
    )
    overlap = train_anchor_speakers & validation_anchor_speakers
    if overlap:
        raise RuntimeError(
            f"Train/validation anchor speakers overlap: {len(overlap)}"
        )

    audit = {
        "vocabulary_size": len(word2ix),
        "device": DEVICE,
        "train_validation_anchor_speaker_overlap": 0,
        "splits": audits,
    }
    audit_path = args.out_dir / "anchor_catalog_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nAnchor catalog build complete")
    for split, summary in audits.items():
        print(
            f"  {split}: processed={summary['processed_clips_total']} "
            f"anchors={summary['anchors_total']} "
            f"words={summary['unique_anchor_words']} "
            f"pairable_speakers={summary['pairable_speakers']}"
        )
    print("  train/validation speaker overlap: 0")
    print(f"  audit: {audit_path}")


if __name__ == "__main__":
    main()
