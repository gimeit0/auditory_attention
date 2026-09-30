#!/bin/bash
#SBATCH --job-name=audattn_v4_numdiag
#SBATCH --partition=GPU-1A
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=01:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v14
#SBATCH --output=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v14/logs/audattn_v4_numdiag_%j.log
#SBATCH --error=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v14/logs/audattn_v4_numdiag_%j.log

set -euo pipefail
umask 077
[[ "$#" -eq 2 ]] || { echo 'ERROR: expected freeze SHA and intent nonce' >&2; exit 2; }
[[ "${SLURM_JOB_ID:-}" =~ ^[1-9][0-9]{0,19}$ ]] || exit 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{32}$ ]] || exit 2
[[ -n "${CUDA_VISIBLE_DEVICES:-}" ]] || exit 2

# Slurm submission uses --export=NONE. Rebuild, never inherit, the Python env.
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONUSERBASE
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL VIRTUAL_ENV
unset LD_PRELOAD LD_LIBRARY_PATH DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
unset BASH_ENV ENV CDPATH
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
KEEP=()
for KEY in SLURM_JOB_ID SLURM_JOB_NODELIST SLURM_NNODES SLURM_NTASKS \
  SLURM_CPUS_PER_TASK SLURM_JOB_GPUS SLURM_STEP_GPUS SLURM_TMPDIR \
  CUDA_VISIBLE_DEVICES
do
  if [[ "${!KEY+x}" == x ]]; then KEEP+=("$KEY=${!KEY}"); fi
done
exec /usr/bin/env -i "${KEEP[@]}" \
  PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$PYTHON" -I -B - "$0" "$1" "$2" <<'BOOTSTRAP_PY'
# BEGIN STDLIB BOOTSTRAP
import hashlib
import json
import os
import pathlib
import re
import stat
import sys
import types

ROOT = pathlib.Path('/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v14')
PYTHON = pathlib.Path('/home/s2510040/miniconda3/envs/attn/bin/python')
PROTOCOL = 'formal40_batch_invariance_diag_20260903_v14'
FILES = ('diagnose_batch_invariance.py', 'numeric_trace.py',
         'submit_numeric_diag.py', 'run_numeric_diag.sbatch')
SCHEDULER_KEYS = ('SLURM_JOB_ID', 'SLURM_JOB_NODELIST', 'SLURM_NNODES',
                  'SLURM_NTASKS', 'SLURM_CPUS_PER_TASK', 'SLURM_JOB_GPUS',
                  'SLURM_STEP_GPUS', 'SLURM_TMPDIR', 'CUDA_VISIBLE_DEVICES')


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def validate_identity(job, sha, nonce):
    if (not re.fullmatch(r'[1-9][0-9]{0,19}', job)
            or not re.fullmatch(r'[0-9a-f]{64}', sha)
            or not re.fullmatch(r'[0-9a-f]{32}', nonce)):
        raise ValueError('invalid job/freeze/intent identity')


def safe_path(raw):
    path = pathlib.Path(raw)
    if (not path.is_absolute() or str(path) != str(raw) or '..' in path.parts
            or any(ord(c) < 32 for c in str(path))):
        raise ValueError('noncanonical absolute path')
    for item in (*reversed(path.parents), path):
        if stat.S_ISLNK(item.lstat().st_mode):
            raise ValueError('symlink in bootstrap path')
    return path


def read_file(path, limit=32 * 1024 * 1024):
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('bootstrap source must be a bounded regular file')
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
        if (len(raw) != before.st_size or identity(before) != identity(os.fstat(fd))
                or identity(before) != identity(path.lstat())):
            raise ValueError('bootstrap source changed while reading')
        return raw
    finally:
        os.close(fd)


def read_json(path):
    raw = read_file(path)
    value = json.loads(raw)
    if not isinstance(value, dict) or canonical(value) != raw:
        raise ValueError('bootstrap JSON must be canonical')
    return value, raw


def expected_intent(root, sha, nonce, runner_sha):
    return dict(schema_version=1, diagnostic_protocol=PROTOCOL,
                intent_nonce=nonce, input_freeze_sha256=sha,
                runner_sha256=runner_sha, status='SUBMISSION_INTENT',
                argv=['/usr/bin/sbatch', '--parsable', '--export=NONE',
                      f'--comment=audattn-v4-numdiag-{nonce[:12]}',
                      str(root / 'tools/run_numeric_diag.sbatch'), sha, nonce])


