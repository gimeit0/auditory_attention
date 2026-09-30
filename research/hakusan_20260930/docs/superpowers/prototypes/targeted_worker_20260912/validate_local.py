"""Single bounded local test run; no SSH, production model or Slurm.

Supervisor creates new evidence, runs hermetic tests in a separate CPU process,
and independently checks returned counts, PID and source/artifact hashes.
"""

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
SOURCES = ("baseline_bridge.py", "test_baseline_bridge.py", "validate_local.py")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def child(folder):
    import unittest
    sys.path.insert(0, str(HERE))
    import test_baseline_bridge as tests
    import torch
    import numpy as np
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests.BaselineBridgeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun == 17 and result.wasSuccessful() and not result.skipped
    runs = tests.BaselineBridgeTests.complete_runs
    passed = passed and len(runs) == 2 and not torch.cuda.is_initialized()
    value = {
        "status": "LOCAL_HERMETIC_V18_BRIDGE_PASS" if passed else "LOCAL_HERMETIC_V18_BRIDGE_FAILED",
        "scope": "original_v18_operators_and_guards_with_hermetic_CPU_fixtures_only",
        "worker_pid": os.getpid(), "tests": result.testsRun, "skips": len(result.skipped),
        "python": sys.version.split()[0], "torch": torch.__version__, "numpy": np.__version__,
        "complete_runs": runs, "same_process_synthetic_reference": True,
        "fixture_contract_sha256": tests.BaselineBridgeTests.sha,
        "real_parent_replay_completed": False, "production_model_loaded": False,
        "cuda_initialized": torch.cuda.is_initialized(), "production_authority": False,
        "ready_for_gpu": False, "jobs_submitted": 0,
    }
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
    evidence = WORKSPACE / "docs/superpowers/evidence"
    folder = Path(tempfile.mkdtemp(prefix=f"baseline-bridge-local-{stamp}-", dir=evidence))
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
    passed = (code == 0 and before == after and value.get("status") == "LOCAL_HERMETIC_V18_BRIDGE_PASS"
              and value.get("worker_pid") == process.pid and value.get("tests") == 17 and value.get("skips") == 0
              and value.get("production_model_loaded") is False and value.get("cuda_initialized") is False)
    runs = value.get("complete_runs", [])
    passed = passed and len(runs) == 2 and [r["result"]["cell"] for r in runs] == ["A2", "B2"]
    for run in runs:
        passed = (passed and run["load_calls"] == 1 and run["forward_calls"] == 34
                  and run["raw_batch_sizes"] == [16, 16] + [1] * 32
                  and run["cue_batch_sizes"] == [16, 16] + [1] * 32
                  and run["result"]["worker_pid"] == process.pid
                  and run["result"]["original_guard_domain"] == "hermetic-test"
                  and run["result"]["production_execution_authority_verified"] is False)
    artifacts = {name: {"sha256": sha(folder / name), "size": (folder / name).stat().st_size}
                 for name in ("output.log", "child-result.json") if (folder / name).exists()}
    receipt = {"status": "LOCAL_BASELINE_BRIDGE_ACCEPTED" if passed else "LOCAL_BASELINE_BRIDGE_FAILED",
               "schema_version": 1, "child_pid": process.pid, "returncode": code,
               "elapsed_seconds": round(time.monotonic() - started, 3), "timeout_seconds": 180,
               "source_sha256": before, "artifacts": artifacts, "automatic_retry": False,
               "production_model_loaded": False, "real_parent_replay_completed": False,
               "observed_worker_integrated": False, "ready_for_gpu": False, "jobs_submitted": 0}
    save(folder / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
