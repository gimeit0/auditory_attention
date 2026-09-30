#!/bin/bash
# Mac entry: audit inputs, create one NEW v11 freeze, print its SHA, then stop.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算"
  cd same_bank_eval_2026_09_03_v4_numeric_diag_v11
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v11-r2-candidate-manifest.sha256"
  CS=1b6e6f83115f995548bf9a859c02db86ed199f3bdcc5d05dfea386e351b990a9
  printf '%s  %s\n' "$CS" "$C" | /usr/bin/shasum -a 256 -c -
  /usr/bin/shasum -a 256 -c "$C"

  CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
  ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
umask 077
trap 'printf "AUDIT_FREEZE_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040
command -v jq >/dev/null

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v11"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
M="$R/input_freeze.json"
PROTO=formal40_batch_invariance_diag_20260903_v11
test -x "$P"

test -d "$B"
test ! -L "$B"
test -O "$B"
DIRS=(tools logs state attempts submitted_runners)
PATHS=("$R")
for NAME in "${DIRS[@]}"
do
  PATHS+=("$R/$NAME")
done
for ITEM in "${PATHS[@]}"
do
  test -d "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
  test "$(stat -c %a "$ITEM")" = 700
done
if [ -e "$M" ] || [ -L "$M" ]; then
  echo "STOP: diagnostic v11 input_freeze.json already exists"
  echo "Inspect the existing freeze; do not rerun or overwrite it."
  exit 2
fi
EXPECTED=$(printf "%s\n" "${DIRS[@]}" | LC_ALL=C sort)
ACTUAL=$(find "$R" -mindepth 1 -maxdepth 1 -printf "%f\n" |
  LC_ALL=C sort)
test "$ACTUAL" = "$EXPECTED"
for NAME in logs state attempts submitted_runners
do
  ITEM=$(find "$R/$NAME" -mindepth 1 -print -quit)
  test -z "$ITEM"
done

Q1=$(squeue -h -u "$(id -un)" -n audattn_samebank_v4)
Q2=$(squeue -h -u "$(id -un)" -n audattn_v4_numdiag)
printf 'V4_QUEUE=%s\nDIAG_QUEUE=%s\n' "$Q1" "$Q2"
if [ -n "$Q1" ] || [ -n "$Q2" ]; then
  printf "%s\n" "$Q1" "$Q2"
  echo "STOP: related job exists"
  exit 2
fi

FILES=(diagnose_batch_invariance.py numeric_trace.py)
FILES+=(submit_numeric_diag.py run_numeric_diag.sbatch)
HASHES=(
  39ee10def3d2b90b981ee56812492b1de7266943add6a370e3ef14943f490b83
  fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
  7b21cf94186bc1ffbd342c4107bf232f455d125b5235005d121bd9cdb09ddbf2
  7cd333b4c3509612faafffbdf94790d37722316e727991d9c456cde9e106df74
)
EXPECTED=$(printf "%s\n" "${FILES[@]}" | LC_ALL=C sort)
ACTUAL=$(find "$R/tools" -mindepth 1 -maxdepth 1 -printf "%f\n" |
  LC_ALL=C sort)
test "$ACTUAL" = "$EXPECTED"
for I in 0 1 2 3
do
  ITEM="$R/tools/${FILES[$I]}"
  test -f "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
  test "$(stat -c %a "$ITEM")" = 600
  test "$(stat -c %h "$ITEM")" = 1
  printf "%s  %s\n" "${HASHES[$I]}" "$ITEM" |
    /usr/bin/sha256sum -c -
done

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0

# Slurp enforces one JSON document; a summary never hides a failed producer.
summarize ()
{
  jq -e -s --arg expected "$1" --arg protocol "$PROTO" --arg root "$R" '
    if length != 1 then
      error("expected exactly one diagnostic JSON document")
    else
      .[0] |
      if type == "object" and
         .schema_version == 1 and
         .status == $expected and
         .diagnostic_protocol == $protocol and
         .roots.diagnostic_root == $root and
         (.trials | type) == "array" and
         (.trials | length) == 32 and
         .v4.status == "V4_MANIFEST_PASS" and
         .v4.pinned_file_count == 24 then
        {
          status: .status,
          diagnostic_protocol: .diagnostic_protocol,
          trials: (.trials | length),
          pinned_files: .v4.pinned_file_count
        }
      else
        error("diagnostic status/protocol/root/count mismatch")
      end
    end
  '
}

echo "DIAG_V11_AUDIT_BEGIN"
"$P" -I -B "$D" audit-inputs | summarize AUDIT_PASS
echo "DIAG_V11_AUDIT_INPUTS=PASS"

ARGS=(freeze-inputs --confirm-protocol "$PROTO")
echo "DIAG_V11_FREEZE_BEGIN"
"$P" -I -B "$D" "${ARGS[@]}" | summarize INPUTS_FROZEN

test -f "$M"
test ! -L "$M"
test -O "$M"
test "$(stat -c %a "$M")" = 600
test "$(stat -c %h "$M")" = 1
summarize INPUTS_FROZEN < "$M" >/dev/null
/usr/bin/sha256sum "$M"
echo "DIAG_V11_FREEZE=PASS"
echo "NEXT: review this NEW freeze SHA before check-only; no job submitted."
REMOTE
)
RC=$?
printf 'AUDIT_FREEZE_RC=%s\n' "$RC"
if [ "$RC" -ne 0 ]; then
  echo "STOP: keep the current state; inspect before any retry."
fi
exit "$RC"
