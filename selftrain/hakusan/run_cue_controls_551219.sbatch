#!/bin/bash
# Frozen, paired cue-counterfactual evaluation for Job 551219.
# Default: independent 32-trial reproducibility smoke test.
# Full 10k run requires the formal manifest and evaluation-code SHA values
# printed by a successful smoke job.
#
# Smoke (mode is deliberately explicit to defeat inherited shell variables):
#   sbatch --export=ALL,CUE_CONTROL_MODE=smoke \
#     selftrain/hakusan/run_cue_controls_551219.sbatch
# Full (after smoke PASS):
#   sbatch --export=ALL,CUE_CONTROL_MODE=full,EXPECTED_MANIFEST_SHA256=<sha>,EXPECTED_EVAL_CODE_SHA256=<sha> \
#     selftrain/hakusan/run_cue_controls_551219.sbatch
#SBATCH -J audattn_cuectrl_551219
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 04:00:00
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
PYTHON="$HOME/miniconda3/envs/attn/bin/python"
[ -x "$PYTHON" ] || { echo "Missing attn Python: $PYTHON" >&2; exit 2; }

export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"
export PYTHONPATH="$PROJECT_ROOT"
export CUBLAS_WORKSPACE_CONFIG=:4096:8

TRAIN_JOB=551219
TRAIN_ROOT="$PROJECT_ROOT/selftrain/experiments/diag_1dist_0db_20ep/$TRAIN_JOB"
CONFIG="$TRAIN_ROOT/config.yaml"
CHECKPOINT="$TRAIN_ROOT/diag_1dist_0db_20ep/checkpoints/last.ckpt"
RUN_METADATA="$TRAIN_ROOT/run_metadata.env"
SOURCE_MANIFEST="$TRAIN_ROOT/source.sha256"
EXPECTED_CHECKPOINT_SHA256="5662840b2866355b0b27de3cf4e09eafec9f603de178c0177ba2acfa947d935c"
EXPECTED_CONFIG_SHA256="1260fa688aad2cfc127c5051301c5b562443383383a288ccdc3e1b42cfd4e838"

RESULT_ROOT="$PROJECT_ROOT/selftrain/experiments/cue_controls/job551219"
SMOKE_BANK="$RESULT_ROOT/cue_control_smoke_32_seed20260814.tsv"
FORMAL_BANK="$RESULT_ROOT/cue_control_bank_10000_seed20260815.tsv"
mkdir -p "$RESULT_ROOT" "$RESULT_ROOT/jobs"

echo "Verifying the exact live files used by Job $TRAIN_JOB..."
(cd "$PROJECT_ROOT" && sha256sum -c "$SOURCE_MANIFEST")
ACTUAL_SOURCE_MANIFEST_SHA256=$(sha256sum "$SOURCE_MANIFEST" | awk '{print $1}')
RECORDED_SOURCE_MANIFEST_SHA256=$(awk -F= '$1=="AUDATTN_SOURCE_SHA256"{print $2}' "$RUN_METADATA")
[ "$ACTUAL_SOURCE_MANIFEST_SHA256" = "$RECORDED_SOURCE_MANIFEST_SHA256" ] || {
    echo "Frozen source manifest SHA does not match run_metadata.env" >&2
    exit 2
}
ACTUAL_CKPT_SHA256=$(sha256sum "$CHECKPOINT" | awk '{print $1}')
ACTUAL_CONFIG_SHA256=$(sha256sum "$CONFIG" | awk '{print $1}')
[ "$ACTUAL_CKPT_SHA256" = "$EXPECTED_CHECKPOINT_SHA256" ] || {
    echo "Frozen checkpoint SHA mismatch" >&2
    exit 2
}
[ "$ACTUAL_CONFIG_SHA256" = "$EXPECTED_CONFIG_SHA256" ] || {
    echo "Frozen config SHA mismatch" >&2
    exit 2
}

: "${CUE_CONTROL_MODE:?submit with explicit CUE_CONTROL_MODE=smoke or full}"
case "$CUE_CONTROL_MODE" in
    smoke|full) ;;
    *) echo "CUE_CONTROL_MODE must be smoke or full" >&2; exit 2 ;;
esac

