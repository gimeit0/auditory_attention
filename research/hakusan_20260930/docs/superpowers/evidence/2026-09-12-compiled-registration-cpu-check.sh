#!/usr/bin/env bash
# One authentication followed immediately by ONE bounded synthetic CPU probe.
# No password storage, automatic retry, production deployment, or GPU submission.
set -euo pipefail

test "$(uname -s)" = Darwin
W="$HOME/发表/超算"
C="$W/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
D="$W/docs/superpowers/prototypes/targeted_compiled_20260912"
P="/opt/anaconda3/envs/audattn/bin/python"
test -x "$P"
test -f "$C" && test ! -L "$C"
test -d "$D" && test ! -L "$D"

printf '%s  %s\n' \
  601ca2e23d7d4907b39a3b72d601decb012d5eacfa5fecdb6833d1bc291f347a "$C" \
  66b6b75d130add467b515d94b1cc0a02e52ad94dab6344f346ffe920fa16e09c "$D/probe_driver.py" \
  424ba51350710917af334c1ea27763d99ea0b3a84c7c15a29c339803b1fa50e3 "$D/SOURCE_MANIFEST.json" |
  /usr/bin/shasum -a 256 -c -

"$P" -I -B "$D/probe_driver.py" --check-only
echo "SCOPE: authentication, then one synthetic compiled CPU batch."
echo "CPU child <=60 seconds; no checkpoints, production writes or GPU jobs."
echo "Enter any SSH password only at its terminal prompt, never in chat or this script."
bash "$C"

RC=0
"$P" -I -B "$D/probe_driver.py" --remote-probe || RC=$?
printf 'COMPILED_CPU_RC=%s\n' "$RC"
echo "Stop here and return this output for review; no automatic retry."
exit "$RC"

