"""Local synthetic checks only. Never connects, submits or loads checkpoints."""

import json
from pathlib import Path
import sys
import unittest


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_stream_capture
    import test_formal_plan
    import test_trace_observer
    import torch

    torch.set_num_threads(1)
    suite = unittest.TestSuite()
    for module, expected in ((test_trace_observer, 28), (test_stream_capture, 34),
                             (test_formal_plan, 4)):
        group = unittest.defaultTestLoader.loadTestsFromModule(module)
        if group.countTestCases() != expected:
            raise RuntimeError(f"unexpected test count: {module.__name__}: {group.countTestCases()}")
        suite.addTests(group)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = (result.wasSuccessful() and result.testsRun == 66
          and not result.skipped and not result.expectedFailures and not torch.cuda.is_initialized())
    print(json.dumps({"status": "STREAM_SYNTHETIC_CPU_PASS" if ok else "TESTS_FAILED",
                      "tests": result.testsRun, "python": sys.version.split()[0],
                      "torch": torch.__version__, "compiled_test_backend": "eager",
                      "cuda_initialized": torch.cuda.is_initialized(),
                      "production_model_loaded": False, "jobs_submitted": 0,
                      "ready_for_gpu": False}))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
