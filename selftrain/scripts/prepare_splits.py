"""
Prepare leak-free Common Voice manifests for training a model from scratch.

The two completed reproduction experiments were built from validated.tsv, which
overlaps the official Common Voice train/dev/test splits.  To keep those
experiments usable as a held-out test, this script excludes every speaker used
by either experiment from both the self-training and validation candidates.

Outputs (under --out-dir):
  eval_speakers.txt
  train_candidates.tsv.gz
  validation_candidates.tsv.gz
  split_audit.json

This step only establishes split boundaries.  Forced alignment and anchor-word
screening are deliberately left to the next stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


SAMPLE_SPEAKER_COLUMNS = (
    "target_speaker",
    "cue_speaker",
    "same_dist_speaker",
    "diff_dist_speaker",
)
SAMPLE_PATH_COLUMNS = (
    "target_path",
    "cue_path",
    "same_dist_path",
    "diff_dist_path",
)
REQUIRED_CV_COLUMNS = ("client_id", "path", "sentence", "gender")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cv-dir",
        type=Path,
        default=Path(
            "/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en"
        ),
        help="Common Voice English directory containing train/dev/test TSVs.",
    )
    parser.add_argument(
        "--samples",
        type=Path,
        default=Path(
            "reproduction/experiment_1_gender/data/samples_expanded.csv"
        ),
        help="Manifest used by the completed single-talker experiment.",
    )
    parser.add_argument(
        "--distractor-pool",
        type=Path,
        default=Path(
            "reproduction/experiment_2_talker_count/data/distractor_pool.csv"
        ),
        help="Anchored pool used by the completed multi-talker experiment.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("selftrain/artifacts/splits"),
    )
    parser.add_argument(
        "--include-test-in-validation",
        action="store_true",
        help=(
            "Combine the official Common Voice test split with dev for "
            "validation candidates. Use this only when the speaker-disjoint "
            "dev pool cannot meet the formal validation-vocabulary gate."
        ),
    )
    return parser.parse_args()


def read_cv_split(cv_dir: Path, name: str) -> pd.DataFrame:
    path = cv_dir / f"{name}.tsv"
    if not path.exists():
        raise FileNotFoundError(f"Missing Common Voice split: {path}")
    data = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    missing = sorted(set(REQUIRED_CV_COLUMNS) - set(data.columns))
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    return data


def nonempty_values(data: pd.DataFrame, columns: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for column in columns:
        if column not in data:
            continue
        values.update(
            value
            for value in data[column].astype(str)
            if value and value.lower() != "nan"
        )
    return values


def collect_eval_scope(
    samples_path: Path, pool_path: Path
) -> tuple[set[str], set[str], dict[str, int]]:
    samples = pd.read_csv(samples_path, dtype=str, keep_default_na=False)
    pool = pd.read_csv(pool_path, dtype=str, keep_default_na=False)

    missing_sample = sorted(
        {"target_speaker", "target_path", "cue_path"} - set(samples.columns)
    )
    if missing_sample:
        raise ValueError(f"{samples_path} is missing columns: {missing_sample}")
    if not {"speaker", "path"}.issubset(pool.columns):
        raise ValueError(f"{pool_path} must contain speaker and path columns")

    sample_speakers = nonempty_values(samples, SAMPLE_SPEAKER_COLUMNS)
    pool_speakers = nonempty_values(pool, ("speaker",))
    sample_paths = nonempty_values(samples, SAMPLE_PATH_COLUMNS)
    pool_paths = nonempty_values(pool, ("path",))

    speakers = sample_speakers | pool_speakers
    paths = sample_paths | pool_paths
    counts = {
        "sample_rows": int(len(samples)),
        "pool_rows": int(len(pool)),
        "sample_speakers": len(sample_speakers),
        "pool_speakers": len(pool_speakers),
        "all_eval_speakers": len(speakers),
        "sample_files": len(sample_paths),
        "pool_files": len(pool_paths),
        "all_eval_files": len(paths),
    }
    return speakers, paths, counts


def keep_usable_rows(
    data: pd.DataFrame, excluded_speakers: set[str]
) -> tuple[pd.DataFrame, dict[str, int]]:
    before = len(data)
    after_blacklist = data[~data["client_id"].isin(excluded_speakers)].copy()
    after_gender = after_blacklist[
        after_blacklist["gender"].isin(["male", "female"])
    ].copy()

    gender_counts = after_gender.groupby("client_id")["gender"].nunique()
    consistent_speakers = set(gender_counts[gender_counts == 1].index)
    after_consistency = after_gender[
        after_gender["client_id"].isin(consistent_speakers)
    ].copy()
    after_consistency = after_consistency.drop_duplicates("path").reset_index(
        drop=True
    )

    summary = {
        "rows_original": int(before),
        "rows_after_eval_speaker_exclusion": int(len(after_blacklist)),
        "rows_after_gender_filter": int(len(after_gender)),
        "rows_final": int(len(after_consistency)),
        "speakers_final": int(after_consistency["client_id"].nunique()),
        "female_rows_final": int(
            (after_consistency["gender"] == "female").sum()
        ),
        "male_rows_final": int((after_consistency["gender"] == "male").sum()),
    }
    return after_consistency, summary


def sha256_lines(values: set[str]) -> str:
    digest = hashlib.sha256()
    for value in sorted(values):
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def assert_disjoint(name_a: str, a: set[str], name_b: str, b: set[str]) -> None:
    overlap = a & b
    if overlap:
        example = sorted(overlap)[:3]
        raise RuntimeError(
            f"{name_a} and {name_b} overlap by {len(overlap)} speakers; "
            f"examples: {example}"
        )


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    eval_speakers, eval_paths, eval_counts = collect_eval_scope(
        args.samples, args.distractor_pool
    )
    raw_train = read_cv_split(args.cv_dir, "train")
    raw_dev = read_cv_split(args.cv_dir, "dev")
    raw_test = read_cv_split(args.cv_dir, "test")

    official_speakers = {
        "train": set(raw_train["client_id"]),
        "dev": set(raw_dev["client_id"]),
        "test": set(raw_test["client_id"]),
    }
    assert_disjoint(
        "official train", official_speakers["train"],
        "official dev", official_speakers["dev"],
    )
    assert_disjoint(
        "official train", official_speakers["train"],
        "official test", official_speakers["test"],
    )
    assert_disjoint(
        "official dev", official_speakers["dev"],
        "official test", official_speakers["test"],
    )

    validation_source_splits = ["dev"]
    raw_validation = raw_dev
    if args.include_test_in_validation:
        validation_source_splits.append("test")
        raw_validation = pd.concat(
            [raw_dev, raw_test], ignore_index=True, sort=False
        )

    train, train_summary = keep_usable_rows(raw_train, eval_speakers)
    validation, validation_summary = keep_usable_rows(
        raw_validation, eval_speakers
    )

    train_speakers = set(train["client_id"])
    validation_speakers = set(validation["client_id"])
    assert_disjoint("self-train", train_speakers, "validation", validation_speakers)
    assert_disjoint("self-train", train_speakers, "held-out eval", eval_speakers)
    assert_disjoint(
        "validation", validation_speakers, "held-out eval", eval_speakers
    )

    blacklist_path = args.out_dir / "eval_speakers.txt"
    blacklist_path.write_text(
        "".join(f"{speaker}\n" for speaker in sorted(eval_speakers)),
        encoding="utf-8",
    )
    train_path = args.out_dir / "train_candidates.tsv.gz"
    validation_path = args.out_dir / "validation_candidates.tsv.gz"
    train.to_csv(train_path, sep="\t", index=False, compression="gzip")
    validation.to_csv(
        validation_path, sep="\t", index=False, compression="gzip"
    )

    split_file_sets = {
        "train": set(raw_train["path"]),
        "dev": set(raw_dev["path"]),
        "test": set(raw_test["path"]),
    }
    audit = {
        "purpose": (
            "Speaker-disjoint candidates for training from random initialization; "
            "the completed reproduction experiments remain held out."
        ),
        "inputs": {
            "cv_dir": str(args.cv_dir.resolve()),
            "samples": str(args.samples.resolve()),
            "distractor_pool": str(args.distractor_pool.resolve()),
            "validation_source_splits": validation_source_splits,
        },
        "eval_scope": {
            **eval_counts,
            "speaker_blacklist_sha256": sha256_lines(eval_speakers),
            "files_in_official_train": len(eval_paths & split_file_sets["train"]),
            "files_in_official_dev": len(eval_paths & split_file_sets["dev"]),
            "files_in_official_test": len(eval_paths & split_file_sets["test"]),
            "speakers_in_official_train": len(
                eval_speakers & official_speakers["train"]
            ),
            "speakers_in_official_dev": len(
                eval_speakers & official_speakers["dev"]
            ),
            "speakers_in_official_test": len(
                eval_speakers & official_speakers["test"]
            ),
        },
        "train_candidates": train_summary,
        "validation_candidates": validation_summary,
        "checks": {
            "official_splits_speaker_disjoint": True,
            "train_validation_speaker_disjoint": True,
            "train_eval_speaker_disjoint": True,
            "validation_eval_speaker_disjoint": True,
        },
        "outputs": {
            "eval_speakers": str(blacklist_path.resolve()),
            "train_candidates": str(train_path.resolve()),
            "validation_candidates": str(validation_path.resolve()),
        },
    }
    audit_path = args.out_dir / "split_audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("Self-training split preparation complete")
    print(f"  held-out evaluation speakers: {len(eval_speakers):,}")
    print(
        "  train candidates: "
        f"{len(train):,} rows / {train['client_id'].nunique():,} speakers"
    )
    print(
        "  validation candidates: "
        f"{len(validation):,} rows / "
        f"{validation['client_id'].nunique():,} speakers "
        f"from {'+'.join(validation_source_splits)}"
    )
    print("  leakage checks: PASS")
    print(f"  audit: {audit_path}")


if __name__ == "__main__":
    main()
