"""Expose the unmodified v10 model-snapshot exception on frozen formal40/CPU.

Temporary source/cache transfer only; no forward, deployment, freeze or sbatch.
"""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "2c3e07d218076abb27ba613556cfda4792ed7490821cbdbc43ad610788b637eb"
MANIFEST_SHA = "ca282426ebead30831fb87b22ce6de0f1fb93cf09c397a8cc1c75c41745bdee1"


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v10_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v10"
    module.MANIFEST = module.MANIFEST.with_name("v10-r3-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v10")
    snapshot_anchor = '                stage = "materialize_model_callable_graphs"'
    snapshot_step = '''
                registry_types = {}
                for _, child, _, _ in inventory:
                    for registry_name in ("_parameters", "_buffers", "_modules"):
                        value = vars(child)[registry_name]
                        label = type(value).__module__ + "." + type(value).__qualname__
                        registry_types[label] = registry_types.get(label, 0) + 1
                event("actual_formal40_registry_types", counts=registry_types)
                stage = "snapshot_frozen_formal40_state"
                entries = diag._snapshot_model_entries(model)
                event(stage, status="PASS", entries=len(entries))
'''.rstrip()
    if module.REMOTE.count(snapshot_anchor) != 1:
        raise SystemExit("STOP: snapshot insertion stage differs")
    module.REMOTE = module.REMOTE.replace(
        snapshot_anchor, snapshot_step + "\n" + snapshot_anchor
    )
    cause_anchor = '        traceback.print_exc(limit=8)'
    cause_step = '''
        cause = error.__cause__
        for index in range(5):
            if cause is None:
                break
            event("exception_cause", index=index, error_type=type(cause).__name__, message=str(cause)[:1600])
            cause = cause.__cause__
'''.rstrip()
    if module.REMOTE.count(cause_anchor) != 1:
        raise SystemExit("STOP: cause reporting stage differs")
    module.REMOTE = module.REMOTE.replace(
        cause_anchor, cause_step + "\n" + cause_anchor
    )
    original = "                fingerprint = diag._model_execution_fingerprint(model)"
    replacement = """
                budget = diag._SealBudget()
                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)
                try:
                    fingerprint = diag._model_execution_fingerprint(model)
                finally:
                    event("fingerprint_budget", work=budget.work, unique_callable_nodes=len(budget.nodes), cached_code_objects=len(budget.instructions), cached_literal_defaults=len(budget.literal_defaults))
                    diag._ACTIVE_SEAL_BUDGET.reset(budget_token)
""".rstrip()
    if module.REMOTE.count(original) != 1:
        raise SystemExit("STOP: probe callsite differs")
    module.REMOTE = module.REMOTE.replace(original, replacement)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
