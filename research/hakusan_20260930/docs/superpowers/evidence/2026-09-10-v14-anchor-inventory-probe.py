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
    new_sha = "0f54b2db7fa51af244f953e62b7eaee46f4b9618ab0f2f6c4312e85f1bee5f7e"
    module.SOURCES["diagnose_batch_invariance.py"] = new_sha
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v14"
    module.MANIFEST = module.MANIFEST.with_name("v14-candidate-manifest.sha256")
    module.MANIFEST_SHA = (
        "022ca5b14069a37e46f05e8e0cf23f2718ddaca17ca0cfa9fa814417e196ae35"
    )
    module.REMOTE = module.REMOTE.replace(old_sha, new_sha).replace("v9", "v14")
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
                rows = []
                budget = diag._SealBudget()
                token = diag._ACTIVE_SEAL_BUDGET.set(budget)
                try:
                    for name, issued in sorted(authority.issued_modules.items()):
                        current = [item for item in issued if item[0] is sys.modules.get(name)]
                        selected = current[0] if current else issued[0]
                        for member, value in selected[3].items():
                            before = budget.work
                            diag._callable_anchor(value)
                            first_work = budget.work - before
                            before = budget.work
                            diag._callable_anchor(value)
                            second_work = budget.work - before
                            function = diag._callable_function(value)
                            defaults = diag._callable_metadata(function, "__defaults__")
                            keywords = diag._callable_metadata(function, "__kwdefaults__")
                            rows.append({"module": name, "member": member, "first_work": first_work, "repeat_work": second_work, "defaults_type": type(defaults).__name__, "kwdefaults_type": type(keywords).__name__})
                finally:
                    diag._ACTIVE_SEAL_BUDGET.reset(token)
                event("anchor_cost_inventory", callable_entries=len(rows), repeat_work_total=sum(row["repeat_work"] for row in rows), highest_cost=sorted(rows, key=lambda row: row["repeat_work"], reverse=True)[:30])
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
