"""Bounded synthetic timing only; no real model, GPU, remote access or edits.

Used while Job683837 runs, to characterize repeated Python binding work.
Not a production timing measurement or release authority.
"""

import cProfile
import hashlib
import importlib.util
from pathlib import Path
import pstats
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v17/diagnose_batch_invariance.py"
SHA = "f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86"
if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SHA:
    raise RuntimeError("v17 source differs")
SPEC = importlib.util.spec_from_file_location("v17_binding_microprofile", SOURCE)
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
SPEC.loader.exec_module(DIAG)


def main():
    names = ["_v17_synthetic_binding_" + str(i) for i in range(10)]
    extra = ["_v17_unprotected_profile_" + str(i) for i in range(4000)]
    if any(name in sys.modules for name in names + extra):
        raise RuntimeError("synthetic namespace occupied")
    loader = DIAG._SnapshotLoader(Path("/unused"), {n+".py": {} for n in names}, None)
    registered = {}
    token = DIAG._ACTIVE_SEAL_BUDGET.set(DIAG._SealBudget())
    try:
        for name in names:
            module = types.ModuleType(name)
            module.__loader__ = loader
            module.__file__ = "/unused/" + name + ".py"
            module.__spec__ = importlib.util.spec_from_loader(name, loader, origin=module.__file__)
            lines = [f"def function_{i}(value=1): return value" for i in range(15)]
            for i in range(5):
                lines.extend([f"class Class_{i}:",
                              "    def method(self, value=(1, 2)): return value",
                              "    @property", "    def value(self): return 1"])
            exec("\n".join(lines), vars(module))
            loader._bind_module(module)
            registered[name] = module
            sys.modules[name] = module
        for name in extra:
            registered[name] = types.ModuleType(name)
            sys.modules[name] = registered[name]
        sys.meta_path.insert(0, loader)
        loader.seal_runtime_bindings()
        count = sum(len(records[0][3]) for records in loader.issued_modules.values())
        started = time.perf_counter()
        for _ in range(1355):
            loader.verify_runtime_bindings()
        elapsed = time.perf_counter() - started
        print(f"SYNTHETIC_BINDINGS={count} ITERATIONS=1355 SECONDS={elapsed:.6f}")
        profile = cProfile.Profile()
        profile.enable()
        for _ in range(1355):
            loader.verify_runtime_bindings()
        profile.disable()
        pstats.Stats(profile, stream=sys.stdout).strip_dirs().sort_stats("cumtime").print_stats(20)
        print("SCOPE=SYNTHETIC_PYTHON_BINDINGS_NOT_GPU_OR_FORMAL40_TIMING")
    finally:
        DIAG._ACTIVE_SEAL_BUDGET.reset(token)
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)
        for name, module in registered.items():
            if sys.modules.get(name) is module:
                del sys.modules[name]
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SHA:
        raise RuntimeError("v17 source changed during probe")


if __name__ == "__main__":
    main()
