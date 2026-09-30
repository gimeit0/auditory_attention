"""Freeze and verify the exact semantic inputs used by HAKUSAN training."""

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import shutil
import subprocess


SEMANTIC_INPUTS = (
    "src/__init__.py",
    "src/spatialtrain.py",
    "src/spatial_attn_lightning.py",
    "src/spatial_attn_architecture.py",
    "src/audio_transforms.py",
    "src/audio_attention_transforms.py",
    "src/custom_modules.py",
    "src/time_domain_cochleagram.py",
    "src/layers/conv2d_same.py",
    "src/layers/padding.py",
    "corpus/binaural_attention_h5.py",
    "selftrain/__init__.py",
    "selftrain/data/__init__.py",
    "selftrain/data/anchor_index.py",
    "selftrain/data/diotic_attention.py",
    "selftrain/scripts/__init__.py",
    "selftrain/scripts/check_readiness.py",
    "selftrain/scripts/check_dataset.py",
    "selftrain/scripts/check_training_safety.py",
    "selftrain/scripts/check_training_phase.py",
    "selftrain/scripts/check_cue_control_release.py",
    "selftrain/scripts/finalize_training_phase.py",
    "selftrain/scripts/full_started.py",
    "selftrain/scripts/build_full_pilot_eval_bank.py",
    "selftrain/scripts/eval_full_pilot.py",
    "selftrain/scripts/pilot_release.py",
    "selftrain/scripts/run_integrity.py",
    "selftrain/scripts/test_run_integrity.py",
    "selftrain/scripts/test_training_phase.py",
    "selftrain/scripts/test_cue_control_release.py",
    "selftrain/scripts/test_finalize_training_phase.py",
    "selftrain/scripts/test_full_started.py",
    "selftrain/scripts/test_full_pilot_eval.py",
    "selftrain/scripts/test_pilot_release.py",
    "selftrain/configs/full.yaml",
    "selftrain/hakusan/run_training.sbatch",
    "selftrain/hakusan/run_full_pilot_eval.sbatch",
    "selftrain/hakusan/run_numerics_preflight.sbatch",
    "selftrain/hakusan/submit_training.sh",
    "selftrain/hakusan/fork_resume_checkpoint.py",
    "selftrain/hakusan/checkpoint_reference.py",
    "selftrain/artifacts/anchors/train_anchors.tsv.gz",
    "selftrain/artifacts/anchors/validation_anchors.tsv.gz",
    "selftrain/artifacts/anchors/anchor_catalog_audit.json",
    "selftrain/artifacts/splits/eval_speakers.txt",
    "cv_800_word_label_to_int_dict.pkl",
)
PROVENANCE_DIRECTORIES = (
    "src",
    "corpus",
    "selftrain/data",
    "selftrain/scripts",
    "selftrain/configs",
    "selftrain/hakusan",
)
PROVENANCE_SUFFIXES = {".py", ".yaml", ".yml", ".sh", ".sbatch"}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_entries(entries):
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(
            f"{entry['sha256']}  {entry['path']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def _entry(root, relative_path):
    absolute_path = root / relative_path
    if not absolute_path.is_file():
        raise FileNotFoundError(f"Required run input is missing: {absolute_path}")
    return {
        "path": relative_path.as_posix(),
        "sha256": _sha256(absolute_path),
        "size": absolute_path.stat().st_size,
    }


def discover_semantic_inputs(root):
    root = pathlib.Path(root).resolve()
    paths = [pathlib.Path(name) for name in SEMANTIC_INPUTS]
    return [_entry(root, path) for path in paths]


def discover_provenance_inputs(root):
    root = pathlib.Path(root).resolve()
    relative_paths = set(pathlib.Path(name) for name in SEMANTIC_INPUTS)
    for directory_name in PROVENANCE_DIRECTORIES:
        directory = root / directory_name
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Required source directory is missing: {directory}"
            )
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and path.suffix in PROVENANCE_SUFFIXES
                and "__pycache__" not in path.parts
            ):
                relative_paths.add(path.relative_to(root))
    return [
        _entry(root, path)
        for path in sorted(relative_paths, key=lambda value: value.as_posix())
    ]


def build_manifest(root):
    semantic_entries = discover_semantic_inputs(root)
    provenance_entries = discover_provenance_inputs(root)
    return {
        "schema_version": 2,
        "semantic_combined_sha256": _digest_entries(semantic_entries),
        "provenance_combined_sha256": _digest_entries(provenance_entries),
        "semantic_files": semantic_entries,
        "provenance_files": provenance_entries,
    }


def _compare_entries(name, expected_entries, current_entries):
    expected = {
        entry["path"]: (entry["sha256"], int(entry["size"]))
        for entry in expected_entries
    }
    current = {
        entry["path"]: (entry["sha256"], int(entry["size"]))
        for entry in current_entries
    }
    missing = sorted(set(expected).difference(current))
    added = sorted(set(current).difference(expected))
    changed = sorted(
        path
        for path in set(expected).intersection(current)
        if expected[path] != current[path]
    )
    if missing or added or changed:
        raise RuntimeError(
            f"{name} inputs do not match the frozen snapshot: "
            f"missing={missing}, added={added}, changed={changed}"
        )


