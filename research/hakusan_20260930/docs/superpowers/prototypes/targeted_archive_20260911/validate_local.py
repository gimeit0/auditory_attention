"""Record unit tests and three supervised synthetic cold pairs in fresh output."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parent
    evidence = here.parents[3] / 'docs/superpowers/evidence'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = Path(tempfile.mkdtemp(prefix='archive-local-' + stamp + '-', dir=evidence))
    print('ARCHIVE_LOCAL_EVIDENCE=' + str(run), flush=True)
    before = {p.name: sha(p) for p in sorted(here.glob('*.py'))}
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    commands = [('units', [sys.executable, '-I', '-B', str(here / 'run_checks.py')])]
    commands += [(case, [sys.executable, '-I', '-B', str(here / 'run_cold_pair.py'),
                         '--case', case, '--root', str(run / case)])
                 for case in ('invariant', 'dependent', 'interference')]
    records = []
    for name, command in commands:
        with (run / (name + '.log')).open('xb') as output:
            try:
                result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                        env=env, timeout=150, check=False)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        records.append({'case': name, 'returncode': code, 'output_sha256': sha(run / (name + '.log'))})
        print(f'ARCHIVE_LOCAL_{name.upper()}_RC={code}', flush=True)
        if code:
            break
    after = {p.name: sha(p) for p in sorted(here.glob('*.py'))}
    ok = len(records) == 4 and all(r['returncode'] == 0 for r in records) and before == after
    units = [json.loads(line) for line in (run / 'units.log').read_text().splitlines()
             if line.startswith('{"status":')]
    ok = ok and len(units) == 1 and units[0]['status'] == 'ARCHIVE_UNIT_TESTS_PASS' and units[0]['tests'] == 31
    pairs = {}
    if ok:
        for case in ('invariant', 'dependent', 'interference'):
            record = json.loads((run / case / 'PAIR_RECEIPT.json').read_bytes())
            ok = ok and record['case_status'] == 'SUPERVISED_SYNTHETIC_COLD_PAIR_PASS'
            pairs[case] = record
    receipt = {'status': 'LOCAL_ARCHIVE_VALIDATION_PASS' if ok else 'LOCAL_ARCHIVE_VALIDATION_FAILED',
               'source_sha256': before, 'source_unchanged': before == after,
               'unit_tests': units, 'records': records, 'pairs': pairs,
               'remote_execution': False, 'production_model_loaded': False, 'jobs_submitted': 0,
               'ready_for_gpu': False}
    with (run / 'receipt.json').open('x') as output:
        json.dump(receipt, output, indent=2)
        output.write('\n')
    print('LOCAL_ARCHIVE_VALIDATION=' + ('PASS' if ok else 'FAIL'), flush=True)
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
