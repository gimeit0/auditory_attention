"""Reviewed, reversible integration into pinned gpu_child.run, not a submit CLI.

Derive a candidate function without editing the previously deployed package.
Only startup/import ordering, scratch binding and startup-stack cleanup change.
Callers must use a separately reviewed NEW deployment/manifest/authorization.
"""
import ast
import copy
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD_ENTRY = HERE.parent / "targeted_gpu_job_20260913/gpu_child.py"
OLD_SHA = "021f81b4cf5b051b69b13b5c28224cae40c9053db205c1400e3058bef0af828a"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def statement(source):
    return ast.parse(source).body[0]


def derive():
    raw = OLD_ENTRY.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == OLD_SHA, "old GPU entry differs")
    original = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == "run")
    changed = copy.deepcopy(original)
    numeric = next(i for i, n in enumerate(changed.body) if isinstance(n, ast.Import)
                   and any(a.name == "cuda_registration" for a in n.names))
    # Two adjacent search-path statements plus the three exact numeric imports.
    block = changed.body[numeric - 2:numeric + 3]
    require([ast.unparse(n) for n in block] == [
        "sys.path.insert(0, str(HERE.parent / 'targeted_production_preparation_20260913'))",
        "sys.path.insert(0, str(HERE.parent / 'targeted_gpu_pair_20260913'))",
        "import cuda_registration as cuda", "import archive_adapter", "from bounded_archive import archive"],
        "numeric import block differs")
    del changed.body[numeric - 2:numeric + 3]
    attempt = next(n for n in changed.body if isinstance(n, ast.Try))
    changed.body.insert(changed.body.index(attempt), statement("startup_stack = _startup_contextlib.ExitStack()"))
    attempt.body[:0] = [statement("startup_lease = startup_stack.enter_context(_startup.open_scratch(contract, role))"), *block]
    old_binding = "scratch_type, scope, _ = scratch_adapter.build(diag)"
    replacements = [n for n in attempt.body if isinstance(n, ast.Assign) and ast.unparse(n) == old_binding]
    require(len(replacements) == 1, "original scratch binding differs")
    bind_index = attempt.body.index(replacements[0])
    attempt.body[bind_index] = statement("scratch_type, scope, _ = _startup.bind_scope(startup_lease, diag, cuda.bridge)")
    cleanup = next(n for n in attempt.finalbody if isinstance(n, ast.For) and ast.unparse(n.target) == "item")
    require(ast.unparse(cleanup.iter) == "(request, lease, writer, store)", "original cleanup tuple differs")
    cleanup.iter.elts.append(ast.Name(id="startup_stack", ctx=ast.Load()))

    # Undo precisely those edits and compare EVERY AST field to the pinned run.
    restored = copy.deepcopy(changed)
    restored.body = [n for n in restored.body if ast.unparse(n) != "startup_stack = _startup_contextlib.ExitStack()"]
    restore_try = next(n for n in restored.body if isinstance(n, ast.Try))
    restored_block = restore_try.body[1:6]
    del restore_try.body[:6]
    index = next(i for i, n in enumerate(restore_try.body) if isinstance(n, ast.Assign)
                 and ast.unparse(n).startswith("scratch_type, scope, _ ="))
    restore_try.body[index] = statement(old_binding)
    restore_cleanup = next(n for n in restore_try.finalbody if isinstance(n, ast.For) and ast.unparse(n.target) == "item")
    restore_cleanup.iter.elts.pop()
    restored.body[numeric - 2:numeric - 2] = restored_block
    require(ast.dump(restored) == ast.dump(original), "startup adaptation changed unrelated execution logic")
    tree = ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[]))
    return tree, {"original_entry_sha256": OLD_SHA, "original_run_ast_restored_exactly": True,
                  "scratch_before_numeric_imports": True, "numeric_import_errors_inside_failure_handler": True,
                  "startup_stack_cleaned_after_writer_and_store": True,
                  "scientific_runtime_or_tolerances_changed": False}


def bind(namespace, startup):
    """Explicit integration seam; no executable CLI, scheduler or GPU launch."""
    import contextlib
    tree, audit = derive()
    copied = {**namespace, "_startup": startup, "_startup_contextlib": contextlib}
    exec(compile(tree, "<gpu-child-scratch-first-candidate>", "exec"), copied)
    return copied["run"], audit
