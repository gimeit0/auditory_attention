"""Fixed synthetic CPU suites against an unmodified, temporary v19 package."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import unittest

GROUPS = {
    'input_binding': ('targeted_gpu_job_20260915_v5', 'test_input_binding', 25),
    'startup': ('targeted_gpu_job_20260915_v5', 'test_startup', 12),
    'result_identity': ('targeted_gpu_job_20260915_v5', 'test_result_identity', 11),
    'adapter_cpu': ('targeted_production_preparation_20260915_scan', 'test_cuda_registration', 30),
    'scratch_lifetime': ('targeted_gpu_job_20260915_v5', 'test_scratch_integration', 2),
}


def main():
    if len(sys.argv) != 4 or sys.argv[2] not in GROUPS:
        raise SystemExit('fixed package, suite and mode required')
    root, name, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if mode not in ('NATIVE_CPU', 'LOCAL_HARNESS'):
        raise SystemExit('invalid mode')
    if os.environ.get('CUDA_VISIBLE_DEVICES') != '' or os.environ.get('OMP_NUM_THREADS') != '1':
        raise RuntimeError('CPU-only fixed environment required')
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError('isolated no-bytecode child required')
    if mode == 'NATIVE_CPU':
        if len(os.sched_getaffinity(0)) != 1 or sys.version.split()[0] != '3.11.5':
            raise RuntimeError('native one-CPU child required')
    directory, module, expected = GROUPS[name]
    sys.path.insert(0, str(root / 'docs/superpowers/prototypes' / directory))
    suite = unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(module))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    torch = sys.modules.get('torch')
    cuda = bool(torch is not None and torch.cuda.is_initialized())
    version = importlib.metadata.version('torch')
    passed = (outcome.wasSuccessful() and outcome.testsRun == expected and not outcome.skipped
              and not cuda and (mode != 'NATIVE_CPU' or version == '2.1.1+cu118'))
    value = {'status': 'SYNTHETIC_CPU_SUITE_PASS' if passed else 'SYNTHETIC_CPU_SUITE_FAILED',
        'group': name, 'mode': mode, 'pid': os.getpid(), 'tests': outcome.testsRun,
        'errors': len(outcome.errors), 'failures': len(outcome.failures), 'skips': len(outcome.skipped),
        'python': sys.version.split()[0], 'torch': version, 'cuda_initialized': cuda,
        'cpu_affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
        'production_model_loaded': False, 'jobs_submitted': 0,
        'scope': 'synthetic CPU; not production model, CUDA, Inductor, or real mount-factory validation'}
    print('V19_CPU_CHILD=' + json.dumps(value, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
