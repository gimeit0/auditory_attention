"""Experimental module-registry policy, NOT a production replacement.

Run in an isolated process. It patches only its private diagnostic module.
Full frozen-import lifecycle coverage is required before production use.
"""
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v3"
spec = importlib.util.spec_from_file_location("registry_policy_experiment", PACKAGE / "diagnose_batch_invariance.py")
diag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diag
spec.loader.exec_module(diag)
trace = diag._get_trace()
original_identity = diag._container_execution_identity
registry = sys.modules
initial_bindings = dict(registry)
# Experimental only: production must derive protected names from frozen inventory.
protected_tops = {"src", "selftrain", "corpus"}

def identity(value, *args, **kwargs):
    if value is registry:
        names = set(initial_bindings)
        names.update(n for n in registry if n.partition(".")[0] in protected_tops)
        return ("registry-policy-experiment", id(registry), tuple(
            (name, id(registry.get(name))) for name in sorted(names)))
    return original_identity(value, *args, **kwargs)

diag._container_execution_identity = identity
path = ROOT / "same_bank_eval_2026_08_29_v4" / "locked_same_bank_eval.py"
payload = path.read_bytes()
assert hashlib.sha256(payload).hexdigest() == diag.V4_EVALUATOR_SHA256
facade = diag.load_verified_v4_evaluator(
    trace, path, len(payload), diag.V4_EVALUATOR_SHA256, allowed_root=path.parent)
values = {n: getattr(facade, n) for n in diag.V4_EVALUATOR_WHITELIST}
baseline = diag._VERIFIED_PRODUCTION_EVALUATORS[id(facade)][3]

def graph():
    return diag._callable_graphs(values, materialize_module_attributes=True)

def report(name, passed):
    print(json.dumps({"check": name, "pass": passed}), flush=True)
    assert passed, name

report("real_loader_cleanup_allowed", graph() == baseline)
import pandas as pd
pd.read_csv(io.StringIO("trial_id\n1\n"), sep="\t")
report("pandas_import_allowed", graph() == baseline)
name = "_unrelated_policy_fixture"
try:
    assert name not in registry
    registry[name] = types.ModuleType(name)
    report("unrelated_module_allowed", graph() == baseline)
finally:
    registry.pop(name, None)
name = "selftrain._unauthorized_policy_fixture"
try:
    assert name not in registry
    registry[name] = types.ModuleType(name)
    report("protected_insertion_detected", graph() != baseline)
finally:
    registry.pop(name, None)
original = registry["json"]
try:
    registry["json"] = types.ModuleType("json")
    report("existing_module_replacement_detected", graph() != baseline)
finally:
    registry["json"] = original
original = values["strict_load_model"]
try:
    values["strict_load_model"] = lambda *a, **k: None
    report("function_replacement_detected", graph() != baseline)
finally:
    values["strict_load_model"] = original
report("restoration_matches", graph() == baseline)
