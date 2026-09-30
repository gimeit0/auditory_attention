#!/bin/bash
# Bounded synthetic CPU compatibility only. Never reconnect or submit a job.
set -euo pipefail
umask 077

test "$(uname -s)" = Darwin
B="$HOME/发表/超算"
D="$B/docs/superpowers/prototypes/targeted_pair_native_20260915"
E="$B/docs/superpowers/evidence"
E="$E/v19-local_harness-20260915T042507Z-joll00yp/receipt.json"
P=/opt/anaconda3/envs/audattn/bin/python

H=e2f677c3067ce222e2ef4e72b0b77b300116f85110b2f6f8fda99fbbc070e6ec
S=4d2f742eea588eaaea8015538f48c8122d1258ed795c276eb86272d4840128da
F=97eda2c2b8c24580dac42de05e7352d84705949ed49967af52c546efc1639742
printf '%s  %s\n' "$H" "$D/driver.py" \
  "$S" "$D/PROBE_RELEASE.json" "$F" "$E" |
  /usr/bin/shasum -a 256 -c -

"$P" -I -B "$D/driver.py" check-only
if [ "${1:-}" = --check-only ] && [ "$#" -eq 1 ]; then
  echo 'LOCAL_ENTRY_CHECK=PASS; no network action.'
  exit 0
fi
if [ "$#" -ne 0 ]; then
  echo 'Usage: bash 2026-09-15-v19-pair-native-cpu.sh [--check-only]'
  exit 2
fi
if [ ! -S "$B/.hakusan-control/master.sock" ]; then
  echo 'STOP: shared SSH connection is absent.'
  echo 'Run 2026-09-10-hakusan-connect.sh in your terminal first.'
  echo 'No automatic connection, retry, or job submission.'
  exit 2
fi

echo 'SCOPE: <=90 seconds, one CPU, 80 synthetic tests on HAKUSAN.'
echo 'Temporary source/cache files only; cleanup required.'
echo 'No production model, GPU, permanent deployment, freeze, or submission.'
RC=0
"$P" -I -B "$D/driver.py" remote-cpu --local-receipt "$E" || RC=$?
printf 'V19_NATIVE_CPU_RC=%s\n' "$RC"
echo 'Return the final summary/receipt path for review; no automatic retry.'
exit "$RC"
