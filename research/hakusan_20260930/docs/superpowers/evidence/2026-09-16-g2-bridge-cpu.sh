#!/usr/bin/env bash
# Explicit actions only. Authentication is separate; default is read-only.
set -euo pipefail
test "$(uname -s)" = Darwin
W="$HOME/发表/超算"
P=/opt/anaconda3/envs/audattn/bin/python
D="$W/docs/superpowers/prototypes/g2_bridge_batch_20260916/driver.py"
L="$W/docs/superpowers/evidence/g2-bridge-batch-20260916/local-tjfvm5j0"
printf '%s  %s\n' \
  a7b4191c3440fb1ba7e8239c79fc2ca37c9bd6bb70832b069b1182b2b127e1af "$D" \
  50820c6fa76f60064cdcc0dd0ae3d9f4a5de2dd64ed41d2256e5e2c1945fa227 "$L/BATCH_RELEASE.json" \
  88a72b2f8982afde2c329468d4c70d13302a362869035c5e3cd76189a203a957 "$L/LOCAL_REVIEW.json" |
  /usr/bin/shasum -a 256 -c -
ACTION="${1:-preflight}"
case "$ACTION" in
  preflight|deploy|test-only|status|collect)
    test "$#" -le 1
    exec "$P" -I -B "$D" "$ACTION" --local "$L"
    ;;
  submit)
    test "$#" -eq 2
    echo 'One approved CPU job only; no automatic retry.'
    exec "$P" -I -B "$D" submit --local "$L" --test "$2" \
      --confirmation ONE_SYNTHETIC_CPU_JOB_1CPU_6000M_22MIN_NO_GPU
    ;;
  review)
    test "$#" -eq 2
    exec "$P" -I -B "$D" review --local "$L" --collection "$2"
    ;;
  *)
    echo 'Usage: script [preflight|deploy|test-only|status|collect]'
    echo '       script submit TEST_RECEIPT_DIRECTORY'
    echo '       script review COLLECTION_DIRECTORY'
    exit 2
    ;;
esac
