"""Reproducible, exclusive mechanical fork; never edits a frozen input.

Default is read-only verification. --create materializes only absent, explicitly
listed new files. This is NOT an upload, freeze, or submission command.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PROTO = ROOT / "docs/superpowers/prototypes"
OLD = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v18"
NEW = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v19"
OLD_MANIFEST = ROOT / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v18-candidate-manifest.sha256"
OLD_MANIFEST_SHA = "bcd7d3e5bb776323d2b3975791962418893a3fa1746905dd3719563925f77e72"
OLD_CONTROL = PROTO / "targeted_gpu_control_20260914_v4/CONTROL_RELEASE.json"
OLD_CONTROL_SHA = "abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864"
SCANNER = PROTO / "guard_scan_20260915/scanner.py"
SCANNER_SHA = "afb98f56aa2e17716ddc6ab52a2a684a7b345c78d63d9268cc0ce149577202d1"
TARGET = "_live_protected_module_bindings"
DIRECTORIES = {
    "targeted_worker_20260912": "targeted_worker_20260915_scan",
    "targeted_lifecycle_20260912": "targeted_lifecycle_20260915_scan",
    "targeted_preparation_20260912": "targeted_preparation_20260915_scan",
    "targeted_compiled_20260912": "targeted_compiled_20260915_scan",
    "targeted_real_registration_20260913": "targeted_real_registration_20260915_scan",
    "targeted_production_preparation_20260913": "targeted_production_preparation_20260915_scan",
    "targeted_gpu_pair_20260913": "targeted_gpu_pair_20260915_scan",
}
EXTRA = {
    "targeted_lifecycle_20260912/test_observer_lifecycle.py": "7e3bb5db6f45933be8d4dfef2c3feeb3428718170345d01f7b267e0bcee8f385",
    "targeted_preparation_20260912/test_prepare_registration.py": "bb844d0122b0acc381e4acf2f5b73e709d6449520140877d2b800a996fbb43d8",
    "targeted_compiled_20260912/test_compiled_registration.py": "236eaeda6d67587c663ccc81fe503cd36057bbb5d98c03def84de1fc322c936e",
}
# Topological order is intentional: every changed child pin is known before its
# importing parent is produced. The historical array matcher and plan stay old.
ORDER = (
    "targeted_worker_20260912/baseline_bridge.py",
    "targeted_worker_20260912/test_baseline_bridge.py",
    "targeted_lifecycle_20260912/observer_lifecycle.py",
    "targeted_lifecycle_20260912/test_observer_lifecycle.py",
    "targeted_preparation_20260912/prepare_registration.py",
    "targeted_preparation_20260912/test_prepare_registration.py",
    "targeted_compiled_20260912/compiled_registration.py",
    "targeted_compiled_20260912/test_compiled_registration.py",
    "targeted_real_registration_20260913/admission.py",
    "targeted_real_registration_20260913/probe_cpu.py",
    "targeted_real_registration_20260913/test_admission.py",
    "targeted_production_preparation_20260913/cuda_registration.py",
    "targeted_production_preparation_20260913/test_cuda_registration.py",
    "targeted_gpu_pair_20260913/pass_archive.py",
    "targeted_gpu_pair_20260913/archive_adapter.py",
    "targeted_gpu_pair_20260913/test_pair_archive.py",
    "targeted_gpu_pair_20260913/test_reference_integration.py",
)


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected):
    require(path.is_file() and not path.is_symlink(), "not a regular source: " + str(path))
    raw = path.read_bytes()
    require(sha(raw) == expected, "source SHA differs: " + str(path))
    return raw


def scanner_delta(text):
    replacement = read(SCANNER, SCANNER_SHA).decode()
    node = next(n for n in ast.parse(replacement).body if isinstance(n, ast.FunctionDef) and n.name == TARGET)
    segment = ast.get_source_segment(replacement, node)
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == TARGET]
    require(len(nodes) == 1 and not nodes[0].decorator_list, "scanner definition differs")
    before = ast.parse(text)
    lines, old = text.splitlines(keepends=True), nodes[0]
    result = "".join(lines[:old.lineno - 1]) + segment + "\n" + "".join(lines[old.end_lineno:])
    omit = lambda tree: [ast.dump(n) for n in tree.body
                         if not (isinstance(n, ast.FunctionDef) and n.name == TARGET)]
    require(omit(before) == omit(ast.parse(result)), "non-scanner AST changed")
    return result


def version(text):
    return text.replace("20260903_v18", "20260903_v19").replace("2026-09-03_v18", "2026-09-03_v19")


def parent_files():
    pins = {str(OLD_MANIFEST.relative_to(ROOT)): OLD_MANIFEST_SHA,
            str(OLD_CONTROL.relative_to(ROOT)): OLD_CONTROL_SHA,
            str(SCANNER.relative_to(ROOT)): SCANNER_SHA}
    for line in read(OLD_MANIFEST, OLD_MANIFEST_SHA).decode().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        require(Path(name).name == name, "unexpected parent manifest path")
        pins[str((OLD / name).relative_to(ROOT))] = digest
    pins.update(json.loads(read(OLD_CONTROL, OLD_CONTROL_SHA))["files"])
    pins.update({str((PROTO / name).relative_to(ROOT)): digest for name, digest in EXTRA.items()})
    for name, digest in pins.items():
        read(ROOT / name, digest)
    return pins


def recipe():
    inputs = parent_files()
    outputs, changes = {}, {}
    for path in sorted(OLD.iterdir()):
        if path.suffix not in (".py", ".sbatch"):
            continue
        raw = read(path, inputs[str(path.relative_to(ROOT))])
        text = version(raw.decode())
        if path.name == "diagnose_batch_invariance.py":
            text = scanner_delta(text)
        if path.name == "test_resource_limits.py":
            # Preserve all resource assertions and the historical v17→v18
            # evidence, then add the one allowed scanner delta to the expected
            # source. No equality assertion is dropped or changed to a subset.
            extra_import = ('\nimport importlib.util as _release_util\n'
                '_recipe_path = HERE.parent / "docs/superpowers/prototypes/guard_scan_integration_20260915/build_release.py"\n'
                '_recipe_spec = _release_util.spec_from_file_location("v19_release_recipe", _recipe_path)\n'
                '_recipe = _release_util.module_from_spec(_recipe_spec)\n'
                '_recipe_spec.loader.exec_module(_recipe)\n')
            text = text.replace('\n\ndef versioned(source):', extra_import + '\n\ndef versioned(source):')
            needle = '        self.assertEqual((HERE / "diagnose_batch_invariance.py").read_text(), expected)'
            require(text.count(needle) == 1, "historical scope assertion differs")
            text = text.replace(needle, '        expected = _recipe.scanner_delta(expected)\n' + needle)
        out = NEW / path.name
        outputs[out] = text.encode()
        changes[sha(raw)] = sha(outputs[out])

    for relative in ORDER:
        path = PROTO / relative
        raw = read(path, inputs[str(path.relative_to(ROOT))])
        text = raw.decode()
        for old, new in DIRECTORIES.items():
            text = text.replace(old, new)
        text = text.replace("same_bank_eval_2026_09_03_v4_numeric_diag_v18", NEW.name)
        # Source version names describe the NEW executable, not the immutable
        # historical replay.FREEZE_SHA / Job685198 data contract.
        text = text.replace("load_v18", "load_v19").replace("V18_SHA", "V19_SHA")
        text = text.replace("HERMETIC_V18_BASELINE_BRIDGE_PASS", "HERMETIC_V19_BASELINE_BRIDGE_PASS")
        text = text.replace("targeted_worker_v18_", "targeted_worker_v19_")
        text = text.replace('"v18_parent"', '"v19_scanner_candidate"')
        text = text.replace("v18 module", "v19 candidate module").replace("v18 source", "v19 candidate source")
        for old_sha, new_sha in changes.items():
            text = text.replace(old_sha, new_sha)
        if relative.endswith("/probe_cpu.py"):
            # This older remote CPU entry has a v18-only freeze contract. Keep
            # its allocation unit tests, but fail closed until a new audited
            # v19 deployment/CLI binding is provided. Never run the old entry.
            text = text.replace("def main():\n", "def main():\n    raise RuntimeError(\"v19 integration is local-only; new freeze and runner review required\")\n")
        new_dir, name = relative.split("/")
        out = PROTO / DIRECTORIES[new_dir] / name
        outputs[out] = text.encode()
        changes[sha(raw)] = sha(outputs[out])

    # Every importer in this copy must contain NEW pins for a changed file;
    # no obsolete SHA may silently direct it back to the frozen release.
    for path, raw in outputs.items():
        if path.parent == NEW:
            continue
        for old_sha, new_sha in changes.items():
            require(old_sha == new_sha or old_sha.encode() not in raw,
                    "stale source pin: " + str(path))
        if path.suffix == ".py":
            compile(raw, str(path), "exec", dont_inherit=True)
    record = {"schema_version": 1, "status": "LOCAL_INTEGRATION_CANDIDATE",
              "diagnostic_protocol": "formal40_batch_invariance_diag_20260903_v19",
              "candidate_root": "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v19",
              "parent_freeze_sha256": "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178",
              "candidate_input_freeze_sha256": None, "ready_for_gpu": False,
              "gpu_job_entry_integrated": False, "submission_authorized": False,
              "scanner_sha256": SCANNER_SHA, "recipe_sha256": sha(Path(__file__).read_bytes()),
              "parent_files": inputs,
              "files": {str(p.relative_to(ROOT)): sha(raw) for p, raw in outputs.items()}}
    return outputs, record


def main():
    require(sys.argv[1:] in ([], ["--create"]), "use no arguments or --create only")
    outputs, record = recipe()
    manifest = HERE / "SOURCE_MANIFEST.json"
    outputs[manifest] = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
    # Validate all targets before the first mutation; only this candidate's
    # explicit file set may be created, never a prior version or an arbitrary path.
    for path, raw in outputs.items():
        require(not path.is_symlink() and not any(p.is_symlink() for p in path.parents), "symlink target")
        if path.exists():
            require(path.is_file() and path.read_bytes() == raw, "existing target differs: " + str(path))
        else:
            require(sys.argv[1:] == ["--create"], "missing candidate: " + str(path))
    if sys.argv[1:] == ["--create"]:
        for path, raw in outputs.items():
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(raw)
    parent_files()
    print(json.dumps({"status": "INTEGRATION_SOURCES_EXACT", "files": len(record["files"]),
                      "manifest_sha256": sha(outputs[manifest]), "parents_unchanged": True,
                      "ready_for_gpu": False, "jobs_submitted": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
