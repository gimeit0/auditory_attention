#!/bin/bash
# 0 dB 学习性诊断延长版：从随机初始化独立跑满 20 epochs。
# 不读取、不改写 Job 548509；它不是正式 full 任务，也不能证明模型使用 cue。
# Job 548509 实测约 2:22/epoch，20 epochs 预计约 47--50 小时，申请 3 天。
# 提交: sbatch selftrain/hakusan/run_diag_1dist_0db_20ep.sbatch
# 结束后必须比较 40 个验证点，再进行 correct/shuffled/silent cue 对照。
#SBATCH -J audattn_diag_1d0_20
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 3-00:00:00
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

EXP_DIR="$PROJECT_ROOT/selftrain/experiments/diag_1dist_0db_20ep/${SLURM_JOB_ID}"
CONFIG="selftrain/configs/diag_1dist_0db_20ep.yaml"
mkdir -p "$EXP_DIR"

echo "Diagnostic run: independent 20-epoch, 1 distractor at target 0 dB with correct cue, JOB_ID=$SLURM_JOB_ID"
echo "Python: $PYTHON"
"$PYTHON" -u -m selftrain.scripts.check_diag_stage \
    --config "$CONFIG" \
    --stage 1dist-0db-20ep
cp "$CONFIG" "$EXP_DIR/config.yaml"
sha256sum \
    "$CONFIG" \
    selftrain/hakusan/run_diag_1dist_0db_20ep.sbatch \
    selftrain/scripts/check_diag_stage.py \
    selftrain/data/anchor_index.py \
    selftrain/data/diotic_attention.py \
    selftrain/artifacts/anchors/train_anchors.tsv.gz \
    selftrain/artifacts/anchors/validation_anchors.tsv.gz \
    src/audio_transforms.py \
    src/custom_modules.py \
    src/spatial_attn_architecture.py \
    src/spatial_attn_lightning.py \
    src/spatialtrain.py \
    > "$EXP_DIR/source.sha256"

# Bind every checkpoint to this exact diagnostic run, config, and source
# manifest. This does not alter optimization; it makes rolling/last checkpoints
# eligible for the project's strict audited-resume checks if a later job is
# needed after a node or wall-time interruption.
export AUDATTN_RUN_ID="diag_1dist_0db_20ep_${SLURM_JOB_ID}"
export AUDATTN_CONFIG_SHA256
AUDATTN_CONFIG_SHA256="$(sha256sum "$CONFIG" | awk '{print $1}')"
export AUDATTN_SOURCE_SHA256
AUDATTN_SOURCE_SHA256="$(sha256sum "$EXP_DIR/source.sha256" | awk '{print $1}')"
printf 'AUDATTN_RUN_ID=%s\nAUDATTN_CONFIG_SHA256=%s\nAUDATTN_SOURCE_SHA256=%s\n' \
    "$AUDATTN_RUN_ID" \
    "$AUDATTN_CONFIG_SHA256" \
    "$AUDATTN_SOURCE_SHA256" \
    > "$EXP_DIR/run_metadata.env"
echo "Run metadata: $EXP_DIR/run_metadata.env"

"$PYTHON" -u -m src.spatialtrain \
    --config "$CONFIG" \
    --exp_dir "$EXP_DIR" \
    --gpus 1 \
    --n_jobs 8 \
    --precision 16-mixed \
    --random_seed 20260721

echo "DIAG 1DIST 0DB 20EP RUN COMPLETE: $EXP_DIR"
