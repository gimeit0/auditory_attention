"""Local synthetic CPU tests with a nonzero expected test count."""

import json
from pathlib import Path
import sys
import unittest


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import torch
    import test_trace_observer

    suite = unittest.defaultTestLoader.loadTestsFromModule(test_trace_observer)
    expected = 28
    if suite.countTestCases() != expected:
        raise RuntimeError(f"test discovery differs: {suite.countTestCases()} != {expected}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    complete = (result.wasSuccessful() and result.testsRun == expected
                and not result.skipped and not result.expectedFailures)
    print(json.dumps({"status": "SYNTHETIC_CPU_TESTS_PASS" if complete else "TESTS_FAILED",
                      "tests": result.testsRun, "python": sys.version.split()[0],
                      "torch": torch.__version__, "cuda_initialized": torch.cuda.is_initialized(),
                      "compiled_test_backend": "eager", "production_model_loaded": False,
                      "scope": "prototype only; not Inductor, A100, or production guard validation"}))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
