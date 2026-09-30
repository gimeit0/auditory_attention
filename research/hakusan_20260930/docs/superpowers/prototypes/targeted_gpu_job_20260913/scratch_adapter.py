"""Private node-local caches while preserving the account's real HOME.

Independent candidate: original v18 scratch source and dictionaries unchanged.
Uses original spill/mmap logic and anchors, with a separate exact check type.
"""
import ast
import contextlib
import copy
import hashlib
import os
from pathlib import Path
import stat
import types

V18_SHA = "7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def build(diag):
    raw = Path(diag.__file__).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == V18_SHA, "original scratch source differs")
    original = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == "_worker_scratch")
    original_paths = diag._WORKER_WRITE_PATHS
    private_paths = types.MappingProxyType({k: v for k, v in original_paths.items() if k != "HOME"})
    require(len(private_paths) == 10 and original_paths.get("HOME") == "home", "original cache policy differs")
    home_before = os.environ.get("HOME")  # read only; NEVER assign HOME
    require(type(home_before) is str and home_before.startswith("/"), "real HOME must already be present")

    class PrivateScratch(diag._WorkerScratch):
        def check(self):
            require(type(self) is PrivateScratch, "exact candidate scratch type required")
            require(os.environ.get("HOME") == home_before, "account HOME changed")
            for anchor in self.anchors:
                anchor.check()
                info = os.fstat(anchor.fd)
                require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                        "scratch ownership/mode changed")
            for key, relative in private_paths.items():
                require(os.environ.get(key) == str(self.root / relative), "private cache environment changed: " + key)

    # The copied function's two names resolve to candidate-only objects.
    # Its body is byte/AST-identical; original module globals stay unchanged.
    tree = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(original)], type_ignores=[]))
    namespace = dict(vars(diag))
    namespace.update(_WORKER_WRITE_PATHS=private_paths, _WorkerScratch=PrivateScratch)
    exec(compile(tree, "<private-scratch-preserve-home>", "exec"), namespace)
    require(diag._WORKER_WRITE_PATHS is original_paths, "original scratch globals changed")

    @contextlib.contextmanager
    def scope(args, role):
        require(diag._WORKER_WRITE_PATHS is original_paths and os.environ.get("HOME") == home_before,
                "scratch entry policy changed")
        with namespace["_worker_scratch"](args, role) as scratch:
            require(type(scratch) is PrivateScratch, "scratch factory type differs")
            scratch.record.update(candidate_home_policy="real_HOME_preserved__private_cache_variables_only")
            yield scratch
        require(os.environ.get("HOME") == home_before, "scratch exit changed HOME")

    return PrivateScratch, scope, private_paths


def reference_loop(archive_adapter, scratch_type):
    """Only substitute exact private scratch type in the old production guard.

This changed scratch authority is explicit; no assertion is removed. Removing
the name substitution restores the previously verified archive-loop AST.
"""
    tree, audit = archive_adapter.derive("reference")
    restored = copy.deepcopy(tree)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, value in enumerate(node.comparators):
                if isinstance(value, ast.Attribute) and ast.unparse(value) == "diag._WorkerScratch":
                    node.comparators[i] = ast.Name(id="_private_scratch_type", ctx=ast.Load())
                    count += 1
    require(count == 1, "original exact scratch gate missing")
    back = copy.deepcopy(tree)
    for node in ast.walk(back):
        if isinstance(node, ast.Compare):
            for i, value in enumerate(node.comparators):
                if isinstance(value, ast.Name) and value.id == "_private_scratch_type":
                    node.comparators[i] = ast.Attribute(value=ast.Name(id="diag", ctx=ast.Load()), attr="_WorkerScratch", ctx=ast.Load())
    require(ast.dump(back) == ast.dump(restored), "reference scratch adaptation changed other logic")
    return ast.fix_missing_locations(tree), {**audit, "scratch_type_substitutions": count,
                                             "scratch_policy": "preserve_real_HOME"}
