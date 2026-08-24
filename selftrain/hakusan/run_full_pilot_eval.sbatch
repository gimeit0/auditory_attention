#!/bin/bash
# Frozen 10k full-distribution evaluation for the four-epoch pilot.
# Submit only after state/PILOT4_COMPLETE.json exists:
#   RUN_ID=<id> sbatch --export=ALL selftrain/hakusan/run_full_pilot_eval.sbatch
# The prediction-independent bank must already have been materialised by the
# pilot training runner before the first optimizer step.  This job only
# validates it and never creates PILOT4_GO; a human review record is required.
#SBATCH -J audattn_pilot4_eval
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 12:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/selective_listening_repro/code/auditory_attention
#SBATCH --output=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --error=/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Eeuo pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

PROJECT_ROOT="/home/s2510040/selective_listening_repro/code/auditory_attention"
: "${RUN_ID:?Set RUN_ID to the completed pilot run ID}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "RUN_ID contains unsupported characters: $RUN_ID" >&2
    exit 2
fi
RUN_ROOT="$PROJECT_ROOT/selftrain/experiments/runs/$RUN_ID"
SNAPSHOT_DIR="$RUN_ROOT/snapshot"
STATE_DIR="$RUN_ROOT/state"
MANIFEST="$SNAPSHOT_DIR/manifest.json"
CONFIG="$SNAPSHOT_DIR/files/selftrain/configs/full.yaml"
EVALUATOR="$SNAPSHOT_DIR/files/selftrain/scripts/eval_full_pilot.py"
STAGE0="$RUN_ROOT/full/checkpoints/stage-0.ckpt"
EVALUATION_ROOT="$RUN_ROOT/evaluation/pilot4"
BANK="$EVALUATION_ROOT/frozen_bank.tsv"
PYTHON="$HOME/miniconda3/envs/attn/bin/python"

for required in \
    "$STATE_DIR/PILOT4_COMPLETE.json" \
    "$STATE_DIR/cue_control_release.json" \
    "$MANIFEST" \
    "$CONFIG" \
    "$EVALUATOR" \
    "$STAGE0"
do
    if [ ! -f "$required" ]; then
        echo "Required pilot-evaluation input is missing: $required" >&2
        exit 2
    fi
done
if [ ! -x "$PYTHON" ]; then
    echo "Pinned attn Python is missing: $PYTHON" >&2
    exit 2
fi
if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required for duplicate evaluator protection" >&2
    exit 2
fi
mkdir -p "$EVALUATION_ROOT" "$PROJECT_ROOT/selftrain/hakusan/logs"
exec 8>"$EVALUATION_ROOT/evaluation.lock"
if ! flock -n 8; then
    echo "Another pilot evaluator is active for RUN_ID=$RUN_ID" >&2
    exit 75
fi

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"
cd "$PROJECT_ROOT"
"$PYTHON" -m selftrain.scripts.run_integrity verify \
    --root "$PROJECT_ROOT" --manifest "$MANIFEST" >/dev/null
"$PYTHON" -m selftrain.scripts.run_integrity verify \
    --root "$SNAPSHOT_DIR/files" --manifest "$MANIFEST" >/dev/null

export PYTHONPATH="$SNAPSHOT_DIR/files"
export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"
cd "$SNAPSHOT_DIR/files"

# The bank must predate pilot predictions.  Refuse to create it here, because
# doing so after seeing four-epoch metrics would weaken prediction independence.
if [ ! -f "$BANK" ] || [ ! -f "$STATE_DIR/PILOT4_BANK_FROZEN.json" ]; then
    echo "Pre-training PILOT4 bank/state is missing; evaluation is forbidden" >&2
    exit 2
fi
"$PYTHON" -m selftrain.scripts.build_full_pilot_eval_bank \
    --config "$CONFIG" \
    --project-root "$PROJECT_ROOT" \
    --bank-seed 20260816 \
    --output "$BANK" \
    --validate-only
