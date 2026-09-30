"""Bounded local regression evidence only. No SSH, deployment or scheduler."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent / "targeted_gpu_control_20260913"))
import control
sys.path.insert(0, str(HERE.parent / "targeted_gpu_job_20260913"))
import process_runner as runner
sys.path.insert(0, str(HERE))
import startup

SOURCES = ("startup.py", "entry_adapter.py", "test_startup.py", "probe_startup.py", "validate_local.py")
EXPECTED_TESTS = 15


def sources():
    raw, release, files = control.package()  # all 51 old release pins, read-only
    return {"prior_control_release_sha256": hashlib.sha256(raw).hexdigest(),
            "prior_pinned_file_count": len(files),
            "candidate_source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in SOURCES}}


def unit_child(path):
    import unittest
    import test_startup
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_startup)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and result.testsRun == EXPECTED_TESTS and not result.skipped
    runner.write_once(path, {"passed": passed, "tests": result.testsRun, "skips": len(result.skipped),
                             "pid": os.getpid(), "scope": "local stdlib lifecycle and AST integration"})
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--unit-child":
        return unit_child(Path(sys.argv[2]))
    startup.require(len(sys.argv) == 1, "local validation only")
    before = sources()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix="gpu-startup-local-" + stamp + "-", dir=ROOT / "docs/superpowers/evidence"))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
           "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    cases = [("unit", [str(HERE / "validate_local.py"), "--unit-child"])]
    cases += [(name, [str(HERE / "probe_startup.py"), mode, role]) for name, mode, role in (
        ("old-real-reference", "old-real", "reference"),
        ("old-synthetic-reference", "old-synthetic", "reference"),
        ("new-reference", "new", "reference"), ("new-observed", "new", "observed"))]
    outcomes, error, unchanged = [], None, False
    try:
        for name, command in cases:
            print("CASE_BEGIN=" + name, flush=True)
            output = folder / (name + ".json")
            run = runner.run_process([sys.executable, "-I", "-B", *command, str(output)], env,
                                     folder / (name + ".log"), seconds=90, max_log_bytes=2 * 1024**2)
            result = json.loads(output.read_bytes()) if output.is_file() else None
            outcomes.append({"case": name, "process": run, "result": result})
            startup.require(run["returncode"] == 0 and run["error"] is None and result is not None,
                            "local case failed: " + name)
            startup.require(result["pid"] == run["pid"], "fresh child result PID differs")
            if name == "unit":
                startup.require(result["passed"] and result["tests"] == EXPECTED_TESTS and result["skips"] == 0,
                                "unit suite differs")
            else:
                startup.require(result["status"] == "LOCAL_STARTUP_PROBE_PASS"
                                and not result["cuda_initialized"] and result["home_preserved"], "probe scope differs")
                if name == "old-synthetic-reference":
                    startup.require(result["collision_reproduced"], "old ordering synthetic reproduction missing")
                elif name.startswith("new-"):
                    startup.require(result["new_startup_pass"] and result["anchors_closed"]
                                    and result["caches_initially_empty"] and result["torch_absent_when_scratch_opened"],
                                    "new startup order differs")
                    if name == "new-reference":
                        startup.require(result["mmap"]["synthetic_lifetime_pass"]
                                        and result["mmap"]["archive_passes"] == 2, "original CPU mmap/archive failed")
            print("CASE_PASS=" + name, flush=True)
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    try:
        unchanged = before == sources()
        startup.require(unchanged, "pinned old or candidate source changed during validation")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "LOCAL_STARTUP_FIX_VERIFIED" if error is None else "LOCAL_STARTUP_FIX_FAILED",
               "sources": before, "sources_unchanged": unchanged, "cases": outcomes, "error": error,
               "artifacts": {p.name: runner.file_record(p) for p in sorted(folder.iterdir()) if p.is_file()},
               "automatic_retry": False, "remote_executed": False, "jobs_submitted": 0,
               "production_model_loaded": False, "ready_for_gpu": False,
               "limitation": "local torch only; Linux mount decision is an explicit test stub; no HAKUSAN/A100/Inductor validation"}
    runner.write_once(folder / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "error": error, "sources_unchanged": unchanged,
                      "jobs_submitted": 0, "ready_for_gpu": False}), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
