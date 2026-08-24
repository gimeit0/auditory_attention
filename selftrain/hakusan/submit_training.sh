#!/bin/bash
# Run this wrapper on the HAKUSAN login node. It performs all cheap validation
# before placing a guarded A100 job in the queue.
set -Eeuo pipefail

PROJECT_ROOT="/home/s2510040/selective_listening_repro/code/auditory_attention"
cd "$PROJECT_ROOT"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"

: "${RUN_ID:?Set a unique RUN_ID, for example task2a_20260801_v2}"
MODE="${MODE:-new}"
RUN_PHASE="${RUN_PHASE:-pilot4}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "RUN_ID contains unsupported characters: $RUN_ID" >&2
    exit 2
fi
case "$MODE" in
    new|fork-stage0|fork-resume|resume) ;;
    *)
        echo "MODE must be new, fork-stage0, fork-resume, or resume" >&2
        exit 2
        ;;
esac
case "$RUN_PHASE" in
    pilot4|full) ;;
    *)
        echo "RUN_PHASE must be pilot4 or full" >&2
        exit 2
        ;;
esac
if [ "$RUN_PHASE" = "pilot4" ] \
    && [ "$MODE" != "new" ] \
    && [ "$MODE" != "resume" ]; then
    echo "pilot4 supports only MODE=new or MODE=resume" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "full" ] && [ "$MODE" != "resume" ]; then
    echo "RUN_PHASE=full is allowed only as MODE=resume after pilot review" >&2
    exit 2
fi

RESUME_KIND="${RESUME_KIND:-epoch}"
if [ -z "${TRAIN_TIME:-}" ]; then
    if [ "$RUN_PHASE" = "pilot4" ]; then
        TRAIN_TIME="1-12:00:00"
    else
        TRAIN_TIME="4-00:00:00"
    fi
fi
python - "$TRAIN_TIME" <<'PY'
import re
import sys

value = sys.argv[1]
match = re.fullmatch(r"(?:(\d+)-)?(\d+):(\d{2}):(\d{2})", value)
if match is None:
    raise SystemExit(
        "TRAIN_TIME must look like HH:MM:SS or D-HH:MM:SS"
    )
days, hours, minutes, seconds = match.groups()
if days is not None and int(hours) >= 24:
    raise SystemExit("D-HH:MM:SS requires HH < 24")
if int(minutes) >= 60 or int(seconds) >= 60:
    raise SystemExit("TRAIN_TIME minutes and seconds must be below 60")
if int(days or 0) == int(hours) == int(minutes) == int(seconds) == 0:
    raise SystemExit("TRAIN_TIME must be positive")
PY

JOB_MODE="$MODE"
if [ "$MODE" = "fork-resume" ]; then
    JOB_MODE="resume"
fi

for command_name in sbatch squeue flock sha256sum python; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required command is unavailable: $command_name" >&2
        exit 2
    fi
done

RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$RUN_ID"
SNAPSHOT_DIR="$RUN_ROOT/snapshot"
STATE_DIR="$RUN_ROOT/state"
RUN_ID_TAG=$(printf '%s' "$RUN_ID" | sha256sum | cut -c1-8)
JOB_NAME="aud_${RUN_ID:0:28}_${RUN_ID_TAG}"
SBATCH_SCRIPT="$PROJECT_ROOT/selftrain/hakusan/run_training.sbatch"

SUBMISSION_LOCK_DIR="$PROJECT_ROOT/selftrain/experiments/submission_locks"
mkdir -p "$SUBMISSION_LOCK_DIR"
exec 8>"$SUBMISSION_LOCK_DIR/${RUN_ID}.lock"
if ! flock -n 8; then
    echo "Another submission process is handling RUN_ID=$RUN_ID" >&2
    exit 75
fi

if squeue -u "$USER" -h -o "%j" | grep -Fxq "$JOB_NAME"; then
    echo "A PD/R job already exists for RUN_ID=$RUN_ID ($JOB_NAME)" >&2
    exit 75
