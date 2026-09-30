"""Bind future v19 inputs to historical v18 data WITHOUT reusing its code ID.

Pure read-only relation check, not a freeze writer, production loader, or job
authorization. The future runner must additionally perform v19's unchanged
live _load_worker_inputs/_revalidate_worker_inputs and resource checks.
"""
import copy
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PARENT = ROOT / "docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json"
PARENT_SHA = "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178"
SOURCE_MANIFEST_SHA = "93508d886b6608dcdb31a4d84e7a033716cfb53fa80e62cb019743f18aeb28bd"
PROTOCOL = "formal40_batch_invariance_diag_20260903_v19"
REMOTE = "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v19"
LOCAL = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v19"
NAMES = ("diagnose_batch_invariance.py", "numeric_trace.py", "submit_numeric_diag.py", "run_numeric_diag.sbatch")
IDENTITY = frozenset(("st_dev", "st_ino", "st_mtime_ns"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def decode(raw, expected):
    require(type(raw) is bytes and len(raw) <= 1024**2, "bounded bytes required")
    require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected), "reviewed SHA required")
    require(sha(raw) == expected, "freeze SHA differs")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    require(type(value) is dict and canonical(value) == raw, "canonical owner JSON required")
    return value


def portable_science(value):
    result = copy.deepcopy(value)
    del result["diagnostic_protocol"]
    del result["roots"]["diagnostic_root"]
    del result["production_files"]  # checked separately against the NEW source manifest
    for name in ("clips", "snapshot_files"):
        for record in result[name]:
            for key in IDENTITY:
                require(type(record[key]) is int and record[key] >= 0, "nonportable metadata is invalid")
                del record[key]
    return result


def verify(candidate_raw, expected_candidate_sha):
    candidate = decode(candidate_raw, expected_candidate_sha)
    parent = decode(PARENT.read_bytes(), PARENT_SHA)
    require(expected_candidate_sha != PARENT_SHA, "parent freeze cannot authorize new code")
    require(candidate.get("diagnostic_protocol") == PROTOCOL
            and candidate.get("status") == "INPUTS_FROZEN"
            and candidate.get("roots", {}).get("diagnostic_root") == REMOTE,
            "new diagnostic protocol/root required")
    manifest_raw = (HERE / "SOURCE_MANIFEST.json").read_bytes()
    require(sha(manifest_raw) == SOURCE_MANIFEST_SHA, "reviewed source manifest differs")
    manifest = json.loads(manifest_raw)
    require(manifest["diagnostic_protocol"] == PROTOCOL and manifest["candidate_root"] == REMOTE,
            "candidate release identity differs")
    production = candidate.get("production_files")
    require(type(production) is list and len(production) == 4, "four production files required")
    seen = set()
    for record in production:
        require(type(record) is dict and set(record) == {
            "relative_path", "mode", "size", "sha256", "st_dev", "st_ino", "st_mtime_ns"},
            "production record schema differs")
        name = record["relative_path"]
        require(type(name) is str and name in NAMES and name not in seen, "production name differs")
        seen.add(name)
        path = LOCAL / name
        require(not path.is_symlink() and path.is_file(), "regular candidate source required")
        raw = path.read_bytes()
        expected = manifest["files"][str(path.relative_to(ROOT))]
        require(sha(raw) == record["sha256"] == expected and record["size"] == len(raw)
                and type(record["size"]) is int and type(record["mode"]) is int and record["mode"] == 0o600,
                "production content/mode differs from new release")
        require(all(type(record[k]) is int and record[k] >= 0 for k in IDENTITY), "production metadata invalid")
    require(canonical(portable_science(candidate)) == canonical(portable_science(parent)),
            "frozen scientific inputs differ from historical parent")
    return {"status": "SCIENTIFIC_INPUT_RELATION_PASS", "parent_freeze_sha256": PARENT_SHA,
            "candidate_freeze_sha256": expected_candidate_sha, "candidate_protocol": PROTOCOL,
            "candidate_source_manifest_sha256": sha(manifest_raw),
            "parent_is_data_reference_only": True, "production_live_inputs_verified": False,
            "submission_authorized": False, "ready_for_gpu": False}
