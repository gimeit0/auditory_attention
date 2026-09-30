#!/bin/bash
set -euo pipefail
umask 077
test "$#" -eq 3
PACKAGE="$1"
RELEASE_SHA="$2"
STATE="$3"
test "$PACKAGE" = '@REMOTE_ROOT@/package'
test "$STATE" = '@REMOTE_ROOT@/state'
cmp -s -- "$0" "$PACKAGE/run_e2.sbatch"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin
E2_SCRATCH=$(mktemp -d /tmp/audattn_e2_XXXXXXXX)
export TMPDIR="$E2_SCRATCH"
export MPLCONFIGDIR="$E2_SCRATCH/mpl"
export TORCH_HOME="$E2_SCRATCH/torch"
export XDG_CACHE_HOME="$E2_SCRATCH/cache"
printf 'E2_SCRATCH=%s\n' "$E2_SCRATCH"
exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
  "$PACKAGE/e2_entry.py" run "$RELEASE_SHA"
