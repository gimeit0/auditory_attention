#!/bin/bash
# Full-data structural check plus A100 smoke/throughput preflight.
# Each submission writes into a job-specific directory, so reruns never mix
# checkpoints from different preflight jobs.
#SBATCH -J audattn_preflight
#SBATCH -p GPU-1A
#SBATCH -N 1
#SBATCH -G 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 01:00:00
#SBATCH -o selftrain/hakusan/logs/%x_%j.log
#SBATCH -e selftrain/hakusan/logs/%x_%j.log
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s2510040@jaist.ac.jp

set -Ee -o pipefail
trap 'rc=$?; echo "ERROR: line $LINENO exited with $rc" >&2; exit "$rc"' ERR

source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate "$HOME/miniconda3/envs/attn"

cd "$SLURM_SUBMIT_DIR"
export CV_CLIPS="$SLURM_SUBMIT_DIR/cv_train/clips"

PREFLIGHT_ROOT="selftrain/preflight_runs/${SLURM_JOB_ID}"
PREFLIGHT_CONFIG="$PREFLIGHT_ROOT/full_preflight.yaml"
mkdir -p "$PREFLIGHT_ROOT"

cp selftrain/configs/full.yaml "$PREFLIGHT_CONFIG"
sed -i 's/examples_per_epoch: 500000/examples_per_epoch: 3200/' "$PREFLIGHT_CONFIG"
sed -i 's/validation_examples: 10000/validation_examples: 320/' "$PREFLIGHT_CONFIG"
sed -i 's/  epochs: 10/  epochs: 1/' "$PREFLIGHT_CONFIG"
sed -i 's/diotic_selftrain_full_random_init/diotic_selftrain_preflight_batch32/' "$PREFLIGHT_CONFIG"

echo "Preflight host: $(hostname)"
nvidia-smi

python -m selftrain.scripts.check_readiness --require-all-words
python -u -m selftrain.scripts.check_dataset --batch-size 2

python -u -m src.spatialtrain \
    --config selftrain/configs/smoke.yaml \
    --exp_dir "$PREFLIGHT_ROOT" \
    --gpus 1 \
    --n_jobs 0 \
    --precision 16-mixed \
    --random_seed 20260721

/usr/bin/time -p python -u -m src.spatialtrain \
    --config "$PREFLIGHT_CONFIG" \
    --exp_dir "$PREFLIGHT_ROOT" \
    --gpus 1 \
    --n_jobs 8 \
    --precision 16-mixed \
    --random_seed 20260721

find "$PREFLIGHT_ROOT" -type f -name '*.ckpt' -ls
echo "A100 preflight: PASS"
