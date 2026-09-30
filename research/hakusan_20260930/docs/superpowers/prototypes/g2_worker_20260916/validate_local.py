"""Bounded local regression evidence; no remote actions or job submission."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import cell_bridge as bridge


def record(path):
    raw = path.read_bytes()
    return dict(path=str(path), size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def sources():
    paths = [HERE / n for n in ('cell_bridge.py', 'test_cell_bridge.py', 'validate_local.py')]
    paths += [HERE.parent / 'g2_profiles_20260916/profiles.py', HERE.parent / 'g2_native_20260916/backend_evidence.py']
    parent = ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19'
    paths += [parent / n for n in ('diagnose_batch_invariance.py', 'numeric_trace.py', 'test_numeric_diag.py')]
    fixed = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    for profile, expected in bridge.CORE_SHAS.items():
        path = fixed / profile / 'diagnose_batch_invariance.py'
        bridge.read(path, expected)
        paths += [path, path.with_name('numeric_trace.py')]
    return [record(path) for path in paths]


def parse_reports(directory):
    rows = (directory / 'tests.stdout').read_text().splitlines()
    reports = [json.loads(r.split('=', 1)[1]) for r in rows if r.startswith('G2_BRIDGE_TEST_REPORT=')]
    guards = [json.loads(r.split('=', 1)[1]) for r in rows if r.startswith('G2_GUARDED_REPORT=')]
    failures = [json.loads(r.split('=', 1)[1]) for r in rows if r.startswith('G2_FAILURE_REPORT=')]
    bridge.require(len(reports) == 1, 'exactly one final test report required')
    return reports[0], guards, failures


def verify(directory):
    receipt = json.loads((directory / 'RECEIPT.json').read_bytes())
    bridge.require(receipt['status'] == 'LOCAL_G2_BRIDGE_VERIFIED' and receipt['rc'] == 0
                   and not receipt['timed_out'] and receipt['sources_before'] == receipt['sources_after'] == sources(),
                   'local evidence status or sources differ')
    for name in ('tests.stdout', 'tests.stderr'):
        bridge.require(record(directory / name) == receipt['artifacts'][name], 'test log differs')
    for index, source in enumerate(receipt['sources_before']):
        snapshot = directory / 'sources' / (str(index) + '-' + Path(source['path']).name)
        bridge.read(snapshot, source['sha256'])
    report, guards, failures = parse_reports(directory)
    bridge.require(report == receipt['report'] and guards == receipt['guarded_reports']
                   and failures == receipt['failure_reports']
                   and report['tests'] == 16 and report['errors'] == report['failures'] == report['skipped'] == 0
                   and report['jobs_submitted'] == report['remote_operations'] == 0
                   and not any(report[k] for k in ('production_ready', 'production_model_loaded',
                                                  'cuda_initialized', 'native_compiled_integration_verified')),
                   'scope or report differs')
    bridge.require([g['profile'] for g in guards] == ['D', 'E']
                   and all(g['model_calls'] == 34 and g['strict_loads'] == 1 and len(g['checks']) == 13
                           and g['numeric']['status'] == 'NUMERIC_ACCEPT' and not g['production_ready'] for g in guards),
                   'guarded integration result differs')
    bridge.require([f['profile'] for f in failures] == ['D', 'E']
                   and all(f['model_calls'] == 2 and f['attempts'] == [16, 16, 1]
                           and f['attestation_revoked'] and f['repeat_rejected']
                           and not f['partial_results_returned'] for f in failures), 'failure containment differs')
    print('LOCAL_G2_BRIDGE_RECHECK=PASS', flush=True)


def run():
    os.umask(0o077)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    directory = Path(tempfile.mkdtemp(prefix='g2-bridge-local-' + stamp, dir=ROOT / 'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE=' + str(directory), flush=True)
    before = sources()
    (directory / 'sources').mkdir(mode=0o700)
    for index, source in enumerate(before):
        raw = bridge.read(source['path'], source['sha256'])
        with (directory / 'sources' / (str(index) + '-' + Path(source['path']).name)).open('xb') as stream:
            stream.write(raw)
    started, timed_out = time.monotonic(), False
    with (directory / 'tests.stdout').open('xb') as out, (directory / 'tests.stderr').open('xb') as err:
        proc = subprocess.Popen([sys.executable, '-I', '-B', str(HERE / 'test_cell_bridge.py')],
            env={**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'},
            stdout=out, stderr=err, start_new_session=True)
        try:
            rc = proc.wait(timeout=150)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            rc = 124
    after = sources()
    try:
        report, guards, failures = parse_reports(directory)
    except bridge.BridgeError:
        report, guards, failures = None, [], []
    receipt = dict(status='LOCAL_G2_BRIDGE_VERIFIED' if rc == 0 and before == after else 'LOCAL_G2_BRIDGE_FAILED',
                   rc=rc, timed_out=timed_out, elapsed_seconds=time.monotonic() - started, timeout_seconds=150,
                   sources_before=before, sources_after=after, report=report, guarded_reports=guards, failure_reports=failures,
                   artifacts={n: record(directory / n) for n in ('tests.stdout', 'tests.stderr')},
                   production_ready=False, jobs_submitted=0, remote_operations=0)
    with (directory / 'RECEIPT.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')
    bridge.require(rc == 0, 'tests failed; retained evidence at ' + str(directory))
    verify(directory)
    print('LOCAL_G2_BRIDGE=PASS; no SSH or jobs', flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]).resolve())
    elif len(sys.argv) == 1:
        run()
    else:
        raise SystemExit('usage: validate_local.py [verify EVIDENCE_DIRECTORY]')
