"""Bounded temporary CPU compatibility execution; never a deployed job runner.

SPEC is supplied by the locally checked driver. Every package byte is bound to
the reviewed manifest. No remote shell, scheduler, production data/model load,
permanent root, or authorization/freeze writer is called.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import resource
import signal
import socket
import sys
import tempfile
import time

PACKAGE_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'
JOB = 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5'
MANIFEST = JOB + '/SOURCE_MANIFEST.json'
COUNTS = {'input_binding': 25, 'startup': 12, 'result_identity': 11, 'adapter_cpu': 30, 'scratch_lifetime': 2}
CAP_BYTES = 16 * 1024**2
WALL_SECONDS = 90


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def member(name):
    require(type(name) is str and name and '\\' not in name, 'invalid source member')
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'source path escape')
    return path


def unpack(spec):
    require(spec['mode'] in ('NATIVE_CPU', 'LOCAL_HARNESS') and spec['package_sha256'] == PACKAGE_SHA,
            'fixed mode/package required')
    require(type(spec['request_id']) is str and len(spec['request_id']) == 32
            and all(c in '0123456789abcdef' for c in spec['request_id']), 'request identity invalid')
    require(type(spec['files']) is dict and len(spec['files']) == 163, 'exact package inventory required')
    files, total = {}, 0
    for name, encoded in spec['files'].items():
        member(name)
        require(type(encoded) is str and len(encoded) <= CAP_BYTES * 2, 'bounded encoded source required')
        raw = base64.b64decode(encoded, validate=True)
        total += len(raw)
        require(total <= CAP_BYTES, 'package byte budget exceeded')
        files[name] = raw
    require(sha(files[MANIFEST]) == PACKAGE_SHA, 'reviewed package manifest differs')
    manifest = json.loads(files[MANIFEST])
    require(set(files) == {*manifest['files'], MANIFEST}, 'extra/missing source member')
    require(all(sha(files[n]) == s for n, s in manifest['files'].items()), 'source digest differs')
    child = base64.b64decode(spec['child_source'], validate=True)
    require(len(child) <= 64 * 1024 and sha(child) == spec['child_sha256'], 'child source differs')
    return files, child, manifest


def child_environment(root):
    # Account HOME is passed through unchanged; all generated caches stay private.
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG', 'LC_ALL') if k in os.environ}
    require(type(env.get('HOME')) is str and env['HOME'].startswith('/'), 'existing HOME required')
    caches = {'TMPDIR': 'tmp', 'TMP': 'tmp', 'TEMP': 'tmp', 'MPLCONFIGDIR': 'mpl',
        'XDG_CACHE_HOME': 'xdg', 'TORCH_HOME': 'torch', 'NUMBA_CACHE_DIR': 'numba',
        'TORCHINDUCTOR_CACHE_DIR': 'inductor', 'TRITON_CACHE_DIR': 'triton', 'CUDA_CACHE_PATH': 'cuda'}
    for relative in set(caches.values()):
        (root / relative).mkdir(mode=0o700)
    env.update({key: str(root / relative) for key, relative in caches.items()})
    env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        TOKENIZERS_PARALLELISM='false', PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
    return env


def source_check(root, files):
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    require(actual == set(files), 'temporary package inventory changed')
    for name, raw in files.items():
        path = root / member(name)
        require(not path.is_symlink() and path.read_bytes() == raw, 'temporary source changed')


def main(spec):
    started = time.monotonic()
    os.umask(0o077)
    require(sys.flags.isolated and sys.dont_write_bytecode, 'isolated interpreter required')
    native = spec.get('mode') == 'NATIVE_CPU'
    if native:
        require(sys.platform == 'linux' and pwd.getpwuid(os.getuid()).pw_name == 's2510040'
                and sys.version.split()[0] == '3.11.5', 'native account/Python differs')
        require(Path(sys.executable).resolve() == Path('/home/s2510040/miniconda3/envs/attn/bin/python').resolve(),
                'native interpreter path differs')
        require(socket.gethostname().split('.')[0].startswith('hakusan'), 'login-node CPU scope only')
        allowed = os.sched_getaffinity(0)
        require(bool(allowed), 'CPU affinity unavailable')
        os.sched_setaffinity(0, {min(allowed)})
        require(len(os.sched_getaffinity(0)) == 1, 'one CPU affinity required')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    previous_home = os.environ.get('HOME')
    records, error, removed, root = [], None, False, None
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('native compatibility 90-second deadline')))
    signal.alarm(WALL_SECONDS)
    try:
        files, child, manifest = unpack(spec)
        with tempfile.TemporaryDirectory(prefix='v19-native-cpu-', dir='/tmp') as temporary:
            root = Path(temporary).resolve()
            package = root / 'package'
            package.mkdir(mode=0o700)
            for name, raw in files.items():
                path = package / member(name)
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(raw)
            child_path = root / 'child_checks.py'
            with child_path.open('xb') as stream:
                stream.write(child)
            runner_path = package / JOB / 'process_runner.py'
            loader = importlib.util.spec_from_file_location('native_cpu_process_supervisor', runner_path)
            runner = importlib.util.module_from_spec(loader)
            loader.loader.exec_module(runner)
            source_check(package, files)
            for group, count in COUNTS.items():
                remaining = WALL_SECONDS - (time.monotonic() - started) - 5
                require(remaining > 1, 'no bounded time left; stop without retry')
                cache = root / group
                cache.mkdir(mode=0o700)
                env = child_environment(cache)
                print('V19_CPU_GROUP_BEGIN=' + group, flush=True)
                log = root / (group + '.log')
                outcome = runner.run_process([sys.executable, '-I', '-B', str(child_path), str(package), group, spec['mode']],
                    env, log, seconds=min(50, remaining), max_log_bytes=1024**2)
                raw_log = log.read_bytes()
                lines = [line.removeprefix('V19_CPU_CHILD=') for line in raw_log.decode(errors='replace').splitlines()
                         if line.startswith('V19_CPU_CHILD=')]
                record = json.loads(lines[0]) if len(lines) == 1 else None
                row = {'group': group, 'process': outcome, 'record': record,
                       'log_base64': base64.b64encode(raw_log).decode('ascii')}
                records.append(row)
                require(outcome['returncode'] == 0 and outcome['error'] is None and type(record) is dict,
                        'native child failed: ' + group)
                require(record['status'] == 'SYNTHETIC_CPU_SUITE_PASS' and record['tests'] == count
                        and record['group'] == group and record['pid'] == outcome['pid'], 'child response differs')
                require(record['cuda_initialized'] is False and record['production_model_loaded'] is False,
                        'CPU test exceeded declared scope')
                source_check(package, files)
                require(child_path.read_bytes() == child, 'child checker changed')
                print('V19_CPU_GROUP_PASS=' + group, flush=True)
            require(len({r['record']['pid'] for r in records}) == len(COUNTS), 'cold test PID reused')
        removed = not root.exists()
        require(removed and os.environ.get('HOME') == previous_home, 'temporary cleanup/HOME differs')
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
        removed = root is not None and not root.exists()
    finally:
        signal.alarm(0)
    value = {'status': ('NATIVE_V19_CPU_PASS' if native else 'LOCAL_NATIVE_HARNESS_PASS') if error is None
             else 'V19_CPU_CHECK_FAILED', 'request_id': spec['request_id'], 'mode': spec['mode'],
        'package_sha256': spec['package_sha256'], 'child_sha256': spec['child_sha256'],
        'elapsed_seconds': round(time.monotonic() - started, 3), 'groups': records, 'error': error,
        'temporary_directory_removed': removed, 'permanent_files_written': False,
        'jobs_submitted': 0, 'production_model_loaded': False, 'ready_for_gpu': False,
        'candidate_input_freeze_sha256': None, 'automatic_retry': False,
        'scope': 'temporary synthetic CPU compatibility only; not real production/GPU/mount validation'}
    print('V19_NATIVE_RESULT=' + json.dumps(value, sort_keys=True), flush=True)
    return 0 if error is None else 2


if __name__ == '__main__':
    raise SystemExit(main(SPEC))
