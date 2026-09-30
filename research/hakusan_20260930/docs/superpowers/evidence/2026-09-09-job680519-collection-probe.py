"""Read-only local reproduction of a v7 seal incompatibility, not a GPU test."""

import ast
from collections import deque
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import torch


WORKSPACE = Path(__file__).resolve().parents[3]
DIAGNOSTIC = (
    WORKSPACE
    / "same_bank_eval_2026_09_03_v4_numeric_diag_v7"
    / "diagnose_batch_invariance.py"
)
MODEL_SOURCE = Path(
    "/Users/gigi/projects/auditory_attention/src/spatial_attn_lightning.py"
)
DIAGNOSTIC_SHA = "7e18242bf96be03e8e50e713be877b4a52c321c6874cb81bca2b9955db924167"
MODEL_SHA = "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9"


def verified_payload(path, expected):
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise RuntimeError(f"local source SHA mismatch: {path}")
    return payload


def observe(function):
    try:
        function()
    except diag.DiagnosticError as error:
        return {"accepted": False, "error": str(error)}
    return {"accepted": True}


verified_payload(DIAGNOSTIC, DIAGNOSTIC_SHA)
model_payload = verified_payload(MODEL_SOURCE, MODEL_SHA)
spec = importlib.util.spec_from_file_location("job680519_collection_probe", DIAGNOSTIC)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)

tree = ast.parse(model_payload)
model_class = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "BinauralAttentionModule"
)
init = next(
    node for node in model_class.body
    if isinstance(node, ast.FunctionDef) and node.name == "__init__"
)
assignment = next(
    node for node in init.body
    if isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
        and target.attr == "_amp_overflow_window"
        for target in node.targets
    )
)
expression = ast.Expression(body=assignment.value)
# Only execute the reviewed constructor expression, not the full model/module.
assert ast.dump(expression) == ast.dump(
    ast.parse("deque(maxlen=overflow_window_steps)", mode="eval")
)
window = eval(
    compile(expression, str(MODEL_SOURCE), "eval"),
    {"__builtins__": {}, "deque": deque, "overflow_window_steps": 1000},
)
assert type(window) is deque and window.maxlen == 1000 and len(window) == 0

cases = {
    "plain_list": [],
    "plain_tuple": (),
    "source_amp_overflow_window": window,
    "torch_size": torch.Size([1, 2]),
}
container_results = {
    name: observe(lambda value=value: diag._container_execution_identity(value))
    for name, value in cases.items()
}
module = torch.nn.Module()
plain_module = observe(lambda: diag._module_config_fingerprint(module))
module._amp_overflow_window = window
module_with_window = observe(lambda: diag._module_config_fingerprint(module))

assert container_results["plain_list"]["accepted"]
assert container_results["plain_tuple"]["accepted"]
assert plain_module["accepted"]
for result in (container_results["source_amp_overflow_window"], module_with_window):
    assert result == {
        "accepted": False,
        "error": "unsupported execution collection type",
    }

print(json.dumps({
    "status": "LOCAL_COMPATIBILITY_FAILURE_REPRODUCED",
    "torch_version": torch.__version__,
    "diagnostic_sha256": DIAGNOSTIC_SHA,
    "model_source_sha256": MODEL_SHA,
    "source_line": assignment.lineno,
    "attribute": "_amp_overflow_window",
    "exact_type": "collections.deque",
    "fixture_maxlen": window.maxlen,
    "containers": container_results,
    "plain_module": plain_module,
    "module_with_source_window": module_with_window,
    "limits": [
        "Local CPU diagnostic only; no checkpoint, full model or audio loaded.",
        "maxlen=1000 is a fixture value, not a reading of remote checkpoint state.",
        "No proof that this is the first or only collection rejected in Job 680519.",
        "No source patch, threshold change or remote submission.",
    ],
}, indent=2))
