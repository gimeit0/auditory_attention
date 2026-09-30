#!/bin/bash
# Mac entry: verify staging and publish once. No freeze or job submission.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v8"
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v8-candidate-manifest.sha256"
  /usr/bin/shasum -a 256 -c "$C"

  ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
umask 077
trap 'printf "PUBLISH_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v8"
S="$R/.upload-staging"
T="$R/tools"

test -d "$B"
test ! -L "$B"
test -O "$B"
NAMES=(tools .upload-staging logs state attempts submitted_runners)
DIRS=("$R")
for N in "${NAMES[@]}"
do
  DIRS+=("$R/$N")
done
for D in "${DIRS[@]}"
do
  test -d "$D"
  test ! -L "$D"
  test -O "$D"
  test "$(stat -c %a "$D")" = 700
done

EXPECTED=$(printf '%s\n' "${NAMES[@]}" | LC_ALL=C sort)
ACTUAL=$(find "$R" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "STOP: unexpected diagnostic root entries"
  printf '%s\n' "$ACTUAL"
  exit 2
fi
for N in tools logs state attempts submitted_runners
do
  ITEM=$(find "$R/$N" -mindepth 1 -print -quit)
  if [ -n "$ITEM" ]; then
    echo "STOP: directory is not empty: $R/$N"
    exit 2
  fi
done

Q1=$(squeue -h -u "$(id -un)" -n audattn_samebank_v4)
Q2=$(squeue -h -u "$(id -un)" -n audattn_v4_numdiag)
printf 'V4_QUEUE=%s\nDIAG_QUEUE=%s\n' "$Q1" "$Q2"
if [ -n "$Q1" ] || [ -n "$Q2" ]; then
  echo "STOP: related job exists"
  exit 2
fi

F=(diagnose_batch_invariance.py numeric_trace.py)
F+=(submit_numeric_diag.py run_numeric_diag.sbatch)
H=(
  6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182
  fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
  cfadc25782eb8218d696c569e4df201b545d93fe0abe7c276879850bcdbb5487
  72085b49debf2c70e730f546eb12fd62d0aa4ee64c46cfdd67d433ad4992743b
)
test "${#F[@]}" -eq "${#H[@]}"
EXPECTED=$(printf '%s\n' "${F[@]}" | LC_ALL=C sort)
ACTUAL=$(find "$S" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "STOP: staging file list differs"
  printf '%s\n' "$ACTUAL"
  exit 2
fi

for I in "${!F[@]}"
do
  P="$S/${F[$I]}"
  test -f "$P"
  test ! -L "$P"
  test -O "$P"
  test "$(stat -c %h "$P")" = 1
  test ! -e "$T/${F[$I]}"
  test ! -L "$T/${F[$I]}"
  printf '%s  %s\n' "${H[$I]}" "$P" | /usr/bin/sha256sum -c -
done
echo "DIAG_V8_PUBLISH_PREFLIGHT=PASS"

# ln -T never overwrites an existing target or follows it as a directory.
for I in "${!F[@]}"
do
  /usr/bin/ln -T -- "$S/${F[$I]}" "$T/${F[$I]}"
  chmod 600 "$T/${F[$I]}"
done
for I in "${!F[@]}"
do
  P="$T/${F[$I]}"
  test -f "$P"
  test ! -L "$P"
  test -O "$P"
  test "$S/${F[$I]}" -ef "$P"
  test "$(stat -c %h "$P")" = 2
  test "$(stat -c %a "$P")" = 600
  printf '%s  %s\n' "${H[$I]}" "$P" | /usr/bin/sha256sum -c -
done

# Remove only verified staging links; the same data remain under tools.
for I in "${!F[@]}"
do
  test -f "$S/${F[$I]}"
  test ! -L "$S/${F[$I]}"
  test "$S/${F[$I]}" -ef "$T/${F[$I]}"
  /usr/bin/unlink "$S/${F[$I]}"
done
rmdir "$S"
for I in "${!F[@]}"
do
  P="$T/${F[$I]}"
  test -f "$P"
  test ! -L "$P"
  test -O "$P"
  test "$(stat -c %h "$P")" = 1
  test "$(stat -c %a "$P")" = 600
done
find "$R" -maxdepth 2 -mindepth 1 -printf '%y|%m|%P\n' | LC_ALL=C sort
echo "REMOTE_DIAG_V8_TOOLS_PUBLISHED=PASS"
echo "Staging links removed; all four verified files retained under tools."
echo "No inputs frozen and no job submitted."
REMOTE
)
RC=$?
printf 'PUBLISH_RC=%s\n' "$RC"
if [ "$RC" -ne 0 ]; then
  echo "STOP: preserve partial state; do not rerun, overwrite, or remove anything."
fi
exit "$RC"
