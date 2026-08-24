#!/bin/bash
# Long FP16 numerical-stability preflight for the formal self-training setup.
# It executes 27000 training batches / 3000 optimizer attempts, crossing the
# default GradScaler growth window and the failure position of Job 510011.
#SBATCH -J audattn_numcheck
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 16:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/selective_listening_repro/code/auditory_attention
#SBATCH --output=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --error=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Eeuo pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"

PROJECT_ROOT="/home/s2510040/selective_listening_repro/code/auditory_attention"
cd "$PROJECT_ROOT"
export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"

NUMERICS_ROOT="$PROJECT_ROOT/selftrain/numerics_preflight_runs/${SLURM_JOB_ID}"
NUMERICS_CONFIG="$NUMERICS_ROOT/numerics_preflight.yaml"
SOURCE_SNAPSHOT="$NUMERICS_ROOT/source_snapshot"
TRAIN_LOG="$NUMERICS_ROOT/training.log"
PASS_PATH="$NUMERICS_ROOT/PASS.json"

if [ -e "$NUMERICS_ROOT" ]; then
    echo "Refusing to reuse numerical-preflight directory: $NUMERICS_ROOT" >&2
    exit 2
fi
mkdir -p "$NUMERICS_ROOT"

python -m selftrain.scripts.run_integrity snapshot \
    --root "$PROJECT_ROOT" \
    --output-dir "$SOURCE_SNAPSHOT" >/dev/null

python - selftrain/configs/full.yaml "$NUMERICS_CONFIG" <<'PY'
import pathlib
import sys
import yaml

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
config = yaml.safe_load(source.read_text(encoding="utf-8"))
config["model_name"] = "diotic_selftrain_numerics_preflight"
config["corpus"]["examples_per_epoch"] = 864000
config["corpus"]["validation_examples"] = 320
config["hparas"]["epochs"] = 1
config["hparas"]["save_last"] = False
config["hparas"]["save_stage_zero"] = False
config["hparas"]["checkpoint_every_n_epochs"] = 0
config["hparas"]["checkpoint_every_n_train_steps"] = 1000
config["hparas"]["save_train_checkpoint"] = False

assert config["corpus"]["examples_per_epoch"] == 864000
assert config["corpus"]["validation_examples"] == 320
assert config["hparas"]["batch_size"] == 32
assert config["hparas"]["accumulate_grad_batches"] == 9
assert config["hparas"]["epochs"] == 1
assert config["hparas"]["checkpoint_every_n_train_steps"] == 1000
examples = config["corpus"]["examples_per_epoch"]
batch_size = config["hparas"]["batch_size"]
accumulate = config["hparas"]["accumulate_grad_batches"]
assert examples % batch_size == 0
expected_batches = examples // batch_size
assert expected_batches % accumulate == 0
expected_attempts = expected_batches // accumulate
assert expected_batches == 27000
assert expected_attempts == 3000
destination.write_text(
    yaml.safe_dump(config, sort_keys=False),
    encoding="utf-8",
)
print(
    f"Generated numerical config: batches={expected_batches}, "
    f"optimizer_attempts={expected_attempts}"
)
PY

SOURCE_SEMANTIC_SHA256=$(python - "$SOURCE_SNAPSHOT/manifest.json" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest["semantic_combined_sha256"])
PY
)
CONFIG_SHA256=$(sha256sum "$NUMERICS_CONFIG" | awk '{print $1}')
export AUDATTN_RUN_ID="numerics_${SLURM_JOB_ID}"
export AUDATTN_SOURCE_SHA256="$SOURCE_SEMANTIC_SHA256"
export AUDATTN_CONFIG_SHA256="$CONFIG_SHA256"

echo "Numerics preflight host: $(hostname)"
echo "Expected training examples: 864000"
echo "Expected training batches: 27000"
echo "Expected optimizer attempts: 3000"
nvidia-smi

cd "$SOURCE_SNAPSHOT/files"
python -m selftrain.scripts.check_readiness --require-all-words
python -u -m selftrain.scripts.check_dataset --batch-size 2
python -m selftrain.scripts.check_training_safety

/usr/bin/time -p python -u -m src.spatialtrain \
    --config "$NUMERICS_CONFIG" \
    --exp_dir "$NUMERICS_ROOT" \
    --gpus 1 \
    --n_jobs 8 \
    --precision 16-mixed \
    --random_seed 20260721 \
    2>&1 | tee "$TRAIN_LOG"

python - \
    "$NUMERICS_ROOT/numerics_preflight/checkpoints/rolling.ckpt" \
    "$NUMERICS_CONFIG" \
    "$SOURCE_SNAPSHOT/files/selftrain/configs/full.yaml" \
    "$SOURCE_SNAPSHOT/manifest.json" \
    "$TRAIN_LOG" \
    "$PASS_PATH" <<'PY'
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys

import torch
import yaml

from selftrain.scripts.run_integrity import environment_fingerprint


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


checkpoint_path = pathlib.Path(sys.argv[1]).resolve()
config_path = pathlib.Path(sys.argv[2]).resolve()
base_config_path = pathlib.Path(sys.argv[3]).resolve()
manifest_path = pathlib.Path(sys.argv[4]).resolve()
log_path = pathlib.Path(sys.argv[5]).resolve()
pass_path = pathlib.Path(sys.argv[6]).resolve()

if not checkpoint_path.is_file():
    raise SystemExit(f"Rolling checkpoint was not created: {checkpoint_path}")
