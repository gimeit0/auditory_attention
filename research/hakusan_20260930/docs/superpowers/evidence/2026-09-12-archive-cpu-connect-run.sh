#!/bin/bash
# Mac entry: authenticate and immediately run one bounded synthetic CPU probe.
# Default is local validation only. No automatic retry or Slurm submission.
set -euo pipefail
umask 077

MODE=${1:---check-only}
if [ "$#" -gt 1 ]; then
  echo "Usage: bash 2026-09-12-archive-cpu-connect-run.sh [--check-only|--run]" >&2
  exit 2
fi
case "$MODE" in
  --check-only|--run) ;;
  *) echo "STOP: expected --check-only or --run" >&2; exit 2 ;;
esac
test "$(uname -s)" = Darwin

BASE="/Users/gigi/发表/超算"
EVIDENCE="$BASE/docs/superpowers/evidence"
CONNECT="$EVIDENCE/2026-09-10-hakusan-connect.sh"
DRIVER="$EVIDENCE/2026-09-11-archive-cpu-check.py"
PYTHON="/opt/anaconda3/envs/audattn/bin/python"
SOCKET="$BASE/.hakusan-control/master.sock"

finish ()
{
  PIPELINE_RC=$?
  trap - EXIT
  printf 'ARCHIVE_CPU_PIPELINE_RC=%s\n' "$PIPELINE_RC"
  exit "$PIPELINE_RC"
}
trap finish EXIT

verify_inputs ()
{
  test -x "$PYTHON"
  for INPUT in "$CONNECT" "$DRIVER"
  do
    test -f "$INPUT" && test ! -L "$INPUT" && test -O "$INPUT" || return 2
  done
  printf '%s  %s\n' \
    601ca2e23d7d4907b39a3b72d601decb012d5eacfa5fecdb6833d1bc291f347a "$CONNECT" \
    93eb072c954031db11f9788b2cfc4cfe82f6de86f6598bd6d55e0bffb1a8d2a8 "$DRIVER" |
    /usr/bin/shasum -a 256 -c -
}

verify_inputs
"$PYTHON" -I -B "$DRIVER"
if [ "$MODE" = --check-only ]; then
  echo "ARCHIVE_CPU_ENTRY_VALID=PASS; local validation only, no SSH or jobs."
  exit 0
fi

echo "SCOPE: connect, then one synthetic CPU probe and archive recheck. No GPU job."
echo "Enter the password only at the SSH prompt. Keep this terminal/network active."
/bin/bash "$CONNECT"
verify_inputs
/usr/bin/ssh -S "$SOCKET" -O check s2510040@hakusan1
echo "ARCHIVE_CPU_RUN_BEGIN; no automatic reconnection or retry."
"$PYTHON" -I -B "$DRIVER" --run
