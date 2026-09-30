"""Read-only local probe using the actual SHA-pinned v4 evaluator source."""
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v3"
spec = importlib.util.spec_from_file_location("v3_probe", PACKAGE / "diagnose_batch_invariance.py")
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)
path = ROOT / "same_bank_eval_2026_08_29_v4" / "locked_same_bank_eval.py"
payload = path.read_bytes()
assert hashlib.sha256(payload).hexdigest() == diag.V4_EVALUATOR_SHA256
trace = diag._get_trace()
evaluator = diag.load_verified_v4_evaluator(
    trace, path, len(payload), diag.V4_EVALUATOR_SHA256, allowed_root=path.parent
)
entry = diag._VERIFIED_PRODUCTION_EVALUATORS[id(evaluator)]
values = {name: getattr(evaluator, name) for name in diag.V4_EVALUATOR_WHITELIST}

def differences(a, b, where=()):
    if type(a) is type(b) and isinstance(a, (list, tuple)):
        if len(a) != len(b):
            yield {"index": where, "length_before": len(a), "length_after": len(b)}
        for i, (x, y) in enumerate(zip(a, b)):
            yield from differences(x, y, where + (i,))
    elif a != b:
        yield {"index": where, "before": repr(a)[:300], "after": repr(b)[:300]}

def compare(label):
    current = diag._callable_graphs(values, materialize_module_attributes=True)
    report = {}
    for name in values:
        delta = list(differences(entry[3][name], current[name]))
        if delta:
            report[name] = {"count": len(delta), "first": delta[:5]}
    print(json.dumps({"stage": label, "graph_differences": report,
        "anchors_match": all(diag._callable_anchor_equal(
            diag._callable_anchor(values[n]), entry[2][n]) for n in values)}, indent=2))

compare("immediate_second_read")
import pandas as pd
pd.read_csv(io.StringIO("trial_id\n1\n"), sep="\t")
compare("after_pandas_read_csv")

# Contrast a benign module-table update with an actual exposed-function swap.
# This only mutates this short-lived probe interpreter, never package files.
baseline = diag._callable_graphs(values, materialize_module_attributes=True)
probe_name = "_local_unrelated_module_probe"
assert probe_name not in sys.modules
try:
    sys.modules[probe_name] = types.ModuleType(probe_name)
    changed = diag._callable_graphs(values, materialize_module_attributes=True)
    affected = [name for name in values if baseline[name] != changed[name]]
    assert affected, "expected to reproduce module-table false positive"
    print(json.dumps({"stage": "benign_unrelated_module_insert",
                      "affected": affected, "false_positive_reproduced": True}))
finally:
    sys.modules.pop(probe_name, None)

name = "strict_load_model"
original = getattr(evaluator, name)
try:
    setattr(evaluator, name, lambda *args, **kwargs: None)
    anchor_changed = not diag._callable_anchor_equal(
        diag._callable_anchor(getattr(evaluator, name)), entry[2][name])
    assert anchor_changed, "actual function replacement must remain detectable"
    print(json.dumps({"stage": "actual_function_replacement",
                      "anchor_changed": anchor_changed}))
finally:
    setattr(evaluator, name, original)
