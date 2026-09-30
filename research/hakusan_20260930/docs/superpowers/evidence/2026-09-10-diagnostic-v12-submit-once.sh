#!/bin/bash
# Mac entry. One submission invocation after the reviewed v12 CHECK_PASS receipt.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算"
  cd same_bank_eval_2026_09_03_v4_numeric_diag_v12
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v12-candidate-manifest.sha256"
  CS=afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b
  printf '%s  %s\n' "$CS" "$C" | /usr/bin/shasum -a 256 -c -
  /usr/bin/shasum -a 256 -c "$C"

  CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
  ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
umask 077
trap 'printf "SUBMIT_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v12"
P="$HOME/miniconda3/envs/attn/bin/python"
S="$R/tools/submit_numeric_diag.py"
M="$R/input_freeze.json"
# Fixed from the reviewed freeze and successful check-only receipts.
F=6cd0407c8f48709e37fa9f0b6cdddcc6cbc5425b740b405c806c8a010eee9031
H=27322b33cb694e4a6cf43d9b20576c8096bc7f2ec99d0860cf9bf2bbba080c42

test -x "$P"
test -d "$B"
test ! -L "$B"
test -O "$B"
DIRS=(tools logs state attempts submitted_runners)
for ITEM in "$R" "${DIRS[@]/#/$R/}"
do
  test -d "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
  test "$(stat -c %a "$ITEM")" = 700
done
for ITEM in "$S" "$M"
do
  test -f "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
  test "$(stat -c %a "$ITEM")" = 600
  test "$(stat -c %h "$ITEM")" = 1
done
printf '%s  %s\n' "$H" "$S" "$F" "$M" |
  /usr/bin/sha256sum -c -

# Any prior attempt, including a journal lock, requires inspection first.
for NAME in state logs attempts submitted_runners
do
  ITEM=$(find "$R/$NAME" -mindepth 1 -print -quit)
  if [ -n "$ITEM" ]; then
    printf 'STOP: existing evidence in %s\n' "$R/$NAME"
    echo "Use read-only status; do not clear records or resubmit."
    exit 2
  fi
done

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0

ARGS=(submit --confirm-action)
ARGS+=(SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC)
ARGS+=(--confirm-v4-job-id 646900)
ARGS+=(--expected-input-freeze-sha256 "$F")

echo "DIAG_V12_SUBMIT_BEGIN"
echo "One submitter invocation only; preserve the following receipt."
# The pinned submitter rechecks inputs/queues under its journal lock.
# Do not pipe away its response, retry it, or call sbatch directly.
"$P" -I -B "$S" "${ARGS[@]}"
REMOTE
)
RC=$?
printf 'SUBMIT_RC=%s\n' "$RC"
if [ "$RC" -ne 0 ]; then
  echo "STOP: submission may be incomplete or uncertain; inspect status before any action."
fi
echo "Do not rerun this script. Return the output/receipt for review."
exit "$RC"
