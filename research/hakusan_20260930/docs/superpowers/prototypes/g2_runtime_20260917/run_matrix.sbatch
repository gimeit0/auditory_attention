#!/bin/bash
# Resource arguments and approved plan SHA must come from the reviewed
# one-shot submitter. This file does not submit, reconnect or retry.
set -euo pipefail
umask 077
test "$#" -eq 3
test "$(id -un)" = s2510040
test "$(uname -s)" = Linux
R=/home/s2510040/audattn_external_eval_diag
R="$R/formal40_numeric_profiles_20260916_v1"
P=/home/s2510040/miniconda3/envs/attn/bin/python
E="$R/package/docs/superpowers/prototypes/g2_runtime_20260917/bootstrap.py"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
exec "$P" -I -B "$E" "$1" "$2" "$3" "$0"