fi

python -m selftrain.hakusan.test_fork_resume_checkpoint
python -m selftrain.hakusan.test_checkpoint_reference
python -m selftrain.scripts.test_run_integrity
python -m selftrain.scripts.test_training_phase
python -m selftrain.scripts.test_cue_control_release
python -m selftrain.scripts.test_finalize_training_phase
python -m selftrain.scripts.test_full_started
python -m selftrain.scripts.test_full_pilot_eval
python -m selftrain.scripts.test_pilot_release
python -m selftrain.scripts.check_training_safety
python -m selftrain.scripts.check_training_phase \
    --config selftrain/configs/full.yaml \
    --phase "$RUN_PHASE"
if [ "$MODE" = "new" ] && [ "$RUN_PHASE" = "pilot4" ]; then
    : "${CUE_CONTROL_JOB_ROOT:?new pilot4 requires a CONFIRMATORY_PASS CUE_CONTROL_JOB_ROOT}"
    python -m selftrain.scripts.check_cue_control_release \
        --job-root "$CUE_CONTROL_JOB_ROOT"
fi

PREPARING_ROOT=""
cleanup_preparing_root() {
    if [ -n "$PREPARING_ROOT" ] && [ -d "$PREPARING_ROOT" ]; then
        rm -rf -- "$PREPARING_ROOT"
    fi
}
trap cleanup_preparing_root EXIT

if [ "$MODE" = "new" ] \
    || [ "$MODE" = "fork-stage0" ] \
    || [ "$MODE" = "fork-resume" ]; then
    : "${NUMERICS_PASS:?new/fork-stage0/fork-resume requires NUMERICS_PASS}"
    if [ ! -f "$NUMERICS_PASS" ]; then
        echo "Numerical-preflight PASS not found: $NUMERICS_PASS" >&2
        exit 2
    fi

    if [ ! -e "$RUN_ROOT" ]; then
        PREPARING_ROOT="${RUN_ROOT}.preparing.$$"
        if [ -e "$PREPARING_ROOT" ]; then
            echo "Preparation path already exists: $PREPARING_ROOT" >&2
            exit 2
        fi
        mkdir -p "$PREPARING_ROOT/state"
        if [ "$MODE" = "new" ] && [ "$RUN_PHASE" = "pilot4" ]; then
            python -m selftrain.scripts.check_cue_control_release \
                --job-root "$CUE_CONTROL_JOB_ROOT" \
                --output "$PREPARING_ROOT/state/cue_control_release.json" \
                >/dev/null
        fi
        python -m selftrain.scripts.run_integrity snapshot \
            --root "$PROJECT_ROOT" \
            --output-dir "$PREPARING_ROOT/snapshot" >/dev/null
        python -m selftrain.scripts.run_integrity validate-pass \
            --pass-path "$NUMERICS_PASS" \
            --manifest "$PREPARING_ROOT/snapshot/manifest.json" >/dev/null
        python - "$NUMERICS_PASS" <<'PY'
import json
import pathlib
import sys

result = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
gpu_name = (result.get("environment", {}).get("gpu") or {}).get("name")
if gpu_name != "NVIDIA A100-PCIE-40GB":
    raise SystemExit(
        "Formal GPU-1A training requires an A100 numerical PASS; "
        f"got gpu={gpu_name!r}"
    )
PY
        cp "$NUMERICS_PASS" "$PREPARING_ROOT/snapshot/numerics_PASS.json"

        if [ "$MODE" = "fork-stage0" ]; then
            : "${CKPT_PATH:?fork-stage0 requires CKPT_PATH}"
            if [ ! -f "$CKPT_PATH" ]; then
                echo "Stage-zero checkpoint not found: $CKPT_PATH" >&2
                exit 2
            fi
            python - "$CKPT_PATH" <<'PY'
