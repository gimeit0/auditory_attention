(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  ssh s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v7"
P="$HOME/miniconda3/envs/attn/bin/python"
S="$R/tools/submit_numeric_diag.py"
M="$R/input_freeze.json"
J=680519
F=6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920
H=d74c4878ccd5e9c79cd3854139009c1d2c5449df846082667ac7407ade474e86

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

printf 'EXPECTED_DIAG_JOB=%s\n' "$J"
echo "DIAG_V7_STATUS_BEGIN"
STATUS_RC=0
"$P" -I -B "$S" status || STATUS_RC=$?
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
