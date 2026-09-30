#!/usr/bin/env bash
set -euo pipefail
test "$(uname -s)" = Darwin

TASK_ROOT="$HOME/发表/超算"
ENTRY="$TASK_ROOT/docs/superpowers/evidence"
ENTRY="$ENTRY/2026-09-15-staged-scratch-native-cpu.py"
PYTHON="/opt/anaconda3/envs/audattn/bin/python"
test -x "$PYTHON"
test -f "$ENTRY"
test ! -L "$ENTRY"
printf '%s  %s\n' \
  dcae39b7d121e9ebf20f0852e76b74d197ed84724721f9a506cc9f39781d46cc \
  "$ENTRY" | /usr/bin/shasum -a 256 -c -

if [ ! -S "$TASK_ROOT/.hakusan-control/master.sock" ]; then
  echo 'STOP: authenticated shared SSH socket is absent; nothing submitted.'
  echo 'First run the connection script in your own terminal:'
  echo 'bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"'
  exit 2
fi

RC=0
"$PYTHON" -I -B "$ENTRY" || RC=$?
printf 'STAGED_NATIVE_CPU_RC=%s\n' "$RC"
echo 'Return this output for review. No automatic retry or GPU submission.'
exit "$RC"
