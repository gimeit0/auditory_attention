#!/bin/bash
# Guarded Tier-0 training. Submit only through submit_training.sh so all path,
# PASS, checkpoint, duplicate-job, and snapshot checks happen before GPU queueing.
#SBATCH -J audattn_selftrain
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 24:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/selective_listening_repro/code/auditory_attention
#SBATCH --output=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --error=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Eeuo pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

PROJECT_ROOT="/home/s2510040/selective_listening_repro/code/auditory_attention"
cd "$PROJECT_ROOT"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"

: "${RUN_ID:?RUN_ID must be supplied by submit_training.sh}"
: "${MODE:?MODE must be supplied by submit_training.sh}"
: "${RUN_PHASE:?RUN_PHASE must be supplied by submit_training.sh}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "RUN_ID contains unsupported characters: $RUN_ID" >&2
    exit 2
fi
case "$MODE" in
    new|fork-stage0|resume) ;;
    *) echo "MODE must be new, fork-stage0, or resume" >&2; exit 2 ;;
esac
case "$RUN_PHASE" in
    pilot4|full) ;;
    *) echo "RUN_PHASE must be pilot4 or full" >&2; exit 2 ;;
esac
if [ "$RUN_PHASE" = "pilot4" ] \
    && [ "$MODE" != "new" ] \
    && [ "$MODE" != "resume" ]; then
    echo "pilot4 supports only MODE=new or MODE=resume" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "full" ] && [ "$MODE" != "resume" ]; then
    echo "RUN_PHASE=full is allowed only as MODE=resume" >&2
    exit 2
fi

RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$RUN_ID"
SNAPSHOT_DIR="$RUN_ROOT/snapshot"
STATE_DIR="$RUN_ROOT/state"
PASS_PATH="$SNAPSHOT_DIR/numerics_PASS.json"
MANIFEST_PATH="$SNAPSHOT_DIR/manifest.json"

for required in \
    "$STATE_DIR/PREPARED.json" \
    "$PASS_PATH" \
    "$MANIFEST_PATH" \
    "$SNAPSHOT_DIR/files/selftrain/configs/full.yaml"
do
    if [ ! -f "$required" ]; then
        echo "Prepared-run file is missing: $required" >&2
        exit 2
    fi
done
if [ -e "$STATE_DIR/COMPLETE" ]; then
    echo "Run is already marked COMPLETE: $RUN_ID" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "pilot4" ] \
    && [ -e "$STATE_DIR/PILOT4_COMPLETE.json" ]; then
    echo "Four-epoch pilot is already complete: $RUN_ID" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "pilot4" ] \
    && [ ! -f "$STATE_DIR/cue_control_release.json" ]; then
    echo "Pilot requires state/cue_control_release.json" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "full" ] \
    && [ "$MODE" = "resume" ] \
    && [ ! -f "$STATE_DIR/PILOT4_COMPLETE.json" ]; then
    echo "Full continuation requires a validated PILOT4_COMPLETE.json" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "full" ]; then
    python -m selftrain.scripts.pilot_release validate \
        --run-root "$RUN_ROOT" >/dev/null
fi
if [ "$RUN_PHASE" = "full" ] \
    && [ "$MODE" = "resume" ] \
    && [ ! -f "$STATE_DIR/PILOT4_GO.json" ]; then
    echo "Full continuation requires a reviewed PILOT4_GO.json" >&2
    exit 2
fi

if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required for duplicate-writer protection" >&2
    exit 2
fi
exec 9>"$STATE_DIR/run.lock"
if ! flock -n 9; then
    echo "Another job is already writing RUN_ID=$RUN_ID" >&2
    exit 75
fi
# Revalidate the external 10k results after allocation for both phases.  The
# structured record alone is not trusted if its source CSV/summary changed.
python -m selftrain.scripts.check_cue_control_release \
    --release-record "$STATE_DIR/cue_control_release.json" >/dev/null

# Recheck the mutable live tree, the copied snapshot, the numerical PASS, and
# the A100 software environment after allocation. Training itself runs from the
# snapshot so a later rsync cannot change an active experiment.
python -m selftrain.scripts.run_integrity verify \
    --root "$PROJECT_ROOT" \
    --manifest "$MANIFEST_PATH" >/dev/null
python -m selftrain.scripts.run_integrity verify \
    --root "$SNAPSHOT_DIR/files" \
    --manifest "$MANIFEST_PATH" >/dev/null
