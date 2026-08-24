#!/bin/bash
# 学习性诊断第二阶段：1 名随机干扰者、target 固定 +10 dB、cue 全保留。
# 这是诊断而非正式运行，不走 submit_training.sh 的守卫链，直接从活动源码树运行。
# 提交（A100 默认）:  sbatch selftrain/hakusan/run_diag_1dist_p10db.sbatch
# 提交到 H100:       sbatch -p VM-GPU-L --exclude=spcc-cld-gl02 selftrain/hakusan/run_diag_1dist_p10db.sbatch
# 强通过门槛：final val_acc >= 20%，曲线总体上升，final 距 best <= 3 个百分点。
#SBATCH -J audattn_diag_1d10
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

EXP_DIR="$PROJECT_ROOT/selftrain/experiments/diag_1dist_p10db/${SLURM_JOB_ID}"
CONFIG="selftrain/configs/diag_1dist_p10db.yaml"
mkdir -p "$EXP_DIR"

echo "Diagnostic run: 1 distractor at target +10 dB, JOB_ID=$SLURM_JOB_ID"
echo "Python: $PYTHON"
"$PYTHON" -u -m selftrain.scripts.check_diag_stage \
    --config "$CONFIG" \
    --stage 1dist-p10db
cp "$CONFIG" "$EXP_DIR/config.yaml"
sha256sum \
    "$CONFIG" \
    selftrain/scripts/check_diag_stage.py \
    src/audio_transforms.py \
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

echo "DIAG 1DIST +10DB RUN COMPLETE: $EXP_DIR"
