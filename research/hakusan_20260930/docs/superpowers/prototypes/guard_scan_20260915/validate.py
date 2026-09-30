"""Bounded local candidate tests and A/B timing; no remote/GPU capability."""
import cProfile
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / "docs/superpowers/evidence"
sys.path.insert(0, str(HERE))
import candidate


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def dependencies():
    source = EVIDENCE / "2026-09-15-guard-cpu-profile.py"
    require(hashlib.sha256(source.read_bytes()).hexdigest() ==
            "b34d51a3d5f48887341eb7625a42dfbfb9c3f23793cb36182192471f1cf60e8e", "profile helper changed")
    profile = load(source, "unchanged_profile_helper")
    profile.sources()
    sys.path.insert(0, str(profile.JOB))
    import process_runner as runner
    return profile, runner


def local_sources():
    paths = list(HERE.glob("*.py")) + [candidate.SOURCE.with_name(n + ".py")
                                     for n in ("test_binding_scan", "test_module_name_classification")]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def fixture_for(diag):
    sys.path.insert(0, str(ROOT / "docs/superpowers/prototypes/targeted_worker_20260912"))
    import test_baseline_bridge as fixture
    # Only hermetic fixture setup is redirected. Production bridge rejects diag.
    fixture.diag = diag
    fixture.fixture.diagnose = diag
    fixture.torch.set_num_threads(1)
    return fixture


def microbenchmark(diag):
    import test_scanner
    original = test_scanner.original_scanner(diag)
    rows = []
    for count in (2048, 8192):
        registry = {"src.x": object(), **{"unprotected_" + str(i): object() for i in range(count - 1)}}
        times = {"original": [], "candidate": []}
        for repeat in range(6):
            order = ("original", "candidate") if repeat % 2 == 0 else ("candidate", "original")
            for variant in order:
                function = original if variant == "original" else diag._live_protected_module_bindings
                with test_scanner.scan_context(diag, registry, diag._SealBudget()):
                    require(set(function({"src"})) == {"src.x"}, "warm-up result differs")
                    started = time.perf_counter()
                    for _ in range(800):
                        result = function({"src"})
                    elapsed = time.perf_counter() - started
                    require(result["src.x"] is registry["src.x"] and len(result) == 1, "scan result differs")
                times[variant].append(elapsed)
        medians = {variant: statistics.median(t) for variant, t in times.items()}
        rows.append({"registry_keys": count, "scans_per_repeat": 800, "repeats": 6, "cprofile": False,
                     "timings_seconds": times, "medians_seconds": medians,
                     "speedup": medians["original"] / medians["candidate"]})
    return rows


def child(folder, label, profile, runner):
    variant = "original" if label.startswith("original") else "candidate"
    diag, source_sha = candidate.load(variant)
    fixture = fixture_for(diag)
    record = {"status": "LOCAL_CANDIDATE_FAILED", "label": label, "variant": variant, "pid": os.getpid(),
              "assembled_sha256": source_sha, "production_model_loaded": False,
              "production_snapshot_loaded": False, "jobs_submitted": 0, "ready_for_gpu": False,
              "python": sys.version.split()[0], "torch": str(fixture.torch.__version__)}
    if label == "tests":
        import test_scanner
        result = unittest.TextTestRunner(verbosity=2).run(test_scanner.make_suite(diag, fixture))
        require(result.wasSuccessful() and result.testsRun == 28 and not result.skipped, "candidate tests failed")
        record.update(tests=28, skips=0, microbenchmark=microbenchmark(diag))
    else:
        measured = label.endswith("profile")
        passes, compacts = [], []
        with fixture.worker("B2") as (run, trials, evaluator, scene):
            with profile.synthetic_loader(diag, 1):
                for pass_id, size in (("pass1", 16), ("pass2", 1)):
                    print(json.dumps({"event": "PASS_BEGIN", "label": label, "batch_size": size}), flush=True)
                    profiler = cProfile.Profile()
                    start = time.perf_counter()
                    if measured:
                        profiler.enable()
                    try:
                        output = diag.run_trace_pass(run, trials, pass_id, size, False, Path(run["scratch_root"]))
                    finally:
                        if measured:
                            profiler.disable()
                    elapsed = time.perf_counter() - start
                    compacts.append(fixture.compact_pass(output))
                    passes.append({"batch_size": size, "wall_seconds": elapsed, "registry_size": len(sys.modules),
                                   "functions": profile.profile_rows(profiler, "<guard-scan-local-test-" + variant + ">")
                                   if measured else []})
                    print(json.dumps({"event": "PASS_END", "label": label, "batch_size": size,
                                      "wall_seconds": elapsed}), flush=True)
                require(evaluator.calls.count("model") == 34 and len(evaluator.load_calls) == 1, "lifetime differs")
                require([len(c[0]) for c in scene.raw_calls] == [16, 16] + [1] * 32, "raw schedule differs")
        record.update(cprofile=measured, passes=passes, compact_passes=compacts, model_calls=34)
    require(not fixture.torch.cuda.is_initialized(), "unexpected CUDA initialization")
    record.update(status="LOCAL_CANDIDATE_TEST_COMPLETE", cuda_initialized=False)
    runner.write_once(folder / (label + "-result.json"), record)