try:
    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
except TypeError:
    checkpoint = torch.load(checkpoint_path, map_location="cpu")

required_checkpoint_keys = {
    "state_dict",
    "optimizer_states",
    "lr_schedulers",
    "loops",
    "epoch",
    "global_step",
    "audattn_amp_state_v1",
    "audattn_rng_state_v1",
    "audattn_run_metadata_v1",
}
missing = sorted(required_checkpoint_keys.difference(checkpoint))
if missing:
    raise SystemExit(f"Rolling checkpoint is incomplete; missing={missing}")
if int(checkpoint["global_step"]) != 3000:
    raise SystemExit(
        f"Expected global_step=3000, got {checkpoint['global_step']}"
    )
if not checkpoint["optimizer_states"]:
    raise SystemExit("Rolling checkpoint has no optimizer state")

expected_metadata = {
    "run_id": os.environ["AUDATTN_RUN_ID"],
    "source_semantic_sha256": os.environ["AUDATTN_SOURCE_SHA256"],
    "config_sha256": os.environ["AUDATTN_CONFIG_SHA256"],
}
if checkpoint["audattn_run_metadata_v1"] != expected_metadata:
    raise SystemExit(
        "Rolling checkpoint run metadata mismatch: "
        f"actual={checkpoint['audattn_run_metadata_v1']}, "
        f"expected={expected_metadata}"
    )
rng_state = checkpoint["audattn_rng_state_v1"]
rng_required = {"python", "numpy", "torch_cpu", "torch_cuda"}
rng_missing = sorted(rng_required.difference(rng_state))
if rng_missing:
    raise SystemExit(
        f"Rolling checkpoint RNG state is incomplete: missing={rng_missing}"
    )


def assert_finite(value, name):
    if isinstance(value, torch.Tensor):
        if value.is_floating_point() and not torch.isfinite(value).all():
            raise SystemExit(f"Non-finite tensor in checkpoint: {name}")
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_finite(item, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_finite(item, f"{name}[{index}]")


assert_finite(checkpoint["state_dict"], "state_dict")
assert_finite(checkpoint["optimizer_states"], "optimizer_states")

scaler_state = checkpoint.get("MixedPrecision")
if scaler_state is None:
    scaler_state = checkpoint.get("native_amp_scaling_state")
if not scaler_state:
    raise SystemExit("Rolling checkpoint has no native AMP scaler state")
scaler_scale = float(scaler_state.get("scale", 0.0))
if not scaler_scale > 0 or not torch.isfinite(torch.tensor(scaler_scale)):
    raise SystemExit(f"Invalid GradScaler scale: {scaler_scale}")

amp_state = checkpoint["audattn_amp_state_v1"]
attempts = int(amp_state["total_optimizer_attempts"])
successful = int(amp_state["successful_optimizer_steps"])
overflows = int(amp_state["total_overflows"])
if attempts != 3000:
    raise SystemExit(f"Expected 3000 audited attempts, got {attempts}")
if successful + overflows != attempts:
    raise SystemExit(
        "AMP accounting mismatch: "
        f"successful={successful}, overflows={overflows}, attempts={attempts}"
    )

config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
assert config["corpus"]["examples_per_epoch"] == 864000
assert config["hparas"]["batch_size"] == 32
assert config["hparas"]["accumulate_grad_batches"] == 9

log_text = log_path.read_text(encoding="utf-8", errors="replace")
detections = log_text.count("AMP gradient overflow detected")
safe_skips = log_text.count(
    "AMP optimizer step safely skipped and scale reduced"
)
if detections != safe_skips:
    raise SystemExit(
        "Every detected AMP overflow must have a confirmed skip/backoff: "
        f"detected={detections}, confirmed={safe_skips}"
    )
if detections != overflows:
    raise SystemExit(
        "Log/checkpoint AMP accounting mismatch: "
        f"detected={detections}, checkpoint_overflows={overflows}"
    )
if "Too many AMP gradient overflows" in log_text:
    raise SystemExit("Numerical preflight exceeded an AMP overflow limit")

source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
result = {
    "schema_version": 3,
    "status": "PASS",
    "job_id": os.environ["SLURM_JOB_ID"],
    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "precision": "16-mixed",
    "expected_train_examples": 864000,
    "expected_train_batches": 27000,
    "batch_size": 32,
    "accumulate_grad_batches": 9,
    "effective_batch_size": 288,
    "expected_optimizer_attempts": 3000,
    "global_step": int(checkpoint["global_step"]),
    "successful_optimizer_steps": successful,
    "amp_overflows": overflows,
    "confirmed_amp_skip_backoffs": safe_skips,
    "checkpoint": str(checkpoint_path),
    "checkpoint_sha256": sha256(checkpoint_path),
    "generated_config_sha256": sha256(config_path),
    "base_config_relative_path": "selftrain/configs/full.yaml",
    "base_config_sha256": sha256(base_config_path),
    "source_semantic_sha256": source_manifest[
        "semantic_combined_sha256"
    ],
    "source_provenance_sha256": source_manifest[
        "provenance_combined_sha256"
    ],
    "environment": environment_fingerprint(),
    "grad_scaler_scale": scaler_scale,
}
temporary_path = pass_path.with_suffix(".json.tmp")
temporary_path.write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.replace(temporary_path, pass_path)
print(json.dumps(result, indent=2, sort_keys=True))
PY

echo "NUMERICS PREFLIGHT: PASS"
echo "PASS record: $PASS_PATH"
