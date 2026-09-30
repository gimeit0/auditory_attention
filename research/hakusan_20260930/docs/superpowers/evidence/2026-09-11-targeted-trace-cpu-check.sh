#!/bin/bash
# User-run Mac entry: authenticate interactively, then one CPU-only synthetic probe.
# Password stays in the SSH prompt. No Slurm submission or production deployment.
set -euo pipefail
umask 077
test "$(uname -s)" = Darwin
BASE="/Users/gigi/发表/超算"
E="$BASE/docs/superpowers/evidence"
T="$BASE/docs/superpowers/prototypes/targeted_trace_20260911"
CONNECT="$E/2026-09-10-hakusan-connect.sh"
DRIVER="$T/run_remote_cpu.py"
for F in "$CONNECT" "$DRIVER"
do
  test -f "$F"
  test ! -L "$F"
done
C=601ca2e23d7d4907b39a3b72d601decb012d5eacfa5fecdb6833d1bc291f347a
S=3e3e199671e2ec411161b1ada6fab566ab5dfc8fbe2a840f3cbad5bd7fdc23b0
printf '%s  %s\n' "$C" "$CONNECT" "$S" "$DRIVER" |
  /usr/bin/shasum -a 256 -c -
echo "SCOPE: connect, then <=90 seconds synthetic CPU checks; no GPU job."
bash "$CONNECT"
/opt/anaconda3/envs/audattn/bin/python -I -B "$DRIVER"
