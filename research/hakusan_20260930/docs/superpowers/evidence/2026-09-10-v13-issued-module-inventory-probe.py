"""Inspect actual post-load issued module identities; no forward or deployment."""

import hashlib
import importlib.util
from pathlib import Path

BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")


def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == (
        "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
    )
    spec = importlib.util.spec_from_file_location("inventory_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    new_sha = "4fd9204bddf6291b2e5a0b2d0c797d4a883db5fb6c6fb57ddb0a7a5338b62d52"
    module.SOURCES["diagnose_batch_invariance.py"] = new_sha
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v13"
    module.MANIFEST = module.MANIFEST.with_name("v13-candidate-manifest.sha256")
    module.MANIFEST_SHA = (
        "9cee85c7940c0ee3e5f75aeff28f7beea2124ef3b25dd30e55a2250f6e935839"
    )
    module.REMOTE = module.REMOTE.replace(old_sha, new_sha).replace("v9", "v13")
    old = '                require(not any(diag._direct_module_training_state(item[1]) for item in inventory), "non-eval module")'
    assert module.REMOTE.count(old) == 1
    module.REMOTE = module.REMOTE.replace(
        old, "                diag._require_registered_modules_eval(model)"
    )
    start = '                stage = "materialize_model_callable_graphs"'
    end = '            stage = "post_source_check"'
    assert module.REMOTE.count(start) == module.REMOTE.count(end) == 1
    left, rest = module.REMOTE.split(start)
    _, right = rest.split(end)
    module.REMOTE = (
        left
        + """                authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
                summary = []
                for name, issued in sorted(authority.issued_modules.items()):
                    summary.append({"name": name, "issued_count": len(issued), "unique_objects": len({id(item[0]) for item in issued}), "current_issued_ordinals": [i for i, item in enumerate(issued) if sys.modules.get(name) is item[0]]})
                event("actual_post_load_issued_modules", modules=summary, forward_executed=False)
"""
        + end
        + right
    )
    module.REMOTE = module.REMOTE.replace(
        "FORMAL40_CPU_SEAL_PROBE_PASS", "ISSUED_MODULE_INVENTORY_PROBE_COMPLETE"
    )
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
