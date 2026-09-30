#!/bin/bash
# Mac entry point. Query only; no directory creation, file upload or submission.
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
trap 'printf "PREFLIGHT_STOP_LINE=%s\n" "$LINENO" >&2' ERR
test "$(uname -s)" = Linux
test "$(id -un)" = s2510040

B="$HOME/audattn_external_eval_diag"
O="$B/same_bank_v4_job646900_2026-09-03_v7"
R="$B/same_bank_v4_job646900_2026-09-03_v8"
V="$HOME/audattn_external_eval/same_bank_2026-08-29_v4"
P="$HOME/miniconda3/envs/attn/bin/python"

for D in "$B" "$O" "$O/state" "$O/logs" "$V" "$V/state" "$V/tools"
do
  test -d "$D"
  test ! -L "$D"
  test -O "$D"
done

if [ -e "$R" ] || [ -L "$R" ]; then
  echo "STOP: diagnostic v8 root already exists; inspect, do not overwrite"
  ls -ld "$R"
  exit 2
fi

FILES=("$V/input_freeze.json" "$V/state/evaluation.lock")
FILES+=("$V/tools/locked_same_bank_eval.py")
FILES+=("$V/tools/run_locked_same_bank_eval.sbatch")
FILES+=("$O/input_freeze.json" "$O/state/DIAGNOSTIC_FAILED.json")
FILES+=("$O/logs/audattn_v4_numdiag_680519.log")
HASHES=(
  1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5
  63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710
  31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4
  b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495
  6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920
  2ecd6af2807d9315b4c5d1938188f0d0bf59e40fa544cee9132e7cfbffa57628
  92ad39871c7d20b36405bc78464a351c6842bbb5b220df99213337cd51f1dd92
)
test "${#FILES[@]}" -eq "${#HASHES[@]}"
for I in "${!FILES[@]}"
do
  ITEM="${FILES[$I]}"
  test -f "$ITEM"
  test ! -L "$ITEM"
  test -O "$ITEM"
  printf '%s  %s\n' "${HASHES[$I]}" "$ITEM" |
    /usr/bin/sha256sum -c -
done
echo "OLD_V7_AND_V4_EVIDENCE=PASS"

Q1=$(squeue -h -u "$(id -un)" -n audattn_samebank_v4)
Q2=$(squeue -h -u "$(id -un)" -n audattn_v4_numdiag)
printf 'V4_QUEUE=%s\nDIAG_QUEUE=%s\n' "$Q1" "$Q2"
if [ -n "$Q1" ] || [ -n "$Q2" ]; then
  echo "STOP: related job exists; no next-stage actions allowed"
  exit 2
fi

test -x "$P"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
echo "SAME_ENVIRONMENT_PROBE_BEGIN"
"$P" -I -B - <<'PY'
import json
from collections import deque
import torch


def require(condition, message):
    if not condition:
        raise SystemExit("STOP: " + message)


def probe_collections():
    # API primitives used by v8, not an import or execution of its evaluator.
    window = deque([0, 1, 0], maxlen=1000)
    require(type(window) is deque, "deque exact type differs")
    require(deque.__len__(window) == 3, "deque length differs")
    require(deque.maxlen.__get__(window, deque) == 1000, "deque capacity differs")
    require(tuple(deque.__iter__(window)) == (0, 1, 0), "deque contents differ")
    before = tuple(deque.__iter__(window))
    window[0] = 1
    require(tuple(deque.__iter__(window)) != before, "deque mutation unreadable")
    shape = torch.Size([1, 2, 3])
    dimensions = tuple(tuple.__iter__(shape))
    require(type(shape) is torch.Size, "torch.Size exact type differs")
    require(tuple.__len__(shape) == 3, "torch.Size length differs")
    require(dimensions == (1, 2, 3), "torch.Size dimensions differ")
    require(all(type(item) is int for item in dimensions), "shape type differs")
    types_seen = []
    for cls in (deque, torch.Size):
        module = type.__dict__["__module__"].__get__(cls)
        name = type.__dict__["__qualname__"].__get__(cls)
        require(type(module) is str and type(name) is str, "type metadata differs")
        types_seen.append(module + "." + name)
    return {"deque_maxlen": 1000, "shape_dimensions": dimensions, "types": types_seen}


print("TORCH_VERSION=" + torch.__version__, flush=True)
require(torch.__version__ == "2.1.1+cu118", "attn torch version is unexpected")
torch.use_deterministic_algorithms(True)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
torch.set_float32_matmul_precision("medium")
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
runtime = (
    torch.are_deterministic_algorithms_enabled(),
    torch.backends.cudnn.deterministic,
    torch.backends.cudnn.benchmark,
    torch.get_float32_matmul_precision(),
    torch.backends.cuda.matmul.allow_tf32,
    torch.backends.cudnn.allow_tf32,
)
expected = (True, True, False, "high", True, True)
print("RUNTIME_VALUES=" + json.dumps(runtime), flush=True)
require(runtime == expected, "runtime values differ")
require(
    all(type(actual) is type(wanted) for actual, wanted in zip(runtime, expected)),
    "runtime value types differ",
)
print("RUNTIME_SIX_FLAGS=PASS", flush=True)
print("COLLECTION_API_VALUES=" + json.dumps(probe_collections()), flush=True)
print("COLLECTION_API_PROBE=PASS", flush=True)
print("PROBE_SCOPE=API_ONLY_NO_V8_EVALUATOR_NO_MODEL_NO_GPU_INFERENCE", flush=True)
PY
echo "SAME_ENVIRONMENT_PROBE_END"
echo "REMOTE_DIAG_V8_PREFLIGHT=PASS"
echo "Read-only preflight; no root created, files uploaded, freeze or job submitted."
REMOTE
)
RC=$?
printf 'PREFLIGHT_RC=%s\n' "$RC"
exit "$RC"
