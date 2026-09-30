"""Bounded CPU-only supervisor. No SSH, GPU, model checkpoint or submission."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[3]
SOURCES = ("observer_lifecycle.py", "test_observer_lifecycle.py", "validate_local.py")
EXPECTED_TESTS = 25


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def child(folder):
    import unittest
    sys.path.insert(0, str(HERE))
    import test_observer_lifecycle as tests
    import torch
    import numpy as np
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests.LifecycleTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    runs = tests.LifecycleTests.complete_runs
    passed = (result.testsRun == EXPECTED_TESTS and result.wasSuccessful() and not result.skipped
              and len(runs) == 2 and not torch.cuda.is_initialized())
    value = {"status": "LOCAL_HERMETIC_LIFECYCLE_PASS" if passed else "LOCAL_HERMETIC_LIFECYCLE_FAILED",
             "scope": "original_v18_guards_preissued_toy_hooks_CPU_only",
             "tests": result.testsRun, "skips": len(result.skipped), "worker_pid": os.getpid(),
             "python": sys.version.split()[0], "torch": torch.__version__, "numpy": np.__version__,
             "complete_runs": runs, "same_process_synthetic_reference": True,
             "cuda_initialized": torch.cuda.is_initialized(), "production_model_loaded": False,
             "production_preparation_integration": False, "real_parent_replay_completed": False,
             "compiled_backend": None, "ready_for_gpu": False, "jobs_submitted": 0}
    save(folder / "child-result.json", value)
    print(json.dumps(value, sort_keys=True), flush=True)
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    if len(sys.argv) != 1:
        raise SystemExit("Usage: validate_local.py (local CPU only)")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=f"observer-lifecycle-local-{stamp}-",
                                  dir=WORKSPACE / "docs/superpowers/evidence"))
    print(f"EVIDENCE_DIRECTORY={folder}", flush=True)
    before = {name: sha(HERE / name) for name in SOURCES}
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    command = [sys.executable, "-I", "-B", str(HERE / "validate_local.py"), "--child", str(folder)]
    started = time.monotonic()
    with (folder / "output.log").open("xb") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = 124
    after = {name: sha(HERE / name) for name in SOURCES}
    value = json.loads((folder / "child-result.json").read_text()) if (folder / "child-result.json").exists() else {}
    passed = (code == 0 and before == after and value.get("status") == "LOCAL_HERMETIC_LIFECYCLE_PASS"
              and value.get("worker_pid") == process.pid and value.get("tests") == EXPECTED_TESTS
              and value.get("skips") == 0 and value.get("production_model_loaded") is False
              and value.get("cuda_initialized") is False)
    runs = value.get("complete_runs", [])
    passed = passed and len(runs) == 2 and [r["result"]["cell"] for r in runs] == ["A2", "B2"]
    for run in runs:
        r = run["result"]
        passed = (passed and run["load_calls"] == 1 and run["forward_calls"] == 34
                  and run["hooks_removed"] is True and run["old_identity_revoked"] is True
                  and r["worker_pid"] == process.pid and r["batches"] == 34
                  and r["stage_invocations"] == 136 and r["capture_records"] == 16
                  and r["original_guard_domain"] == "hermetic-test" and r["ready_for_gpu"] is False)
    artifacts = {name: {"sha256": sha(folder / name), "size": (folder / name).stat().st_size}
                 for name in ("output.log", "child-result.json") if (folder / name).exists()}
    receipt = {"status": "LOCAL_OBSERVER_LIFECYCLE_ACCEPTED" if passed else "LOCAL_OBSERVER_LIFECYCLE_FAILED",
               "schema_version": 1, "child_pid": process.pid, "returncode": code,
               "elapsed_seconds": round(time.monotonic() - started, 3), "timeout_seconds": 180,
               "source_sha256": before, "artifacts": artifacts, "automatic_retry": False,
               "production_model_loaded": False, "real_parent_replay_completed": False,
               "production_preparation_integration": False, "ready_for_gpu": False, "jobs_submitted": 0}
    save(folder / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

