"""Local-only array/AST/hermetic-reference checks with durable receipts.

Never connects, uploads, submits or imports a production checkpoint. One test
attempt per invocation; failed evidence remains in a new private directory.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EXPECTED_TESTS = 38


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def package_check():
    raw = (HERE / "SOURCE_MANIFEST.json").read_bytes()
    manifest = json.loads(raw)
    for name, digest in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("invalid source path")
        path = ROOT / relative
        if not stat.S_ISREG(path.lstat().st_mode) or sha(path.read_bytes()) != digest:
            raise RuntimeError("source changed: " + name)
    return sha(raw), manifest


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def child(folder):
    import unittest
    sys.path.insert(0, str(HERE))
    import test_pair_archive
    import test_reference_integration
    import torch
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m)
                               for m in (test_pair_archive, test_reference_integration))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and result.testsRun == EXPECTED_TESTS and not result.skipped and not torch.cuda.is_initialized()
    record = {"status": "LOCAL_GPU_PAIR_ARCHIVE_TESTS_PASS" if passed else "LOCAL_GPU_PAIR_ARCHIVE_TESTS_FAILED",
              "pid": os.getpid(), "tests": result.testsRun, "skips": len(result.skipped),
              "python": sys.version.split()[0], "torch": str(torch.__version__),
              "production_model_loaded": False, "production_preparation_validated": False,
              "cuda_initialized": torch.cuda.is_initialized(), "ready_for_gpu": False, "jobs_submitted": 0,
              "scope": "synthetic two-process arrays, AST and original hermetic CPU reference; scratch is a test double, no real mmap/CUDA/compiled/production execution"}
    save(folder / "child-result.json", record)
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    if len(sys.argv) != 1:
        raise SystemExit("Usage: validate_local.py (local tests only; no GPU submission)")
    before = package_check()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix="gpu-pair-archive-local-" + stamp + "-",
                                  dir=ROOT / "docs/superpowers/evidence"))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    env = dict(os.environ)
    env.update({"CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    started = time.monotonic()
    with (folder / "output.log").open("xb") as output:
        process = subprocess.Popen([sys.executable, "-I", "-B", str(HERE / "validate_local.py"), "--child", str(folder)],
                                   stdout=output, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        while True:
            try:
                code = process.wait(timeout=20)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - started
                print("LOCAL_TEST_RUNNING_SECONDS=" + str(round(elapsed)), flush=True)
                if elapsed >= 120:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    code = 124
                    break
    record = json.loads((folder / "child-result.json").read_bytes()) if (folder / "child-result.json").exists() else {}
    unchanged = before == package_check()
    passed = (code == 0 and unchanged and record.get("pid") == process.pid and record.get("tests") == EXPECTED_TESTS
              and record.get("status") == "LOCAL_GPU_PAIR_ARCHIVE_TESTS_PASS" and record.get("skips") == 0
              and record.get("production_model_loaded") is False and record.get("cuda_initialized") is False)
    value = {"status": "LOCAL_GPU_PAIR_ARCHIVE_CANDIDATE_VERIFIED" if passed else "LOCAL_GPU_PAIR_ARCHIVE_CANDIDATE_FAILED",
             "returncode": code, "manifest_sha256": before[0], "source_files": len(before[1]["files"]),
             "child": record, "elapsed_seconds": round(time.monotonic() - started, 3),
             "artifacts": {name: {"size": (folder / name).stat().st_size, "sha256": sha((folder / name).read_bytes())}
                           for name in ("output.log", "child-result.json") if (folder / name).exists()},
             "automatic_retry": False, "jobs_submitted": 0, "remote_executed": False, "ready_for_gpu": False}
    save(folder / "receipt.json", value)
    print(json.dumps(value, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
