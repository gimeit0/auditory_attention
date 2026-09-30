#!/usr/bin/env bash
#SBATCH --job-name=audattn_g2_bridge_cpu
#SBATCH --partition=TINY
#SBATCH --account=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --threads-per-core=1
#SBATCH --mem=6000M
#SBATCH --time=00:22:00
#SBATCH --no-requeue
#SBATCH --export=NONE
set -euo pipefail
umask 077
R=/home/s2510040/audattn_external_eval_diag/g2_bridge_cpu_2026-09-16_v1
P=/home/s2510040/miniconda3/envs/attn/bin/python
H="$R/package/docs/superpowers/prototypes/g2_bridge_batch_20260916/runtime.py"
export SLURM_EXPORT_ENV=ALL
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export CUDA_VISIBLE_DEVICES=''
exec /usr/bin/srun --ntasks=1 --cpus-per-task=1 --cpu-bind=threads \
  "$P" -I -B "$H" "$R" "$1" "$2"
