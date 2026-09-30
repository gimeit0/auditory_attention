"""Local package validation only. No SSH, scheduler, or native run command."""
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support as s
import protocol as p


def build(directory):
    sources = s.inventory()
    package = directory / 'package'
    package.mkdir(mode=0o700)
    for relative, record in sources.items():
        destination = package / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        raw = s.read(s.ROOT / relative)
        s.require(s.sha(raw) == record['sha256'], 'source changed during copy')
        s.write(destination, raw)
    release = dict(schema_version=1, sources=sources)
    s.check(package, release)
    s.write(directory / 'RELEASE.json', s.wire(release))
    return release


def environment(cache):
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
               OPENBLAS_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', PYTHONHASHSEED='0',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', TORCHINDUCTOR_COMPILE_THREADS='1')
    for name in ('TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TORCH_HOME',
                 'XDG_CACHE_HOME', 'MPLCONFIGDIR', 'NUMBA_CACHE_DIR', 'TMPDIR'):
        target = cache / name
        target.mkdir(mode=0o700)
        env[name] = str(target)
    # Preserve HOME. Do not repurpose user identity to redirect caches.
    return env


def record(path):
    raw = s.read(path)
    return dict(size=len(raw), sha256=s.sha(raw))


def verify(directory):
    release = json.loads(s.read(directory / 'RELEASE.json'))
    digest = s.sha(s.wire(release))
    s.check(directory / 'package', release)
    terminal = json.loads(s.read(directory / 'TERMINAL.json'))
    s.require(terminal['status'] == 'LOCAL_SYNTHETIC_CHECK_PASS' and terminal['mode'] == 'local'
              and terminal['release_sha256'] == digest and terminal['jobs_submitted'] == 0
              and terminal['remote_operations'] == 0 and terminal['ready_for_gpu'] is False,
              'local terminal status differs')
    s.require(terminal['automatic_retry'] is False and len(terminal['children']) == 4, 'incomplete child receipt')
    artifacts = terminal['artifacts']
    s.require(set(artifacts) == {f'{n}-{r}.{ext}' for n in 'DE' for r in ('reference', 'observed')
                               for ext in ('json', 'log')}, 'artifact inventory differs')
    for name, expected in artifacts.items():
        s.require(record(directory / name) == expected, 'artifact differs: ' + name)
    pairs, pids = [], []
    for i, name in enumerate('DE'):
        values = []
        for j, role in enumerate(('reference', 'observed')):
            value = json.loads(s.read(directory / f'{name}-{role}.json'))
            process = terminal['children'][i*2+j]
            s.require(process['error'] is None and process['returncode'] == 0 and process['pid'] == value['pid']
                      and process['profile'] == name and process['role'] == role, 'child process differs')
            s.require(process['log'] == dict(name=f'{name}-{role}.log', **artifacts[f'{name}-{role}.log']),
                      'process log differs')
            pids.append(process['pid'])
            values.append(value)
        pairs.append(p.pair(*values, native=False, release_sha=digest, nonce=terminal['nonce']))
    s.require(len(set(pids)) == 4 and pairs == terminal['pairs'], 'pair summary/process reuse differs')
    print('LOCAL_SYNTHETIC_G2_PAIR_RECHECK=PASS', flush=True)
    return terminal


def run():
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    directory = Path(tempfile.mkdtemp(prefix='g2-paired-local-' + stamp, dir=s.ROOT / 'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE=' + str(directory), flush=True)
    release = build(directory)
    digest, nonce = s.sha(s.wire(release)), uuid.uuid4().hex
    supervisor = s.runner()
    started = time.monotonic()
    terminal = dict(status='LOCAL_SYNTHETIC_CHECK_FAILED', mode='local', release_sha256=digest, nonce=nonce,
                    children=[], pairs=[], artifacts={}, automatic_retry=False, ready_for_gpu=False,
                    jobs_submitted=0, remote_operations=0, child_limit_seconds=60, total_limit_seconds=180)
    s.write(directory / 'STARTED.json', s.wire(terminal))
    try:
        with tempfile.TemporaryDirectory(prefix='g2-pair-caches-') as raw_cache:
            cache_root = Path(raw_cache).resolve()
            for name in 'DE':
                values = []
                for role in ('reference', 'observed'):
                    part = cache_root / (name + '-' + role)
                    part.mkdir(mode=0o700)
                    output = directory / f'{name}-{role}.json'
                    log = directory / f'{name}-{role}.log'
                    command = [sys.executable, '-I', '-B', str(directory / 'package' / s.SELF / 'child.py'),
                               'local', name, role, str(output), digest, nonce]
                    remaining = 180 - (time.monotonic() - started)
                    s.require(remaining > 0, 'total deadline reached')
                    process = supervisor.run_process(command, environment(part), log,
                                                     seconds=min(60, remaining), max_log_bytes=4*1024**2)
                    process.update(profile=name, role=role)
                    terminal['children'].append(process)
                    terminal['artifacts'][log.name] = record(log)
                    s.require(process['error'] is None and process['returncode'] == 0, 'child failed: ' + name + '/' + role)
                    terminal['artifacts'][output.name] = record(output)
                    value = json.loads(s.read(output))
                    s.require(process['pid'] == value['pid'], 'child PID differs')
                    p.child(value, profile=name, role=role, native=False, release_sha=digest, nonce=nonce)
                    values.append(value)
                terminal['pairs'].append(p.pair(*values, native=False, release_sha=digest, nonce=nonce))
        s.check(directory / 'package', release)
        s.require(release['sources'] == s.inventory(), 'live source changed during check')
        terminal['status'] = 'LOCAL_SYNTHETIC_CHECK_PASS'
    except BaseException as error:
        terminal['error'] = dict(type=type(error).__name__, message=str(error))
    terminal['elapsed_seconds'] = time.monotonic() - started
    s.write(directory / 'TERMINAL.json', s.wire(terminal))
    s.require(terminal['status'] == 'LOCAL_SYNTHETIC_CHECK_PASS', 'check failed; evidence retained: ' + str(directory))
    verify(directory)
    print('LOCAL_CHECK_COMPLETE; no SSH, upload or submission', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'local':
        run()
    elif len(sys.argv) == 3 and sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit('usage: run_check.py local | verify EVIDENCE_DIRECTORY; native scheduler entry NOT PROVIDED')
