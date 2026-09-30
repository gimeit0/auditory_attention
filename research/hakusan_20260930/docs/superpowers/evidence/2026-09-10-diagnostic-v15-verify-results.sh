#!/bin/bash
# Read-only terminal result verification; never submits, freezes or repairs.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin
  CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
  ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040
B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v15"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
M="$R/input_freeze.json"
F=f3cf353561f18cc34b92a00c89bd72c1311ebe5c78c52fa0e8f97f433a8ae4aa
H=993d89b6c97f706cb7bc1e1f6dc8b27d2c608e7866fb5b4cbef316ddcb389cca
for ITEM in "$B" "$R" "$R/tools" "$R/state"
do
  test -d "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
done
for ITEM in "$D" "$M"
do
  test -f "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
done
printf '%s  %s\n' "$H" "$D" "$F" "$M" |
  /usr/bin/sha256sum -c -
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
ARGS=(verify-results --expected-input-freeze-sha256 "$F")
ARGS+=(--job-id 683523)
echo "DIAG_V15_VERIFY_RESULTS_BEGIN"
VERIFY_RC=0
"$P" -I -B "$D" "${ARGS[@]}" || VERIFY_RC=$?
printf 'VERIFY_RC=%s\n' "$VERIFY_RC"
echo "Read-only verification; no submission or changes."
exit "$VERIFY_RC"
REMOTE
)
RC=$?
printf 'VERIFY_SCRIPT_RC=%s\n' "$RC"
exit "$RC"
