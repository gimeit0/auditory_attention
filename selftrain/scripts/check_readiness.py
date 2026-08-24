"""Audit whether anchor catalogs are safe and large enough for formal training."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import pandas as pd

from selftrain.data.anchor_index import cue_eligible_target_mask


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train",
        type=Path,
        default=Path("selftrain/artifacts/anchors/train_anchors.tsv.gz"),
    )
    parser.add_argument(
        "--validation",
        type=Path,
        default=Path(
            "selftrain/artifacts/anchors/validation_anchors.tsv.gz"
        ),
    )
    parser.add_argument(
        "--eval-speakers",
        type=Path,
        default=Path("selftrain/artifacts/splits/eval_speakers.txt"),
    )
    parser.add_argument(
        "--word-table",
        type=Path,
        default=Path("cv_800_word_label_to_int_dict.pkl"),
    )
    parser.add_argument(
        "--require-all-words",
        action="store_true",
        help=(
            "Exit nonzero unless training covers all 800 words and validation "
            "meets --min-validation-words."
        ),
    )
    parser.add_argument(
        "--min-validation-words",
        type=int,
        default=700,
        help=(
            "Minimum pairable validation vocabulary. The cleaned dev split's "
            "transcript-level upper bound is 764/800."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete JSON report, including every missing word.",
    )
    return parser.parse_args()


def pairable_target_rows(anchors: pd.DataFrame) -> pd.DataFrame:
    return anchors.loc[cue_eligible_target_mask(anchors)].copy()


def summarize(anchors: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    target_rows = pairable_target_rows(anchors)
    return (
        {
            "anchor_rows": int(len(anchors)),
            "all_anchor_speakers": int(anchors["speaker"].nunique()),
            "pairable_target_speakers": int(
                target_rows["speaker"].nunique()
            ),
            "target_rows": int(len(target_rows)),
            "target_words": int(target_rows["label"].nunique()),
            "female_target_rows": int(
                (target_rows["gender"] == "female").sum()
            ),
            "male_target_rows": int(
                (target_rows["gender"] == "male").sum()
            ),
        },
        target_rows,
    )


def main() -> None:
    args = parse_args()
    with args.word_table.open("rb") as handle:
        word_to_label = pickle.load(handle)
    if len(word_to_label) != 800:
        raise ValueError(
            f"Expected an 800-word table, found {len(word_to_label)}"
        )

    train = pd.read_csv(args.train, sep="\t", dtype={"speaker": str})
    validation = pd.read_csv(
        args.validation, sep="\t", dtype={"speaker": str}
    )
    train_summary, train_targets = summarize(train)
    validation_summary, validation_targets = summarize(validation)

    train_speakers = set(train["speaker"])
    validation_speakers = set(validation["speaker"])
    eval_speakers = {
        line.strip()
        for line in args.eval_speakers.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    overlaps = {
        "train_validation": len(train_speakers & validation_speakers),
        "train_eval": len(train_speakers & eval_speakers),
        "validation_eval": len(validation_speakers & eval_speakers),
    }
    if any(overlaps.values()):
        raise RuntimeError(f"Speaker leakage detected: {overlaps}")

    expected_labels = set(map(int, word_to_label.values()))
    train_labels = set(map(int, train_targets["label"]))
    validation_labels = set(map(int, validation_targets["label"]))
    missing_train_labels = sorted(expected_labels - train_labels)
    missing_validation_labels = sorted(expected_labels - validation_labels)
    label_to_word = {
        int(label): word for word, label in word_to_label.items()
    }
    report = {
        "ready_for_formal_training": (
            not missing_train_labels
            and len(validation_labels) >= args.min_validation_words
        ),
        "speaker_overlaps": overlaps,
        "train": train_summary,
        "validation": validation_summary,
        "missing_train_words": [
            label_to_word[label] for label in missing_train_labels
        ],
        "missing_validation_words": [
            label_to_word[label] for label in missing_validation_labels
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "Self-training readiness\n"
            f"  ready: {report['ready_for_formal_training']}\n"
            f"  speaker overlaps: {overlaps}\n"
            f"  train: {train_summary['target_words']}/800 words, "
            f"{train_summary['pairable_target_speakers']} pairable speakers\n"
            f"  validation: {validation_summary['target_words']}/800 words, "
            f"{validation_summary['pairable_target_speakers']} pairable "
            f"speakers (required >= {args.min_validation_words})\n"
            f"  first missing train words: "
            f"{[label_to_word[label] for label in missing_train_labels[:20]]}"
        )

    if args.require_all_words and not report["ready_for_formal_training"]:
        raise SystemExit(
            "NOT READY: continue forced alignment until pairable training "
            "targets cover all 800 words and validation reaches the configured "
            "minimum."
        )


if __name__ == "__main__":
    main()