def validate_inputs(root, spool, job, sha, nonce):
    # Private fixture arguments; production main supplies literal ROOT only.
    validate_identity(job, sha, nonce)
    root = safe_path(root)
    for name in ('tools', 'state', 'attempts', 'submitted_runners'):
        if not safe_path(root / name).is_dir():
            raise ValueError('missing bootstrap directory')
    if list((root / 'attempts').iterdir()) or list((root / 'submitted_runners').iterdir()):
        raise ValueError('previous attempt or submitted runner exists; no retry')
    for name in ('DIAGNOSTIC_COMPLETE.json', 'DIAGNOSTIC_FAILED.json'):
        if os.path.lexists(root / 'state' / name):
            raise ValueError('diagnostic already terminal')
    freeze, raw = read_json(root / 'input_freeze.json')
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('input freeze SHA mismatch')
    records = freeze.get('production_files')
    if (not isinstance(records, list) or len(records) != len(FILES)
            or any(not isinstance(r, dict) for r in records)
            or {r.get('relative_path') for r in records} != set(FILES)):
        raise ValueError('production inventory differs')
    payloads = {}
    for record in records:
        name = record['relative_path']
        raw = read_file(root / 'tools' / name)
        if type(record.get('size')) is not int or len(raw) != record['size']:
            raise ValueError('production source size differs')
        if hashlib.sha256(raw).hexdigest() != record.get('sha256'):
            raise ValueError('production source SHA differs')
        payloads[name] = raw
    spool_raw = read_file(spool)
    if spool_raw != payloads['run_numeric_diag.sbatch']:
        raise ValueError('spool/live/frozen runner mismatch')
    runner_sha = hashlib.sha256(spool_raw).hexdigest()
    intent, _ = read_json(root / 'state/INTENT.json')
    if intent != expected_intent(root, sha, nonce, runner_sha):
        raise ValueError('submission intent mismatch')
    # No receipt wait here: coordinator owns bounded wait and final job binding.
    return freeze, payloads['diagnose_batch_invariance.py']


def validate_parent_policy(parent, info, *, supplied):
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('scratch parent is not a directory')
    if supplied:
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Slurm scratch parent is not private/user-owned')
    elif parent != pathlib.Path('/tmp') or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o1777:
        raise ValueError('only root-owned sticky 01777 /tmp fallback is allowed')


def create_scratch(diag, job, scheduler):
    supplied = 'SLURM_TMPDIR' in scheduler
    raw = scheduler.get('SLURM_TMPDIR', '/tmp')
    if not raw:
        raise ValueError('empty supplied Slurm scratch parent')
    parent = safe_path(raw)
    with diag._PinnedArtifactDirectory(parent) as anchor:
        validate_parent_policy(parent, os.fstat(anchor.fd), supplied=supplied)
        diag._require_local_scratch_mount(parent)
        name = f'audattn_v4_numdiag_{job}'
        os.mkdir(name, 0o700, dir_fd=anchor.fd)
        anchor.check()
        scratch = parent / name
        with diag._PinnedArtifactDirectory(scratch) as local:
            for name in sorted(set(diag._COORDINATOR_WRITE_PATHS.values())):
                os.mkdir(name, 0o700, dir_fd=local.fd)
            local.check()
        anchor.check()
    return scratch


def main():
    if len(sys.argv) != 4 or not sys.platform.startswith('linux'):
        raise ValueError('bootstrap requires Linux and exactly spool/SHA/nonce')
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode or pathlib.Path(sys.executable).resolve() != PYTHON.resolve():
        raise ValueError('bootstrap interpreter differs')
    spool, sha, nonce = sys.argv[1:]
    scheduler = {k: os.environ[k] for k in SCHEDULER_KEYS if k in os.environ}
    job = scheduler.get('SLURM_JOB_ID', '')
    freeze, code = validate_inputs(ROOT, spool, job, sha, nonce)
    # Execute exactly the SHA-verified stdlib source bytes, not a second file read.
    diag = types.ModuleType('_runner_verified_diag')
    diag.__file__ = str(ROOT / 'tools/diagnose_batch_invariance.py')
    sys.modules[diag.__name__] = diag
    exec(compile(code, diag.__file__, 'exec'), diag.__dict__)
    diag._validate_freeze_value(freeze, diag.production_contract(),
                                status='INPUTS_FROZEN', diagnostic_root=ROOT)
    args = types.SimpleNamespace(job_id=job, intent_nonce=nonce,
             expected_input_freeze_sha256=sha, spool_runner=spool)
    command = diag.coordinator_command(args)
    # Validate scheduler/environment before creating any directory.
    probe = pathlib.Path('/tmp') / f'audattn_v4_numdiag_{job}'
    diag.coordinator_environment(job, str(probe), scheduler)
    scratch = create_scratch(diag, job, scheduler)
    environment = diag.coordinator_environment(job, str(scratch), scheduler)
    os.environ.clear()
    os.environ.update(environment)
    with diag._coordinator_scratch(args) as check:
        if validate_inputs(ROOT, spool, job, sha, nonce) != (freeze, code):
            raise ValueError('bootstrap input changed before exec')
        record = canonical(dict(job_id=job, argv=command, environment=environment))
        print('BOOTSTRAP_ENVIRONMENT=' + record.decode('ascii').rstrip(), file=sys.stderr, flush=True)
        print('BOOTSTRAP_ENVIRONMENT_SHA256=' + hashlib.sha256(record).hexdigest(), file=sys.stderr, flush=True)
        check()
        os.execve(command[0], command, environment)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('ERROR: runner bootstrap: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(2)
# END STDLIB BOOTSTRAP
BOOTSTRAP_PY
