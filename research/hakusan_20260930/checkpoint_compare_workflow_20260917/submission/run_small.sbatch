#!/bin/bash
set -euo pipefail
umask 077
export PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/bin:/bin
unset PYTHONPATH PYTHONHOME
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export OPENBLAS_NUM_THREADS=8
export NUMEXPR_NUM_THREADS=8
export PYTHONUNBUFFERED=1
test "$#" -eq 1
P=/home/s2510040/miniconda3/envs/attn/bin/python
R=/home/s2510040/audattn_external_eval_ops/eager_small_20260917_v1
exec "$P" -I -B -u "$R/tools/launch_small.py" "$1"