python -m selftrain.scripts.run_integrity validate-pass \
    --pass-path "$PASS_PATH" \
    --manifest "$MANIFEST_PATH" \
    --check-environment >/dev/null

SOURCE_SEMANTIC_SHA256=$(python - "$MANIFEST_PATH" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest["semantic_combined_sha256"])
PY
)
RUN_CONFIG="$SNAPSHOT_DIR/files/selftrain/configs/full.yaml"
CONFIG_SHA256=$(sha256sum "$RUN_CONFIG" | awk '{print $1}')
export AUDATTN_RUN_ID="$RUN_ID"
export AUDATTN_SOURCE_SHA256="$SOURCE_SEMANTIC_SHA256"
export AUDATTN_CONFIG_SHA256="$CONFIG_SHA256"
export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"
export PYTHONPATH="$SNAPSHOT_DIR/files"

CHECKPOINT_MODE=""
CHECKPOINT_PATH=""
if [ "$MODE" = "fork-stage0" ]; then
    CHECKPOINT_MODE="stage-zero"
    CHECKPOINT_PATH="$RUN_ROOT/restart/stage-0.ckpt"
    RECORDED_STAGE0_SHA256=$(python - "$RUN_ROOT/restart/source.json" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(record["sha256"])
PY
)
    ACTUAL_STAGE0_SHA256=$(sha256sum "$CHECKPOINT_PATH" | awk '{print $1}')
    if [ "$RECORDED_STAGE0_SHA256" != "$ACTUAL_STAGE0_SHA256" ]; then
        echo "Prepared stage-zero checkpoint hash mismatch" >&2
        exit 2
    fi
elif [ "$MODE" = "resume" ]; then
    RESUME_KIND="${RESUME_KIND:-epoch}"
    : "${EXPECTED_CKPT_BASENAME:?resume requires an exact checkpoint basename}"
    case "$RESUME_KIND" in
        epoch)
            if [[ ! "$EXPECTED_CKPT_BASENAME" =~ ^(last(-v[1-9][0-9]*)?|pilot4-final)\.ckpt$ ]]; then
                echo "Invalid epoch checkpoint basename: $EXPECTED_CKPT_BASENAME" >&2
                exit 2
            fi
            ;;
        best-effort-rolling)
            if [ "$EXPECTED_CKPT_BASENAME" != "rolling.ckpt" ]; then
                echo "Rolling resume requires rolling.ckpt" >&2
                exit 2
            fi
            echo "WARNING: rolling resume preserves model/optimizer/scaler " \
                 "state but the ordinary DataLoader is not bitwise resumable."
            ;;
        *)
            echo "RESUME_KIND must be epoch or best-effort-rolling" >&2
            exit 2
            ;;
    esac
    CHECKPOINT_DIRECTORY="$RUN_ROOT/full/checkpoints"
    CHECKPOINT_PATH="$CHECKPOINT_DIRECTORY/$EXPECTED_CKPT_BASENAME"
    CHECKPOINT_MODE="resume"
    : "${EXPECTED_CKPT_SHA256:?resume requires EXPECTED_CKPT_SHA256}"
    : "${EXPECTED_CKPT_GLOBAL_STEP:?resume requires EXPECTED_CKPT_GLOBAL_STEP}"
    if ! python -m selftrain.hakusan.checkpoint_reference verify \
        --checkpoint-directory "$CHECKPOINT_DIRECTORY" \
        --resume-kind "$RESUME_KIND" \
        --basename "$EXPECTED_CKPT_BASENAME" \
        --expected-sha256 "$EXPECTED_CKPT_SHA256" \
        --expected-global-step "$EXPECTED_CKPT_GLOBAL_STEP"
    then
        echo "Checkpoint reference changed after submission" >&2
        exit 75
    fi
    FIRST_FULL_CONTINUATION="${FIRST_FULL_CONTINUATION:-0}"
    if [ "$FIRST_FULL_CONTINUATION" != 0 ] \
        && [ "$FIRST_FULL_CONTINUATION" != 1 ]; then
        echo "FIRST_FULL_CONTINUATION must be 0 or 1" >&2
        exit 2
    fi
    if [ "$FIRST_FULL_CONTINUATION" = 1 ]; then
        python - \
            "$STATE_DIR/PILOT4_COMPLETE.json" \
            "$EXPECTED_CKPT_BASENAME" \
            "$EXPECTED_CKPT_SHA256" \
            "$EXPECTED_CKPT_GLOBAL_STEP" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
