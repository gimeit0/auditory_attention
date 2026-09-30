#!/bin/bash
# Mac entry: verify staging and publish once. No freeze or job submission.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v10"
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v10-r3-candidate-manifest.sha256"
  CS=ca282426ebead30831fb87b22ce6de0f1fb93cf09c397a8cc1c75c41745bdee1
  printf '%s  %s\n' "$CS" "$C" | /usr/bin/shasum -a 256 -c -
  /usr/bin/shasum -a 256 -c "$C"

  CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
  ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    s2510040@hakusan1 bash -s <<'REMOTE'
set -euo pipefail
umask 077
trap 'printf "PUBLISH_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
R="$B/same_bank_v4_job646900_2026-09-03_v10"
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
  2c3e07d218076abb27ba613556cfda4792ed7490821cbdbc43ad610788b637eb
  fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
  e123b172cf150fc4a015992fa3511e2a9a9c9109987575c405dcf0bee0aa322b
  63dc1293528612afbf69c79273aa3b2f37ca41ed524cfa5f054f9f4f48d77cfa
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
echo "DIAG_V10_PUBLISH_PREFLIGHT=PASS"

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
echo "REMOTE_DIAG_V10_TOOLS_PUBLISHED=PASS"
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
