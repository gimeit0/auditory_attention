"""Portable, write-once source bundle for the synthetic bridge check."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PREFIX = 'docs/superpowers/prototypes/'
FIXED = 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/'
PARENT = 'same_bank_eval_2026_09_03_v4_numeric_diag_v19/'
SELF = PREFIX + 'g2_compiled_check_20260916/'
PINS = {
    PREFIX + 'g2_worker_20260916/cell_bridge.py': '9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d',
    PREFIX + 'g2_profiles_20260916/profiles.py': 'd5d83e810fef28c15835c28a583f1a5c4a4401adcf558e164ef3e5f46ea91227',
    PREFIX + 'g2_native_20260916/backend_evidence.py': '018089bf401af07a076818f2e7d7b9347aff60572bd57951b6b3207f504179a4',
    PREFIX + 'targeted_gpu_job_20260915_v5/process_runner.py': '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a',
    PARENT + 'diagnose_batch_invariance.py': 'c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d',
    PARENT + 'test_numeric_diag.py': '453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf',
}
TRACE = 'fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b'
PINS[PARENT + 'numeric_trace.py'] = TRACE
for name, digest in zip('RCDE', (
        'd77b316ca1d3dfdc0954100c73dd51783a074974a5ebb1d69c655a11a6ecdebd',
        '32b79a3264ff3f1da3b43cdfed8d509c8aaa40df8da20ee9b8fd15b97da1b189',
        '92fbad73ee2efa665d529fc69267d9b9397941e571b43cbb5bf35fa54920167b',
        '4302bb1d2fc21897ced6618006587d3776c1c7c5339c5906fbf46d99babfd864')):
    PINS[FIXED + name + '/diagnose_batch_invariance.py'] = digest
    PINS[FIXED + name + '/numeric_trace.py'] = TRACE
FILES = tuple(sorted((*PINS, *(SELF + n for n in (
    'support.py', 'protocol.py', 'child.py', 'run_check.py', 'test_check.py', 'README.md')))))


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path, limit=16 * 1024**2):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink rejected')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        a = os.fstat(stream.fileno())
        require(stat.S_ISREG(a.st_mode) and a.st_uid == os.getuid() and a.st_nlink == 1
                and a.st_size <= limit, 'bounded owned regular file required')
        raw = stream.read(limit + 1)
        b = os.fstat(stream.fileno())
    def identity(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
    require(identity(a) == identity(b) == identity(path.lstat()) and len(raw) == a.st_size, 'file changed')
    return raw


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def inventory(root=ROOT):
    result = {}
    for relative in FILES:
        raw = read(root / relative)
        digest = sha(raw)
        require(relative not in PINS or PINS[relative] == digest, 'pinned source changed: ' + relative)
        result[relative] = dict(size=len(raw), sha256=digest)
    return result


def check(root, release):
    require(set(release) == {'schema_version', 'sources'} and release['schema_version'] == 1
            and release['sources'] == inventory(root), 'release source inventory differs')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def runner():
    relative = PREFIX + 'targeted_gpu_job_20260915_v5/process_runner.py'
    require(sha(read(ROOT / relative)) == PINS[relative], 'process supervisor changed')
    return load(ROOT / relative, 'g2_check_process_runner')
