#!/bin/bash
# Execute only after all v18 resource-bound and regression tests pass.
# Scientific/guard/publication bodies are byte-identical to v17.
# Evidence: 2026-09-11-diagnostic-v18-resource-extension.md.

# Mac only: create a previously absent v18 root and upload four files to staging.
# No publication, freeze, sbatch or retry. Inspect partial state after failure.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v18"
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v18-candidate-manifest.sha256"
  CS=bcd7d3e5bb776323d2b3975791962418893a3fa1746905dd3719563925f77e72
  printf '%s  %s\n' "$CS" "$C" | /usr/bin/shasum -a 256 -c -
  /usr/bin/shasum -a 256 -c "$C"

  FILES=(diagnose_batch_invariance.py numeric_trace.py)
  FILES+=(submit_numeric_diag.py run_numeric_diag.sbatch)
  for F in "${FILES[@]}"
  do
    test -f "$F"
    test ! -L "$F"
  done

  CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
  ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
umask 077
trap 'printf "CREATE_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
O="$B/same_bank_v4_job646900_2026-09-03_v17"
R="$B/same_bank_v4_job646900_2026-09-03_v18"
V="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"

for D in "$B" "$O" "$O/state" "$O/logs" "$V" "$V/state" "$V/tools"
do
  test -d "$D"
  test ! -L "$D"
  test -O "$D"
done

if [ -e "$R" ] || [ -L "$R" ]; then
  echo "STOP: diagnostic v18 root already exists; inspect, do not overwrite"
  ls -ld "$R"
  exit 2
fi

OLD_FILES=("$V/input_freeze.json" "$V/state/evaluation.lock")
OLD_FILES+=("$V/tools/locked_same_bank_eval.py")
OLD_FILES+=("$V/tools/run_locked_same_bank_eval.sbatch")
OLD_FILES+=("$O/input_freeze.json" "$O/state/DIAGNOSTIC_FAILED.json")
OLD_FILES+=("$O/logs/audattn_v4_numdiag_683837.log")
HASHES=(
  1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5
  63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710
  31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4
  b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495
  a62ad2eaa97d4007505b584106b17812981364768170d8bc486291921fd39111
  aa7f03142c21a42b08014de170e0676cb39c8aa25cdbea27b16139c69707abb3
  47ce80f74713cc573ed5e32f5a2687f5e9fa19732b95d18aab4afcc3b6cc0eb0
)
test "${#OLD_FILES[@]}" -eq "${#HASHES[@]}"
for I in "${!OLD_FILES[@]}"
do
  F="${OLD_FILES[$I]}"
  test -f "$F"
  test ! -L "$F"
  test -O "$F"
  printf '%s  %s\n' "${HASHES[$I]}" "$F" |
    /usr/bin/sha256sum -c -
done

Q1=$(squeue -h -u "$(id -un)" -n audattn_samebank_v4)
Q2=$(squeue -h -u "$(id -un)" -n audattn_v4_numdiag)
printf 'V4_QUEUE=%s\nDIAG_QUEUE=%s\n' "$Q1" "$Q2"
if [ -n "$Q1" ] || [ -n "$Q2" ]; then
  echo "STOP: related job exists"
  exit 2
fi
echo "DIAG_V18_CREATE_PREFLIGHT=PASS"

# Deliberately no mkdir -p: an existing root, including a race, must fail.
mkdir -m 700 "$R"
NAMES=(tools .upload-staging logs state attempts submitted_runners)
DIRS=("$R")
for N in "${NAMES[@]}"
do
  mkdir -m 700 "$R/$N"
  DIRS+=("$R/$N")
done
for D in "${DIRS[@]}"
do
  test -d "$D"
  test ! -L "$D"
  test -O "$D"
  test "$(stat -c %a "$D")" = 700
done
find "$R" -mindepth 1 -maxdepth 1 -printf '%y|%m|%f\n' | LC_ALL=C sort
echo "REMOTE_DIAG_V18_ROOT_CREATED=PASS"
REMOTE

  # Do not transfer modified files if the local candidate changed during SSH.
  /usr/bin/shasum -a 256 -c "$C"
  for F in "${FILES[@]}"
  do
    test -f "$F"
    test ! -L "$F"
  done
  DEST="s2510040@hakusan1:audattn_external_eval_diag"
  DEST="$DEST/same_bank_v4_job646900_2026-09-03_v18/.upload-staging/"
  scp -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 "${FILES[@]}" "$DEST"
  echo "DIAG_V18_UPLOAD_TO_STAGING=PASS"
  echo "Staging transfer only. Remote hash verification/publication still required."
)
RC=$?
printf 'UPLOAD_RC=%s\n' "$RC"
if [ "$RC" -ne 0 ]; then
  echo "STOP: do not rerun or remove anything; return output for read-only inspection."
fi
exit "$RC"
