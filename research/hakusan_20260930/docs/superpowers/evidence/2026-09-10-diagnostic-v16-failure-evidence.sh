#!/bin/bash
# Mac entry. Read-only failure verification/context for Job 683649.
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
command -v jq >/dev/null

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v16"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
M="$R/input_freeze.json"
J=683649
PROTO=formal40_batch_invariance_diag_20260903_v16
F=0ee7cb2cfe50b2a1cfb6dd34f4fa43ade84f0316f3acb7c3d48ed061c8bd64fe
H=e776d9917ecad3da529d311d536de89d90121d23bceb2cefe9fdadc7450609ec
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
  # v16's bounded metadata can exceed the generic display-line limit. Show that
  # specific packet intact, never the huge terminal record or arbitrary stdout.
  echo "BOUNDED_EXCEPTION_CHAIN_BEGIN"
  awk '
    /^DIAGNOSTIC_EXCEPTION_CHAIN=/ {
      if (length($0) > 16384) {
        print "STOP: exception metadata exceeds reviewed bound"
        exit 2
      }
      print
    }
  ' "$L" || READ_RC=$?
  echo "BOUNDED_EXCEPTION_CHAIN_END"
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
