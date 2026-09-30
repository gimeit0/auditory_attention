"""Bounded local diagnosis of unchanged v18 guards, NOT production validation.

No SSH, sbatch, checkpoint load, CUDA inference, guard replacement, or release
edit. cProfile runs only in separate synthetic CPU processes. Cumulative
function times overlap; they must not be summed or extrapolated to the A100.
"""
import contextlib
import cProfile
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pstats
import sys
import tempfile
import time
import types

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JOB = ROOT / "docs/superpowers/prototypes/targeted_gpu_job_20260914_v4"
RELEASE = ROOT / "docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/CONTROL_RELEASE.json"
RELEASE_SHA = "abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864"
TARGETS = {"run_trace_pass", "trace_predict_batch", "_live_inference_attestation",
           "_model_execution_fingerprint", "_callable_graph_fingerprint",
           "_verify_active_import_authority", "verify_runtime_bindings",
           "_live_protected_module_bindings", "_snapshot_defined_callables",
           "_invoke_attested_operator"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sources():
    raw = RELEASE.read_bytes()
    require(sha(raw) == RELEASE_SHA, "original control release SHA differs")
    files = json.loads(raw)["files"]
    require(len(files) == 58, "original release inventory differs")
    for relative, expected in files.items():
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, "invalid release path")
        require(sha((ROOT / path).read_bytes()) == expected, "source differs: " + relative)
    return files


@contextlib.contextmanager
def synthetic_loader(diag, count):
    """Exercise ORIGINAL loader method with minimal synthetic bound modules.

    This is not the real snapshot's module set or a production capability.
    ContextVar and synthetic module installation are test setup, not a guard
    monkeypatch. Existing sys.modules objects and guard functions stay intact.
    """
    if not count:
        require(diag._ACTIVE_SNAPSHOT_AUTHORITY.get() is None, "unexpected import authority")
        yield None
        return
    names = ["_guard_cpu_profile_fixture_" + str(i) for i in range(count)]
    require(not any(n in sys.modules for n in names), "synthetic module collision")
    loader = diag._SnapshotLoader(Path("/unused-guard-profile"), {n + ".py": {} for n in names}, None)
    token = None
    try:
        sys.meta_path.insert(0, loader)
        for name in names:
            module = types.ModuleType(name)
            module.__loader__ = loader
            module.__file__ = "/unused-guard-profile/" + name + ".py"
            module.__spec__ = importlib.util.spec_from_loader(name, loader, origin=module.__file__)
            exec(compile("def function(value=1): return value\n", module.__file__, "exec"), vars(module))
            loader._bind_module(module)
            sys.modules[name] = module
        loader.seal_runtime_bindings()
        token = diag._ACTIVE_SNAPSHOT_AUTHORITY.set(loader)
        yield loader
        loader.verify_runtime_bindings()
    finally:
        if token is not None:
            diag._ACTIVE_SNAPSHOT_AUTHORITY.reset(token)
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)
        for name in names:
            sys.modules.pop(name, None)


def profile_rows(profile, diag_file):
    rows = []
    for (filename, line, name), (primitive, calls, own, cumulative, callers) in pstats.Stats(profile).stats.items():
        if filename == diag_file and name in TARGETS:
            rows.append({"function": name, "line": line, "calls": calls, "primitive_calls": primitive,
                         "self_seconds": own, "cumulative_seconds": cumulative,
                         "v18_callers": [{"function": key[2], "line": key[1], "calls": value[1]}
                                         for key, value in callers.items() if key[0] == diag_file]})
    return sorted(rows, key=lambda r: r["function"])


