#!/usr/bin/env python3
"""Build a strict same-speaker dichotic-listening evaluation manifest.

Each speaker contributes two different target recordings with different anchor
words plus a third Common Voice recording used only as the cue.  The cue
sentence is required not to contain either target word.  Each pair produces
four trials: two left/right assignments times two cued ears.

The target items come from the already audited Experiment 1 manifest.  Extra
cue candidates are read from Common Voice validated.tsv so that the probe does
not accidentally reuse one of the dichotic target recordings as its cue.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import soundfile as sf


REPO = Path(__file__).resolve().parents[2]
CV_ROOT = Path("/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en")


def sentence_tokens(sentence: str) -> set[str]:
    return set(re.findall(r"[a-z]+(?:'[a-z]+)?", str(sentence).lower()))


def load_metadata(tsv: Path, speakers: set[str]) -> dict[str, list[dict]]:
    selected: dict[str, list[dict]] = {speaker: [] for speaker in speakers}
    for chunk in pd.read_csv(
        tsv,
        sep="\t",
        usecols=["client_id", "path", "sentence"],
        dtype=str,
        keep_default_na=False,
        chunksize=100_000,
    ):
        subset = chunk[chunk["client_id"].isin(speakers)]
        for row in subset.to_dict("records"):
            selected[row["client_id"]].append(row)
    return selected


def clip_long_enough(path: Path, minimum_s: float = 2.5) -> bool:
    try:
        info = sf.info(path)
    except Exception:
        return False
    return info.frames / info.samplerate >= minimum_s


def choose_pair_and_cue(
    speaker_rows: pd.DataFrame,
    cue_candidates: list[dict],
    clips: Path,
) -> tuple[pd.Series, pd.Series, dict] | None:
    items = (
        speaker_rows.drop_duplicates(
            ["target_path", "target_center_s", "target_norm"]
        )
        .sort_values(["target_path", "target_center_s", "target_norm"])
        .reset_index(drop=True)
    )
    candidates = sorted(cue_candidates, key=lambda row: row["path"])
    for i, a in items.iterrows():
        for j in range(i + 1, len(items)):
            b = items.iloc[j]
            if a["target_path"] == b["target_path"]:
                continue
            if a["target_norm"] == b["target_norm"]:
                continue
            forbidden_paths = {a["target_path"], b["target_path"]}
            forbidden_words = {a["target_norm"], b["target_norm"]}
            for cue in candidates:
                if cue["path"] in forbidden_paths:
                    continue
                if sentence_tokens(cue["sentence"]) & forbidden_words:
                    continue
                if not clip_long_enough(clips / cue["path"]):
                    continue
                return a, b, cue
    return None


def trial_row(
    pair_id: str,
    speaker: str,
    assignment: str,
    cue_ear: str,
    left: pd.Series,
    right: pd.Series,
    cue: dict,
) -> dict:
    cued = left if cue_ear == "left" else right
    opposite = right if cue_ear == "left" else left
    return {
        "trial_id": f"{pair_id}_{assignment}_{cue_ear}",
        "pair_id": pair_id,
        "speaker": speaker,
        "assignment": assignment,
        "cue_ear": cue_ear,
        "cue_path": cue["path"],
        "cue_sentence": cue["sentence"],
        "left_path": left["target_path"],
        "left_center_s": left["target_center_s"],
        "left_word": left["target_norm"],
        "left_label": left["target_label"],
        "right_path": right["target_path"],
        "right_center_s": right["target_center_s"],
        "right_word": right["target_norm"],
        "right_label": right["target_label"],
        "cued_path": cued["target_path"],
        "cued_center_s": cued["target_center_s"],
        "cued_word": cued["target_norm"],
        "cued_label": cued["target_label"],
        "opposite_path": opposite["target_path"],
        "opposite_word": opposite["target_norm"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--samples",
        type=Path,
        default=REPO / "reproduction/experiment_1_gender/data/samples_expanded.csv",
    )
    ap.add_argument("--metadata", type=Path, default=CV_ROOT / "validated.tsv")
    ap.add_argument("--clips", type=Path, default=CV_ROOT / "clips")
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "双耳分析任务/data/dichotic_manifest.csv",
    )
    ap.add_argument("--max-speakers", type=int, default=0)
    args = ap.parse_args()

    samples = pd.read_csv(args.samples, dtype=str, keep_default_na=False)
    possible = {
        speaker
        for speaker, sub in samples.groupby("target_speaker")
        if sub["target_path"].nunique() >= 2
        and sub["target_norm"].nunique() >= 2
    }
    metadata = load_metadata(args.metadata, possible)

    rows: list[dict] = []
    skipped = {"no_strict_pair_and_third_cue": 0}
    completed = 0
    for speaker, sub in samples.groupby("target_speaker", sort=True):
        if speaker not in possible:
            continue
        selected = choose_pair_and_cue(sub, metadata.get(speaker, []), args.clips)
        if selected is None:
            skipped["no_strict_pair_and_third_cue"] += 1
            continue
        a, b, cue = selected
        pair_id = f"pair_{completed:03d}"
        for assignment, left, right in (("ab", a, b), ("ba", b, a)):
            for cue_ear in ("left", "right"):
                rows.append(
                    trial_row(
                        pair_id, speaker, assignment, cue_ear, left, right, cue
                    )
                )
        completed += 1
        if args.max_speakers and completed >= args.max_speakers:
            break

    output = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.out, index=False)
    audit = {
        "project": "Task 1: same-speaker dichotic listening",
        "date": "2026-07-21",
        "speakers_with_two_distinct_target_recordings": len(possible),
        "included_speakers": completed,
        "trials": len(output),
        "trials_per_speaker": 4,
        "skipped": skipped,
        "selection": (
            "deterministic lexical/path order; no model predictions used; "
            "two distinct target recordings and a third cue recording"
        ),
    }
    audit_path = args.out.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    print(f"manifest: {args.out}")
    print(f"audit:    {audit_path}")


if __name__ == "__main__":
    main()
