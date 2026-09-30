"""One bounded, durable local validation attempt. Never connects or submits."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import job_contract as contract  # noqa: E402
import process_runner as runner  # noqa: E402

EXPECTED_NEW = 45
EXPECTED_OLD = 38


def checked_package():
    raw = contract.pinned_read(HERE / "SOURCE_MANIFEST.json")
    sha = hashlib.sha256(raw).hexdigest()
    return sha, contract.check_sources(sha)


def child(folder):
    import unittest
    import test_job_control
    import test_capture_verifier
    import test_scratch_integration
    import test_real_array_budget
    import test_pair_archive
    import test_reference_integration
    import torch
    groups = (("new", (test_job_control, test_capture_verifier, test_scratch_integration, test_real_array_budget), EXPECTED_NEW),
              ("regression", (test_pair_archive, test_reference_integration), EXPECTED_OLD))
    results = []
    for name, modules, expected in groups:
        print("TEST_GROUP=" + name, flush=True)
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)
        outcome = unittest.TextTestRunner(verbosity=2).run(suite)
        results.append({"group": name, "tests": outcome.testsRun, "skips": len(outcome.skipped),
                        "passed": outcome.wasSuccessful() and outcome.testsRun == expected and not outcome.skipped})
    value = {"status": "LOCAL_JOB_CANDIDATE_TESTS_PASS" if all(r["passed"] for r in results)
             and not torch.cuda.is_initialized() else "LOCAL_JOB_CANDIDATE_TESTS_FAILED",
             "pid": os.getpid(), "groups": results, "python": sys.version.split()[0], "torch": str(torch.__version__),
             "cuda_initialized": torch.cuda.is_initialized(), "production_model_loaded": False,
             "ready_for_gpu": False, "jobs_submitted": 0, "remote_executed": False,
             "scope": "synthetic local process/ledger/control checks, real-size zero-array streaming, original hermetic CPU with real mmap; no production/CUDA/Inductor or Linux mount factory"}
    runner.write_once(folder / "child-result.json", value)
    return 0 if value["status"] == "LOCAL_JOB_CANDIDATE_TESTS_PASS" else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    contract.require(len(sys.argv) == 1, "local validation only")
    before = checked_package()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix="gpu-job-v2-local-" + stamp + "-", dir=ROOT / "docs/superpowers/evidence"))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    outcome = runner.run_process([sys.executable, "-I", "-B", str(HERE / "validate_local.py"), "--child", str(folder)],
                                 env, folder / "output.log", seconds=180, max_log_bytes=4 * 1024**2)
    record, error, unchanged = {}, None, False
    try:
        unchanged = before == checked_package()
        record = json.loads(contract.pinned_read(folder / "child-result.json"))
        contract.require(unchanged and outcome["error"] is None and outcome["returncode"] == 0
                         and record["pid"] == outcome["pid"] and record["status"] == "LOCAL_JOB_CANDIDATE_TESTS_PASS"
                         and record["cuda_initialized"] is False and record["production_model_loaded"] is False
                         and record["groups"] == [{"group": "new", "tests": EXPECTED_NEW, "skips": 0, "passed": True},
                                                  {"group": "regression", "tests": EXPECTED_OLD, "skips": 0, "passed": True}],
                         "candidate validation did not pass")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "LOCAL_GPU_JOB_CANDIDATE_VERIFIED" if error is None else "LOCAL_GPU_JOB_CANDIDATE_FAILED",
               "manifest_sha256": before[0], "source_files": len(before[1]["files"]), "sources_unchanged": unchanged,
               "process": outcome, "child": record, "error": error,
               "artifacts": {name: runner.file_record(folder / name) for name in ("output.log", "child-result.json")
                             if (folder / name).is_file()},
               "automatic_retry": False, "remote_executed": False, "jobs_submitted": 0, "ready_for_gpu": False}
    runner.write_once(folder / "receipt.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
