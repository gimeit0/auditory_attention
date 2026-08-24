#!/bin/bash
# 学习性诊断作业：干净目标800词识别（configs/diag_clean.yaml）。
# 这是诊断而非正式运行，不走 submit_training.sh 的守卫链，直接从活动源码树运行。
# 提交（A100 默认）:  sbatch selftrain/hakusan/run_diag.sbatch
# 提交到 H100:       sbatch -p VM-GPU-L selftrain/hakusan/run_diag.sbatch
# 判读：val_acc 在 1 个 epoch 内明显高于随机 0.00125 → 管线可学，问题在难度/时长；
#       始终贴着 0.00125 → 管线有bug，停止提交任何全量训练。
#SBATCH -J audattn_diag_clean
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

EXP_DIR="$PROJECT_ROOT/selftrain/experiments/diag/${SLURM_JOB_ID}"
CONFIG="selftrain/configs/diag_clean.yaml"
mkdir -p "$EXP_DIR"

echo "Diagnostic run: clean-target learnability, JOB_ID=$SLURM_JOB_ID"
echo "Python: $PYTHON"
"$PYTHON" -u -m selftrain.scripts.check_diag_stage \
    --config "$CONFIG" \
    --stage clean
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

echo "DIAG RUN COMPLETE: $EXP_DIR"
