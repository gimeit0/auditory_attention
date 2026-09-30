"""Local controller tests with pinned source and durable evidence; no SSH."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import control  # noqa: E402
import remote_ops as ops  # noqa: E402

EXPECTED_TESTS = 47


def child(folder):
    import unittest
    import test_control
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_control)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and result.testsRun == EXPECTED_TESTS and not result.skipped
    value = {"status": "LOCAL_GPU_CONTROL_TESTS_PASS" if passed else "LOCAL_GPU_CONTROL_TESTS_FAILED",
             "tests": result.testsRun, "skips": len(result.skipped), "pid": os.getpid(), "python": sys.version.split()[0],
             "scheduler": "fake", "ssh": "fake", "production_model_loaded": False, "jobs_submitted": 0,
             "remote_executed": False, "resources_authorized": False, "scope": "local controller only, no GPU validation"}
    ops.write_new(folder / "child-result.json", ops.wire(value))
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child(Path(sys.argv[2]))
    ops.require(len(sys.argv) == 1, "local validation only")
    before = control.package()
    folder = Path(tempfile.mkdtemp(prefix="gpu-control-v3-local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-",
                                  dir=control.WORKSPACE / "docs/superpowers/evidence"))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    command = [sys.executable, "-I", "-B", str(HERE / "validate_local.py"), "--child", str(folder)]
    process = control.transport(command, b"", folder, timeout=60, log_cap=4 * 1024**2)
    record, error = {}, None
    try:
        record = json.loads(ops.read(folder / "child-result.json"))
        ops.require(before == control.package() and process["returncode"] == 0 and process["error"] is None
                    and record["status"] == "LOCAL_GPU_CONTROL_TESTS_PASS" and record["tests"] == EXPECTED_TESTS
                    and record["pid"] == process["pid"]
                    and record["skips"] == 0 and record["jobs_submitted"] == 0 and record["remote_executed"] is False,
                    "local validation failed")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "LOCAL_GPU_CONTROL_VERIFIED" if error is None else "LOCAL_GPU_CONTROL_FAILED",
               "control_release_sha256": ops.sha(before[0]), "job_package_sha256": ops.PACKAGE_SHA,
               "source_files": len(before[2]), "process": process, "child": record, "error": error,
               "artifacts": {name: {"size": (folder / name).stat().st_size, "sha256": ops.sha(ops.read(folder / name))}
                             for name in ("output.log", "child-result.json") if (folder / name).exists()},
               "automatic_retry": False, "remote_executed": False, "resources_authorized": False, "jobs_submitted": 0}
    ops.write_new(folder / "receipt.json", ops.wire(receipt))
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
