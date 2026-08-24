#!/bin/bash
# Resumable MMS forced alignment for the Tier-0 training catalogs.
# Re-submit the same file if the 24-hour job limit interrupts it; completed
# clips are recorded in JSONL and skipped automatically.
#SBATCH -J audattn_align
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH -t 24:00:00
#SBATCH -o selftrain/hakusan/logs/%x_%j.log
#SBATCH -e selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Ee -o pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate $HOME/miniconda3/envs/attn

cd $SLURM_SUBMIT_DIR

TRAIN_MAX_CLIPS=${TRAIN_MAX_CLIPS:-20000}
VALIDATION_MAX_CLIPS=${VALIDATION_MAX_CLIPS:-3000}
echo "Alignment limits: train=${TRAIN_MAX_CLIPS} validation=${VALIDATION_MAX_CLIPS}"

# Expected layout:
#   cv_train/train.tsv
#   cv_train/dev.tsv
#   cv_train/test.tsv
#   cv_train/clips/*.mp3
python -u -m selftrain.scripts.build_anchor_catalog \
    --cv-dir "$SLURM_SUBMIT_DIR/cv_train" \
    --train-max-clips "$TRAIN_MAX_CLIPS" \
    --validation-max-clips "$VALIDATION_MAX_CLIPS" \
    --max-clips-per-speaker 4 \
    --seed 20260721

python -m selftrain.scripts.check_readiness
