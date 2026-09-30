"""Single bounded CPU validation; no SSH, checkpoints, GPU jobs or retry."""

from datetime import datetime, timezone
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
SOURCES = ("prepare_registration.py", "test_prepare_registration.py", "validate_local.py")
TESTS = 18


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def child(folder):
    import unittest
    sys.path.insert(0, str(HERE))
    import test_prepare_registration as tests
    import torch
    import numpy as np
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests.PreparationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    runs = tests.PreparationTests.complete_runs
    passed = result.testsRun == TESTS and result.wasSuccessful() and not result.skipped and len(runs) == 2
    passed = passed and not torch.cuda.is_initialized()
    value = {"status": "LOCAL_PREPARATION_TESTS_PASS" if passed else "LOCAL_PREPARATION_TESTS_FAILED",
             "worker_pid": os.getpid(), "tests": result.testsRun, "skips": len(result.skipped),
             "python": sys.version.split()[0], "torch": torch.__version__, "numpy": np.__version__,
             "complete_runs": runs, "same_process_synthetic_reference": True,
             "production_model_loaded": False, "cuda_initialized": torch.cuda.is_initialized(),
             "production_preparation_validated": False, "ready_for_gpu": False, "jobs_submitted": 0}
    save(folder / "child-result.json", value)
    print(json.dumps(value, sort_keys=True), flush=True)
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    if len(sys.argv) != 1:
        raise SystemExit("Usage: validate_local.py (CPU-only, no remote execution)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix=f"preseal-preparation-local-{stamp}-",
                                  dir=WORKSPACE / "docs/superpowers/evidence"))
    print(f"EVIDENCE_DIRECTORY={folder}", flush=True)
    before = {name: sha(HERE / name) for name in SOURCES}
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    command = [sys.executable, "-I", "-B", str(HERE / "validate_local.py"), "--child", str(folder)]
    started = time.monotonic()
    with (folder / "output.log").open("xb") as output:
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = 124
    after = {name: sha(HERE / name) for name in SOURCES}
    value = json.loads((folder / "child-result.json").read_text()) if (folder / "child-result.json").exists() else {}
    passed = (code == 0 and before == after and value.get("status") == "LOCAL_PREPARATION_TESTS_PASS"
              and value.get("worker_pid") == process.pid and value.get("tests") == TESTS
              and value.get("skips") == 0 and value.get("production_model_loaded") is False
              and value.get("cuda_initialized") is False)
    runs = value.get("complete_runs", [])
    passed = passed and len(runs) == 2 and [r["cell"] for r in runs] == ["A2", "B2"]
    for run in runs:
        prep, observed = run["preparation"], run["observed"]
        passed = (passed and run["load_calls"] == 1 and run["forward_calls"] == 34
                  and run["hooks_removed"] is True and observed["capture_records"] == 16
                  and observed["stage_invocations"] == 136 and observed["worker_pid"] == process.pid
                  and prep["install_count"] == prep["pre_issue_check_count"] == 1
                  and prep["test_model_preinjection_used"] is False
                  and prep["ast_audit"]["original_ast_restored_exactly"] is True
                  and prep["production_preparation_validated"] is False)
    artifacts = {name: {"sha256": sha(folder / name), "size": (folder / name).stat().st_size}
                 for name in ("output.log", "child-result.json") if (folder / name).exists()}
    receipt = {"status": "LOCAL_PRESEAL_PREPARATION_ACCEPTED" if passed else "LOCAL_PRESEAL_PREPARATION_FAILED",
               "schema_version": 1, "child_pid": process.pid, "returncode": code,
               "source_sha256": before, "artifacts": artifacts,
               "elapsed_seconds": round(time.monotonic() - started, 3), "timeout_seconds": 180,
               "automatic_retry": False, "production_model_loaded": False,
               "production_preparation_validated": False, "ready_for_gpu": False, "jobs_submitted": 0}
    save(folder / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