import sys
from src.spatialtrain import _validate_resume_checkpoint

_validate_resume_checkpoint(sys.argv[1], "stage-zero")
PY
            mkdir -p "$PREPARING_ROOT/restart"
            cp "$CKPT_PATH" "$PREPARING_ROOT/restart/stage-0.ckpt"
            SOURCE_CKPT_SHA256=$(sha256sum "$CKPT_PATH" | awk '{print $1}')
            COPIED_CKPT_SHA256=$(sha256sum \
                "$PREPARING_ROOT/restart/stage-0.ckpt" | awk '{print $1}')
            if [ "$SOURCE_CKPT_SHA256" != "$COPIED_CKPT_SHA256" ]; then
                echo "Copied stage-zero checkpoint hash mismatch" >&2
                exit 2
            fi
            python - \
                "$PREPARING_ROOT/restart/source.json" \
                "$CKPT_PATH" \
                "$SOURCE_CKPT_SHA256" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "original_path": str(pathlib.Path(sys.argv[2]).resolve()),
            "sha256": sys.argv[3],
            "global_step": 0,
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
        fi

        if [ "$MODE" = "fork-resume" ]; then
            : "${PARENT_RUN_ID:?fork-resume requires PARENT_RUN_ID}"
            : "${EXPECTED_FORK_GLOBAL_STEP:?fork-resume requires EXPECTED_FORK_GLOBAL_STEP}"
            if [[ ! "$PARENT_RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
                echo "PARENT_RUN_ID contains unsupported characters" >&2
                exit 2
            fi
            if [ "$PARENT_RUN_ID" = "$RUN_ID" ]; then
                echo "PARENT_RUN_ID and RUN_ID must differ" >&2
                exit 2
            fi
            if ! [[ "$EXPECTED_FORK_GLOBAL_STEP" =~ ^[1-9][0-9]*$ ]]; then
                echo "EXPECTED_FORK_GLOBAL_STEP must be a positive integer" >&2
                exit 2
            fi
            EXPECTED_FORK_AMP_OVERFLOWS="${EXPECTED_FORK_AMP_OVERFLOWS:-0}"
            if ! [[ "$EXPECTED_FORK_AMP_OVERFLOWS" =~ ^[0-9]+$ ]]; then
                echo "EXPECTED_FORK_AMP_OVERFLOWS must be nonnegative" >&2
                exit 2
            fi
            case "$RESUME_KIND" in
                epoch)
                    : "${PARENT_CHECKPOINT_BASENAME:?fork-resume epoch requires PARENT_CHECKPOINT_BASENAME}"
                    if [[ ! "$PARENT_CHECKPOINT_BASENAME" =~ ^last(-v[1-9][0-9]*)?\.ckpt$ ]]; then
                        echo "Invalid parent epoch checkpoint basename" >&2
                        exit 2
                    fi
                    SOURCE_CHECKPOINT_NAME="$PARENT_CHECKPOINT_BASENAME"
                    TARGET_CHECKPOINT_NAME="last.ckpt"
                    ;;
                best-effort-rolling)
                    SOURCE_CHECKPOINT_NAME="rolling.ckpt"
                    TARGET_CHECKPOINT_NAME="rolling.ckpt"
                    echo "WARNING: rolling checkpoints do not preserve an " \
                         "ordinary DataLoader cursor bit-for-bit."
                    ;;
                *)
                    echo "RESUME_KIND must be epoch or best-effort-rolling" >&2
                    exit 2
                    ;;
            esac

            PARENT_RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$PARENT_RUN_ID"
            PARENT_STATE_DIR="$PARENT_RUN_ROOT/state"
            PARENT_SNAPSHOT_DIR="$PARENT_RUN_ROOT/snapshot"
            PARENT_CHECKPOINT="$PARENT_RUN_ROOT/full/checkpoints/$SOURCE_CHECKPOINT_NAME"
            for required in \
                "$PARENT_STATE_DIR/PREPARED.json" \
                "$PARENT_SNAPSHOT_DIR/manifest.json" \
                "$PARENT_SNAPSHOT_DIR/files/selftrain/configs/full.yaml" \
                "$PARENT_CHECKPOINT"
            do
                if [ ! -f "$required" ]; then
                    echo "Parent-run file is missing: $required" >&2
                    exit 2
                fi
            done
            if [ -e "$PARENT_STATE_DIR/COMPLETE" ]; then
                echo "Parent run is already complete; fork-resume is unnecessary" >&2
                exit 2
            fi
            python - \
                "$PARENT_STATE_DIR/PREPARED.json" \
                "$PARENT_RUN_ID" <<'PY'
