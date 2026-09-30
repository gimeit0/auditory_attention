(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算"
  cd same_bank_eval_2026_09_03_v4_numeric_diag_v7
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v7-candidate-manifest.sha256"
  /usr/bin/shasum -a 256 -c "$C"

  ssh s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040
command -v jq >/dev/null

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v7"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
M="$R/input_freeze.json"
PROTO=formal40_batch_invariance_diag_20260903_v7
# Fixed from the user's successful v7 freeze receipt; never derive expected SHA here.
F=6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920
H=7e18242bf96be03e8e50e713be877b4a52c321c6874cb81bca2b9955db924167

for ITEM in "$B" "$R" "$R/tools"
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
  test "$(stat -c %a "$ITEM")" = 600
  test "$(stat -c %h "$ITEM")" = 1
done
printf '%s  %s\n' "$H" "$D" "$F" "$M" |
  /usr/bin/sha256sum -c -

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0

validate_result ()
{
  jq -e -s --arg protocol "$PROTO" --arg freeze "$F" --arg root "$R" '
    if length != 1 then
      error("expected exactly one check-only JSON document")
    else
      .[0] |
      if type == "object" and
         .schema_version == 1 and
         .status == "CHECK_PASS" and
         .diagnostic_protocol == $protocol and
         .input_freeze_sha256 == $freeze and
         .layout.root == $root and
         .layout.directories ==
           ["tools", "logs", "state", "attempts", "submitted_runners"] then
        .
      else
        error("check-only status/protocol/freeze/layout mismatch")
      end
    end
  '
}

ARGS=(check-only --expected-input-freeze-sha256 "$F")
echo "DIAG_V7_CHECK_ONLY_BEGIN"
"$P" -I -B "$D" "${ARGS[@]}" | validate_result

printf '%s  %s\n' "$H" "$D" "$F" "$M" |
  /usr/bin/sha256sum -c -
echo "DIAG_V7_CHECK_ONLY=PASS"
echo "NEXT: review CHECK_PASS before single submission; no job submitted."
REMOTE
)
RC=$?
printf 'CHECK_ONLY_RC=%s\n' "$RC"
if [ "$RC" -ne 0 ]; then
  echo "STOP: inspect this output; do not freeze again or submit."
fi
exit "$RC"
