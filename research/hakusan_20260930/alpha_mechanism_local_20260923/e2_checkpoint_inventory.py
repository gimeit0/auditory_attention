"""Bounded byte-identity inventory; never unpickles checkpoints or uses CUDA."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

ROOT = Path('/home/s2510040/selective_listening_repro/code/auditory_attention/selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/full/checkpoints')
CANDIDATES = [(0, 'stage-0.ckpt'), (1, 'stage-epoch=00-step=1736.ckpt'),
              (2, 'stage-epoch=01-step=3472.ckpt'), (4, 'stage-epoch=03-step=6944.ckpt'),
              (8, 'stage-epoch=07-step=13888.ckpt'), (16, 'stage-epoch=15-step=27776.ckpt'),
              (24, 'stage-epoch=23-step=41664.ckpt'), (40, 'formal-final.ckpt')]
FORMAL_SHA = '2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff'
MAX_BYTES = 1024 ** 3

def identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns

def hash_regular(path, limit=MAX_BYTES):
    path = Path(path).absolute()
    for part in reversed((path, *path.parents)):
        if stat.S_ISLNK(part.lstat().st_mode):
            raise ValueError('SYMLINK_REFUSED')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
        raise ValueError('FILE_TYPE_OR_SIZE')
    digest = hashlib.sha256()
    count = 0
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError('CHANGED_BEFORE_READ')
        while True:
            chunk = stream.read(min(4 * 1024 ** 2, limit + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            if count > limit:
                raise ValueError('READ_LIMIT')
            digest.update(chunk)
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError('CHANGED_DURING_READ')
    if identity(path.lstat()) != identity(before) or count != before.st_size:
        raise ValueError('CHANGED_AFTER_READ')
    return dict(path=str(path), size=count, sha256=digest.hexdigest())

def inventory(root=ROOT):
    records = []
    for rounds, name in CANDIDATES:
        row = dict(completed_epochs_candidate=rounds, filename=name,
                   stage_semantics_verified=False, model_loaded=False)
        try:
            row.update(hash_regular(root / name))
            if rounds == 40 and row['sha256'] != FORMAL_SHA:
                raise ValueError('FORMAL40_IDENTITY_MISMATCH')
            row['status'] = 'BYTES_HASHED'
        except (OSError, ValueError) as exc:
            row.update(status='GAP_OR_REFUSED', error=str(exc))
        records.append(row)
    return dict(status='E2_BYTES_HASHED_STAGE_UNVERIFIED' if all(
        r['status'] == 'BYTES_HASHED' for r in records) else 'E2_CHECKPOINT_GAP_RECORDED',
        records=records, jobs_submitted=0, checkpoint_deserialized=False)

def main():
    import pwd
    if pwd.getpwuid(os.getuid()).pw_name != 's2510040':
        raise ValueError('REMOTE_ACCOUNT_REQUIRED')
    def timeout(*args):
        raise TimeoutError('90_SECOND_READ_BUDGET_EXHAUSTED')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(90)
    result = inventory()
    signal.alarm(0)
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    main()