import json
import pathlib
import sys

prepared = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if prepared.get("run_id") != sys.argv[2]:
    raise SystemExit(
        "Parent PREPARED.json run_id mismatch: "
        f"{prepared.get('run_id')!r} != {sys.argv[2]!r}"
    )
PY
            PARENT_RUN_ID_TAG=$(printf '%s' "$PARENT_RUN_ID" \
                | sha256sum | cut -c1-8)
            PARENT_JOB_NAME="aud_${PARENT_RUN_ID:0:28}_${PARENT_RUN_ID_TAG}"
            if squeue -u "$USER" -h -o "%j" \
                | grep -Fxq "$PARENT_JOB_NAME"; then
                echo "Parent run still has a pending/running job: $PARENT_JOB_NAME" >&2
                exit 75
            fi
            exec 7>"$PARENT_STATE_DIR/run.lock"
            if ! flock -n 7; then
                echo "Parent run is currently being written: $PARENT_RUN_ID" >&2
                exit 75
            fi
            python -m selftrain.scripts.run_integrity verify \
                --root "$PARENT_SNAPSHOT_DIR/files" \
                --manifest "$PARENT_SNAPSHOT_DIR/manifest.json" >/dev/null

            if [ -L "$PARENT_CHECKPOINT" ]; then
                echo "Parent checkpoint must not be a symlink" >&2
                exit 2
            fi
            TARGET_CHECKPOINT="$PREPARING_ROOT/full/checkpoints/$TARGET_CHECKPOINT_NAME"
            LINEAGE_PATH="$PREPARING_ROOT/restart/fork_resume_lineage.json"
            ALLOWED_CHANGE_PATHS=(
                "src/spatial_attn_lightning.py"
                "selftrain/scripts/check_training_safety.py"
            )
            FORK_ARGS=()
            for changed_path in "${ALLOWED_CHANGE_PATHS[@]}"; do
                if [ -z "$changed_path" ]; then
                    echo "Internal fork semantic-change whitelist is invalid" >&2
                    exit 2
                fi
                FORK_ARGS+=(--allowed-semantic-change "$changed_path")
            done
            echo "Preparing an immutable fork-resume checkpoint copy..."
            echo "Parent: $PARENT_CHECKPOINT"
            echo "Expected parent global_step: $EXPECTED_FORK_GLOBAL_STEP"
            (
                cd "$PREPARING_ROOT/snapshot/files"
                PYTHONPATH="$PREPARING_ROOT/snapshot/files" \
                    python -m selftrain.hakusan.fork_resume_checkpoint \
                    --source-run-root "$PARENT_RUN_ROOT" \
                    --target-run-root "$PREPARING_ROOT" \
                    --target-logical-run-root "$RUN_ROOT" \
                    --source-run-id "$PARENT_RUN_ID" \
                    --target-run-id "$RUN_ID" \
                    --source-checkpoint "$PARENT_CHECKPOINT" \
                    --target-checkpoint "$TARGET_CHECKPOINT" \
                    --source-manifest "$PARENT_SNAPSHOT_DIR/manifest.json" \
                    --target-manifest "$PREPARING_ROOT/snapshot/manifest.json" \
                    --numerics-pass "$PREPARING_ROOT/snapshot/numerics_PASS.json" \
                    --lineage "$LINEAGE_PATH" \
                    --resume-kind "$RESUME_KIND" \
                    --expected-global-step "$EXPECTED_FORK_GLOBAL_STEP" \
                    --expected-amp-overflows "$EXPECTED_FORK_AMP_OVERFLOWS" \
                    --reason "continue after AMP overflow logging fix" \
                    "${FORK_ARGS[@]}" >/dev/null
            )
            echo "Fork-resume checkpoint validation: PASS"
            RESUME_CHECKPOINT_BASENAME="$TARGET_CHECKPOINT_NAME"
        fi

        python - \
            "$PREPARING_ROOT/state/PREPARED.json" \
            "$MODE" \
            "$JOB_MODE" \
            "$RUN_ID" \
            "${PARENT_RUN_ID:-}" \
            "$RESUME_KIND" \
            "$RUN_PHASE" \
            "${SOURCE_CHECKPOINT_NAME:-}" <<'PY'