def child(folder, mode, runner):
    before = sources()
    fixture_path = ROOT / "docs/superpowers/prototypes/targeted_worker_20260912"
    sys.path.insert(0, str(fixture_path))
    import test_baseline_bridge as fixture
    fixture.torch.set_num_threads(1)
    diag = fixture.diag
    fixture.bridge._require_module(diag)
    count = 1 if mode == "synthetic_loader" else 0
    measured = mode != "plain"
    passes, compacts = [], []
    with fixture.worker("B2") as (run, trials, evaluator, scene):
        with synthetic_loader(diag, count) as loader:
            for pass_id, size in (("pass1", 16), ("pass2", 1)):
                print(json.dumps({"event": "PASS_BEGIN", "mode": mode, "batch_size": size}), flush=True)
                profiler = cProfile.Profile()
                started = time.perf_counter()
                if measured:
                    profiler.enable()
                try:
                    result = diag.run_trace_pass(run, trials, pass_id, size, False, Path(run["scratch_root"]))
                finally:
                    if measured:
                        profiler.disable()
                elapsed = time.perf_counter() - started
                compact = fixture.compact_pass(result)
                compacts.append(compact)
                record = {"pass_id": pass_id, "batch_size": size, "batches": 32 // size,
                          "wall_seconds": elapsed, "snapshot_authority_active": loader is not None,
                          "registry_size": len(sys.modules), "synthetic_protected_modules": count,
                          "functions": profile_rows(profiler, diag.__file__) if measured else []}
                passes.append(record)
                print(json.dumps({"event": "PASS_END", "mode": mode, "batch_size": size,
                                  "wall_seconds": elapsed}), flush=True)
        require(evaluator.calls.count("model") == 34, "expected 34 original model calls")
        require([len(c[0]) for c in scene.raw_calls] == [16, 16] + [1] * 32, "raw batch schedule differs")
        require(len(evaluator.load_calls) == 1, "model was reloaded")
    fixture.bridge._require_module(diag)
    require(before == sources(), "frozen sources changed")
    require(not fixture.torch.cuda.is_initialized(), "CUDA unexpectedly initialized")
    value = {"status": "SYNTHETIC_PROFILE_COMPLETE", "mode": mode, "pid": os.getpid(), "passes": passes,
             "compact_passes": compacts, "python": sys.version.split()[0], "torch": str(fixture.torch.__version__),
             "cprofile_enabled": measured, "model_calls": 34, "source_files_unchanged": 58,
             "production_model_loaded": False, "production_snapshot_loaded": False,
             "cuda_initialized": False, "remote_executed": False, "jobs_submitted": 0, "ready_for_gpu": False}
    runner.write_once(folder / (mode + "-result.json"), value)


def main():
    os.umask(0o077)
    before = sources()  # Check original runner/contract before importing them.
    sys.path.insert(0, str(JOB))
    import process_runner as runner
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        require(sys.argv[3] in ("plain", "profile", "synthetic_loader"), "unknown scenario")
        child(Path(sys.argv[2]), sys.argv[3], runner)
        return 0
    require(len(sys.argv) == 1, "local profiling only")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(tempfile.mkdtemp(prefix="guard-cpu-profile-" + stamp + "-", dir=HERE))
    print("EVIDENCE_DIRECTORY=" + str(folder), flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0"}
    processes, results, error = [], [], None
    driver_sha = sha(Path(__file__).read_bytes())
    started = time.monotonic()
    try:
        for mode in ("plain", "profile", "synthetic_loader"):
            remaining = 300 - (time.monotonic() - started)
            require(remaining > 0, "total profiling budget reached")
            outcome = runner.run_process([sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                                          "--child", str(folder), mode], env, folder / (mode + ".log"),
                                         seconds=min(120, remaining), max_log_bytes=2 * 1024**2)
            processes.append({"mode": mode, **outcome})
            runner.write_once(folder / (mode + "-process.json"), outcome)
            require(outcome["error"] is None and outcome["returncode"] == 0, "scenario failed: " + mode)
            value = json.loads((folder / (mode + "-result.json")).read_bytes())
            require(value["pid"] == outcome["pid"] and value["status"] == "SYNTHETIC_PROFILE_COMPLETE", "invalid child result")
            results.append(value)
        require(all(v["compact_passes"] == results[0]["compact_passes"] for v in results),
                "profiling or synthetic loader changed recorded outputs/boundaries")
        require(before == sources() and driver_sha == sha(Path(__file__).read_bytes()), "source changed during measurement")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    receipt = {"status": "LOCAL_SYNTHETIC_GUARD_PROFILE_VERIFIED" if error is None else "LOCAL_PROFILE_FAILED",
               "error": error, "processes": processes, "results": results, "frozen_release_sha256": RELEASE_SHA,
               "frozen_sources_unchanged": before == sources(), "driver_sha256": driver_sha,
               "artifacts": {p.name: runner.file_record(p) for p in folder.iterdir() if p.is_file()},
               "elapsed_seconds": time.monotonic() - started, "automatic_retry": False,
               "remote_executed": False, "jobs_submitted": 0, "ready_for_gpu": False,
               "scope": "toy CPU call counts and timing only; cumulative times overlap; not a production/A100 profile"}
    runner.write_once(folder / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "error": error,
                      "receipt": str(folder / "receipt.json"), "jobs_submitted": 0}), flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
