#!/bin/bash
# Read-only stdlib probe of SHA-bound v18 timeout handling on the real Python.
set -euo pipefail
test "$(uname -s)" = Darwin
CONTROL="$HOME/发表/超算/.hakusan-control/master.sock"
ssh -o "ControlPath=$CONTROL" -o BatchMode=yes -o ConnectTimeout=12 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 s2510040@hakusan1 \
  /home/s2510040/miniconda3/envs/attn/bin/python -I -B - <<'PROBE'
import hashlib
import pathlib
import sys
import types

path = pathlib.Path('/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18/tools/diagnose_batch_invariance.py')
expected = '7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b'
if path.is_symlink() or not path.is_file():
    raise SystemExit('STOP: source path invalid')
raw = path.read_bytes()
if hashlib.sha256(raw).hexdigest() != expected:
    raise SystemExit('STOP: source SHA differs')
diag = types.ModuleType('_v18_resource_probe')
diag.__file__ = str(path)
sys.modules[diag.__name__] = diag
exec(compile(raw, str(path), 'exec'), diag.__dict__)
args = ('123', 'a' * 64, '/tmp/audattn_v4_numdiag_123')
launcher = diag._ColdChildLauncher(*args)
assert launcher.timeout_seconds == 5400.0
assert launcher._active is None and launcher._attempted == set()
for value in (3000, 3601, 5400):
    assert diag._ColdChildLauncher(*args, timeout_seconds=value).timeout_seconds == value
for value in (True, False, 0, -1, 5400.000001, 5401, 14400, float('inf'), float('nan'), '5400'):
    try:
        diag._ColdChildLauncher(*args, timeout_seconds=value)
    except diag.DiagnosticError:
        pass
    else:
        raise SystemExit('STOP: invalid timeout accepted')
assert not any(name in sys.modules for name in ('torch', 'numpy', 'torchaudio'))
assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
print('PYTHON_VERSION=' + sys.version.split()[0])
print('CHILD_DEFAULT_AND_MAX_SECONDS=5400')
print('RESOURCE_PROBE=PASS')
print('SCOPE=STDLIB_ONLY_NO_FILES_WRITTEN_NO_MODEL_NO_GPU_NO_CHILD_LAUNCHED')
PROBE