import datetime as dt
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "mode": sys.argv[2],
            "job_mode": sys.argv[3],
            "run_id": sys.argv[4],
            "parent_run_id": sys.argv[5] or None,
            "resume_kind": sys.argv[6],
            "initial_run_phase": sys.argv[7],
            "parent_checkpoint_basename": sys.argv[8] or None,
            "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
        mv "$PREPARING_ROOT" "$RUN_ROOT"
        PREPARING_ROOT=""
    else
        if [ ! -f "$STATE_DIR/PREPARED.json" ]; then
            echo "RUN_ID exists but is not a prepared run: $RUN_ROOT" >&2
            exit 2
        fi
        PREPARED_MODE=$(python - "$STATE_DIR/PREPARED.json" <<'PY'
import json
import pathlib
import sys

print(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["mode"])
PY
)
        if [ "$PREPARED_MODE" != "$MODE" ]; then
            echo "Prepared mode is $PREPARED_MODE, requested mode is $MODE" >&2
            exit 2
        fi
        if find "$RUN_ROOT/full/checkpoints" -type f -name '*.ckpt' \
            -print -quit 2>/dev/null | grep -q .; then
            echo "RUN_ID already has training checkpoints; use MODE=resume" >&2
            exit 2
        fi
    fi
else
    if [ ! -f "$STATE_DIR/PREPARED.json" ]; then
        echo "Cannot resume an unprepared RUN_ID: $RUN_ROOT" >&2
        exit 2
    fi
    if [ -e "$STATE_DIR/COMPLETE" ]; then
        echo "Run is already marked COMPLETE: $RUN_ID" >&2
        exit 2
    fi
fi

if [ "$RUN_PHASE" = "pilot4" ] \
    && [ -e "$STATE_DIR/PILOT4_COMPLETE.json" ]; then
    echo "Four-epoch pilot is already complete: $RUN_ID" >&2
    exit 2
fi
if [ "$RUN_PHASE" = "full" ] \
    && [ "$MODE" = "resume" ] \
    && [ ! -f "$STATE_DIR/PILOT4_COMPLETE.json" ]; then
    echo "Full continuation requires state/PILOT4_COMPLETE.json" >&2
    exit 2
fi

