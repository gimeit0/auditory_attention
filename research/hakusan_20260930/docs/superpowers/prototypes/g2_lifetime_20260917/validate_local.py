"""Bounded local lifecycle and actual synthetic mmap checks, with fixed evidence.

No network or Slurm; verification reads existing evidence without rewriting it.
"""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNNER = HERE.parent / 'targeted_gpu_job_20260915_v5/process_runner.py'
RUNNER_SHA = '189495e7af4fe5537df560909de456b8ca95acdf0c9f9d6603435e6230b5411a'
ORDER = ('unit', 'D-pass', 'E-pass', 'E-fail')
REPORT = dict(tests=19, errors=0, failures=0, skipped=0,
              scope='LOCAL_CONTROL_FLOW_DOUBLES_AND_OS_LOCK_ONLY',
              production_model_loaded=False, actual_production_loader_executed=False,
              gpu_validated=False, jobs_submitted=0)


def require(ok, message):
    if not ok: raise RuntimeError(message)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def record(path):
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)), 'unsafe evidence/source path')
    raw = path.read_bytes()
    return dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def sources():
    paths = [HERE / n for n in ('production_cell.py','test_lifetime.py','hermetic_spill_check.py','validate_local.py')]
    paths += [RUNNER, HERE.parent / 'g2_inputs_20260917/input_binding.py',
              HERE.parent / 'g2_scratch_20260917/scratch_binding.py',
              HERE.parent / 'g2_worker_20260916/cell_bridge.py', HERE.parent / 'g2_profiles_20260916/profiles.py']
    fixed = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
    paths += [fixed / p / n for p in 'RCDE' for n in ('diagnose_batch_invariance.py','numeric_trace.py')]
    paths += [ROOT / 'same_bank_eval_2026_09_03_v4_numeric_diag_v19' / n
              for n in ('diagnose_batch_invariance.py','numeric_trace.py','test_numeric_diag.py')]
    return dict(sorted((str(p.relative_to(ROOT)), record(p)) for p in paths))


def write(path, raw):
    with path.open('xb') as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def parse(stage, log):
    prefix = 'G2_LIFETIME_TEST_REPORT=' if stage == 'unit' else 'G2_LIFETIME_MMAP_REPORT='
    values = [json.loads(line[len(prefix):]) for line in log.decode().splitlines() if line.startswith(prefix)]
    require(len(values) == 1, 'missing or repeated result')
    value = values[0]
    if stage == 'unit':
        require(value == REPORT, 'unit scope/report differs')
    else:
        profile, mode = stage.split('-')
        require(value['profile'] == profile and value['mode'] == mode, 'stage identity differs')
        require(value['strict_loads'] == 1 and value['forward_calls'] == (34 if mode == 'pass' else 2)
                and value['spills'] == value['mappings'] == (4 if mode == 'pass' else 2), 'actual schedule/spills differ')
        require(value['status'] == ('HERMETIC_MMAP_TWO_PASS_PASS' if mode == 'pass'
                                  else 'HERMETIC_MMAP_SECOND_PASS_FAILURE_HANDLED'), 'stage outcome differs')
        require(len(value['pass_commitments']) == (2 if mode == 'pass' else 0), 'commitment coverage differs')
        require(all(value[k] is True for k in ('linux_mount_test_stub','home_unchanged','retry_rejected',
                                               'temporary_directory_removed','descriptor_scopes_closed')),
                'local test limits/cleanup differ')
        require(all(value[k] is False for k in ('production_model_loaded','cuda_initialized',
                        'actual_production_loader_executed','production_lifetime_executed'))
                and value['jobs_submitted'] == 0, 'production scope overstated')
    return value


def verify(folder):
    value = json.loads((folder / 'RECEIPT.json').read_bytes())
    require(value['status'] == 'LOCAL_G2_LIFETIME_CHECKS_PASS' and value['before'] == value['after'] == sources()
            and value['stage_order'] == list(ORDER) and 0 <= value['elapsed_seconds'] < 120
            and value['jobs_submitted'] == value['remote_operations'] == 0, 'receipt differs')
    for index, (name, expected) in enumerate(value['before'].items()):
        require(record(folder / 'sources' / (str(index) + '-' + Path(name).name)) == expected, 'snapshot changed')
    pids = []
    for stage in ORDER:
        item = value['stages'][stage]
        log = (folder / (stage + '.log')).read_bytes()
        process = item['process']
        require(process['returncode'] == 0 and process['error'] is None and process['elapsed_seconds'] < 45.5
                and process['log'] == dict(name=stage + '.log', **record(folder / (stage + '.log'))),
                'process/log differs')
        require(parse(stage, log) == item['report'], 'report changed')
        pids.append(process['pid'])
    require(len(set(pids)) == 4, 'cold child PID reused')
    print('LOCAL_G2_LIFETIME_RECHECK=PASS', flush=True)


def main():
    os.umask(0o077)
    require(record(RUNNER)['sha256'] == RUNNER_SHA, 'supervisor changed')
    spec = importlib.util.spec_from_file_location('g2_lifetime_process', RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='g2-lifetime-local-' + stamp, dir=ROOT / 'docs/superpowers/evidence'))
    print('LOCAL_EVIDENCE=' + str(folder), flush=True)
    before = sources()
    (folder / 'sources').mkdir(mode=0o700)
    for index, name in enumerate(before):
        write(folder / 'sources' / (str(index) + '-' + Path(name).name), (ROOT / name).read_bytes())
    stages, error, started = {}, None, time.monotonic()
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    try:
        for stage in ORDER:
            argv = ([str(HERE / 'test_lifetime.py')] if stage == 'unit'
                    else [str(HERE / 'hermetic_spill_check.py'), *stage.split('-')])
            remaining = 115 - (time.monotonic() - started)
            require(remaining > 0, 'local total budget exhausted')
            process = runner.run_process([sys.executable, '-I', '-B', *argv], env,
                         folder / (stage + '.log'), seconds=min(45, remaining), max_log_bytes=2 * 1024**2)
            stages[stage] = dict(process=process)
            require(process['returncode'] == 0 and process['error'] is None, 'child failed: ' + stage)
            stages[stage]['report'] = parse(stage, (folder / (stage + '.log')).read_bytes())
            print(stage + '=PASS', flush=True)
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    elapsed, after = time.monotonic() - started, sources()
    passed = error is None and before == after and elapsed < 120 and list(stages) == list(ORDER)
    value = dict(status='LOCAL_G2_LIFETIME_CHECKS_PASS' if passed else 'LOCAL_G2_LIFETIME_CHECKS_FAILED',
                 before=before, after=after, stages=stages, stage_order=list(stages),
                 elapsed_seconds=elapsed, error=error, jobs_submitted=0, remote_operations=0)
    write(folder / 'RECEIPT.json', wire(value))
    if passed: verify(folder)
    else: print(json.dumps(error), flush=True)
    return 0 if passed else 2


if __name__ == '__main__':
    if len(sys.argv) == 1: raise SystemExit(main())
    if len(sys.argv) == 3 and sys.argv[1] == 'verify': verify(Path(sys.argv[2]).resolve())
    else: raise SystemExit('usage: validate_local.py [verify EVIDENCE_DIRECTORY]')