def snapshot(root, output_dir):
    root = pathlib.Path(root).resolve()
    output_dir = pathlib.Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"Snapshot directory already exists: {output_dir}")
    temporary_dir = output_dir.with_name(
        f".{output_dir.name}.tmp-{os.getpid()}"
    )
    if temporary_dir.exists():
        raise FileExistsError(f"Snapshot temporary directory exists: {temporary_dir}")
    files_dir = temporary_dir / "files"
    files_dir.mkdir(parents=True)

    try:
        manifest = build_manifest(root)
        manifest["created_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        for entry in manifest["provenance_files"]:
            source = root / entry["path"]
            destination = files_dir / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if (
                destination.stat().st_size != int(entry["size"])
                or _sha256(destination) != entry["sha256"]
            ):
                raise IOError(f"Snapshot copy verification failed: {destination}")

        manifest_path = temporary_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify(files_dir, manifest_path)
        temporary_dir.replace(output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def verify(root, manifest_path):
    root = pathlib.Path(root).resolve()
    manifest_path = pathlib.Path(manifest_path).resolve()
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = build_manifest(root)
    _compare_entries(
        "Semantic",
        expected["semantic_files"],
        current["semantic_files"],
    )
    _compare_entries(
        "Provenance",
        expected["provenance_files"],
        current["provenance_files"],
    )
    for key in ("semantic_combined_sha256", "provenance_combined_sha256"):
        if expected[key] != current[key]:
            raise RuntimeError(f"Run-input digest does not match: {key}")
    return current


def environment_fingerprint():
    packages = {}
    for distribution in (
        "numpy",
        "pandas",
        "scipy",
        "soundfile",
        "PyYAML",
        "torch",
        "torchaudio",
        "pytorch-lightning",
        "chcochleagram",
    ):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution] = None

    import torch

    gpu = None
    if torch.cuda.is_available():
        gpu = {
            "name": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
        }
    driver = None
    try:
        driver = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader",
                "-i",
                "0",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return {
        "schema_version": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "torch_cuda": torch.version.cuda,
        "torch_cudnn": torch.backends.cudnn.version(),
        "gpu": gpu,
        "nvidia_driver": driver,
    }


def validate_numerics_pass(pass_path, manifest_path, check_environment=False):
    pass_path = pathlib.Path(pass_path).resolve()
    manifest_path = pathlib.Path(manifest_path).resolve()
    result = json.loads(pass_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_version": 3,
        "status": "PASS",
        "precision": "16-mixed",
        "expected_train_examples": 864000,
        "expected_train_batches": 27000,
        "batch_size": 32,
        "accumulate_grad_batches": 9,
        "effective_batch_size": 288,
        "expected_optimizer_attempts": 3000,
        "global_step": 3000,
        "base_config_relative_path": "selftrain/configs/full.yaml",
    }
    errors = []
    for key, expected in required.items():
        if result.get(key) != expected:
            errors.append(f"{key}={result.get(key)!r}, expected {expected!r}")
    if (
        result.get("source_semantic_sha256")
        != manifest["semantic_combined_sha256"]
    ):
        errors.append("source semantic digest does not match")
    semantic_hashes = {
        entry["path"]: entry["sha256"]
        for entry in manifest.get("semantic_files", [])
    }
    base_config_path = result.get("base_config_relative_path")
    if result.get("base_config_sha256") != semantic_hashes.get(base_config_path):
        errors.append("base config digest does not match semantic manifest")
    examples = int(result.get("expected_train_examples", -1))
    batches = int(result.get("expected_train_batches", -1))
    batch_size = int(result.get("batch_size", -1))
    accumulate = int(result.get("accumulate_grad_batches", -1))
    effective_batch = int(result.get("effective_batch_size", -1))
    attempts = int(result.get("expected_optimizer_attempts", -1))
    if batch_size <= 0 or examples != batches * batch_size:
        errors.append("train examples/batches/batch_size are inconsistent")
    if accumulate <= 0 or batches != attempts * accumulate:
        errors.append("train batches/attempts/accumulation are inconsistent")
    if effective_batch != batch_size * accumulate:
        errors.append("effective batch size is inconsistent")
    successful = int(result.get("successful_optimizer_steps", -1))
    overflows = int(result.get("amp_overflows", -1))
    confirmed = int(result.get("confirmed_amp_skip_backoffs", -1))
    if successful + overflows != attempts:
        errors.append("successful steps plus overflows does not equal attempts")
    if confirmed != overflows:
        errors.append("confirmed skip/backoffs does not equal overflows")
    if check_environment and result.get("environment") != environment_fingerprint():
        errors.append("runtime environment fingerprint does not match")
    if errors:
        raise RuntimeError(
            f"Invalid numerical-preflight PASS {pass_path}: "
            + "; ".join(errors)
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "digest",
            "snapshot",
            "verify",
            "environment",
            "validate-pass",
        ),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--output-dir")
    parser.add_argument("--manifest")
    parser.add_argument("--pass-path")
    parser.add_argument("--check-environment", action="store_true")
    args = parser.parse_args()

    if args.command == "digest":
        result = build_manifest(args.root)
    elif args.command == "snapshot":
        if not args.output_dir:
            parser.error("snapshot requires --output-dir")
        result = snapshot(args.root, args.output_dir)
    elif args.command == "verify":
        if not args.manifest:
            parser.error("verify requires --manifest")
        result = verify(args.root, args.manifest)
    elif args.command == "environment":
        result = environment_fingerprint()
    else:
        if not args.pass_path or not args.manifest:
            parser.error("validate-pass requires --pass-path and --manifest")
        result = validate_numerics_pass(
            args.pass_path,
            args.manifest,
            check_environment=args.check_environment,
        )

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
