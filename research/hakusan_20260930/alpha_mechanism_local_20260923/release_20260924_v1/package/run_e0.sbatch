#!/bin/bash
set -euo pipefail
umask 077
test "$#" -eq 3
PACKAGE="$1"
RELEASE_SHA="$2"
STATE="$3"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin
cmp -s -- "$0" "$PACKAGE/run_e0.sbatch"
SCRATCH=$(mktemp -d /tmp/audattn_e0_XXXXXXXX)
export TMPDIR="$SCRATCH"
export MPLCONFIGDIR="$SCRATCH/mpl"
export TORCH_HOME="$SCRATCH/torch"
export XDG_CACHE_HOME="$SCRATCH/cache"
printf 'E0_SCRATCH=%s\n' "$SCRATCH"
exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
  "$PACKAGE/e0_entry.py" run "$RELEASE_SHA" "$STATE/attempt"
