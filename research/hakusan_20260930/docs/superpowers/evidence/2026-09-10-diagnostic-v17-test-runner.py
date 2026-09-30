"""Independent subprocess entrypoints; no merged discovery or remote execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v17"
LOG_ROOT = ROOT / 'docs/superpowers/evidence' / ('v17-validation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))


def run(path):
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(path)],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    with (LOG_ROOT / (path.name + '.log')).open('x') as stream:
        stream.write(output)
    return path.name, result.returncode, output


def main():
    tests = sorted(PACKAGE.glob("test_*.py"))
    failures = []
    LOG_ROOT.mkdir(mode=0o700)
    print('VALIDATION_LOG_ROOT=' + str(LOG_ROOT), flush=True)
    source_sha = hashlib.sha256((PACKAGE / 'diagnose_batch_invariance.py').read_bytes()).hexdigest()
    records = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, rc, output in pool.map(run, tests):
            counts = re.findall(r'Ran (\d+) tests? in ', output)
            count = int(counts[-1]) if counts else None
            print(f"TEST_ENTRY={name} RC={rc} TESTS={count}", flush=True)
            records.append({'name': name, 'rc': rc, 'tests': count,
                'log_sha256': hashlib.sha256(output.encode()).hexdigest()})
            if rc:
                print(output[-5000:], flush=True)
                failures.append(name)
            if count is None:
                failures.append(name + ': count absent')
    if hashlib.sha256((PACKAGE / 'diagnose_batch_invariance.py').read_bytes()).hexdigest() != source_sha:
        failures.append('candidate source changed during tests')
    summary = {'source_sha256': source_sha, 'entries': records, 'failures': failures,
        'tests': sum(item['tests'] or 0 for item in records)}
    with (LOG_ROOT / 'summary.json').open('x') as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(f"ENTRIES={len(tests)} TESTS={summary['tests']} FAILURES={failures}", flush=True)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
