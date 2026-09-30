(
  set -euo pipefail
  test "$(uname -s)" = Darwin

  cd "$HOME/发表/超算"
  cd same_bank_eval_2026_09_03_v4_numeric_diag_v7
  C="../.superpowers/sdd"
  C="$C/2026-09-03-v4-numerical-diagnostic-implementation"
  C="$C/v7-candidate-manifest.sha256"
  /usr/bin/shasum -a 256 -c "$C"

  ssh s2510040@hakusan1 '
    set -euo pipefail
    umask 077
    test "$(uname -s)" = Linux
    test "$(id -un)" = s2510040

    B="$HOME/audattn_external_eval_diag"
    R="$B/same_bank_v4_job646900_2026-09-03_v7"
    S="$R/.upload-staging"
    T="$R/tools"

    test -d "$B"
    test ! -L "$B"
    test -O "$B"
    DIRS=(tools .upload-staging logs state attempts submitted_runners)
    for D in "$R" "${DIRS[@]/#/$R/}"
    do
      test -d "$D"
      test ! -L "$D"
      test -O "$D"
      test "$(stat -c %a "$D")" = 700
    done

    EXPECTED=$(printf "%s\n" "${DIRS[@]}" | LC_ALL=C sort)
    ACTUAL=$(find "$R" -mindepth 1 -maxdepth 1 -printf "%f\n" |
      LC_ALL=C sort)
    if [ "$ACTUAL" != "$EXPECTED" ]; then
      echo "STOP: unexpected diagnostic root entries"
      printf "%s\n" "$ACTUAL"
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

    Q1=$(squeue -h -u "$USER" -n audattn_samebank_v4)
    Q2=$(squeue -h -u "$USER" -n audattn_v4_numdiag)
    if [ -n "$Q1" ] || [ -n "$Q2" ]; then
      printf "%s\n" "$Q1" "$Q2"
      echo "STOP: related job exists"
      exit 2
    fi

    F=(diagnose_batch_invariance.py numeric_trace.py)
    F+=(submit_numeric_diag.py run_numeric_diag.sbatch)
    H=(
      7e18242bf96be03e8e50e713be877b4a52c321c6874cb81bca2b9955db924167
      fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
      d74c4878ccd5e9c79cd3854139009c1d2c5449df846082667ac7407ade474e86
      19c0d314f5ec1c8c3d93eae8a04c7c33d38b98079f1ee447cfabe95dacad0b62
    )
    EXPECTED=$(printf "%s\n" "${F[@]}" | LC_ALL=C sort)
    ACTUAL=$(find "$S" -mindepth 1 -maxdepth 1 -printf "%f\n" |
      LC_ALL=C sort)
    if [ "$ACTUAL" != "$EXPECTED" ]; then
      echo "STOP: staging file list differs"
      printf "%s\n" "$ACTUAL"
      exit 2
    fi

    for I in 0 1 2 3
    do
      P="$S/${F[$I]}"
      test -f "$P"
      test ! -L "$P"
      test -O "$P"
      test "$(stat -c %h "$P")" = 1
      test ! -e "$T/${F[$I]}"
      test ! -L "$T/${F[$I]}"
      printf "%s  %s\n" "${H[$I]}" "$P" |
        /usr/bin/sha256sum -c -
    done
    echo "DIAG_V7_PUBLISH_PREFLIGHT=PASS"

    for I in 0 1 2 3
    do
      /usr/bin/ln -T -- "$S/${F[$I]}" "$T/${F[$I]}"
      chmod 600 "$T/${F[$I]}"
    done

    for I in 0 1 2 3
    do
      P="$T/${F[$I]}"
      test -f "$P"
      test ! -L "$P"
      test -O "$P"
      test "$S/${F[$I]}" -ef "$P"
      test "$(stat -c %h "$P")" = 2
      test "$(stat -c %a "$P")" = 600
      printf "%s  %s\n" "${H[$I]}" "$P" |
        /usr/bin/sha256sum -c -
    done

    for I in 0 1 2 3
    do
      test "$S/${F[$I]}" -ef "$T/${F[$I]}"
      /usr/bin/unlink "$S/${F[$I]}"
    done
    rmdir "$S"

    for I in 0 1 2 3
    do
      P="$T/${F[$I]}"
      test -f "$P"
      test ! -L "$P"
      test -O "$P"
      test "$(stat -c %h "$P")" = 1
      test "$(stat -c %a "$P")" = 600
    done
    find "$R" -maxdepth 2 -mindepth 1 -printf "%y|%m|%P\n" |
      LC_ALL=C sort
    echo "REMOTE_DIAG_V7_TOOLS_PUBLISHED=PASS"
  '
)
RC=$?
printf 'PUBLISH_RC=%s\n' "$RC"
exit "$RC"
