"""Read-only S2a evidence; sbatch is used only for its version query."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('s2_inspect_shipping', Path(__file__).with_name('ship_s2.py'))
ship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ship)
EVIDENCE, SOCKET, c, package = ship.EVIDENCE, ship.SOCKET, ship.c, ship.package


REMOTE = r'''
import hashlib, json, pathlib, subprocess
r = pathlib.Path('/home/s2510040/audattn_external_eval_ops/eager_s2a_20260918_v1')
def query(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return dict(argv=argv, rc=p.returncode, stdout=p.stdout, stderr=p.stderr)
report = {'scope': 'READ_ONLY_NO_JOB_SUBMISSION_NO_CHANGES'}
report['queue'] = query(['/usr/bin/squeue', '-h', '-u', 's2510040', '-o', '%A|%T|%j|%k'])
report['version'] = query(['/usr/bin/sbatch', '--version'])
config = query(['/usr/bin/scontrol', 'show', 'config'])
allowed = ('JobSubmitPlugins', 'CliFilterPlugins', 'GresTypes', 'SelectType', 'SlurmctldVersion')
config['stdout'] = '\n'.join(x for x in config['stdout'].splitlines() if x.strip().startswith(allowed))
report['selected_config'] = config
report['sbatch_file'] = query(['/usr/bin/file', '/usr/bin/sbatch'])
report['state_names'] = sorted(p.name for p in (r / 'state').iterdir())
report['attempt_names'] = sorted(p.name for p in (r / 'attempts').iterdir())
raw = (r / 'state/TEST_ONLY.json').read_bytes()
report['test_only_sha256'] = hashlib.sha256(raw).hexdigest()
report['test_only'] = json.loads(raw)
print(json.dumps(report, sort_keys=True))
'''


def main():
    _, _, digest = package()
    master = subprocess.run(
        ['ssh', '-S', str(SOCKET), '-O', 'check', 's2510040@hakusan1'],
        capture_output=True, text=True, timeout=15,
    )
    c.require(master.returncode == 0, 'No shared connection; no reconnection attempted')
    folder = Path(tempfile.mkdtemp(prefix='scheduler-inspection-', dir=EVIDENCE))
    c.write(folder / 'request.py', REMOTE.encode())
    argv = ['ssh', '-S', str(SOCKET), '-o', 'BatchMode=yes', '-o', 'ProxyCommand=false',
            's2510040@hakusan1', c.PYTHON, '-I', '-B', '-']
    result = subprocess.run(argv, input=REMOTE, capture_output=True, text=True, timeout=150)
    c.write(folder / 'stdout.log', result.stdout.encode())
    c.write(folder / 'stderr.log', result.stderr.encode())
    report = {'rc': result.returncode, 'time_utc': c.now(), 'release_sha256': digest,
              'result': json.loads(result.stdout) if result.returncode == 0 else None}
    c.write(folder / 'RESULT.json', c.wire(report))
    print('INSPECTION_EVIDENCE=' + str(folder))
    if report['result']:
        brief = dict(report['result'])
        brief['test_only'] = brief['test_only']['result']
        print(json.dumps(brief, indent=2))
    else:
        print(result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
