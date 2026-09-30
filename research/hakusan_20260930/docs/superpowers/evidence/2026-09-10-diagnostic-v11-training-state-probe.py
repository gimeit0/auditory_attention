"""Identify the real non-eval modules without changing any training flag."""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "4143df86f71c69de37b1ae99813d6ad405dd962ec72552996571847e5694bbf9"
MANIFEST_SHA = "2e72c2dccda2a50980a097581b7b43da8f6502147ac97ced335b5e8fcd55ea01"


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v11_training_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v11"
    module.MANIFEST = module.MANIFEST.with_name("v11-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v11")
    anchor = '                require(not any(diag._direct_module_training_state(item[1]) for item in inventory), "non-eval module")'
    if module.REMOTE.count(anchor) != 1:
        raise SystemExit("STOP: original eval assertion differs")
    inspect = """
                standard = {id(child) for child in model.modules()}
                bad = []
                for name, child, _, _ in inventory:
                    if not diag._direct_module_training_state(child):
                        continue
                    namespace = vars(child)
                    bad.append({
                        "path": name,
                        "type": type(child).__module__ + "." + type(child).__qualname__,
                        "training": namespace["training"],
                        "in_registered_model_tree": id(child) in standard,
                        "parameters": [{"name": key, "requires_grad": value.requires_grad} for key, value in diag._native_registry_items(namespace["_parameters"]) if value is not None],
                        "buffers": [{"name": key, "shape": list(value.shape), "requires_grad": value.requires_grad} for key, value in diag._native_registry_items(namespace["_buffers"]) if value is not None],
                    })
                event("exact_non_eval_modules", inventory_entries=len(inventory), unique_modules=len({id(item[1]) for item in inventory}), registered_modules=len(standard), modules=bad, flags_changed=False, forward_executed=False)
""".rstrip()
    module.REMOTE = module.REMOTE.replace(anchor, inspect + "\n" + anchor)
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
