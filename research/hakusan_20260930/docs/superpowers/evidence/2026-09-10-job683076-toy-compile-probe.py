"""Synthetic CPU-only Dynamo/import-seal probe; never a model evaluation.

Reads the pinned published v12 implementation. Temporary toy source is unrelated
to the scientific snapshot. No checkpoint, audio, CUDA, sbatch or acceptance edits.
Synthetic backends return the graph or deliberately raise. --inductor-cpu also
compiles the eight-element toy with CPU Inductor, one compiler thread/private cache.
"""

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile


DIAG_SHA = "b5cf658961739a9f9b1ae3532554ce35f28dd43d927af43534dea70928c213a4"
TRACE_SHA = "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b"


def main():
    signal.alarm(120)
    path = Path(sys.argv[1]).resolve(strict=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == DIAG_SHA
    assert (
        hashlib.sha256(path.with_name("numeric_trace.py").read_bytes()).hexdigest()
        == TRACE_SHA
    )
    spec = importlib.util.spec_from_file_location("toy_compile_diag", path)
    diag = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = diag
    spec.loader.exec_module(diag)
    import torch

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    print("TORCH_VERSION=" + torch.__version__, flush=True)
    assert not any(name == "src" or name.startswith("src.") for name in sys.modules)
    payloads = {
        "src/__init__.py": b"",
        "src/toy.py": (
            b"import torch\nclass Toy(torch.nn.Module):\n"
            b"    def forward(self, x):\n        return torch.sin(x) + 1\n"
        ),
    }

    def success_backend(graph, inputs):
        return graph.forward

    def failing_backend(graph, inputs):
        raise RuntimeError("DELIBERATE_TOY_BACKEND_FAILURE")

    with tempfile.TemporaryDirectory(prefix="job683076-toy-seal-") as scratch:
        root = Path(scratch).resolve()
        # Private synthetic compiler artifacts, never any published cache/root.
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(root / "inductor-cache")
        os.environ["TRITON_CACHE_DIR"] = str(root / "triton-cache")
        import torch._inductor.config

        torch._inductor.config.compile_threads = 1
        records = {}
        for relative, payload in payloads.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            records[relative] = {
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        cases = [
            ("success", success_backend, False),
            ("failure", failing_backend, False),
            ("orphan_success", success_backend, True),
            ("orphan_failure", failing_backend, True),
        ]
        if "--inductor-cpu" in sys.argv[2:]:
            cases.extend(
                (("inductor", "inductor", False), ("orphan_inductor", "inductor", True))
            )
        for name, backend, orphan in cases:
            torch._dynamo.reset()
            finder = diag._SnapshotLoader(root, records, diag._get_trace())
            sys.meta_path.insert(0, finder)
            try:
                module = importlib.import_module("src.toy")
                model = module.Toy().eval()
                compiled = torch.compile(model, backend=backend)
                # Emulate the evaluator's post-construction src cleanup,
                # keeping a live model with no current import-table binding.
                if orphan:
                    for key in tuple(sys.modules):
                        if key == "src" or key.startswith("src."):
                            sys.modules.pop(key)
                finder.seal_runtime_bindings()
                before = dict(finder.sealed_bindings)
                failure = None
                try:
                    result = compiled(torch.arange(8, dtype=torch.float32))
                    assert torch.allclose(
                        result, model(torch.arange(8, dtype=torch.float32))
                    )
                except Exception as error:
                    failure = error
                after = {
                    key: value
                    for key, value in sys.modules.items()
                    if key.partition(".")[0] == "src"
                }
                guard_error = None
                try:
                    finder.verify_runtime_bindings()
                except diag.DiagnosticError as error:
                    guard_error = str(error)
                inner = (
                    vars(failure).get("inner_exception")
                    if failure is not None
                    else None
                )
                print(
                    json.dumps(
                        {
                            "case": name,
                            "added_modules": sorted(set(after) - set(before)),
                            "removed_modules": sorted(set(before) - set(after)),
                            "replaced_modules": sorted(
                                key
                                for key in before.keys() & after.keys()
                                if before[key] is not after[key]
                            ),
                            "guard_error": guard_error,
                            "operator_error_type": type(failure).__name__
                            if failure
                            else None,
                            "inner_error_type": type(inner).__name__ if inner else None,
                            "inner_is_standard_cause": failure.__cause__ is inner
                            if inner
                            else None,
                            "scope": "SYNTHETIC_EIGHT_ELEMENT_CPU_NO_SCIENTIFIC_MODEL",
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                if name.endswith("failure"):
                    assert type(failure).__name__ == "BackendCompilerFailed"
                    assert type(inner) is RuntimeError
            finally:
                sys.meta_path.remove(finder)
                for key in tuple(sys.modules):
                    if key == "src" or key.startswith("src."):
                        sys.modules.pop(key)
        torch._dynamo.reset()
    print("TOY_PROBE_COMPLETE_NOT_GPU_ACCEPTANCE", flush=True)


if __name__ == "__main__":
    main()
