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

    test -d "$B"
    test ! -L "$B"
    test -O "$B"

    if [ -e "$R" ] || [ -L "$R" ]; then
      echo "STOP: diagnostic v7 root already exists"
      ls -ld "$R"
      exit 2
    fi

    Q1=$(squeue -h -u "$USER" -n audattn_samebank_v4)
    Q2=$(squeue -h -u "$USER" -n audattn_v4_numdiag)
    if [ -n "$Q1" ] || [ -n "$Q2" ]; then
      printf "%s\n" "$Q1" "$Q2"
      echo "STOP: related job exists"
      exit 2
    fi

    mkdir -m 700 "$R"
    NAMES="tools .upload-staging logs state attempts submitted_runners"
    for N in $NAMES
    do
      mkdir -m 700 "$R/$N"
    done

    for D in "$R" "$R/.upload-staging" "$R"/*
    do
      test -d "$D"
      test ! -L "$D"
      test -O "$D"
      test "$(stat -c %a "$D")" = 700
    done
    echo "REMOTE_DIAG_V7_ROOT_CREATED=PASS"
  '

  DEST="s2510040@hakusan1:audattn_external_eval_diag"
  DEST="$DEST/same_bank_v4_job646900_2026-09-03_v7"
  DEST="$DEST/.upload-staging/"

  FILES=(diagnose_batch_invariance.py numeric_trace.py)
  FILES+=(submit_numeric_diag.py run_numeric_diag.sbatch)
  scp "${FILES[@]}" "$DEST"

  echo "DIAG_V7_UPLOAD_TO_STAGING=PASS"
)
RC=$?
printf 'UPLOAD_RC=%s\n' "$RC"
exit "$RC"