actual = (sys.argv[2], sys.argv[3], int(sys.argv[4]))
expected = (
    record["checkpoint_basename"],
    record["checkpoint_sha256"],
    int(record["global_step"]),
)
if actual != expected:
    raise SystemExit("First full continuation is not bound to pilot checkpoint")
PY
    fi
fi

cd "$SNAPSHOT_DIR/files"
if [ "$RUN_PHASE" = "pilot4" ]; then
    PILOT_EVALUATION_ROOT="$RUN_ROOT/evaluation/pilot4"
    PILOT_BANK="$PILOT_EVALUATION_ROOT/frozen_bank.tsv"
    PILOT_BANK_STATE="$STATE_DIR/PILOT4_BANK_FROZEN.json"
    mkdir -p "$PILOT_EVALUATION_ROOT"
    if [ "$MODE" = "resume" ]; then
        if [ ! -f "$PILOT_BANK" ] || [ ! -f "$PILOT_BANK_STATE" ]; then
            echo "Pilot resume has no pre-training frozen evaluation bank" >&2
            exit 2
        fi
    elif [ ! -e "$PILOT_BANK" ]; then
        # This runs before spatialtrain/model construction and therefore before
        # any pilot prediction can influence paths, crops, SNRs or cue donors.
        python -m selftrain.scripts.build_full_pilot_eval_bank \
            --config "$RUN_CONFIG" \
            --project-root "$PROJECT_ROOT" \
            --bank-seed 20260816 \
            --output "$PILOT_BANK"
    fi
    python -m selftrain.scripts.build_full_pilot_eval_bank \
        --config "$RUN_CONFIG" \
        --project-root "$PROJECT_ROOT" \
        --bank-seed 20260816 \
        --output "$PILOT_BANK" \
        --validate-only >/dev/null
    PILOT_BANK_SHA256=$(sha256sum "$PILOT_BANK" | awk '{print $1}')
    PILOT_EVALUATOR_SHA256=$(sha256sum \
        "$SNAPSHOT_DIR/files/selftrain/scripts/eval_full_pilot.py" \
        | awk '{print $1}')
    python - \
        "$PILOT_BANK_STATE" \
        "$PILOT_BANK" \
        "$PILOT_BANK_SHA256" \
        "$CONFIG_SHA256" \
        "$SOURCE_SEMANTIC_SHA256" \
        "$PILOT_EVALUATOR_SHA256" \
        "$MODE" <<'PY'
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
expected = {
    "schema_version": 1,
    "status": "FROZEN_BEFORE_PILOT_TRAINING",
    "bank": str(pathlib.Path(sys.argv[2]).resolve()),
    "bank_sha256": sys.argv[3],
    "bank_seed": 20260816,
    "config_sha256": sys.argv[4],
    "source_semantic_sha256": sys.argv[5],
    "evaluator_sha256": sys.argv[6],
    "global_step_before_training": 0,
}
if path.exists():
    record = json.loads(path.read_text(encoding="utf-8"))
    mismatches = {
        key: (record.get(key), value)
        for key, value in expected.items()
        if record.get(key) != value
    }
    if mismatches:
        raise SystemExit(f"Frozen pilot bank state mismatch: {mismatches}")
