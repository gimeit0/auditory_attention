"""Bounded cold-process local checks, durable evidence, no network or scheduler."""
from datetime import datetime, timezone
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import job_contract as contract
import process_runner as runner
import release_manifest
import verify_recipe

GROUPS = {
    'control': (HERE, ('test_job_control',), 27),
    'input_binding': (HERE, ('test_input_binding',), 25),
    'startup': (HERE, ('test_startup',), 12),
    'result_identity': (HERE, ('test_result_identity',), 11),
    'captures': (HERE, ('test_capture_verifier',), 13),
    'array_budget': (HERE, ('test_real_array_budget',), 3),
    'runtime_timing': (HERE, ('test_runtime_timing',), 16),
    'scratch_lifetime': (HERE, ('test_scratch_integration',), 2),
    'archive_regression': (HERE.parent / 'targeted_gpu_pair_20260915_scan',
                            ('test_pair_archive', 'test_reference_integration'), 38),
    'freeze_regression': (HERE.parent / 'guard_scan_integration_20260915', ('test_freeze_relation',), 15),
}


def child(name, folder):
    path, names, expected = GROUPS[name]
    sys.path.insert(0, str(path))
    modules = [importlib.import_module(n) for n in names]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    # Never import torch only for reporting after a stdlib-only suite.
    torch = sys.modules.get('torch')
    cuda = bool(torch is not None and torch.cuda.is_initialized())
    record = {'group': name, 'pid': os.getpid(), 'tests': outcome.testsRun,
              'errors': len(outcome.errors), 'failures': len(outcome.failures), 'skips': len(outcome.skipped),
              'passed': outcome.wasSuccessful() and outcome.testsRun == expected and not outcome.skipped and not cuda,
              'cuda_initialized': cuda, 'production_model_loaded': False, 'jobs_submitted': 0,
              'python': sys.version.split()[0], 'torch': importlib.metadata.version('torch'),
              'scope': 'local synthetic CPU only; no actual production/CUDA/Inductor/Linux-mount claim'}
    runner.write_once(folder / (name + '.json'), record)
    return 0 if record['passed'] else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 4 and sys.argv[1] == '--child':
        return child(sys.argv[2], Path(sys.argv[3]))
    contract.require(len(sys.argv) == 1, 'local validation only')
    before = release_manifest.check()
    derivation = verify_recipe.verify()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = Path(tempfile.mkdtemp(prefix='gpu-pair-v19-local-' + stamp + '-',
                                 dir=ROOT / 'docs/superpowers/evidence'))
    print('EVIDENCE_DIRECTORY=' + str(folder), flush=True)
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    results = []
    for name, (_, _, count) in GROUPS.items():
        print('COLD_TEST_GROUP=' + name, flush=True)
        result = runner.run_process([sys.executable, '-I', '-B', str(HERE / 'validate_local.py'),
            '--child', name, str(folder)], env, folder / (name + '.log'), seconds=150, max_log_bytes=4 * 1024**2)
        record = json.loads((folder / (name + '.json')).read_bytes()) if (folder / (name + '.json')).is_file() else {}
        ok = (result['returncode'] == 0 and result['error'] is None and record.get('passed') is True
              and record.get('pid') == result['pid'] and record.get('tests') == count)
        results.append({'group': name, 'process': result, 'record': record, 'verified': ok})
    unchanged = before == release_manifest.check()
    good = unchanged and all(r['verified'] for r in results)
    artifacts = {p.name: runner.file_record(p) for p in sorted(folder.iterdir())}
    receipt = {'status': 'LOCAL_V19_PAIR_RUNTIME_PASS' if good else 'LOCAL_V19_PAIR_RUNTIME_FAILED',
        'manifest_sha256': before[0], 'source_files': len(before[1]['files']), 'sources_unchanged': unchanged,
        'derivation': derivation, 'groups': results, 'tests': sum(r['record'].get('tests', 0) for r in results),
        'artifacts': artifacts, 'remote_executed': False, 'jobs_submitted': 0, 'submission_authorized': False,
        'candidate_input_freeze_sha256': None, 'ready_for_gpu': False, 'automatic_retry': False}
    runner.write_once(folder / 'receipt.json', receipt)
    print(json.dumps({'status': receipt['status'], 'tests': receipt['tests'], 'groups': len(results),
        'receipt': str(folder / 'receipt.json'), 'jobs_submitted': 0, 'ready_for_gpu': False}), flush=True)
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
