"""Test exact candidate publication on remote tmp and NFS, in disposable paths."""

import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v17/diagnose_batch_invariance.py'
SHA = 'f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86'
REMOTE = r'''
import base64, hashlib, json, os, pathlib, signal, stat, sys, tempfile, types
signal.alarm(60)
assert sys.flags.isolated and sys.dont_write_bytecode
assert os.getuid() == pathlib.Path('/home/s2510040').stat().st_uid
base = pathlib.Path('/home/s2510040/audattn_external_eval_ops')
assert base.is_dir() and not base.is_symlink() and base.stat().st_uid == os.getuid()
data = sys.stdin.buffer.read(1_000_001)
assert len(data) <= 1_000_000
raw = base64.b64decode(json.loads(data)['source'], validate=True)
assert hashlib.sha256(raw).hexdigest() == 'f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86'
diag = types.ModuleType('publication_probe_v17')
diag.__file__ = '<sha-pinned-v17-publication-probe>'
sys.modules[diag.__name__] = diag
exec(compile(raw, diag.__file__, 'exec'), diag.__dict__)
import numpy as np
observations = []
for label, parent in (('local_tmp', pathlib.Path('/tmp')), ('home_filesystem', base)):
    with tempfile.TemporaryDirectory(prefix='v17-publication-probe-', dir=parent) as temporary:
        root = pathlib.Path(temporary)
        attempt = root / 'attempts' / 'slurm-1'
        attempt.mkdir(mode=0o700, parents=True)
        with diag._AttemptArtifactStore(attempt) as store:
            relative = 'reference_cold/REFERENCE_INPUTS.json'
            payload = b'{"synthetic_probe":true}\n'
            record = store.publish_bytes(relative, payload)
            assert record['sha256'] == hashlib.sha256(payload).hexdigest()
            assert (attempt / relative).stat().st_nlink == 1
            assert stat.S_IMODE((attempt / relative).stat().st_mode) == 0o600
            store.verify_record(record)
            logits = np.arange(32 * 800, dtype=np.float32).reshape(32, 800)
            npy = 'cells/A1/LOGITS_PASS1.npy'
            npy_record = store.publish_npy(npy, logits)
            assert (attempt / npy).stat().st_nlink == 1
            assert stat.S_IMODE((attempt / npy).stat().st_mode) == 0o600
            store.verify_record(npy_record)
            assert np.array_equal(np.load(attempt / npy, allow_pickle=False), logits)
            try:
                store.publish_bytes(relative, b'OVERWRITE')
            except FileExistsError:
                pass
            else:
                raise AssertionError('existing destination overwritten')
            assert (attempt / relative).read_bytes() == payload
        hidden = [p for p in root.rglob('*') if p.name.startswith('.nfs') or p.name.endswith('.partial')]
        assert not hidden
        observations.append({'filesystem_scope': label, 'json_and_npy_publication': 'PASS',
            'mode': '0600', 'nlink': 1, 'existing_destination_rejected': True,
            'hidden_or_partial_files': 0})
print(json.dumps({'status': 'V17_PUBLICATION_PROBE_PASS', 'source_sha256': hashlib.sha256(raw).hexdigest(),
    'scope': 'SYNTHETIC_FILES_ONLY_NO_MODEL_NO_JOB', 'observations': observations,
    'temporary_probe_files_removed': True}), flush=True)
'''


def main():
    log = Path(__file__).with_name('2026-09-10-diagnostic-v17-final-nfs.log')
    if log.exists():
        raise SystemExit('STOP: final NFS evidence exists; do not overwrite')
    raw = SOURCE.read_bytes()
    if SOURCE.is_symlink() or hashlib.sha256(raw).hexdigest() != SHA:
        raise SystemExit('STOP: candidate source differs')
    compile(REMOTE, 'remote_publication_probe', 'exec')
    result = subprocess.run(
        ['ssh', '-S', str(ROOT / '.hakusan-control/master.sock'),
         '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', 's2510040@hakusan1',
         '/home/s2510040/miniconda3/envs/attn/bin/python -I -B -c ' + shlex.quote(REMOTE)],
        input=json.dumps({'source': base64.b64encode(raw).decode('ascii')}).encode(),
        timeout=80, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    with log.open('xb') as output:
        output.write(result.stdout)
    print(result.stdout.decode(errors='replace'), end='', flush=True)
    print('NFS_LOG_SHA256=' + hashlib.sha256(result.stdout).hexdigest(), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
