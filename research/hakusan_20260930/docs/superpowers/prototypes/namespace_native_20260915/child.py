"""33 selected candidate CPU checks + scanner microbenchmark; not full compatibility."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

ASSEMBLED = '6daa2ac0f4a606a681dc5acf17676afb41bc2dd79fbd9a43887a54497aef1e03'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def main():
    require(len(sys.argv) == 4 and sys.argv[2] == 'namespace_subset', 'fixed subset required')
    root, group, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    require(mode in ('NATIVE_CPU', 'LOCAL_HARNESS') and sys.flags.isolated and sys.dont_write_bytecode,
            'isolated CPU child required')
    require(os.environ.get('CUDA_VISIBLE_DEVICES') == '' and all(os.environ.get(n) == '1'
            for n in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')), 'CPU environment differs')
    sys.path.insert(0, str(root / 'docs/superpowers/prototypes/namespace_scan_20260915'))
    import candidate
    import study
    import test_namespace
    study.sources()  # Entire frozen parent package before any synthetic model setup.
    diag, assembled = candidate.load('candidate')
    require(assembled == ASSEMBLED, 'assembled test-only candidate differs')
    fixture = study.fixture_for(diag)
    if mode == 'NATIVE_CPU':
        require(sys.version.split()[0] == '3.11.5' and str(fixture.torch.__version__) == '2.1.1+cu118'
                and len(os.sched_getaffinity(0)) == 1, 'native Python/torch/affinity differs')
    suite, existing = test_namespace.make_suite(diag, fixture)
    # Selection is explicit: unchanged 15 candidate tests plus 18 original
    # binding/name tests. No edits to test bodies, samples or assertions. The
    # 106 other tests and complete expected_contract are NOT certified here.
    selected = [t for t in cases(suite) if type(t).__name__ == 'NamespaceTests' or
                type(t).__module__ in ('namespace_overlay_test_binding_scan',
                                      'namespace_overlay_test_module_name_classification')]
    ids = [t.id() for t in selected]
    require(existing == 124 and len(ids) == len(set(ids)) == 33, 'subset inventory differs')
    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    passed = outcome.wasSuccessful() and outcome.testsRun == 33 and not outcome.skipped
    timings = test_namespace.microbenchmark(diag) if passed else []
    study.sources()
    cuda = fixture.torch.cuda.is_initialized()
    require(not cuda, 'CUDA unexpectedly initialized')
    value = {'status': 'SYNTHETIC_CPU_SUITE_PASS' if passed else 'SYNTHETIC_CPU_SUITE_FAILED',
        'group': group, 'mode': mode, 'pid': os.getpid(), 'tests': outcome.testsRun, 'test_ids': ids,
        'errors': len(outcome.errors), 'failures': len(outcome.failures), 'skips': len(outcome.skipped),
        'python': sys.version.split()[0], 'torch': str(fixture.torch.__version__),
        'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'cuda_initialized': cuda, 'assembled_sha256': assembled, 'microbenchmark': timings,
        'production_model_loaded': False, 'production_snapshot_loaded': False,
        'full_expected_contract_executed': False, 'original_native_compatibility_verified': False,
        'jobs_submitted': 0, 'ready_for_gpu': False,
        'scope': '33 namespace candidate rejection/equivalence tests and synthetic scanner timing only; no full trace or GPU'}
    print('NAMESPACE_CPU_CHILD=' + json.dumps(value, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
