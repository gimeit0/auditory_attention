"""Cold subprocess integration checks; CPU fixtures only, never SSH or Slurm."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import build_release as recipe

JOB = ROOT / "docs/superpowers/prototypes/targeted_gpu_job_20260914_v4"
PROCESS_SHA = "17de3782532bd2c2908a43dbea722c369fdd236833af66e17eb382a4fa4559f9"
recipe.read(JOB / "process_runner.py", PROCESS_SHA)
sys.path.insert(0, str(JOB))
import process_runner as runner

CORE_NAMES = tuple(p.stem for p in sorted(recipe.NEW.glob("test_*.py")))
recipe.require(len(CORE_NAMES) == 23, "complete v19 core test inventory required")
GROUPS = {
    **{"core_" + name: (recipe.NEW, [name], None) for name in CORE_NAMES},
    "identity": (HERE, ["test_integration"], 15),
    "freeze_relation": (HERE, ["test_freeze_relation"], 15),
    "reference": (recipe.PROTO / "targeted_worker_20260915_scan", ["test_baseline_bridge"], 17),
    "lifecycle": (recipe.PROTO / "targeted_lifecycle_20260915_scan", ["test_observer_lifecycle"], 25),
    "preparation": (recipe.PROTO / "targeted_preparation_20260915_scan", ["test_prepare_registration"], 18),
    "compiled": (recipe.PROTO / "targeted_compiled_20260915_scan", ["test_compiled_registration"], 16),
    "cuda_structure": (recipe.PROTO / "targeted_production_preparation_20260915_scan", ["test_cuda_registration"], 30),
    "archive": (recipe.PROTO / "targeted_gpu_pair_20260915_scan", ["test_pair_archive", "test_reference_integration"], 38),
}


def current_sources():
    files, manifest = recipe.recipe()
    for path, raw in files.items():
        recipe.require(path.read_bytes() == raw, "candidate changed: " + str(path))
    recipe.require(json.loads((HERE / "SOURCE_MANIFEST.json").read_bytes()) == manifest, "manifest changed")
    paths = list(files) + [HERE / n for n in ("SOURCE_MANIFEST.json", "build_release.py", "test_integration.py",
                                             "validate_local.py", "freeze_relation.py", "test_freeze_relation.py")]
    return {str(p.relative_to(ROOT)): recipe.sha(p.read_bytes()) for p in paths}, manifest


def child(group, folder):
    directory, names, expected = GROUPS[group]
    sys.path.insert(0, str(directory))
    # Match the historical runner's per-file process isolation. Several core
    # tests deliberately own the same private loader names; merged discovery
    # would test namespace collisions instead of the release's behavior.
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
    discovered = suite.countTestCases()
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    # Never introduce a numerical import AFTER tests which temporarily replace
    # torch module bindings. Some core tests are stdlib-only. Read only modules
    # already present, and get the installed version via package metadata.
    torch_module = sys.modules.get("torch")
    cuda_module = sys.modules.get("torch.cuda")
    cuda_initialized = cuda_module.is_initialized() if cuda_module is not None else False
    passed = (outcome.wasSuccessful() and not outcome.skipped and discovered == outcome.testsRun
              and (expected is None or outcome.testsRun == expected) and not cuda_initialized)
    record = {"status": "PASS" if passed else "FAIL", "group": group, "tests": outcome.testsRun,
              "expected_tests": expected, "discovered_tests": discovered, "skipped": len(outcome.skipped),
              "failures": len(outcome.failures), "errors": len(outcome.errors), "pid": os.getpid(),
              "python": sys.version.split()[0], "torch": importlib.metadata.version("torch"),
              "torch_imported": torch_module is not None,
              "cuda_initialized": cuda_initialized, "production_model_loaded": False,
              "scope": "local synthetic CPU only; not HAKUSAN/A100/Inductor or production integration"}
    runner.write_once(folder / (group + ".json"), record)
    print(json.dumps(record, sort_keys=True), flush=True)
    return 0 if passed else 2


def main():
    os.umask(0o077)
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        return child(sys.argv[2], Path(sys.argv[3]))
    recipe.require(len(sys.argv) == 1, "one full local validation only")
    before, manifest = current_sources()
    folder = Path(tempfile.mkdtemp(prefix="scan-integration-local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-",
                                   dir=ROOT / "docs/superpowers/evidence"))
    print("INTEGRATION_EVIDENCE=" + str(folder), flush=True)
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    def execute(name):
        result = runner.run_process([sys.executable, "-I", "-B", str(HERE / "validate_local.py"),
                                     "--child", name, str(folder)], env, folder / (name + ".log"), seconds=240)
        print("GROUP_FINISHED=" + name + " rc=" + str(result["returncode"]), flush=True)
        return name, result
    # Two local CPUs at most; every group has a fresh interpreter and 240s cap.
    with ThreadPoolExecutor(max_workers=2) as pool:
        processes = dict(pool.map(execute, GROUPS))
    unchanged = current_sources()[0] == before
    records = {name: json.loads((folder / (name + ".json")).read_bytes())
               for name in GROUPS if (folder / (name + ".json")).is_file()}
    core_total = sum(r["tests"] for name, r in records.items() if name.startswith("core_"))
    passed = (unchanged and set(records) == set(GROUPS) and core_total == 751
              and all(p["returncode"] == 0 and p["error"] is None for p in processes.values())
              and all(r["status"] == "PASS" and r["pid"] == processes[name]["pid"] for name, r in records.items()))
    receipt = {"status": "LOCAL_INTEGRATION_VERIFIED" if passed else "LOCAL_INTEGRATION_FAILED",
               "sources": before, "sources_unchanged": unchanged, "parent_files": manifest["parent_files"],
               "parents_unchanged": True, "core_tests": core_total, "groups": records, "processes": processes,
               "artifacts": {p.name: runner.file_record(p) for p in folder.iterdir() if p.is_file()},
               "remote_executed": False, "jobs_submitted": 0, "ready_for_gpu": False,
               "gpu_job_entry_integrated": False, "automatic_retry": False}
    runner.write_once(folder / "receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "tests": sum(r["tests"] for r in records.values()),
                      "receipt": str(folder / "receipt.json"), "jobs_submitted": 0, "ready_for_gpu": False}, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
