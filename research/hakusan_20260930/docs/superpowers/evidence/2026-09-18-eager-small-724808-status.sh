#!/bin/bash
set -euo pipefail
test "$(uname -s)" = Darwin
cd "$HOME/发表/超算"
P=/opt/anaconda3/envs/audattn/bin/python
S=checkpoint_compare_workflow_20260917/submission/release_724808.py
H=c0b4ff2d9d1962f421485f0d868a644727c270e2d9b6a0156f0d64e4e3696067
exec "$P" -I -B "$S" status --expected-source-sha256 "$H"