BANK_SHA256=$(sha256sum "$BANK" | awk '{print $1}')
if [ -n "${EXPECTED_BANK_SHA256:-}" ] \
    && [ "$BANK_SHA256" != "$EXPECTED_BANK_SHA256" ]; then
    echo "Frozen bank differs from EXPECTED_BANK_SHA256" >&2
    exit 2
fi
echo "PILOT_BANK_SHA256=$BANK_SHA256"
"$PYTHON" - "$STATE_DIR/PILOT4_BANK_FROZEN.json" "$BANK" "$BANK_SHA256" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = (str(pathlib.Path(sys.argv[2]).resolve()), sys.argv[3], 0)
actual = (
    record.get("bank"),
    record.get("bank_sha256"),
    int(record.get("global_step_before_training", -1)),
)
if actual != expected:
    raise SystemExit(
        f"Pre-training pilot bank state mismatch: actual={actual}, "
        f"expected={expected}"
    )
PY

read -r PILOT_PATH PILOT_SHA256 PILOT_RUN_ID PILOT_STEP < <(
    "$PYTHON" - "$STATE_DIR/PILOT4_COMPLETE.json" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    record["checkpoint"],
    record["checkpoint_sha256"],
    record["run_id"],
    record["global_step"],
)
PY
)
if [ "$PILOT_RUN_ID" != "$RUN_ID" ] || [ "$PILOT_STEP" != 6944 ]; then
    echo "PILOT4_COMPLETE identity is inconsistent with RUN_ID/pilot4" >&2
    exit 2
fi
CONFIG_SHA256=$(sha256sum "$CONFIG" | awk '{print $1}')
SOURCE_MANIFEST_SHA256=$(sha256sum "$MANIFEST" | awk '{print $1}')
SOURCE_SEMANTIC_SHA256=$("$PYTHON" - "$MANIFEST" <<'PY'
import json
import pathlib
import sys

print(json.loads(pathlib.Path(sys.argv[1]).read_text(
    encoding="utf-8"
))["semantic_combined_sha256"])
PY
)
STAGE0_SHA256=$(sha256sum "$STAGE0" | awk '{print $1}')

JOB_ROOT="$EVALUATION_ROOT/jobs/$SLURM_JOB_ID"
if [ -e "$JOB_ROOT" ]; then
    echo "Pilot evaluation job output already exists: $JOB_ROOT" >&2
    exit 2
fi
mkdir -p "$JOB_ROOT"
RESULTS="$JOB_ROOT/per_trial_results.csv"
SUMMARY="$JOB_ROOT/PILOT4_EVAL.json"

"$PYTHON" -m selftrain.scripts.eval_full_pilot \
    --run-id "$RUN_ID" \
    --project-root "$PROJECT_ROOT" \
    --config "$CONFIG" \
    --source-manifest "$MANIFEST" \
    --bank "$BANK" \
    --bank-freeze-state "$STATE_DIR/PILOT4_BANK_FROZEN.json" \
    --stage0-checkpoint "$STAGE0" \
    --pilot-checkpoint "$PILOT_PATH" \
    --output "$RESULTS" \
    --summary "$SUMMARY" \
    --expected-bank-sha256 "$BANK_SHA256" \
    --expected-config-sha256 "$CONFIG_SHA256" \
    --expected-source-manifest-sha256 "$SOURCE_MANIFEST_SHA256" \
    --expected-source-semantic-sha256 "$SOURCE_SEMANTIC_SHA256" \
    --expected-stage0-sha256 "$STAGE0_SHA256" \
    --expected-pilot-sha256 "$PILOT_SHA256" \
    --expected-bank-seed 20260816 \
    --batch-size 16 \
    --cache-items 512 \
    --seed 20260816

echo "PILOT4_RESULTS=$RESULTS"
echo "PILOT4_SUMMARY=$SUMMARY"
echo "Evaluation is complete; inspect PILOT4_EVAL.json before writing review."
echo "PILOT4_GO is intentionally not created by this GPU job."
