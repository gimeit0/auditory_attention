"""Independent offline source/artifact/count review; no execution of candidates."""
import ast
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACKAGE = ROOT / "docs/superpowers/prototypes/guard_scan_integration_20260915"
MANIFEST_SHA = "93508d886b6608dcdb31a4d84e7a033716cfb53fa80e62cb019743f18aeb28bd"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v19"
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v18"
EXPECTED_GROUPS = {"identity": 15, "freeze_relation": 15, "reference": 17,
                   "lifecycle": 25, "preparation": 18, "compiled": 16,
                   "cuda_structure": 30, "archive": 38}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected, size=None):
    require(path.is_file() and not path.is_symlink(), "regular artifact required: " + str(path))
    raw = path.read_bytes()
    require(digest(raw) == expected and (size is None or len(raw) == size), "artifact differs: " + str(path))
    return raw


def contained(root, name):
    require(type(name) is str and not Path(name).is_absolute() and ".." not in Path(name).parts,
            "unsafe artifact path")
    path = root / name
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink ancestor")
    return path


def main():
    require(len(sys.argv) == 2, "one completed local evidence directory required")
    folder = Path(sys.argv[1]).resolve(strict=True)
    require(folder.parent == HERE and folder.name.startswith("scan-integration-local-"), "wrong evidence scope")
    manifest_raw = read(PACKAGE / "SOURCE_MANIFEST.json", MANIFEST_SHA)
    manifest = json.loads(manifest_raw)
    require(len(manifest["files"]) == 44 and len(manifest["parent_files"]) == 89, "source inventory count differs")
    require(manifest["candidate_input_freeze_sha256"] is None and not manifest["ready_for_gpu"]
            and not manifest["submission_authorized"] and not manifest["gpu_job_entry_integrated"], "scope differs")
    for group in ("files", "parent_files"):
        for name, expected in manifest[group].items():
            read(contained(ROOT, name), expected)
    read(PACKAGE / "build_release.py", manifest["recipe_sha256"])
    receipt_raw = (folder / "receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    require(receipt["status"] == "LOCAL_INTEGRATION_VERIFIED" and receipt["sources_unchanged"]
            and receipt["parents_unchanged"] and receipt["parent_files"] == manifest["parent_files"], "receipt is not a pass")
    require(receipt["jobs_submitted"] == 0 and not receipt["remote_executed"] and not receipt["ready_for_gpu"]
            and not receipt["gpu_job_entry_integrated"] and not receipt["automatic_retry"], "execution scope differs")
    require(len(receipt["sources"]) == 50, "local harness/source inventory incomplete")
    for name, expected in receipt["sources"].items():
        read(contained(ROOT, name), expected)
    require(all(receipt["sources"][name] == expected for name, expected in manifest["files"].items()), "candidate source binding differs")
    for name, record in receipt["artifacts"].items():
        require(Path(name).name == name, "nested evidence not permitted")
        read(contained(folder, name), record["sha256"], record["size"])
    records, processes = receipt["groups"], receipt["processes"]
    core_names = {"core_" + Path(name).stem for name in manifest["files"]
                  if Path(name).parent.name == NEW.name and Path(name).name.startswith("test_")}
    expected_names = core_names | set(EXPECTED_GROUPS)
    require(len(core_names) == 23 and len(expected_names) == 31 and set(records) == set(processes) == expected_names,
            "independent process groups incomplete")
    require(len({p["pid"] for p in processes.values()}) == 31, "cold process IDs are not distinct")
    require(set(receipt["artifacts"]) == {name + suffix for name in expected_names for suffix in (".log", ".json")},
            "logs/results incomplete")
    for name in expected_names:
        record, process = records[name], processes[name]
        require(json.loads((folder / (name + ".json")).read_bytes()) == record, "group result differs")
        require(process["error"] is None and process["returncode"] == 0 and record["pid"] == process["pid"], "child did not exit normally")
        require(record["status"] == "PASS" and record["tests"] == record["discovered_tests"]
                and record["skipped"] == record["failures"] == record["errors"] == 0,
                "test group did not pass completely")
        require(not record["cuda_initialized"] and not record["production_model_loaded"], "not CPU-only")
        if name in EXPECTED_GROUPS:
            require(record["tests"] == record["expected_tests"] == EXPECTED_GROUPS[name], "test count differs")
    core_total = sum(records[name]["tests"] for name in core_names)
    require(core_total == receipt["core_tests"] == 751 and sum(r["tests"] for r in records.values()) == 925, "total count differs")
    # Independently compare all top-level AST statements, not just a list of
    # known scientific functions. Exactly one function may differ after versioning.
    old = (OLD / "diagnose_batch_invariance.py").read_text().replace("20260903_v18", "20260903_v19").replace("2026-09-03_v18", "2026-09-03_v19")
    before, after = ast.parse(old).body, ast.parse((NEW / "diagnose_batch_invariance.py").read_bytes()).body
    require(len(before) == len(after), "diagnostic statement count changed")
    changed = []
    for a, b in zip(before, after):
        if ast.dump(a) != ast.dump(b):
            require(isinstance(a, ast.FunctionDef) and isinstance(b, ast.FunctionDef) and a.name == b.name,
                    "non-function source changed")
            changed.append(a.name)
    require(changed == ["_live_protected_module_bindings"], "diagnostic scope expanded")
    print(json.dumps({"status": "OFFLINE_INTEGRATION_REVIEW_PASS", "tests": 925, "core_tests": 751,
                      "cold_processes": 31, "new_package_files": 44, "all_checked_sources": 50,
                      "preserved_parent_files": 89, "source_manifest_sha256": MANIFEST_SHA,
                      "receipt_sha256": digest(receipt_raw), "evidence_directory": str(folder),
                      "diagnostic_sha256": digest((NEW / "diagnose_batch_invariance.py").read_bytes()),
                      "scope": "local synthetic CPU; GPU runner/deployment/freeze still pending",
                      "jobs_submitted": 0, "ready_for_gpu": False}, sort_keys=True))


if __name__ == "__main__":
    main()
