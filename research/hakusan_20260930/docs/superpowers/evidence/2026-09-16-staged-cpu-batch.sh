#!/usr/bin/env bash
# Fixed, explicit CPU-only actions. Never reconnect or retry automatically.
set -euo pipefail
umask 077
test "$(uname -s)" = Darwin
cd "$(dirname "$0")/../../.."
P=/opt/anaconda3/envs/audattn/bin/python
T=docs/superpowers/prototypes/staged_scratch_batch_20260915
L="$PWD/docs/superpowers/evidence/staged-cpu-batch-20260915"
L="$L/local-dx511ko2"
F=(common.py runtime.py remote.py driver.py test_batch.py run_cpu.sbatch)
H=(
  d50999d9a1067761153c79ad797418d3b53dceb73356a0df38595cbae87760fd
  a442eb1ff53f8aee6d6a5ca682d67eaa6f7f9b33fb4c07e909aa9446ec1c3d7a
  91cd8804774e4897a522f824f5c8ea29c1eb40a662e105f17900dc1f8c29b195
  17cdd5408ecfc0ecfaea4652a131c541642fea207529dc95242ee47127e9768a
  089412ec0cb23a2b99fbabfb58a37e4665b2c545378e769accb39cd59f6914fd
  83f5d59a93285e4bdae7121647541c5da87b8ad7612d98c509aaa8ea0f7affec
)
for I in 0 1 2 3 4 5
do
  printf '%s  %s\n' "${H[$I]}" "$T/${F[$I]}" |
    /usr/bin/shasum -a 256 -c -
done
printf '%s  %s\n' \
  9fedb04058706453561c874eb9fba90ac37283c46e81e65f54a8148ff35b78db \
  "$L/RELEASE.json" \
  5cb8b36be32926f9a943cfe5cb9b86ae441eb738ed5ca851187ac7ff9666ae1a \
  "$L/LOCAL_REVIEW.json" | /usr/bin/shasum -a 256 -c -
echo 'SCOPE: synthetic CPU batch only; 1 CPU / 6000 MiB / 10 min / 0 GPU.'
echo 'No automatic reconnect, retry, resource increase, or downstream GPU submission.'
"$P" -I -B "$T/driver.py" "$@" --local "$L"
