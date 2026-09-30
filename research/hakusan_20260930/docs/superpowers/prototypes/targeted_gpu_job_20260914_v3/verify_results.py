"""Offline candidate artifact checks; never infer paper/model-comparison success."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "targeted_gpu_pair_20260913"))
import job_contract as contract  # noqa: E402
import process_runner as process  # noqa: E402
from bounded_archive import archive  # noqa: E402
import numpy as np  # noqa: E402


def inventory(root):
    root = Path(root)
    files, directories, total = {}, [], 0
    for current, dirs, names in os.walk(root, followlinks=False):
        info = Path(current).lstat()
        contract.require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                         and info.st_uid == os.getuid(), "private evidence directory required")
        for name in dirs:
            contract.require(not (Path(current) / name).is_symlink(), "evidence symlink directory")
            directories.append(str((Path(current) / name).relative_to(root)))
        for name in names:
            path = Path(current) / name
            info = path.lstat()
            contract.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                             and info.st_size <= archive.MAX_ARRAY, "evidence file type/mode/size differs")
            total += info.st_size
            contract.require(len(files) < 256 and total <= 5 * 1024**3, "evidence inventory budget exceeded")
            files[str(path.relative_to(root))] = process.file_record(path)
    contract.require(len(directories) <= 3, "extra evidence directory")
    return {"files": dict(sorted(files.items())), "directories": sorted(directories), "total_bytes": total}


def verify_captures(root, observer, parent, plan):
    ids = [t["trial_id"] for t in parent["trials"]]
    stages = [{**s, "module": "model._orig_mod." + s["module"]} for s in plan["post_hook_stages"]]
    targets = [t["trial"]["trial_id"] for t in plan["targets"]["B2"]]
    contract.require(observer["plan"] == {"trials": ids, "targets": targets, "stages": stages, "batch_sizes": [16, 1]},
                     "observed real plan differs")
    records, refs = observer["records"], observer["refs"]
    contract.require(len(records) == 34 and len(refs) == 168 and len(stages) == 42 and len(targets) == 2,
                     "complete real capture schedule required")
    contract.require(hashlib.sha256(archive.canonical(records)).hexdigest() == observer["ledger_sha256"], "observer ledger digest differs")
    expected_refs = []
    for record, (pass_id, batch, group) in zip(records, [("pass1", i // 16, ids[i:i + 16]) for i in range(0, 32, 16)]
                                            + [("pass2", i, [trial]) for i, trial in enumerate(ids)]):
        contract.require((record["pass_id"], record["batch_index"], record["trials"]) == (pass_id, batch, group), "observed batch order differs")
        for name, actual in (("cue_features", record["inputs"][0]), ("scene_features", record["inputs"][1]),
                             ("native_logits", record["logits"])):
            contract.require(actual == parent["cells"]["B2"]["passes"][pass_id]["boundaries"][name]["batches"][batch],
                             "observer endpoint differs from pinned parent")
        keys = [[pass_id, batch, index, trial] for index in range(42) for trial in group if trial in targets]
        contract.require([r["key"] for r in record["captures"]] == keys, "capture event order differs")
        expected_refs.extend(record["captures"])
    contract.require(refs == expected_refs, "capture ledger coverage differs")
    dtypes = {"torch.float16": "<f2", "torch.float32": "<f4", "torch.float64": "<f8"}
    total = 0
    for index, ref in enumerate(refs):
        contract.require(ref["ordinal"] == index and ref["store_id"] == refs[0]["store_id"]
                         and re.fullmatch(r"[0-9a-f]{32}", ref["store_id"]), "capture store identity differs")
        contract.require(ref["dtype"] in dtypes and type(ref["shape"]) is list and 1 <= len(ref["shape"]) <= 8
                         and all(type(n) is int and n > 0 for n in ref["shape"]), "capture dtype/shape differs")
        contract.require(len(ref["stride"]) == len(ref["shape"]) and all(type(n) is int and n >= 0 for n in ref["stride"]),
                         "capture stride differs")
        dtype = np.dtype(dtypes[ref["dtype"]])
        contract.require(type(ref["size"]) is int and 0 < ref["size"] <= 128 * 1024**2
                         and ref["size"] == math.prod(ref["shape"]) * dtype.itemsize, "capture byte size differs")
        total += ref["size"]
        contract.require(total <= 2 * 1024**3, "capture total budget exceeded")
        path = Path(root) / "captures" / f"{index:08d}.bin"
        contract.require(process.file_record(path) == {"size": ref["size"], "sha256": ref["sha256"]}, "capture bytes differ")
        # Separate full bounded finite-value scan, never modify or cast values.
        with path.open("rb") as stream:
            while True:
                raw = stream.read(1024**2)
                if not raw:
                    break
                contract.require(bool(np.isfinite(np.frombuffer(raw, dtype=dtype)).all()), "nonfinite capture")
    return {"capture_records": 168, "capture_bytes": total}


def verify_child(root, child_process, *, role, job, package_sha, nonce, diag, parent):
    root = Path(root)
    before = inventory(root)
    result = json.loads(contract.pinned_read(root / "CHILD.json"))
    expected = {"status": "GPU_CHILD_CANDIDATE_COMPLETE", "role": role, "job_id": job,
                "worker_pid": child_process["pid"], "package_sha256": package_sha, "pair_nonce": nonce,
                "input_sha256": contract.FREEZE_SHA, "cell": "B2", "production_model_loaded": True,
                "cuda_initialized": True, "input_checks_unchanged": True, "error": None,
                "cleanup_errors": [], "hooks_removed": True}
    contract.require(all(type(result.get(k)) is type(v) and result[k] == v for k, v in expected.items()), "child identity/completion differs")
    software = json.loads(contract.pinned_read(root / "ENVIRONMENT.json"))
    contract.require(software["worker_pid"] == child_process["pid"] and software["slurm_job_id"] == job
                     and software["python"] == "3.11.5" and software["torch"] == "2.1.1+cu118"
                     and "A100" in software["gpu_name"], "actual worker environment differs")
    contract.require(contract.pinned_read(root / "PRECHECK.json") == contract.pinned_read(root / "POSTCHECK.json"), "input postcheck differs")
    binding = {"pair_nonce": nonce, "role": role, "pid": child_process["pid"], "cell": "B2",
               "input_sha256": contract.FREEZE_SHA, "package_sha256": package_sha}
    arrays = archive.verify_archive(root / "arrays", result["lifetime"]["archive"], binding, parent)
    previous = None
    for part in arrays["passes"]:
        decoded = diag.decode_pass_evidence(part["original_pass_evidence"])
        payload = decoded["payload"]
        contract.require(payload["trial_ids"] == part["trial_ids"] and payload["pass_id"] == part["pass_id"]
                         and payload["batch_size"] == part["batch_size"], "original pass identity differs")
        metadata = payload["boundaries"]["metadata"]
        contract.require(metadata["runtime"] == parent["cells"]["B2"]["passes"][part["pass_id"]]["runtime"]
                         and metadata["autocast_enabled"] is False, "frozen runtime differs")
        attestation = metadata["attestation"]
        contract.require(metadata["worker_pid"] == child_process["pid"] == attestation["worker_pid"]
                         and attestation["trust_domain"] == "production"
                         and metadata["worker_nonce"] == attestation["worker_nonce"]
                         and metadata["model_nonce"] == attestation["model_nonce"]
                         and metadata["load_report_sha256"] == attestation["load_report_sha256"],
                         "original worker provenance differs")
        if previous is not None:
            old = previous["boundaries"]["metadata"]
            contract.require(all(old[k] == metadata[k] for k in ("worker_pid", "worker_nonce", "model_nonce", "attestation")),
                             "worker identity changed between passes")
        for name, array in decoded["outputs"].items():
            record = part["official_outputs"][name]
            contract.require(list(array.shape) == record["shape"] and array.dtype.str == record["dtype"]
                             and hashlib.sha256(array.tobytes(order="C")).hexdigest() == record["sha256"],
                             "decoded official output differs from archived bytes")
        for family in ("model_snapshots", "rng_snapshots"):
            contract.require(payload[family]["before"] == payload[family]["after"], "state/RNG changed within pass")
            if previous is not None:
                contract.require(previous[family]["after"] == payload[family]["before"], "state/RNG reset between passes")
        for name in archive.COARSE + archive.DERIVED:
            source = payload["boundaries"][name] if name in archive.COARSE else payload["boundaries"]["derived"][name]
            expected_array = part["boundaries"][name]
            dtype = {"torch.float16": "<f2", "torch.float32": "<f4", "torch.int64": "<i8", "torch.bool": "|b1"}
            contract.require(source["aggregate"]["sha256"] == expected_array["sha256"]
                             and source["aggregate"]["shape"] == expected_array["shape"]
                             and dtype[source["aggregate"]["dtype"]] == expected_array["dtype"], "original committed array differs")
        previous = payload
    capture = None
    expected_names = {"STARTED.json", "CHILD.json", "PRECHECK.json", "POSTCHECK.json", "ENVIRONMENT.json",
                      "arrays/manifest.json", *(f"arrays/{i:03d}.bin" for i in range(40))}
    expected_dirs = ["arrays"]
    if role == "observed":
        observer = json.loads(contract.pinned_read(root / "OBSERVER.json"))
        plan = json.loads(contract.pinned_read(contract.WORKSPACE / contract.PLAN))
        capture = verify_captures(root, observer, parent, plan)
        expected_names |= {"PREPARATION.json", "OBSERVER.json", *(f"captures/{i:08d}.bin" for i in range(168))}
        expected_dirs += ["captures"]
    contract.require(set(before["files"]) == expected_names and before["directories"] == expected_dirs, "child artifact coverage differs")
    contract.require(inventory(root) == before, "artifacts changed during verification")
    return {"arrays": (root / "arrays", result["lifetime"]["archive"], binding), "inventory": before,
            "software": software, "capture": capture, "original_pass_commitments_verified": True}
