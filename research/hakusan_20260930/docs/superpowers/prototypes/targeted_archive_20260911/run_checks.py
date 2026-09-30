"""Exactly 31 archive unit tests, CPU-only. Independent-pair checks are separate."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import torch  # noqa: E402

torch.set_num_threads(1)
suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent),
                                           pattern='test_trace_archive.py')
if suite.countTestCases() != 31:
    raise RuntimeError('archive test count differs')
result = unittest.TextTestRunner(verbosity=2).run(suite)
ok = result.wasSuccessful() and result.testsRun == 31 and not result.skipped
ok = ok and not torch.cuda.is_initialized()
print(json.dumps({'status': 'ARCHIVE_UNIT_TESTS_PASS' if ok else 'ARCHIVE_TESTS_FAILED',
    'tests': result.testsRun, 'skipped': len(result.skipped), 'torch': str(torch.__version__),
    'cuda_initialized': torch.cuda.is_initialized(), 'production_model_loaded': False,
    'jobs_submitted': 0}), flush=True)
raise SystemExit(0 if ok else 2)
