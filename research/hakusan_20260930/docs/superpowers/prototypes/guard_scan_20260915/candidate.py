"""Explicit test-only source overlay. Does not edit or impersonate a release."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v18/diagnose_batch_invariance.py"
PARENT_SHA = "7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b"
NAME = "_live_protected_module_bindings"


def assemble():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PARENT_SHA:
        raise RuntimeError("parent v18 source changed")
    original = raw.decode("utf-8")
    tree = ast.parse(original)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == NAME]
    if len(nodes) != 1 or nodes[0].decorator_list:
        raise RuntimeError("parent function scope differs")
    replacement_source = (HERE / "scanner.py").read_text()
    replacement_tree = ast.parse(replacement_source)
    replacements = [n for n in replacement_tree.body if isinstance(n, ast.FunctionDef)]
    if len(replacements) != 1 or replacements[0].name != NAME:
        raise RuntimeError("candidate must contain only the scanner function")
    if any(not isinstance(n, (ast.FunctionDef, ast.Expr)) for n in replacement_tree.body):
        raise RuntimeError("candidate top-level execution is not allowed")
    replacement = ast.get_source_segment(replacement_source, replacements[0])
    lines = original.splitlines(keepends=True)
    node = nodes[0]
    assembled = "".join(lines[:node.lineno - 1]) + replacement + "\n" + "".join(lines[node.end_lineno:])
    changed = ast.parse(assembled)
    without_target = lambda t: [ast.dump(n, include_attributes=False) for n in t.body
                                if not (isinstance(n, ast.FunctionDef) and n.name == NAME)]
    if without_target(tree) != without_target(changed):
        raise RuntimeError("overlay changed code outside the scanner")
    return assembled


def load(variant):
    if variant not in ("original", "candidate"):
        raise ValueError("unknown variant")
    # Fixed test-only identity in independent child processes, never bridge.load_v18.
    name = "guard_scan_local_test_evaluator"
    if name in sys.modules:
        raise RuntimeError("test evaluator already loaded")
    assembled = assemble()
    raw = SOURCE.read_text() if variant == "original" else assembled
    spec = importlib.util.spec_from_file_location(name, SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, "<guard-scan-local-test-" + variant + ">", "exec", dont_inherit=True), vars(module))
    module.LOCAL_TEST_VARIANT = variant
    return module, hashlib.sha256(raw.encode()).hexdigest()
