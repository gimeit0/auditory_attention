#!/bin/bash
# Read-only check for the current held phase; never submit, update, or release.
set -euo pipefail
test "$(uname -s)" = Darwin
cd "$HOME/发表/超算"
P=/opt/anaconda3/envs/audattn/bin/python
R=checkpoint_compare_workflow_20260917/submission/repair_724808.py
S=5a365141361327b8b3f4526dff86a47d83126a49f784b64bca02609a5b2c3625
C=d0fb9e2c295765c0aea835490d9ef78c01126d8e9a73b9541bc53c3ca665e503
A=(inspect --expected-source-sha256 "$S")
A+=(--expected-controller-sha256 "$C")
exec "$P" -I -B "$R" "${A[@]}"
