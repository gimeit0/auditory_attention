"""Bounded local synthetic study. No SSH, scheduler, checkpoint or GPU use."""
import cProfile
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
JOB = ROOT / 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5'
RELEASE_SHA = 'c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20'
sys.path.insert(0, str(HERE))
import candidate


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sources():
    raw = (JOB / 'SOURCE_MANIFEST.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == RELEASE_SHA, 'frozen runtime manifest changed')
    files = json.loads(raw)['files']
    require(len(files) == 162, 'frozen source inventory changed')
    for name, expected in files.items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts, 'invalid release path')
        require(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, 'source differs: ' + name)
    return files


def local_sources():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}


def fixture_for(diag):
    sys.path.insert(0, str(ROOT / 'docs/superpowers/prototypes/targeted_worker_20260915_scan'))
    import test_baseline_bridge as fixture
    # Explicit hermetic test seam, NOT acceptance by the pinned production bridge.
    fixture.diag = diag
    fixture.fixture.diagnose = diag
    fixture.torch.set_num_threads(1)
    return fixture


def profile_rows(profiler, filename):
    rows = []
    for (file, line, name), (primitive, calls, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
        if file == filename:
            rows.append({'function': name, 'line': line, 'calls': calls, 'primitive_calls': primitive,
                         'self_seconds': own, 'cumulative_seconds': cumulative,
                         'callers': [{'function': k[2], 'line': k[1], 'calls': v[1]}
                                     for k, v in callers.items() if k[0] == filename]})
    return sorted(rows, key=lambda r: (-r['self_seconds'], r['line']))


def child(folder, label, runner):
    variant = 'original' if label.startswith('original') else 'candidate'
    diag, digest = candidate.load(variant)
    fixture = fixture_for(diag)
    measured = label.endswith('profile')
    record = {'label': label, 'variant': variant, 'assembled_sha256': digest, 'pid': os.getpid(),
              'python': sys.version.split()[0], 'torch': str(fixture.torch.__version__),
              'cprofile': measured, 'production_model_loaded': False, 'jobs_submitted': 0, 'ready_for_gpu': False}
    profiler = cProfile.Profile()
    start = time.perf_counter()
    if label == 'tests':
        import test_namespace
        record.update(test_namespace.run(diag, fixture))
    else:
        print('EXPECTED_CONTRACT_BEGIN=' + label, flush=True)
        if measured:
            profiler.enable()
        try:
            contract = fixture.expected_contract()
        finally:
            if measured:
                profiler.disable()
        wire = fixture.replay.canonical(contract)
        record.update(contract=contract, contract_sha256=hashlib.sha256(wire).hexdigest(),
            functions=profile_rows(profiler, '<namespace-scan-local-' + variant + '>') if measured else [])
        print('EXPECTED_CONTRACT_END=' + label, flush=True)
    record.update(wall_seconds=time.perf_counter() - start)
    require(not fixture.torch.cuda.is_initialized(), 'CUDA unexpectedly initialized')
    record.update(status='LOCAL_SYNTHETIC_CHILD_COMPLETE', cuda_initialized=False)
    runner.write_once(folder / (label + '-result.json'), record)


def main():
    os.umask(0o077)
    before, new_before = sources(), local_sources()
    sys.path.insert(0, str(JOB))
    import process_runner as runner
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        child(Path(sys.argv[2]), sys.argv[3], runner)
        require(before == sources() and new_before == local_sources(), 'sources changed in child')
        return 0
    require(len(sys.argv) == 2 and sys.argv[1] in ('baseline', 'candidate'), 'choose baseline or candidate local study')
    mode = sys.argv[1]
    labels = ('original_1', 'original_profile') if mode == 'baseline' else (
        'tests', 'original_1', 'candidate_1', 'candidate_2', 'original_2', 'original_profile', 'candidate_profile')
    folder = Path(tempfile.mkdtemp(prefix='namespace-' + mode + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-',
                                  dir=ROOT / 'docs/superpowers/evidence'))
    print('EVIDENCE_DIRECTORY=' + str(folder), flush=True)
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONHASHSEED': '0'}
    processes, results, error, summary = [], [], None, {}
    started = time.monotonic()
    try:
        for label in labels:
            remaining = 600 - (time.monotonic() - started)
            require(remaining > 0, 'total study deadline')
            process = runner.run_process([sys.executable, '-I', '-B', str(HERE / 'study.py'), '--child', str(folder), label],
                env, folder / (label + '.log'), seconds=min(180, remaining), max_log_bytes=2 * 1024**2)
            processes.append({'label': label, **process})
            runner.write_once(folder / (label + '-process.json'), process)
            require(process['returncode'] == 0 and process['error'] is None, 'child failed: ' + label)
            result = json.loads((folder / (label + '-result.json')).read_bytes())
            require(result['pid'] == process['pid'] and result['status'] == 'LOCAL_SYNTHETIC_CHILD_COMPLETE', 'invalid result')
            results.append(result)
            print(json.dumps({'label': label, 'wall_seconds': result['wall_seconds']}), flush=True)
        contract_results = [r for r in results if 'contract' in r]
        require(all(r['contract'] == contract_results[0]['contract'] for r in contract_results), 'outputs or boundaries differ')
        summary['synthetic_output_bytes_and_boundary_records_equal'] = True
        if mode == 'candidate':
            profiles = {r['variant']: r for r in results if r['cprofile']}
            # All core named functions except the lowered generator internals.
            counts = [{(f['function']): (f['calls'], f['primitive_calls']) for f in profiles[v]['functions']
                       if not f['function'].startswith('<')} for v in ('original', 'candidate')]
            require(counts[0] == counts[1], 'core guard/operator invocation counts changed')
            summary['core_named_function_call_counts_equal'] = True
            timings = {v: [r['wall_seconds'] for r in contract_results if r['variant'] == v and not r['cprofile']]
                       for v in ('original', 'candidate')}
            medians = {v: statistics.median(t) for v, t in timings.items()}
            summary.update(unprofiled_seconds=timings, medians_seconds=medians,
                           speedup=medians['original'] / medians['candidate'])
        require(before == sources() and new_before == local_sources(), 'sources changed')
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    receipt = {'status': 'LOCAL_NAMESPACE_STUDY_PASS' if error is None else 'LOCAL_NAMESPACE_STUDY_FAILED',
        'mode': mode, 'error': error, 'processes': processes, 'summary': summary,
        'source_sha256': new_before, 'frozen_manifest_sha256': RELEASE_SHA,
        'frozen_sources_unchanged': before == sources(), 'new_sources_unchanged': new_before == local_sources(),
        'artifacts': {p.name: runner.file_record(p) for p in folder.iterdir() if p.is_file()},
        'jobs_submitted': 0, 'remote_executed': False, 'automatic_retry': False, 'ready_for_gpu': False,
        'scope': 'synthetic CPU performance candidate only; no production or HAKUSAN compatibility claim'}
    runner.write_once(folder / 'receipt.json', receipt)
    print(json.dumps({'status': receipt['status'], 'error': error, 'summary': summary, 'receipt': str(folder / 'receipt.json')}), flush=True)
    return 0 if error is None else 2


if __name__ == '__main__':
    raise SystemExit(main())
