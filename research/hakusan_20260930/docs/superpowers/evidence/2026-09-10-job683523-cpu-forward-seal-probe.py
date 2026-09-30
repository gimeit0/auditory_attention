"""Synthetic CPU Dynamo forward/guard diagnostic, never the scientific model."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tempfile

REMOTE = "--remote" in sys.argv
COMPILED = "--native" not in sys.argv
if REMOTE:
    DIAG = Path(
        "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v15/tools/diagnose_batch_invariance.py"
    )
else:
    ROOT = Path(__file__).resolve().parents[3]
    DIAG = (
        ROOT
        / "same_bank_eval_2026_09_03_v4_numeric_diag_v15/diagnose_batch_invariance.py"
    )
SHA = "993d89b6c97f706cb7bc1e1f6dc8b27d2c608e7866fb5b4cbef316ddcb389cca"


def changed_paths(left, right, limit=12):
    changes = []
    visited = 0

    def walk(a, b, path, label, heads=()):
        nonlocal visited
        visited += 1
        if visited > 600_000 or len(changes) >= limit:
            return
        if type(a) is not type(b):
            changes.append({"indices": path, "label": label, "kind": "type"})
            return
        if type(a) in (tuple, list):
            if a and type(a[0]) is str and len(a[0]) <= 200:
                heads = (*heads, a[0])[-12:]
            if a and type(a[0]) is str and a[0].startswith("root"):
                label = a[0][:200]
            if len(a) != len(b):
                keyed = all(
                    type(item) is tuple and item and type(item[0]) is str
                    for item in (*a, *b)
                )
                aa = {item[0] for item in a} if keyed else set()
                bb = {item[0] for item in b} if keyed else set()
                changes.append(
                    {
                        "indices": path,
                        "label": label,
                        "kind": "length",
                        "schema_heads": heads,
                        "before_len": len(a),
                        "after_len": len(b),
                        "added_keys": sorted(bb - aa)[:12],
                        "removed_keys": sorted(aa - bb)[:12],
                    }
                )
                return
            for index, (aa, bb) in enumerate(zip(a, b)):
                walk(aa, bb, path + [index], label, heads)
        elif a != b:
            changes.append({"indices": path, "label": label, "kind": "scalar_record"})

    walk(left, right, [], "")
    return changes


def main():
    if REMOTE:
        assert socket.gethostname().split(".")[0] == "hakusan1"
        assert sys.version_info[:3] == (3, 11, 5)
        assert sys.flags.isolated and sys.dont_write_bytecode
        signal.alarm(120)
    assert hashlib.sha256(DIAG.read_bytes()).hexdigest() == SHA
    with tempfile.TemporaryDirectory(
        prefix="audattn-forward-guard-", dir="/tmp" if REMOTE else None
    ) as temporary:
        previous = {}
        for key in (
            "MPLCONFIGDIR",
            "XDG_CACHE_HOME",
            "TORCHINDUCTOR_CACHE_DIR",
            "TRITON_CACHE_DIR",
            "CUDA_CACHE_PATH",
        ):
            previous[key] = os.environ.get(key)
            path = Path(temporary) / key.lower()
            path.mkdir(mode=0o700)
            os.environ[key] = str(path)
        try:
            import torch

            assert not torch.cuda.is_available()
            if REMOTE:
                assert str(torch.__version__) == "2.1.1+cu118"
            torch.set_num_threads(1)
            torch._dynamo.reset()
            spec = importlib.util.spec_from_file_location("forward_guard_diag", DIAG)
            diag = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = diag
            spec.loader.exec_module(diag)

            class Toy(torch.nn.Module):
                def forward(self, x):
                    return x.sin() + 1

            model = Toy().eval()
            if COMPILED:
                model = torch.compile(model, backend="eager")

            def compiler_observation():
                if not REMOTE or not COMPILED:
                    return None
                # Fixed installed PyTorch 2.1.1 API, not a production guard.
                # No environment, weights, or arbitrary global values are printed.
                from torch._dynamo import eval_frame, utils

                on_enter = model.dynamo_ctx.on_enter
                closure = dict(
                    zip(on_enter.__code__.co_freevars, on_enter.__closure__ or ())
                )
                compiler = closure["compiler_fn"].cell_contents
                return {
                    "most_recent_backend_is_none": eval_frame.most_recent_backend
                    is None,
                    "most_recent_backend_is_this_compiler": eval_frame.most_recent_backend
                    is compiler,
                    "counter_groups": len(utils.counters),
                    "counter_entries": sum(
                        len(value) for value in utils.counters.values()
                    ),
                }

            compiler_before = compiler_observation()
            graph = diag._callable_graphs(
                {"forward": model.forward}, materialize_module_attributes=True
            )
            before = diag._callable_graphs(
                {"forward": model.forward}, materialize_module_attributes=False
            )
            assert graph == before
            full = None
            if REMOTE:
                inventory = diag._direct_model_module_inventory(model)
                full = diag._materialized_model_execution_fingerprint(model, inventory)
                assert full == diag._model_execution_fingerprint(model, inventory)
            values = torch.arange(8, dtype=torch.float32)
            with torch.inference_mode():
                output = model(values)
            assert torch.equal(output, values.sin() + 1)
            after = diag._callable_graphs(
                {"forward": model.forward}, materialize_module_attributes=False
            )
            full_after = (
                diag._model_execution_fingerprint(model, inventory) if REMOTE else None
            )
            compiler_after = compiler_observation()
            # Repeating the tiny forward is a control only. Never rebase the
            # production attestation to any of these snapshots.
            with torch.inference_mode():
                output_second = model(values)
            assert torch.equal(output_second, values.sin() + 1)
            full_second = (
                diag._model_execution_fingerprint(model, inventory) if REMOTE else None
            )
            print(
                json.dumps(
                    {
                        "torch": str(torch.__version__),
                        "scope": "SYNTHETIC_CPU_8_ELEMENTS_TWO_FORWARDS",
                        "compiled_backend": "dynamo_eager" if COMPILED else None,
                        "numerics_equal": True,
                        "forward_graph_unchanged": graph == after,
                        "changes": changed_paths(graph["forward"], after["forward"]),
                        "scientific_model_used": False,
                        "full_model_guard_unchanged": full == full_after
                        if REMOTE
                        else None,
                        "full_model_changes": changed_paths(full, full_after)
                        if REMOTE
                        else [],
                        "second_forward_model_guard_unchanged": full_after
                        == full_second
                        if REMOTE
                        else None,
                        "second_forward_changes": changed_paths(full_after, full_second)
                        if REMOTE
                        else [],
                        "compiler_observation_before": compiler_before,
                        "compiler_observation_after": compiler_after,
                        "compiler_observation_second": compiler_observation(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    main()
