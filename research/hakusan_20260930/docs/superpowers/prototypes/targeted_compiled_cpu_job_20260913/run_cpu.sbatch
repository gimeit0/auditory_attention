#!/bin/bash
#SBATCH --job-name=audattn_cmp_cpu
#SBATCH --partition=TINY
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4096M
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --export=NONE
#SBATCH --chdir=/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1
#SBATCH --output=/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1/slurm-%j.log
#SBATCH --error=/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1/slurm-%j.log

set -euo pipefail
umask 077
[[ "$#" -eq 2 ]] || exit 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{32}$ ]] || exit 2
R=/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1
P=/home/s2510040/miniconda3/envs/attn/bin/python
C="$R/package/docs/superpowers/prototypes/targeted_compiled_cpu_job_20260913/coordinator.py"
KEEP=()
for K in SLURM_JOB_ID SLURM_JOB_NAME SLURM_JOB_PARTITION SLURM_NNODES SLURM_NTASKS SLURM_CPUS_PER_TASK SLURM_MEM_PER_NODE SLURM_JOB_GPUS SLURM_STEP_GPUS
do
  if [[ "${!K+x}" == x ]]; then KEEP+=("$K=${!K}"); fi
done
exec /usr/bin/env -i "${KEEP[@]}" PATH=/usr/local/bin:/usr/bin:/bin \
  CUDA_VISIBLE_DEVICES= PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  "$P" -I -B "$C" "$1" "$2"
