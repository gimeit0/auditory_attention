#!/bin/bash
# Candidate allocated-job entry only; not a submission script.
# Resource requests/held submission require a separate approved deployment controller.
set -euo pipefail
umask 077
test "$#" -eq 2
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8
SCRIPT_DIR=/home/s2510040/audattn_external_eval_ops/eager_p07conf_20260919_v2/package/same_bank_compare_2026_09_19_confirm_v2
if [ "$1" = --release ]; then
  exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
    "$SCRIPT_DIR/launch_approved.py" "$2"
fi
exec /home/s2510040/miniconda3/envs/attn/bin/python -I -B -u \
  "$SCRIPT_DIR/sequence.py" run --contract "$1" --contract-sha256 "$2"