FIRST_FULL_CONTINUATION=0
if [ "$RUN_PHASE" = "full" ]; then
    python -m selftrain.scripts.pilot_release validate \
        --run-root "$RUN_ROOT" >/dev/null
    if [ ! -f "$STATE_DIR/FULL_STARTED.json" ]; then
        FIRST_FULL_CONTINUATION=1
        if [ "$RESUME_KIND" != "epoch" ]; then
            echo "First full continuation must use the pilot epoch checkpoint" >&2
            exit 2
        fi
        PILOT_CHECKPOINT_BASENAME=$(python - \
            "$STATE_DIR/PILOT4_COMPLETE.json" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(record["checkpoint_basename"])
PY
)
        if [ -n "${RESUME_CHECKPOINT_BASENAME:-}" ] \
            && [ "$RESUME_CHECKPOINT_BASENAME" != "$PILOT_CHECKPOINT_BASENAME" ]; then
            echo "First full continuation must use $PILOT_CHECKPOINT_BASENAME" >&2
            exit 2
        fi
        RESUME_CHECKPOINT_BASENAME="$PILOT_CHECKPOINT_BASENAME"
    else
        python -m selftrain.scripts.full_started validate \
            --run-root "$RUN_ROOT" >/dev/null
    fi
fi
if [ "$RUN_PHASE" = "full" ] \
    && [ "$MODE" = "resume" ] \
    && [ ! -f "$STATE_DIR/PILOT4_GO.json" ]; then
    echo "Full continuation requires a reviewed state/PILOT4_GO.json" >&2
    exit 2
fi
# Recompute the confirmatory cue gate from its frozen per-trial CSV on every
# pilot/full submission, not only when the run directory is first prepared.
python -m selftrain.scripts.check_cue_control_release \
    --release-record "$STATE_DIR/cue_control_release.json" >/dev/null

python -m selftrain.scripts.run_integrity verify \
    --root "$PROJECT_ROOT" \
    --manifest "$SNAPSHOT_DIR/manifest.json" >/dev/null
python -m selftrain.scripts.run_integrity verify \
    --root "$SNAPSHOT_DIR/files" \
    --manifest "$SNAPSHOT_DIR/manifest.json" >/dev/null
python -m selftrain.scripts.run_integrity validate-pass \
    --pass-path "$SNAPSHOT_DIR/numerics_PASS.json" \
    --manifest "$SNAPSHOT_DIR/manifest.json" >/dev/null

SOURCE_SEMANTIC_SHA256=$(python - "$SNAPSHOT_DIR/manifest.json" <<'PY'
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

EXPECTED_CKPT_SHA256=""
EXPECTED_CKPT_BASENAME=""
EXPECTED_CKPT_GLOBAL_STEP=""
if [ "$JOB_MODE" = "resume" ]; then
    case "$RESUME_KIND" in
        epoch)
            : "${RESUME_CHECKPOINT_BASENAME:?epoch resume requires RESUME_CHECKPOINT_BASENAME}"
            if [[ ! "$RESUME_CHECKPOINT_BASENAME" =~ ^(last(-v[1-9][0-9]*)?|pilot4-final)\.ckpt$ ]]; then
                echo "Invalid epoch checkpoint basename: $RESUME_CHECKPOINT_BASENAME" >&2
                exit 2
            fi
            EXPECTED_CKPT_BASENAME="$RESUME_CHECKPOINT_BASENAME"
            ;;
        best-effort-rolling)
            if [ -n "${RESUME_CHECKPOINT_BASENAME:-}" ] \
                && [ "$RESUME_CHECKPOINT_BASENAME" != "rolling.ckpt" ]; then
                echo "best-effort-rolling cannot select an epoch checkpoint" >&2
                exit 2
            fi
            EXPECTED_CKPT_BASENAME="rolling.ckpt"
            ;;
        *)
            echo "RESUME_KIND must be epoch or best-effort-rolling" >&2
            exit 2
            ;;
    esac
    CHECKPOINT_DIRECTORY="$RUN_ROOT/full/checkpoints"
    read -r \
        EXPECTED_CKPT_BASENAME \
        EXPECTED_CKPT_SHA256 \
        EXPECTED_CKPT_GLOBAL_STEP < <(
            python -m selftrain.hakusan.checkpoint_reference lock \
                --checkpoint-directory "$CHECKPOINT_DIRECTORY" \
                --resume-kind "$RESUME_KIND" \
                --basename "$EXPECTED_CKPT_BASENAME"
        )
    CHECKPOINT_PATH="$CHECKPOINT_DIRECTORY/$EXPECTED_CKPT_BASENAME"
    python - "$CHECKPOINT_PATH" <<'PY'
