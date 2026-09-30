#!/bin/bash
# Execute only after final v17 CPU, NFS and regression gates pass.
# Evidence: 2026-09-10-diagnostic-v17-publication-performance-repair.md.

# Mac entry: verify staging and publish once. No freeze or job submission.
(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v17"
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v17-candidate-manifest.sha256"
  CS=ad163369b0cdc10626b7bb78d6dc7d1912febf78b8b212949ec5e5cf0e8ee8e9
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
R="$B/same_bank_v4_job646900_2026-09-03_v17"
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
  f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86
  fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
  3ae558e4d80193a8c3d2697b0c7a6e2283c7bad46a1acbcec1a2aaf4e0a967a9
  fd469355ed73e73878fbca8edc0590776c00083c156312c5f39f2b1deb0d34e3
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
echo "DIAG_V17_PUBLISH_PREFLIGHT=PASS"

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
echo "REMOTE_DIAG_V17_TOOLS_PUBLISHED=PASS"
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
