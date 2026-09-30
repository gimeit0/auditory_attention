"""Read-only local reproduction; never print environment contents or run a model."""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import torch


WORKSPACE = Path(__file__).resolve().parents[3]
DIAGNOSTIC = (
    WORKSPACE
    / "same_bank_eval_2026_09_03_v4_numeric_diag_v8/diagnose_batch_invariance.py"
)
MODEL = Path("/Users/gigi/projects/auditory_attention/src/spatial_attn_lightning.py")
DATASET = Path(
    "/Users/gigi/projects/auditory_attention/selftrain/data/diotic_attention.py"
)
PINS = {
    DIAGNOSTIC: "6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182",
    MODEL: "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9",
    DATASET: "26b5cf965aec1652f2d77be517f867bb284a2f53c2f53706b2c5aa2cc0ad9e8a",
}
payloads = {}
for path, digest in PINS.items():
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AssertionError(f"source SHA differs: {path.name}")
    payloads[path] = raw
model_tree = ast.parse(payloads[MODEL])
binding = next(
    node
    for node in ast.walk(model_tree)
    if isinstance(node, ast.Assign)
    and isinstance(node.value, ast.Name)
    and node.value.id == "DioticAttentionDataset"
    and any(
        isinstance(target, ast.Attribute) and target.attr == "dataset"
        for target in node.targets
    )
)
dataset_class = next(
    node
    for node in ast.parse(payloads[DATASET]).body
    if isinstance(node, ast.ClassDef) and node.name == "DioticAttentionDataset"
)
init = next(
    node
    for node in dataset_class.body
    if isinstance(node, ast.FunctionDef) and node.name == "__init__"
)
assignment = next(
    node
    for node in init.body
    if isinstance(node, ast.Assign)
    and ast.dump(node)
    == ast.dump(ast.parse('clips_dir = os.environ.get("CV_CLIPS", clips_dir)').body[0])
)
fixture = ast.parse(
    "class SourceEnvFixture:\n    def __init__(self, clips_dir=None):\n        pass\n"
)
fixture.body[0].body[0].body = [assignment]
namespace = {"__name__": "job680910_source_fixture", "os": os}
# Define the class only: its constructor and environ.get are never invoked.
exec(compile(ast.fix_missing_locations(fixture), str(DATASET), "exec"), namespace)
fixture_class = namespace["SourceEnvFixture"]
spec = importlib.util.spec_from_file_location("job680910_diagnostic", DIAGNOSTIC)
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)


def observe(call):
    try:
        call()
    except diag.DiagnosticError as error:
        return {"accepted": False, "error": str(error)}
    return {"accepted": True}


results = {
    "plain_dict": observe(
        lambda: diag._container_execution_identity({"synthetic": "value"})
    ),
    "mapping_proxy": observe(
        lambda: diag._container_execution_identity(types.MappingProxyType({}))
    ),
    "environ_object": observe(lambda: diag._container_execution_identity(os.environ)),
    "source_constructor_graph": observe(
        lambda: diag._callable_graph_fingerprint(fixture_class)
    ),
}
module = torch.nn.Module()
module.dataset = fixture_class
results["module_with_source_constructor"] = observe(
    lambda: diag._module_config_fingerprint(module)
)
assert results["plain_dict"]["accepted"] and results["mapping_proxy"]["accepted"]
expected = "unsupported execution mapping type: path=root.class[__init__].resolved[os.environ]; type=os._Environ"
for name in ("source_constructor_graph", "module_with_source_constructor"):
    assert results[name] == {"accepted": False, "error": expected}, results[name]
assert not results["environ_object"]["accepted"]
print(
    json.dumps(
        {
            "status": "LOCAL_MAPPING_COMPATIBILITY_FAILURE_REPRODUCED",
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "diagnostic_sha256": PINS[DIAGNOSTIC],
            "model_source_sha256": PINS[MODEL],
            "dataset_source_sha256": PINS[DATASET],
            "model_dataset_binding_line": binding.lineno,
            "dataset_environment_read_line": assignment.lineno,
            "results": results,
            "limits": [
            "No environment contents dumped or altered; fixture environ.get is never invoked.",
                "Only the source-derived minimal class is defined; constructor is never called.",
                "No full model, checkpoint, audio, GPU inference or remote calls.",
                "No implementation fix, published candidate edits, freeze or submission.",
                "Matching error does not prove the unique remote owning class or absence of later errors.",
            ],
        },
        indent=2,
    )
)
