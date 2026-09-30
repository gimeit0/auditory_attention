"""Save one bounded local preparation check; never SSH, freeze, or submit jobs."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_candidate as build
import profiles

SOURCE_NAMES = ('profiles.py', 'adapter.py', 'build_candidate.py', 'test_profiles.py', 'validate_local.py')
FIXTURE_SHA = '453973e8948c12dcc924391ec9d1584497be79d3c5d60d3e1cff721c6d5c98bf'
ARCH_SHA = '84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed'


def record(path, expected=None):
    raw = build.read(path, expected)
    return dict(path=str(path), size=len(raw), sha256=build.sha(raw))


def sources():
    paths = [(HERE / name, None) for name in SOURCE_NAMES]
    paths += [(build.PARENT / 'diagnose_batch_invariance.py', build.PARENT_SHA),
              (build.PARENT / 'numeric_trace.py', build.TRACE_SHA),
              (build.PARENT / 'test_numeric_diag.py', FIXTURE_SHA),
              (build.MODEL, build.MODEL_SHA), (build.EVALUATOR, build.EVALUATOR_SHA),
              (build.MODEL.with_name('spatial_attn_architecture.py'), ARCH_SHA)]
    return [record(path, expected) for path, expected in paths]


def write_json(path, value):
    with path.open('xb') as stream:
        stream.write(build.wire(value))


def run_check(directory):
    before = sources()
    audit = build.source_audit()
    candidates = {name: build.materialize(directory / name, name) for name in profiles.ORDER}
    started = time.monotonic()
    environment = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    timed_out = False
    with (directory / 'tests.stdout').open('xb') as out, (directory / 'tests.stderr').open('xb') as err:
        process = subprocess.Popen([sys.executable, '-I', '-B', str(HERE / 'test_profiles.py')],
                                   cwd=build.ROOT, env=environment, stdout=out, stderr=err, start_new_session=True)
        try:
            rc = process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            rc = 124
    elapsed = time.monotonic() - started
    output = build.read(directory / 'tests.stdout').decode()
    reports = [json.loads(line.split('=', 1)[1]) for line in output.splitlines()
               if line.startswith('G2_LOCAL_TEST_REPORT=')]
    report = reports[0] if len(reports) == 1 else None
    after = sources()
    okay = (rc == 0 and not timed_out and before == after and report is not None
            and report['status'] == 'LOCAL_PREPARATION_TESTS_PASS' and report['tests'] == 22
            and not report['cuda_initialized'] and report['jobs_submitted'] == 0
            and not report['production_model_loaded'] and not report['production_ready'])
    files = [path for path in sorted(directory.rglob('*')) if path.is_file()]
    artifacts = [dict(relative_path=str(path.relative_to(directory)), size=path.stat().st_size,
                      sha256=build.sha(build.read(path))) for path in files]
    receipt = dict(schema_version=1, status='LOCAL_PREPARATION_VERIFIED' if okay else 'LOCAL_PREPARATION_FAILED',
                   source_audit=audit, sources_before=before, sources_after=after, sources_unchanged=before == after,
                   candidate_sha256={name: candidates[name]['candidate_sha256'] for name in profiles.ORDER},
                   test_report=report, rc=rc, timed_out=timed_out, elapsed_seconds=elapsed,
                   timeout_seconds=120, artifacts=artifacts, jobs_submitted=0, remote_operations=0,
                   production_ready=False, gpu_matrix_executed=False,
                   limitations=['local Python/Torch differ from HAKUSAN',
                                'real checkpoints and frozen production trials not loaded',
                                'R/C native Inductor execution and guard integration not verified',
                                'production source/worker/backend collector and GPU authorization pending'])
    write_json(directory / 'RECEIPT.json', receipt)
    build.require(okay, 'local preparation check failed; preserve evidence at ' + str(directory))
    verify(directory)
    return receipt


def verify(directory):
    """Rehash outputs and rederive candidates; local evidence, not GPU authority."""
    receipt = json.loads(build.read(directory / 'RECEIPT.json'))
    build.require(receipt['status'] == 'LOCAL_PREPARATION_VERIFIED'
                  and receipt['sources_before'] == receipt['sources_after'] == sources(), 'sources/status differ')
    expected = {item['relative_path']: item for item in receipt['artifacts']}
    actual = {str(path.relative_to(directory)) for path in directory.rglob('*') if path.is_file()}
    build.require(actual == set(expected) | {'RECEIPT.json'}, 'artifact names differ')
    for name, item in expected.items():
        path = Path(name)
        build.require(not path.is_absolute() and '..' not in path.parts, 'invalid artifact path')
        raw = build.read(directory / path)
        build.require(len(raw) == item['size'] and build.sha(raw) == item['sha256'], 'artifact differs: ' + name)
    for name in profiles.ORDER:
        raw, recipe = build.derive(name)
        build.require(build.read(directory / name / 'diagnose_batch_invariance.py') == raw, 'derived source differs')
        build.require(json.loads(build.read(directory / name / 'RECIPE.json')) == recipe, 'derivation receipt differs')
        build.require(receipt['candidate_sha256'][name] == build.sha(raw), 'candidate digest differs')
    output = build.read(directory / 'tests.stdout').decode()
    reports = [json.loads(line.split('=', 1)[1]) for line in output.splitlines()
               if line.startswith('G2_LOCAL_TEST_REPORT=')]
    build.require(reports == [receipt['test_report']], 'test report differs')
    summary = receipt['test_report']
    build.require(summary['tests'] == 22 and summary['errors'] == summary['failures'] == summary['skipped'] == 0
                  and summary['guarded_cold_profiles'] == ['D', 'E'] and not summary['cuda_initialized']
                  and not summary['production_model_loaded'] and summary['jobs_submitted'] == 0
                  and not summary['production_ready'] and not receipt['production_ready']
                  and not receipt['gpu_matrix_executed'] and receipt['jobs_submitted'] == receipt['remote_operations'] == 0
                  and receipt['rc'] == 0 and not receipt['timed_out'], 'scope/result differs')
    print('LOCAL_PREPARATION_RECHECK=PASS')
    return receipt


if __name__ == '__main__':
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == 'verify':
        location = Path(sys.argv[2]).resolve()
        verify(location)
    elif len(sys.argv) == 1:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        evidence = build.ROOT / 'docs/superpowers/evidence'
        location = Path(tempfile.mkdtemp(prefix='g2-profiles-local-' + stamp, dir=evidence))
        print('LOCAL_EVIDENCE=' + str(location), flush=True)
        run_check(location)
        print('G2_LOCAL_PREPARATION=PASS; no remote operation or submission')
    else:
        raise SystemExit('usage: validate_local.py [verify EVIDENCE_DIRECTORY]')