import sys
from src.spatialtrain import _validate_resume_checkpoint

_validate_resume_checkpoint(sys.argv[1], "resume")
PY
    if ! [[ "$EXPECTED_CKPT_GLOBAL_STEP" =~ ^[1-9][0-9]*$ ]]; then
        echo "Could not lock resume checkpoint global_step" >&2
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
    raise SystemExit(
        f"First full checkpoint does not match pilot completion: "
        f"actual={actual}, expected={expected}"
    )
PY
    elif [ "$RUN_PHASE" = "full" ]; then
        python -m selftrain.scripts.full_started validate \
            --run-root "$RUN_ROOT" \
            --checkpoint-global-step "$EXPECTED_CKPT_GLOBAL_STEP" \
            >/dev/null
    fi
fi

EXPORTS="ALL,MODE=$JOB_MODE,RUN_ID=$RUN_ID,RUN_PHASE=$RUN_PHASE,RESUME_KIND=$RESUME_KIND"
EXPORTS="$EXPORTS,FIRST_FULL_CONTINUATION=$FIRST_FULL_CONTINUATION"
if [ -n "$EXPECTED_CKPT_SHA256" ]; then
    EXPORTS="$EXPORTS,EXPECTED_CKPT_BASENAME=$EXPECTED_CKPT_BASENAME"
    EXPORTS="$EXPORTS,EXPECTED_CKPT_SHA256=$EXPECTED_CKPT_SHA256"
    EXPORTS="$EXPORTS,EXPECTED_CKPT_GLOBAL_STEP=$EXPECTED_CKPT_GLOBAL_STEP"
fi

echo "Checking Slurm request without submitting..."
sbatch --test-only \
    --job-name="$JOB_NAME" \
    --time="$TRAIN_TIME" \
    --export="$EXPORTS" \
    "$SBATCH_SCRIPT"

JOB_ID=$(sbatch --parsable \
    --job-name="$JOB_NAME" \
    --time="$TRAIN_TIME" \
    --export="$EXPORTS" \
    "$SBATCH_SCRIPT")

mkdir -p "$STATE_DIR/submissions"
python - \
    "$STATE_DIR/submissions/${JOB_ID}.json" \
    "$JOB_ID" \
    "$MODE" \
    "$JOB_MODE" \
    "$RUN_ID" \
    "$RUN_PHASE" \
    "$RESUME_KIND" \
    "$EXPECTED_CKPT_BASENAME" \
    "$EXPECTED_CKPT_SHA256" \
    "$EXPECTED_CKPT_GLOBAL_STEP" \
    "$TRAIN_TIME" \
    "${PARENT_RUN_ID:-}" <<'PY'
import datetime as dt
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "job_id": sys.argv[2],
            "requested_mode": sys.argv[3],
            "job_mode": sys.argv[4],
            "run_id": sys.argv[5],
            "run_phase": sys.argv[6],
            "resume_kind": sys.argv[7],
            "expected_checkpoint_basename": sys.argv[8] or None,
            "expected_checkpoint_sha256": sys.argv[9] or None,
            "expected_checkpoint_global_step": (
                int(sys.argv[10]) if sys.argv[10] else None
            ),
            "requested_time": sys.argv[11],
            "parent_run_id": sys.argv[12] or None,
            "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY

echo "Submitted training Job ID: $JOB_ID"
echo "RUN_ID: $RUN_ID"
echo "RUN_PHASE: $RUN_PHASE"
echo "Requested walltime: $TRAIN_TIME"
echo "Check queue: squeue -j $JOB_ID"
echo "Estimated start: squeue --start -j $JOB_ID"
