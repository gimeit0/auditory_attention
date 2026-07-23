"""Write CV paths needed by the leak-free train and validation manifests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--train",
        type=Path,
        default=Path("selftrain/artifacts/splits/train_candidates.tsv.gz"),
    )
    parser.add_argument(
        "--validation",
        type=Path,
        default=Path(
            "selftrain/artifacts/splits/validation_candidates.tsv.gz"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("selftrain/hakusan/selftrain_clips_list.txt"),
    )
    args = parser.parse_args()

    paths: set[str] = set()
    for manifest in (args.train, args.validation):
        data = pd.read_csv(manifest, sep="\t", usecols=["path"], dtype=str)
        paths.update(f"clips/{path}" for path in data["path"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(f"{path}\n" for path in sorted(paths)),
        encoding="utf-8",
    )
    print(f"Wrote {len(paths):,} unique clip paths to {args.out}")


if __name__ == "__main__":
    main()
