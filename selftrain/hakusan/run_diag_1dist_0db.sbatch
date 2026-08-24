#!/bin/bash
# 学习性诊断第三阶段：1 名随机干扰者、target 固定 0 dB、正确 cue 全保留。
# 这是诊断而非正式全量运行；保持 Job 547251 的预算和随机初始化，只改变 SNR。
# 提交（A100）: sbatch -p GPU-1A selftrain/hakusan/run_diag_1dist_0db.sbatch
# 强通过门槛：final val_acc >= 20%，曲线总体上升，final 距 best <= 3 个百分点。
# 8% <= final val_acc < 20% 为可接受但需继续诊断，不能直接进入全量。
# 本阶段通过后还必须做正确 cue 与打乱/静音 cue 的反事实对照。
#SBATCH -J audattn_diag_1d0
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

PROJECT_ROOT="/home/s2510040/selective_listening_repro/code/auditory_attention"
cd "$PROJECT_ROOT"

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"
PYTHON="$HOME/miniconda3/envs/attn/bin/python"
[ -x "$PYTHON" ] || { echo "Missing attn Python: $PYTHON" >&2; exit 2; }

export CV_CLIPS="$PROJECT_ROOT/cv_train/clips"
export PYTHONPATH="$PROJECT_ROOT"

EXP_DIR="$PROJECT_ROOT/selftrain/experiments/diag_1dist_0db/${SLURM_JOB_ID}"
CONFIG="selftrain/configs/diag_1dist_0db.yaml"
mkdir -p "$EXP_DIR"

echo "Diagnostic run: 1 distractor at target 0 dB with correct cue, JOB_ID=$SLURM_JOB_ID"
echo "Python: $PYTHON"
"$PYTHON" -u -m selftrain.scripts.check_diag_stage \
    --config "$CONFIG" \
    --stage 1dist-0db
cp "$CONFIG" "$EXP_DIR/config.yaml"
sha256sum \
    "$CONFIG" \
    selftrain/hakusan/run_diag_1dist_0db.sbatch \
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

"$PYTHON" -u -m src.spatialtrain \
    --config "$CONFIG" \
    --exp_dir "$EXP_DIR" \
    --gpus 1 \
    --n_jobs 8 \
    --precision 16-mixed \
    --random_seed 20260721

echo "DIAG 1DIST 0DB RUN COMPLETE: $EXP_DIR"