ensure_bank () {
    local bank=$1
    local trials=$2
    local seed=$3
    if [ ! -f "$bank" ]; then
        "$PYTHON" -u -m selftrain.scripts.build_cue_control_manifest \
            --config "$CONFIG" \
            --output "$bank" \
            --num-trials "$trials" \
            --bank-seed "$seed" \
            --project-root "$PROJECT_ROOT"
    fi
    "$PYTHON" -u -m selftrain.scripts.build_cue_control_manifest \
        --config "$CONFIG" \
        --output "$bank" \
        --num-trials "$trials" \
        --bank-seed "$seed" \
        --project-root "$PROJECT_ROOT" \
        --validate-only
}

exec 9>"$RESULT_ROOT/bank-build.lock"
flock 9
if [ "$CUE_CONTROL_MODE" = smoke ]; then
    echo "Building/validating independent 32-trial smoke bank..."
    ensure_bank "$SMOKE_BANK" 32 20260814
fi
echo "Building/validating frozen 10,000-trial formal bank..."
ensure_bank "$FORMAL_BANK" 10000 20260815
flock -u 9

FORMAL_MANIFEST_SHA256=$(sha256sum "$FORMAL_BANK" | awk '{print $1}')
BUILDER_SHA256=$(sha256sum selftrain/scripts/build_cue_control_manifest.py | awk '{print $1}')
EVALUATOR_SHA256=$(sha256sum selftrain/scripts/eval_cue_controls.py | awk '{print $1}')
# $0 is Slurm's immutable spool copy of the submitted runner.  Hash its
# contents, not the editable live-tree path, so smoke and full bind the script
# that actually executed.
SUBMITTED_RUNNER_SHA256=$(sha256sum "$0" | awk '{print $1}')
EVAL_CODE_SHA256=$(printf '%s\n' \
    "$BUILDER_SHA256" \
    "$EVALUATOR_SHA256" \
    "$SUBMITTED_RUNNER_SHA256" \
    | sha256sum | awk '{print $1}')
SMOKE_PASS_MARKER="$RESULT_ROOT/smoke_pass.env"

if [ "$CUE_CONTROL_MODE" = full ]; then
    exec 8>"$RESULT_ROOT/full-evaluation.lock"
    flock -n 8 || {
        echo "Another full cue-control evaluation is already active" >&2
        exit 2
    }
    if compgen -G "$RESULT_ROOT/jobs/*/summary_full.json" > /dev/null; then
        echo "A completed full cue-control summary already exists; refusing duplicate GPU work" >&2
        exit 2
    fi
    : "${EXPECTED_MANIFEST_SHA256:?full requires EXPECTED_MANIFEST_SHA256 from smoke}"
    : "${EXPECTED_EVAL_CODE_SHA256:?full requires EXPECTED_EVAL_CODE_SHA256 from smoke}"
    [ "$FORMAL_MANIFEST_SHA256" = "$EXPECTED_MANIFEST_SHA256" ] || {
        echo "Formal cue-control manifest SHA mismatch" >&2
        exit 2
    }
    [ "$EVAL_CODE_SHA256" = "$EXPECTED_EVAL_CODE_SHA256" ] || {
        echo "Evaluation-code SHA mismatch" >&2
        exit 2
    }
    [ -f "$SMOKE_PASS_MARKER" ] || {
        echo "Missing successful smoke marker" >&2
        exit 2
    }
    MARKER_MANIFEST_SHA256=$(awk -F= '$1=="FORMAL_MANIFEST_SHA256"{print $2}' "$SMOKE_PASS_MARKER")
    MARKER_EVAL_CODE_SHA256=$(awk -F= '$1=="EVAL_CODE_SHA256"{print $2}' "$SMOKE_PASS_MARKER")
    [ "$MARKER_MANIFEST_SHA256" = "$FORMAL_MANIFEST_SHA256" ] \
        && [ "$MARKER_EVAL_CODE_SHA256" = "$EVAL_CODE_SHA256" ] || {
        echo "Smoke marker does not match the frozen formal inputs" >&2
        exit 2
    }
    BANK="$FORMAL_BANK"
    EXPECTED_TRIALS=10000
    EXPECTED_BANK_SEED=20260815
    ANALYSIS_KIND=confirmatory
