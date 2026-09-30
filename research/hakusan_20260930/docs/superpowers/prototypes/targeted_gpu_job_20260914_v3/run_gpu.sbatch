#!/bin/bash
# CANDIDATE ONLY: these resource limits have NOT been authorized or submitted.
#SBATCH --job-name=audattn_b2_coldpair
#SBATCH --partition=GPU-1A
#SBATCH --nodes=1
#SBATCH --gres=gpu:nvidia_a100:1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@120
#SBATCH --chdir=/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v3
#SBATCH --output=/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v3/logs/coldpair_%j.log
#SBATCH --error=/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v3/logs/coldpair_%j.log

set -euo pipefail
umask 077
[[ "$#" -eq 2 ]] || exit 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{32}$ ]] || exit 2
[[ "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]{0,19}$ ]] || exit 2
[[ "${HOME:-}" == /home/s2510040 ]] || exit 2

# Copy the existing real HOME unchanged; private cache paths are set by the
# coordinator. No password, shell initialization or automatic retry is used.
KEEP=()
for KEY in HOME PATH SLURM_JOB_ID SLURM_JOB_NODELIST SLURM_NNODES \
  SLURM_NTASKS SLURM_CPUS_PER_TASK SLURM_MEM_PER_NODE SLURM_JOB_PARTITION \
  SLURM_JOB_GPUS SLURM_STEP_GPUS CUDA_VISIBLE_DEVICES
do
  if [[ "${!KEY+x}" == x ]]; then KEEP+=("$KEY=${!KEY}"); fi
done
P=/home/s2510040/miniconda3/envs/attn/bin/python
R=/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v3
C="$R/package/docs/superpowers/prototypes/targeted_gpu_job_20260914_v3"
exec /usr/bin/env -i "${KEEP[@]}" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$C/coordinator.py" "$1" "$2" "$0"
