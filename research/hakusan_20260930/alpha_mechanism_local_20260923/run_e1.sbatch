#!/bin/bash
set -euo pipefail
umask 077
test "$#" -eq 3
PACKAGE="$1"
RELEASE_SHA="$2"
STATE="$3"
test "$PACKAGE" = /home/s2510040/audattn_e1/e1_20260927_v3/package
test "$STATE" = /home/s2510040/audattn_e1/e1_20260927_v3/state
cmp -s -- "$0" "$PACKAGE/run_e1.sbatch"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin
E1_SCRATCH=$(mktemp -d /tmp/audattn_e1_XXXXXXXX)
export TMPDIR="$E1_SCRATCH"
export MPLCONFIGDIR="$E1_SCRATCH/mpl"
export TORCH_HOME="$E1_SCRATCH/torch"
export XDG_CACHE_HOME="$E1_SCRATCH/cache"
printf 'E1_SCRATCH=%s\n' "$E1_SCRATCH"
exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
  "$PACKAGE/e1_entry.py" run "$RELEASE_SHA"
