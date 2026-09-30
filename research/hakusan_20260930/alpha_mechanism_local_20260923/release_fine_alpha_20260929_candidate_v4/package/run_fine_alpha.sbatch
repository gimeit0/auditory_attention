#!/bin/bash
set -euo pipefail
umask 077
test "$#" -eq 3
PACKAGE="$1"
RELEASE_SHA="$2"
STATE="$3"
test "$PACKAGE" = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4/package'
test "$STATE" = '/home/s2510040/audattn_fine_alpha/fine_alpha_20260929_v4/state'
cmp -s -- "$0" "$PACKAGE/run_fine_alpha.sbatch"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin
FINE_ALPHA_SCRATCH=$(mktemp -d /tmp/audattn_fine_alpha_XXXXXXXX)
export TMPDIR="$FINE_ALPHA_SCRATCH"
export MPLCONFIGDIR="$FINE_ALPHA_SCRATCH/mpl"
export TORCH_HOME="$FINE_ALPHA_SCRATCH/torch"
export XDG_CACHE_HOME="$FINE_ALPHA_SCRATCH/cache"
printf 'FINE_ALPHA_SCRATCH=%s\n' "$FINE_ALPHA_SCRATCH"
exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
  "$PACKAGE/fine_alpha_entry.py" run "$RELEASE_SHA"