else:
    if sys.argv[7] != "new":
        raise SystemExit("Only a new pilot may create the bank freeze state")
    record = {
        **expected,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = pathlib.Path(handle.name)
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
PY
    echo "PILOT_BANK_FROZEN_SHA256=$PILOT_BANK_SHA256"
fi
python -m selftrain.scripts.check_readiness --require-all-words
python -m selftrain.scripts.check_training_safety
read -r EXPECTED_COMPLETED_EPOCHS EXPECTED_FINAL_GLOBAL_STEP < <(
    python -m selftrain.scripts.check_training_phase \
        --config "$RUN_CONFIG" \
        --phase "$RUN_PHASE" \
        --tsv
)

if [ "$RUN_PHASE" = "full" ]; then
    FULL_STARTED_PATH="$STATE_DIR/FULL_STARTED.json"
    if [ "${FIRST_FULL_CONTINUATION:-0}" = 1 ]; then
        python -m selftrain.scripts.full_started create \
            --run-root "$RUN_ROOT" \
            --job-id "$SLURM_JOB_ID" >/dev/null
    else
        python -m selftrain.scripts.full_started validate \
            --run-root "$RUN_ROOT" \
            --checkpoint-global-step "$EXPECTED_CKPT_GLOBAL_STEP" \
            >/dev/null
    fi
fi

mkdir -p "$STATE_DIR/jobs"
python - "$STATE_DIR/jobs/${SLURM_JOB_ID}.json" <<'PY'
import datetime as dt
import json
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
record = {
    "job_id": os.environ["SLURM_JOB_ID"],
    "mode": os.environ["MODE"],
    "run_phase": os.environ["RUN_PHASE"],
    "resume_kind": os.environ.get("RESUME_KIND"),
    "run_id": os.environ["RUN_ID"],
    "expected_checkpoint_sha256": os.environ.get("EXPECTED_CKPT_SHA256"),
    "expected_checkpoint_basename": os.environ.get(
        "EXPECTED_CKPT_BASENAME"
    ),
    "expected_checkpoint_global_step": os.environ.get(
        "EXPECTED_CKPT_GLOBAL_STEP"
    ),
    "source_semantic_sha256": os.environ["AUDATTN_SOURCE_SHA256"],
    "config_sha256": os.environ["AUDATTN_CONFIG_SHA256"],
    "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
}
path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PY

TRAIN_ARGS=(
    --config "$RUN_CONFIG"
    --exp_dir "$RUN_ROOT"
    --gpus 1
    --n_jobs 8
    --precision 16-mixed
    --random_seed 20260721
)
if [ "$RUN_PHASE" = "pilot4" ]; then
    PILOT_CHECKPOINT="$RUN_ROOT/full/checkpoints/pilot4-final.ckpt"
    if [ -e "$PILOT_CHECKPOINT" ]; then
        echo "Pilot final checkpoint already exists: $PILOT_CHECKPOINT" >&2
        exit 2
    fi
    TRAIN_ARGS+=(
        --fit_max_epochs 4
        --final_checkpoint_path "$PILOT_CHECKPOINT"
    )
else
    FORMAL_FINAL_CHECKPOINT="$RUN_ROOT/full/checkpoints/formal-final.ckpt"
    if [ -e "$FORMAL_FINAL_CHECKPOINT" ]; then
        echo "Formal final checkpoint already exists: $FORMAL_FINAL_CHECKPOINT" >&2
        exit 2
    fi
    TRAIN_ARGS+=(--final_checkpoint_path "$FORMAL_FINAL_CHECKPOINT")
fi
if [ -n "$CHECKPOINT_MODE" ]; then
    if [ ! -f "$CHECKPOINT_PATH" ]; then
        echo "Checkpoint not found: $CHECKPOINT_PATH" >&2
        exit 2
    fi
    TRAIN_ARGS+=(
        --resume_training
        --checkpoint_mode "$CHECKPOINT_MODE"
        --ckpt_path "$CHECKPOINT_PATH"
    )
fi

echo "Formal training: RUN_ID=$RUN_ID MODE=$MODE PHASE=$RUN_PHASE JOB_ID=$SLURM_JOB_ID"
echo "Frozen source digest: $SOURCE_SEMANTIC_SHA256"
python -u -m src.spatialtrain "${TRAIN_ARGS[@]}"

if [ "$RUN_PHASE" = "pilot4" ]; then
    FINAL_CHECKPOINT="$PILOT_CHECKPOINT"
    FINAL_STATE_PATH="$STATE_DIR/PILOT4_COMPLETE.json"
else
    FINAL_CHECKPOINT="$FORMAL_FINAL_CHECKPOINT"
    FINAL_STATE_PATH="$STATE_DIR/COMPLETE"
fi

python -m selftrain.scripts.finalize_training_phase \
    --checkpoint "$FINAL_CHECKPOINT" \
    --config "$RUN_CONFIG" \
    --phase "$RUN_PHASE" \
    --output "$FINAL_STATE_PATH"
if [ "$RUN_PHASE" = "pilot4" ]; then
    echo "FORMAL TRAINING PILOT4 COMPLETE: RUN_ID=$RUN_ID"
else
    echo "FORMAL TRAINING RUN COMPLETE: RUN_ID=$RUN_ID"
fi
