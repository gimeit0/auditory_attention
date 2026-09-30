"""Fixed CPU-only batch contract and bounded, write-once evidence helpers."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

REMOTE = Path('/home/s2510040/audattn_external_eval_diag/g2_bridge_cpu_2026-09-16_v1')
PREFIX = 'docs/superpowers/prototypes/g2_bridge_batch_20260916/'
OWN = ('common.py', 'remote.py', 'driver.py', 'runtime.py', 'verify.py', 'test_batch.py', 'run_cpu.sbatch')
CORE_SHA = '70ed80ca0d3a39d562bcf06a289d259eeb4a616d8a9a229122625ff3a17029dd'
CORE_PREFIX = 'docs/superpowers/prototypes/g2_compiled_check_20260916/'
CORE_FILES = {
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/C/diagnose_batch_invariance.py": "32b79a3264ff3f1da3b43cdfed8d509c8aaa40df8da20ee9b8fd15b97da1b189",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/C/numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/D/diagnose_batch_invariance.py": "92fbad73ee2efa665d529fc69267d9b9397941e571b43cbb5bf35fa54920167b",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/D/numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/E/diagnose_batch_invariance.py": "4302bb1d2fc21897ced6618006587d3776c1c7c5339c5906fbf46d99babfd864",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/E/numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/R/diagnose_batch_invariance.py": "d77b316ca1d3dfdc0954100c73dd51783a074974a5ebb1d69c655a11a6ecdebd",
    "docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/R/numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/README.md": "22f26d3c902f0b0aef1b4c17e22a10976c4a1dca191a102790f0bcf32cfd37cf",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/child.py": "efbd3dce8fde8d16fa4e6c5c69e1f46ee527b654b928aa951dc8bb23f91fc440",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/protocol.py": "9f527a0eb2cb187851ae22be8212326c4a219c1129aecee4d9ae5236876c7b31",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/run_check.py": "3f010d032b1a9ca5043cf95cb1159fdb5033eef32cfef3881eb3f1d03f5a7721",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/support.py": "1c3a53aae63cfadcb83c44eb2e206fd986b8776d4814fcd732f21e231d000d61",
    "docs/superpowers/prototypes/g2_compiled_check_20260916/test_check.py": "d2f0f012aa56e5863d570cbd2e389cd1d76e57aec1814954614867252253cf36",
    "docs/superpowers/prototypes/g2_native_20260916/backend_evidence.py": "018089bf401af07a076818f2e7d7b9347aff60572bd57951b6b3207f504179a4",
    "docs/superpowers/prototypes/g2_profiles_20260916/profiles.py": "d5d83e810fef28c15835c28a583f1a5c4a4401adcf558e164ef3e5f46ea91227",
    "docs/superpowers/prototypes/g2_worker_20260916/cell_bridge.py": "9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d",
    "docs/superpowers/prototypes/targeted_gpu_job_20260915_v5/process_runner.py": "189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a",
    "same_bank_eval_2026_09_03_v4_numeric_diag_v19/diagnose_batch_invariance.py": "c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d",
    "same_bank_eval_2026_09_03_v4_numeric_diag_v19/numeric_trace.py": "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b",
    "same_bank_eval_2026_09_03_v4_numeric_diag_v19/test_numeric_diag.py": "453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf"
}
EXTRA = {**CORE_FILES, 'CORE_RELEASE.json': CORE_SHA,
         'process_runner.py': '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a'}
LIMITS = dict(cpus=1, memory_mib=6000, gpus=0,
              wall_seconds=1320, child_seconds=300, coordinator_seconds=1260, partition='TINY', jobs=1)
JOB_NAME = 'audattn_g2_bridge_cpu'
CONFIRM = 'ONE_SYNTHETIC_CPU_JOB_1CPU_6000M_22MIN_NO_GPU'


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
                    TimeLimit='00:22:00', Requeue='0', Restarts='0', MinMemoryNode='6000M',
                    Comment='g2-bridge-cpu-' + nonce, WorkDir=str(root), StdIn='/dev/null',
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
            and value['scope'] == 'synthetic_native_guarded_two_pass_bridge_pair'
            and value['remote_root'] == str(REMOTE) and set(value['files']) == names,
            'release contract differs')
    require(all(value['files'][n] == h for n, h in EXTRA.items()), 'pinned dependency differs')
    return value


def source_check(package, manifest):
    observed = {str(p.relative_to(package)) for p in package.rglob('*') if not p.is_dir()}
    require(observed == set(manifest['files']), 'unexpected package member')
    for name, digest in manifest['files'].items():
        require(sha(read(package / member(name))) == digest, 'package source differs: ' + name)