else
    BANK="$SMOKE_BANK"
    EXPECTED_TRIALS=32
    EXPECTED_BANK_SEED=20260814
    ANALYSIS_KIND=smoke
fi
MANIFEST_SHA256=$(sha256sum "$BANK" | awk '{print $1}')

JOB_ROOT="$RESULT_ROOT/jobs/${SLURM_JOB_ID}"
mkdir "$JOB_ROOT"
cp "$0" "$JOB_ROOT/submitted_runner.sbatch"
printf '%s\n' \
    "TRAIN_JOB=$TRAIN_JOB" \
    "CHECKPOINT_SHA256=$ACTUAL_CKPT_SHA256" \
    "CONFIG_SHA256=$ACTUAL_CONFIG_SHA256" \
    "MANIFEST_SHA256=$MANIFEST_SHA256" \
    "FORMAL_MANIFEST_SHA256=$FORMAL_MANIFEST_SHA256" \
    "EVAL_CODE_SHA256=$EVAL_CODE_SHA256" \
    "CUE_CONTROL_MODE=$CUE_CONTROL_MODE" \
    > "$JOB_ROOT/frozen_inputs.env"
sha256sum \
    selftrain/scripts/build_cue_control_manifest.py \
    selftrain/scripts/eval_cue_controls.py \
    "$JOB_ROOT/submitted_runner.sbatch" \
    "$CONFIG" \
    "$RUN_METADATA" \
    "$SOURCE_MANIFEST" \
    "$BANK" \
    > "$JOB_ROOT/evaluation_inputs.sha256"

run_evaluation () {
    local suffix=$1
    "$PYTHON" -u -m selftrain.scripts.eval_cue_controls \
        --checkpoint "$CHECKPOINT" \
        --config "$CONFIG" \
        --run-metadata "$RUN_METADATA" \
        --source-manifest "$SOURCE_MANIFEST" \
        --manifest "$BANK" \
        --output "$JOB_ROOT/results_${suffix}.csv" \
        --summary "$JOB_ROOT/summary_${suffix}.json" \
        --expected-checkpoint-sha256 "$EXPECTED_CHECKPOINT_SHA256" \
        --expected-config-sha256 "$EXPECTED_CONFIG_SHA256" \
        --expected-manifest-sha256 "$MANIFEST_SHA256" \
        --expected-trials "$EXPECTED_TRIALS" \
        --expected-bank-seed "$EXPECTED_BANK_SEED" \
        --analysis-kind "$ANALYSIS_KIND" \
        --project-root "$PROJECT_ROOT" \
        --batch-size 16 \
        --seed 20260815 \
        --bootstrap-seed 20260816 \
        --bootstrap-repetitions 2000
}

if [ "$CUE_CONTROL_MODE" = smoke ]; then
    echo "Running 32-trial smoke twice to prove deterministic inference..."
    run_evaluation smoke_a
    run_evaluation smoke_b
    cmp "$JOB_ROOT/results_smoke_a.csv" "$JOB_ROOT/results_smoke_b.csv"
    cmp "$JOB_ROOT/summary_smoke_a.json" "$JOB_ROOT/summary_smoke_b.json"
    SMOKE_MARKER_TMP="$RESULT_ROOT/.smoke_pass_${SLURM_JOB_ID}.tmp"
    printf '%s\n' \
        "SMOKE_JOB_ID=$SLURM_JOB_ID" \
        "FORMAL_MANIFEST_SHA256=$FORMAL_MANIFEST_SHA256" \
        "EVAL_CODE_SHA256=$EVAL_CODE_SHA256" \
        > "$SMOKE_MARKER_TMP"
    mv "$SMOKE_MARKER_TMP" "$SMOKE_PASS_MARKER"
    echo "CUE CONTROL 32-TRIAL REPRODUCIBILITY SMOKE: PASS"
else
    echo "Running frozen 10,000-trial paired cue controls..."
    run_evaluation full
    echo "CUE CONTROL 10000-TRIAL COMPUTATION: COMPLETE (inspect summary_full.json for the preregistered scientific result)"
fi

echo "FORMAL_MANIFEST_SHA256=$FORMAL_MANIFEST_SHA256"
echo "EVAL_CODE_SHA256=$EVAL_CODE_SHA256"
echo "CUE CONTROL OUTPUT: $JOB_ROOT"
