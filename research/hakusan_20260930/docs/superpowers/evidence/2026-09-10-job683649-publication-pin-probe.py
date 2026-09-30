"""Bounded tiny-file test; private temporary paths only, no model or Slurm job."""

from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
REMOTE = r'''
import hashlib, os, pathlib, signal, stat, sys, tempfile, types
import json
signal.alarm(60)
assert sys.flags.isolated and sys.dont_write_bytecode
assert os.getuid() == pathlib.Path('/home/s2510040').stat().st_uid
base = pathlib.Path('/home/s2510040/audattn_external_eval_ops')
assert base.is_dir() and not base.is_symlink() and base.stat().st_uid == os.getuid()
source = pathlib.Path('/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v16/tools/diagnose_batch_invariance.py')
assert source.is_file() and not source.is_symlink()
raw = source.read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'e776d9917ecad3da529d311d536de89d90121d23bceb2cefe9fdadc7450609ec'
diag = types.ModuleType('publication_probe_v16')
diag.__file__ = str(source)
sys.modules[diag.__name__] = diag
exec(compile(raw, str(source), 'exec'), diag.__dict__)
records = []
for label, parent in (('local_tmp', pathlib.Path('/tmp')), ('home_filesystem', base)):
    with tempfile.TemporaryDirectory(prefix='v16-publication-probe-', dir=parent) as temporary:
        root = pathlib.Path(temporary)
        row = {'filesystem_scope': label, 'path': str(root), 'cycles': []}
        for policy in ('held_open', 'close_before_unlink', 'pin_final_close_private'):
            case = root / policy
            case.mkdir(mode=0o700)
            private = case / 'payload.partial'
            final = case / 'payload.json'
            fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            final_fd = None
            try:
                os.write(fd, b'{}\n')
                os.fsync(fd)
                os.link(private, final)
                if policy == 'pin_final_close_private':
                    final_fd = os.open(final, os.O_RDONLY | os.O_NOFOLLOW)
                    assert diag._same_identity(os.fstat(fd), os.fstat(final_fd))
                    os.close(fd)
                    fd = None
                if policy == 'close_before_unlink':
                    os.close(fd)
                    fd = None
                os.unlink(private)
                before = final.lstat()
                hidden = sum(name.startswith('.nfs') for name in os.listdir(case))
                if final_fd is not None:
                    assert diag._same_identity(before, os.fstat(final_fd))
                    assert os.read(final_fd, 4) == b'{}\n'
            finally:
                if fd is not None:
                    os.close(fd)
                if final_fd is not None:
                    os.close(final_fd)
            after = final.lstat()
            assert final.read_bytes() == b'{}\n'
            row['cycles'].append({'policy': policy, 'before_close_nlink': before.st_nlink,
                'after_close_nlink': after.st_nlink, 'mode': stat.S_IMODE(after.st_mode),
                'hidden_nfs_names_before_close': hidden})
        attempt = root / 'attempts' / 'slurm-1'
        attempt.mkdir(mode=0o700, parents=True)
        with diag._AttemptArtifactStore(attempt) as store:
            try:
                store.publish_bytes('reference_cold/REFERENCE_INPUTS.json', b'{}\n')
            except diag.DiagnosticError as error:
                row['exact_v16_writer'] = {'status': 'REJECTED', 'message': str(error)}
            else:
                row['exact_v16_writer'] = {'status': 'PASS'}
        records.append(row)
print(json.dumps({'status': 'PUBLICATION_PROBE_COMPLETE', 'scope': 'TINY_FILES_ONLY_NO_MODEL_NO_JOB',
    'observations': records, 'temporary_probe_files_removed': True}), flush=True)
'''


def main():
    result = subprocess.run(
        [
            'ssh', '-S', str(ROOT / '.hakusan-control/master.sock'),
            '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', 's2510040@hakusan1',
            '/home/s2510040/miniconda3/envs/attn/bin/python -I -B -c ' + shlex.quote(REMOTE),
        ],
        timeout=80,
    )
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