def main():
    os.umask(0o077)
    profile, runner = dependencies()
    before, new_before = profile.sources(), local_sources()
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3], profile, runner)
        require(before == profile.sources() and new_before == local_sources(), "sources changed in child")
        return 0
    require(len(sys.argv) == 1, "local validation only")
    folder = Path(tempfile.mkdtemp(prefix="guard-scan-candidate-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-", dir=EVIDENCE))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0"}
    started, processes, results, error = time.monotonic(), [], [], None
    # A/B/B/A unprofiled timing; separate profiled children are for call counts.
    labels = ("tests", "original_1", "candidate_1", "candidate_2", "original_2", "original_profile", "candidate_profile")
    summary = {}
    try:
        for label in labels:
            remaining = 480 - (time.monotonic() - started)
            require(remaining > 0, "total deadline reached")
            process = runner.run_process([sys.executable, "-I", "-B", str(HERE / "validate.py"), "--child", str(folder), label],
                                         env, folder / (label + ".log"), seconds=min(120, remaining), max_log_bytes=2 * 1024**2)
            processes.append({"label": label, **process})
            runner.write_once(folder / (label + "-process.json"), process)
            require(process["error"] is None and process["returncode"] == 0, "child failed: " + label)
            value = json.loads((folder / (label + "-result.json")).read_bytes())
            require(value["pid"] == process["pid"] and value["status"] == "LOCAL_CANDIDATE_TEST_COMPLETE", "invalid child result")
            results.append(value)
        require(len({p["pid"] for p in processes}) == len(processes), "cold PID reused")
        require(all(v["compact_passes"] == results[1]["compact_passes"] for v in results[1:]), "output/boundary mismatch")
        profiled = {v["variant"]: v for v in results if v.get("cprofile")}
        for i in range(2):
            counts = [{f["function"]: f["calls"] for f in profiled[v]["passes"][i]["functions"]} for v in ("original", "candidate")]
            require(counts[0] == counts[1], "candidate changed guard/operator call counts")
        for i, size in enumerate((16, 1)):
            timings = {v: [r["passes"][i]["wall_seconds"] for r in results if r["variant"] == v and r.get("cprofile") is False]
                       for v in ("original", "candidate")}
            medians = {v: statistics.median(t) for v, t in timings.items()}
            summary[str(size)] = {"unprofiled_seconds": timings, "medians_seconds": medians,
                                  "speedup": medians["original"] / medians["candidate"]}
        require(before == profile.sources() and new_before == local_sources(), "sources changed")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "LOCAL_SCAN_CANDIDATE_VERIFIED" if error is None else "LOCAL_SCAN_CANDIDATE_FAILED",
               "error": error, "processes": processes, "results": results, "summary": summary,
               "new_sources": new_before, "new_sources_unchanged": new_before == local_sources(),
               "frozen_sources_unchanged": before == profile.sources(), "frozen_release_sha256": profile.RELEASE_SHA,
               "artifacts": {p.name: runner.file_record(p) for p in folder.iterdir() if p.is_file()},
               "remote_executed": False, "jobs_submitted": 0, "automatic_retry": False, "ready_for_gpu": False,
               "scope": "local synthetic candidate only; no production equivalence/performance validation"}
    runner.write_once(folder / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "error": error, "summary": summary,
                      "receipt": str(folder / "receipt.json")}), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
