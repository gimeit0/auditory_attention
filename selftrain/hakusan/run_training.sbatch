#!/bin/bash
# Tier-0 diotic training from random initialization on one HAKUSAN A100.
# First submission:
#   sbatch selftrain/hakusan/run_training.sbatch
# Resume after interruption:
#   RESUME=1 sbatch selftrain/hakusan/run_training.sbatch
# Optional batch-size override is intentionally done in the YAML after a GPU
# smoke test, so the effective batch and run record remain unambiguous.
#SBATCH -J audattn_selftrain
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH -t 24:00:00
#SBATCH -o selftrain/hakusan/logs/%x_%j.log
#SBATCH -e selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate $HOME/miniconda3/envs/attn

cd $SLURM_SUBMIT_DIR
export CV_CLIPS=$SLURM_SUBMIT_DIR/cv_train/clips

python -m selftrain.scripts.check_readiness --require-all-words

if [ "${RESUME:-0}" = "1" ]; then
    python -u -m src.spatialtrain \
        --config selftrain/configs/full.yaml \
        --exp_dir selftrain/experiments \
        --gpus 1 \
        --n_jobs 8 \
        --precision 16-mixed \
        --random_seed 20260721 \
        --resume_training
else
    python -u -m src.spatialtrain \
        --config selftrain/configs/full.yaml \
        --exp_dir selftrain/experiments \
        --gpus 1 \
        --n_jobs 8 \
        --precision 16-mixed \
        --random_seed 20260721
fi
