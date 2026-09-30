"""Synthetic cross-module CPU Dynamo tracing, with the unchanged v13 loader.

No scientific model, weights, audio, GPU inference or Inductor compilation.
Temporary sources and process-local module mutations isolate import lifecycle.
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


DIAG = Path(
    "/home/s2510040/audattn_external_eval_diag/"
    "same_bank_v4_job646900_2026-09-03_v13/tools/diagnose_batch_invariance.py"
)
DIAG_SHA = "4fd9204bddf6291b2e5a0b2d0c797d4a883db5fb6c6fb57ddb0a7a5338b62d52"
TRACE_SHA = "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b"
SOURCES = {
    "src/__init__.py": "",
    "src/audio_transforms.py": ("def transform(x):\n    return x.sin()\n"),
    "src/custom_modules.py": (
        "from src.audio_transforms import transform\n"
        "def helper(x):\n"
        "    return transform(x) + 1\n"
    ),
    "src/toy.py": (
        "import torch\n"
        "from src.custom_modules import helper\n"
        "class Toy(torch.nn.Module):\n"
        "    def forward(self, x):\n"
        "        return helper(x)\n"
    ),
}


def main():
    assert sys.version_info[:3] == (3, 11, 5)
    assert sys.flags.isolated and sys.dont_write_bytecode
    assert hashlib.sha256(DIAG.read_bytes()).hexdigest() == DIAG_SHA
    assert (
        hashlib.sha256(DIAG.with_name("numeric_trace.py").read_bytes()).hexdigest()
        == TRACE_SHA
    )
    signal.alarm(60)
    with tempfile.TemporaryDirectory(prefix="job683154-import-probe-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        for key in ("TORCHINDUCTOR_CACHE_DIR", "TRITON_CACHE_DIR", "XDG_CACHE_HOME"):
            os.environ[key] = str(root / key.lower())
        spec = importlib.util.spec_from_file_location("isolated_v13_probe", DIAG)
        diag = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = diag
        spec.loader.exec_module(diag)
        import torch

        assert torch.__version__ == "2.1.1+cu118"
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        assert not any(key == "src" or key.startswith("src.") for key in sys.modules)
        records = {}
        for relative, source in SOURCES.items():
            payload = source.encode()
            path = root / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(payload)
            records[relative] = {
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        def trace_only_backend(graph, inputs):
            return graph.forward

        for orphan in (False, True):
            torch._dynamo.reset()
            finder = diag._SnapshotLoader(root, records, diag._get_trace())
            sys.meta_path.insert(0, finder)
            try:
                module = importlib.import_module("src.toy")
                model = torch.compile(module.Toy().eval(), backend=trace_only_backend)
                if orphan:
                    for key in tuple(sys.modules):
                        if key == "src" or key.startswith("src."):
                            sys.modules.pop(key)
                finder.seal_runtime_bindings()
                before = dict(finder.sealed_bindings)
                operator_error = None
                try:
                    result = model(torch.arange(8, dtype=torch.float32))
                    assert torch.allclose(result, torch.arange(8).sin() + 1)
                except Exception as error:
                    operator_error = type(error).__name__
                after = {
                    key: value
                    for key, value in sys.modules.items()
                    if key == "src" or key.startswith("src.")
                }
                guard_error = None
                try:
                    finder.verify_runtime_bindings()
                except diag.DiagnosticError as error:
                    guard_error = str(error)
                print(
                    json.dumps(
                        {
                            "scope": "SYNTHETIC_CROSS_MODULE_CPU_TRACE_ONLY",
                            "case": "removed_after_construction"
                            if orphan
                            else "kept_before_seal",
                            "torch": torch.__version__,
                            "operator_error_type": operator_error,
                            "guard_error": guard_error,
                            "added_modules": sorted(after.keys() - before.keys()),
                            "removed_modules": sorted(before.keys() - after.keys()),
                            "replaced_modules": sorted(
                                key
                                for key in after.keys() & before.keys()
                                if after[key] is not before[key]
                            ),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            finally:
                sys.meta_path.remove(finder)
                for key in tuple(sys.modules):
                    if key == "src" or key.startswith("src."):
                        sys.modules.pop(key)
        torch._dynamo.reset()
    signal.alarm(0)


if __name__ == "__main__":
    main()
