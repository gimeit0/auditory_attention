"""Create and verify an immutable reference to one resume checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re

import torch


EPOCH_BASENAME = re.compile(
    r"(?:last(?:-v[1-9][0-9]*)?|pilot4-final)\.ckpt"
)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_global_step(path: pathlib.Path) -> int:
    try:
        checkpoint = torch.load(
            path, map_location="cpu", weights_only=False
        )
    except TypeError:
        checkpoint = torch.load(path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise ValueError(f"Checkpoint payload is not a mapping: {path}")
    global_step = int(checkpoint.get("global_step", -1))
    if global_step <= 0:
        raise ValueError(
            f"Resume checkpoint must have global_step>0: {path}"
        )
    return global_step


def lock_reference(
    checkpoint_directory: str | pathlib.Path,
    resume_kind: str,
    basename: str,
) -> dict:
    directory_argument = pathlib.Path(checkpoint_directory).expanduser()
    directory = directory_argument.resolve()
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Checkpoint directory does not exist: {directory}"
        )
    if resume_kind == "epoch":
        if EPOCH_BASENAME.fullmatch(basename) is None:
            raise ValueError(
                "Epoch basename must be last.ckpt, last-vN.ckpt, or "
                f"pilot4-final.ckpt; got {basename!r}"
            )
    elif resume_kind == "best-effort-rolling":
        if basename != "rolling.ckpt":
            raise ValueError("Rolling resume requires rolling.ckpt")
    else:
        raise ValueError(f"Unsupported resume kind: {resume_kind!r}")

    candidate = directory_argument / basename
    if candidate.is_symlink():
        raise ValueError(f"Checkpoint must not be a symbolic link: {candidate}")
    resolved = candidate.resolve()
    if resolved.parent != directory:
        raise ValueError(f"Checkpoint escapes its directory: {candidate}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Checkpoint does not exist: {resolved}")
    return {
        "schema_version": 1,
        "resume_kind": resume_kind,
        "basename": basename,
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "global_step": _load_global_step(resolved),
    }


def verify_reference(
    checkpoint_directory: str | pathlib.Path,
    resume_kind: str,
    basename: str,
    expected_sha256: str,
    expected_global_step: int,
) -> dict:
    reference = lock_reference(
        checkpoint_directory, resume_kind, basename
    )
    if reference["sha256"] != expected_sha256:
        raise RuntimeError(
            "Checkpoint content changed after submission: "
            f"actual={reference['sha256']}, expected={expected_sha256}"
        )
    if reference["global_step"] != int(expected_global_step):
        raise RuntimeError(
            "Checkpoint global_step changed after submission: "
            f"actual={reference['global_step']}, "
            f"expected={expected_global_step}"
        )
    return reference


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("lock", "verify"))
    parser.add_argument("--checkpoint-directory", required=True)
    parser.add_argument(
        "--resume-kind",
        required=True,
        choices=("epoch", "best-effort-rolling"),
    )
    parser.add_argument("--basename", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-global-step", type=int)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "lock":
        reference = lock_reference(
            args.checkpoint_directory, args.resume_kind, args.basename
        )
        print(
            reference["basename"],
            reference["sha256"],
            reference["global_step"],
        )
        return
    if args.expected_sha256 is None or args.expected_global_step is None:
        raise SystemExit(
            "verify requires --expected-sha256 and --expected-global-step"
        )
    reference = verify_reference(
        args.checkpoint_directory,
        args.resume_kind,
        args.basename,
        args.expected_sha256,
        args.expected_global_step,
    )
    print(json.dumps(reference, sort_keys=True))


if __name__ == "__main__":
    main()
