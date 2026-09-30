"""Check the pinned v10 candidate with the same real formal40 CPU probe.

Temporary source/cache transfer only; no forward, deployment, freeze or sbatch.
"""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "5e25caf8ccc53559a916f4813d783141ae371ef228426861c9439f605b171736"
MANIFEST_SHA = "11d0aa6ecc6615d79436fa85a534413b4a1b3371541832ec8e6c22613add7524"


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v10_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v10"
    module.MANIFEST = module.MANIFEST.with_name("v10-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v10")
    original = "                fingerprint = diag._model_execution_fingerprint(model)"
    replacement = """
                budget = diag._SealBudget()
                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)
                try:
                    fingerprint = diag._model_execution_fingerprint(model)
                finally:
                    event("fingerprint_budget", work=budget.work, unique_callable_nodes=len(budget.nodes), cached_code_objects=len(budget.instructions))
                    diag._ACTIVE_SEAL_BUDGET.reset(budget_token)
""".rstrip()
    if module.REMOTE.count(original) != 1:
        raise SystemExit("STOP: probe callsite differs")
    module.REMOTE = module.REMOTE.replace(original, replacement)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
