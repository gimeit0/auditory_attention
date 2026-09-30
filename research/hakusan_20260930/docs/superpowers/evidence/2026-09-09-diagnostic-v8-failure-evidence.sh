#!/bin/bash
# Mac entry. Read-only failure verification/context for Job 680910.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040
command -v jq >/dev/null

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v8"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
M="$R/input_freeze.json"
J=680910
PROTO=formal40_batch_invariance_diag_20260903_v8
F=1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c
H=6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182
T="$R/state/DIAGNOSTIC_FAILED.json"
L="$R/logs/audattn_v4_numdiag_${J}.log"

test -x "$P"
for ITEM in "$B" "$R" "$R/tools" "$R/state" "$R/logs"
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
ARGS+=(--job-id "$J")
echo "VERIFY_RESULTS_BEGIN"
VERIFY_RC=0
"$P" -I -B "$D" "${ARGS[@]}" || VERIFY_RC=$?
printf 'VERIFY_RC=%s\n' "$VERIFY_RC"
echo "VERIFY_RESULTS_END"

# Continue collecting read-only context after a recorded diagnostic failure.
READ_RC=0
echo "FAILED_MARKER_SUMMARY_BEGIN"
if [ -f "$T" ] && [ ! -L "$T" ] && [ -O "$T" ]; then
  /usr/bin/sha256sum "$T" || READ_RC=$?
  jq -e --arg job "$J" --arg freeze "$F" --arg protocol "$PROTO" '
    if .job_id != $job or .input_freeze_sha256 != $freeze or
       .diagnostic_protocol != $protocol or .status != "DIAGNOSTIC_FAILED" then
      error("failure marker identity differs")
    else {
      status,
      job_id,
      diagnostic_protocol,
      input_freeze_sha256,
      lock_acquired,
      primary_error,
      post_errors,
      matrix_status: (.matrix.status // null),
      artifact_files: [.artifact_inventory.files[].relative_path]
    } end
  ' "$T" || READ_RC=$?
else
  printf 'FAILED_MARKER_MISSING_OR_INVALID=%s\n' "$T"
  READ_RC=2
fi
echo "FAILED_MARKER_SUMMARY_END"

echo "LOG_TAIL_BEGIN"
if [ -f "$L" ] && [ ! -L "$L" ] && [ -O "$L" ]; then
  /usr/bin/sha256sum "$L" || READ_RC=$?
  echo "Display: last 120 lines, at most 2400 characters per line; original file unchanged."
  tail -n 120 "$L" | awk '
    length($0) > 2400 {
      print substr($0, 1, 2400) " ... [DISPLAY_TRUNCATED]"
      next
    }
    { print }
  ' || READ_RC=$?
else
  printf 'LOG_MISSING_OR_INVALID=%s\n' "$L"
  READ_RC=2
fi
echo "LOG_TAIL_END"
printf 'READ_RC=%s\n' "$READ_RC"
echo "Read-only evidence collection; no code changes or submission."
if [ "$VERIFY_RC" -ne 0 ]; then
  exit "$VERIFY_RC"
fi
exit "$READ_RC"
REMOTE
)
RC=$?
printf 'EVIDENCE_RC=%s\n' "$RC"
echo "A recorded diagnostic failure normally gives VERIFY_RC=2; do not resubmit."
exit "$RC"
