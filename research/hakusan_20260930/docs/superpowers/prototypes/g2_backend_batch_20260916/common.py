"""Fixed CPU-only batch contract and bounded, write-once evidence helpers."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

REMOTE = Path('/home/s2510040/audattn_external_eval_diag/g2_backend_cpu_2026-09-16_v1')
PREFIX = 'docs/superpowers/prototypes/g2_backend_batch_20260916/'
OWN = ('common.py', 'remote.py', 'driver.py', 'runtime.py', 'child.py', 'verify.py', 'test_batch.py', 'run_cpu.sbatch')
EXTRA = {'backend_evidence.py': '018089bf401af07a076818f2e7d7b9347aff60572bd57951b6b3207f504179a4',
         'process_runner.py': '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a'}
LIMITS = dict(cpus=1, memory_mib=6000, gpus=0,
              wall_seconds=600, child_seconds=240, coordinator_seconds=540, partition='TINY', jobs=1)
JOB_NAME = 'audattn_g2_backend_cpu'
CONFIRM = 'ONE_SYNTHETIC_CPU_JOB_1CPU_6000M_10MIN_NO_GPU'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')


def member(name):
    require(type(name) is str, 'member must be text')
    p = Path(name)
    require(type(name) is str and name and not p.is_absolute() and '..' not in p.parts
            and str(p) == name and '\\' not in name, 'invalid relative member')
    return p


def safe(path):
    require(path.is_absolute() and '..' not in path.parts
            and not any(p.is_symlink() for p in (path, *path.parents)), 'unsafe path')
    return path


def directory(path):
    st = safe(path).stat()
    require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
            and stat.S_IMODE(st.st_mode) == 0o700, 'private owned directory required')


def read(path, limit=8 * 1024**2):
    fd = os.open(safe(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_size <= limit, 'bounded owned regular file required')
        chunks, size = [], 0
        while True:
            raw = os.read(fd, min(1024**2, limit + 1 - size))
            if not raw:
                break
            chunks.append(raw)
            size += len(raw)
            require(size <= limit, 'read budget exceeded')
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
        require(size == before.st_size and identity(before) == identity(os.fstat(fd)) == identity(path.lstat()), 'file changed during read')
        return b''.join(chunks)
    finally:
        os.close(fd)


def write(path, raw):
    directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return sha(raw)


def command(argv):
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG') if k in os.environ}
    p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=30)
    require(len(p.stdout) + len(p.stderr) <= 1024**2, 'command output exceeded budget')
    return dict(returncode=p.returncode, stdout=p.stdout.decode(), stderr=p.stderr.decode())


def fields(text):
    pairs = re.findall(r'(?:^|\s)([A-Za-z0-9_/]+)=([^\s]*)', text)
    require(len(dict(pairs)) == len(pairs), 'duplicate scheduler field')
    return dict(pairs)


def tres(text):
    pairs = [x.split('=', 1) for x in text.split(',')]
    require(all(len(p) == 2 for p in pairs) and len(dict(pairs)) == len(pairs), 'invalid TRES')
    result = dict(pairs)
    require(result == {'cpu': '1', 'mem': '6000M', 'node': '1', 'billing': '1'}, 'CPU-only resource request differs')
    return result


def job_check(text, job, nonce, root, *, held):
    f = fields(text)
    expected = dict(JobId=job, JobName=JOB_NAME, Partition='TINY', Account='student', NumCPUs='1', NumTasks='1',
                    TimeLimit='00:10:00', Requeue='0', Restarts='0', MinMemoryNode='6000M',
                    Comment='g2-backend-cpu-' + nonce, WorkDir=str(root), StdIn='/dev/null',
                    StdOut=str(root / 'logs' / ('cpu_' + job + '.log')),
                    StdErr=str(root / 'logs' / ('cpu_' + job + '.log')),
                    Command=str(root / 'package' / PREFIX / 'run_cpu.sbatch'))
    require(all(f.get(k) == v for k, v in expected.items()) and f.get('CPUs/Task') == '1'
            and f.get('NumNodes') in ('1', '1-1') and re.fullmatch(r's2510040\([0-9]+\)', f.get('UserId', '')), 'job identity/resources differ')
    tres(f.get('ReqTRES', ''))
    require(not any(k in f for k in ('ArrayJobId', 'HetJobId'))
            and all('gres' not in f.get(k, '').lower() for k in ('TresPerNode', 'TresPerJob', 'TresPerTask')),
            'GPU/array/heterogeneous request rejected')
    if held:
        require(all(f.get(k) == v for k, v in dict(JobState='PENDING', Reason='JobHeldUser', Priority='0',
                    RunTime='00:00:00', NodeList='', AllocTRES='(null)').items()), 'job must remain unallocated and held')
    else:
        require(f.get('JobState') in ('RUNNING', 'COMPLETING'), 'compute job must be running')
        tres(f.get('AllocTRES', ''))
    return f


def release(raw, expected):
    require(sha(raw) == expected, 'release digest differs')
    value = json.loads(raw)
    names = {*(PREFIX + n for n in OWN), *EXTRA}
    require(wire(value) == raw and value['limits'] == LIMITS
            and value['scope'] == 'synthetic_native_inductor_cpu_pair'
            and value['remote_root'] == str(REMOTE) and set(value['files']) == names,
            'release contract differs')
    require(all(value['files'][n] == h for n, h in EXTRA.items()), 'pinned dependency differs')
    return value


def source_check(package, manifest):
    observed = {str(p.relative_to(package)) for p in package.rglob('*') if not p.is_dir()}
    require(observed == set(manifest['files']), 'unexpected package member')
    for name, digest in manifest['files'].items():
        require(sha(read(package / member(name))) == digest, 'package source differs: ' + name)

