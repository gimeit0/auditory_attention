"""Read-only offline verification of local candidate and native CPU receipts."""
import ast
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOCAL = HERE / "guard-scan-candidate-20260914T164836Z-e0wtqyns"
NATIVE = HERE / "scan-native-cpu-20260914T170321Z-9ft5iemx"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path, digest, size=None):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == digest and (size is None or len(raw) == size), str(path))
    return raw


def ratios(rows):
    for row in rows:
        samples = row.get("timings_seconds", row.get("unprofiled_seconds"))
        medians = {k: statistics.median(v) for k, v in samples.items()}
        require(medians == row["medians_seconds"], "medians differ")
        require(row["speedup"] == medians["original"] / medians["candidate"], "speedup differs")


def main():
    local = json.loads(read(LOCAL / "receipt.json", "47d3a9e52cbd42f8ce7a1908a4632a3ae0908aac435bc7580f5afd3c579f3a80"))
    require(local["status"] == "LOCAL_SCAN_CANDIDATE_VERIFIED" and local["error"] is None
            and local["new_sources_unchanged"] and local["frozen_sources_unchanged"], "local verification failed")
    require(local["jobs_submitted"] == 0 and not local["remote_executed"] and not local["ready_for_gpu"], "scope differs")
    for name, digest in local["new_sources"].items():
        require(not Path(name).is_absolute() and ".." not in Path(name).parts, "unsafe source path")
        read(ROOT / name, digest)
    release = ROOT / "docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/CONTROL_RELEASE.json"
    files = json.loads(read(release, local["frozen_release_sha256"]))["files"]
    require(len(files) == 58, "frozen inventory differs")
    for name, digest in files.items():
        read(ROOT / name, digest)
    for name, record in local["artifacts"].items():
        require(Path(name).name == name, "unsafe artifact path")
        read(LOCAL / name, record["sha256"], record["size"])
    results = local["results"]
    require(len(results) == len(local["processes"]) == len({p["pid"] for p in local["processes"]}) == 7, "process count differs")
    for result, process in zip(results, local["processes"]):
        require(result["pid"] == process["pid"] and result["label"] == process["label"]
                and process["returncode"] == 0 and process["error"] is None and process["elapsed_seconds"] < 120,
                "process failed or identity differs")
        require(result == json.loads((LOCAL / (result["label"] + "-result.json")).read_bytes()), "result binding differs")
        require(not result["cuda_initialized"] and not result["production_model_loaded"] and not result["production_snapshot_loaded"], "scope differs")
    require(results[0]["tests"] == 28 and results[0]["skips"] == 0, "local tests differ")
    require(all(r["compact_passes"] == results[1]["compact_passes"] for r in results[1:]), "outputs/boundaries differ")
    require([r["variant"] for r in results[1:5]] == ["original", "candidate", "candidate", "original"], "timing order differs")
    for a, b in zip(results[-2]["passes"], results[-1]["passes"]):
        a_counts = {f["function"]: f["calls"] for f in a["functions"]}
        b_counts = {f["function"]: f["calls"] for f in b["functions"]}
        require(a_counts == b_counts and a["registry_size"] == b["registry_size"], "checks changed")
        require(a_counts["_live_protected_module_bindings"] == (3060 if a["batch_size"] == 16 else 45900), "scan count differs")
    ratios(results[0]["microbenchmark"])
    ratios(local["summary"].values())
    native = json.loads(read(NATIVE / "receipt.json", "38ec2ddeafabf6641ec410dea2e2aff7d6315fc482578dc09b098666c1e57731"))
    require(native["status"] == "NATIVE_CPU_RECHECK_PASS" and native["error"] is None, "native failed")
    read(NATIVE / "request.py", native["payload_sha256"])
    log = read(NATIVE / "output.log", native["output_sha256"])
    decoded = [json.loads(s.removeprefix("NATIVE_SCAN_RESULT=")) for s in log.decode().splitlines() if s.startswith("NATIVE_SCAN_RESULT=")]
    remote = native["remote"]
    require(decoded == [remote] and remote["request_id"] == native["spec"]["request_id"], "native response binding differs")
    require(remote["assembled_sha256"] == results[0]["assembled_sha256"] and remote["source_sha256"] == native["spec"]["source_sha256"], "candidate changed")
    require(remote["tests"] == 18 and not remote["skipped"] and remote["python"] == "3.11.5"
            and remote["installed_torch"] == "2.1.1+cu118" and not remote["cuda_initialized"]
            and not remote["production_model_loaded"] and not remote["production_snapshot_loaded"]
            and not remote["remote_files_written"] and remote["jobs_submitted"] == 0, "native scope differs")
    require(native["transport"]["returncode"] == 0 and native["transport"]["error"] is None
            and native["transport"]["elapsed_seconds"] < 75, "transport failed")
    ratios(remote["timings"])
    print(json.dumps({"status": "SCAN_CANDIDATE_EVIDENCE_RECHECK_PASS", "local_tests": 28, "native_tests": 18,
                      "frozen_files_unchanged": 58, "checks_and_synthetic_outputs_unchanged": True,
                      "local_batch1_time_reduction_fraction": 1 - 1 / local["summary"]["1"]["speedup"],
                      "native_scan_speedups": [r["speedup"] for r in remote["timings"]],
                      "gpu_jobs_submitted": 0, "production_gpu_timeout_fixed": "not_yet_verified"}, sort_keys=True))


if __name__ == "__main__":
    main()
