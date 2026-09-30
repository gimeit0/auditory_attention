"""Offline consistency checks for the pinned, bounded CPU profiling attempt."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FOLDER = HERE / "guard-cpu-profile-20260914T162903Z-id_7igm_"
RECEIPT_SHA = "6783152fd9c65c6ebdebd9305a61278181b5c1daac6f67dabb547a4aff83f110"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def checked(path, sha, size=None):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == sha and (size is None or len(raw) == size), str(path))
    return raw


def counts(record):
    result = {f["function"]: f["calls"] for f in record["functions"]}
    require(len(result) == len(record["functions"]), "duplicate function row")
    return result


def main():
    receipt = json.loads(checked(FOLDER / "receipt.json", RECEIPT_SHA))
    require(receipt["status"] == "LOCAL_SYNTHETIC_GUARD_PROFILE_VERIFIED" and receipt["error"] is None,
            "profile was not complete")
    require(receipt["remote_executed"] is False and receipt["jobs_submitted"] == 0
            and receipt["ready_for_gpu"] is False and receipt["frozen_sources_unchanged"] is True,
            "scope or source evidence differs")
    checked(HERE / "2026-09-15-guard-cpu-profile.py", receipt["driver_sha256"])
    release = ROOT / "docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/CONTROL_RELEASE.json"
    files = json.loads(checked(release, receipt["frozen_release_sha256"]))["files"]
    require(len(files) == 58, "release size differs")
    for relative, digest in files.items():
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "unsafe relative path")
        checked(ROOT / relative, digest)
    for name, record in receipt["artifacts"].items():
        require(Path(name).name == name, "unsafe artifact name")
        checked(FOLDER / name, record["sha256"], record["size"])
    processes, results = receipt["processes"], receipt["results"]
    require(len(processes) == len(results) == len({p["pid"] for p in processes}) == 3, "not three cold processes")
    for mode, process, result in zip(("plain", "profile", "synthetic_loader"), processes, results):
        require(mode == process["mode"] == result["mode"] and process["pid"] == result["pid"], "process identity differs")
        require(process["error"] is None and process["returncode"] == 0 and process["elapsed_seconds"] < 120,
                "process failed/exceeded deadline")
        require(result == json.loads((FOLDER / (mode + "-result.json")).read_bytes()), "child/receipt mismatch")
        require(result["cuda_initialized"] is False and result["production_model_loaded"] is False
                and result["production_snapshot_loaded"] is False and result["model_calls"] == 34,
                "fixture scope differs")
        require(result["compact_passes"] == results[0]["compact_passes"], "boundary/output evidence changed")
        require([p["batch_size"] for p in result["passes"]] == [16, 1], "schedule differs")
        for p in result["passes"]:
            n = p["batches"]
            require(n == 32 // p["batch_size"] and p["wall_seconds"] > 0, "invalid pass")
            require(p["snapshot_authority_active"] == (mode == "synthetic_loader"), "loader scope differs")
            c = counts(p)
            if mode == "plain":
                require(not c, "unexpected profiling in control")
                continue
            require(c["trace_predict_batch"] == n and c["run_trace_pass"] == 1, "operator schedule differs")
            require(c["_live_inference_attestation"] == c["_model_execution_fingerprint"] == 3 + 21 * n,
                    "live guard counts differ")
            require(c["_callable_graph_fingerprint"] == c["_verify_active_import_authority"] == 34 * (3 + 21 * n),
                    "call graph/import check counts differ")
            require(c.get("verify_runtime_bindings", 0) == (34 * (3 + 21 * n) if mode == "synthetic_loader" else 0),
                    "binding counts differ")
            require(c.get("_live_protected_module_bindings", 0) == 2 * c.get("verify_runtime_bindings", 0),
                    "before/after scan counts differ")
    regressions = (("guard-binding-regression-rv_5s2q4", "binding.log", 5),
                   ("guard-classification-regression-ixtkjifv", "classification.log", 13))
    for folder, log, expected in regressions:
        meta = json.loads((HERE / folder / "receipt.json").read_bytes())
        proc = meta["processes"][0] if "processes" in meta else meta["process"]
        require(proc["returncode"] == 0 and proc["error"] is None, "regression did not pass")
        raw = checked(HERE / folder / log, proc["log"]["sha256"], proc["log"]["size"])
        require(("Ran %s tests" % expected).encode() in raw and raw.rstrip().endswith(b"OK"), "test count/result differs")
    print(json.dumps({"status": "PROFILE_EVIDENCE_RECHECK_PASS", "frozen_sources": 58,
                      "cold_processes": 3, "original_guard_regression_tests": 18,
                      "same_recorded_boundaries_and_outputs": True,
                      "model_or_guard_source_modified": False, "jobs_submitted": 0,
                      "production_performance_verified": False, "ready_for_gpu": False}, sort_keys=True))


if __name__ == "__main__":
    main()
