"""Check the pinned v10 R2 candidate with the same real formal40 CPU probe.

Temporary source/cache transfer only; no forward, deployment, freeze or sbatch.
"""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "8b2085e17f618fce17603d8a0029f7b00d67cbc7336a7986163ef2d1e22bf2f6"
MANIFEST_SHA = "f4fe619500a9c4acfd110c20b859192d3ffc2b799337659b4a020440a257be66"


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v10_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v10"
    module.MANIFEST = module.MANIFEST.with_name("v10-r2-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v10")
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
