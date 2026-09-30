#!/bin/bash
# Mac entry. Read-only status for the single submitted v13 Job 683154.
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
R="$B/same_bank_v4_job646900_2026-09-03_v13"
P="$HOME/miniconda3/envs/attn/bin/python"
S="$R/tools/submit_numeric_diag.py"
M="$R/input_freeze.json"
J=683154
F=48b6c9ec1115796da95bed4710395bce7c7eb8eb45084f135689821df4971f51
H=aa6c6f5e1977bcdf2aff69fabf4579d21f4a8fc6e25f7d44b7fe90202937504e

test -x "$P"
for ITEM in "$B" "$R" "$R/tools"
do
  test -d "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
done
for ITEM in "$S" "$M"
do
  test -f "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
done
printf '%s  %s\n' "$H" "$S" "$F" "$M" |
  /usr/bin/sha256sum -c -

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0

validate_identity ()
{
  jq -e -s --arg job "$J" --arg freeze "$F" '
    length == 1 and
    (.[0] | type == "object" and
      .job_id == $job and
      .input_freeze_sha256 == $freeze and
      .results_verified == false)
  ' >/dev/null
}

printf 'EXPECTED_DIAG_JOB=%s\n' "$J"
echo "DIAG_V13_STATUS_BEGIN"
STATUS_RC=0
STATUS_JSON=$("$P" -I -B "$S" status) || STATUS_RC=$?
printf '%s\n' "$STATUS_JSON"
if [ "$STATUS_RC" -eq 0 ]; then
  if ! printf '%s\n' "$STATUS_JSON" | validate_identity; then
    echo "STOP: status job/freeze binding differs; preserve records."
    STATUS_RC=2
  fi
fi
printf 'STATUS_RC=%s\n' "$STATUS_RC"

echo "SLURM_ACCOUNTING_BEGIN"
FMT=JobIDRaw,State,ExitCode,Elapsed,Start,End,NodeList
ACCOUNTING_RC=0
/usr/bin/sacct -j "$J" -X -P --format="$FMT" || ACCOUNTING_RC=$?
printf 'ACCOUNTING_RC=%s\n' "$ACCOUNTING_RC"
echo "SLURM_ACCOUNTING_END"

echo "Query only. Even a terminal status still requires verify-results."
if [ "$STATUS_RC" -ne 0 ]; then
  exit "$STATUS_RC"
fi
exit "$ACCOUNTING_RC"
REMOTE
)
RC=$?
printf 'QUERY_RC=%s\n' "$RC"
exit "$RC"
