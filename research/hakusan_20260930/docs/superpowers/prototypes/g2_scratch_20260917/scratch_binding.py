"""G2-only scratch/bridge adapter; no submitter, model loader or GPU entry.

The fixed 20260916 bridge expects the exact old scratch type, whose environment
policy rewrites HOME. Derive an explicit new type and replace ONLY that exact
type comparison in a copy of CellBridge.run. Keep the released files unchanged.
The original spill, mount, fd, ownership and exclusive-creation checks remain.
"""
import ast
import contextlib
import copy
import os
from pathlib import Path
import sys
import types

BRIDGE_SHA = '9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d'
PROFILES = ('R', 'C', 'D', 'E')
SIDES = ('reference', 'observed')
ROLES = frozenset(p + '-' + s for p in PROFILES for s in SIDES)
NUMERIC = frozenset(('torch', 'numpy', 'pandas', 'torchaudio', 'matplotlib', 'scipy'))


def require(ok, message):
    if not ok:
        raise RuntimeError('G2 scratch: ' + message)


def cold():
    require(not any(n.partition('.')[0] in NUMERIC for n in sys.modules),
            'scratch must precede numeric imports')


def role_name(profile, side):
    require(type(profile) is str and profile in PROFILES
            and type(side) is str and side in SIDES, 'unknown profile/side')
    return profile + '-' + side


def _replace(tree, predicate, replacement):
    count = 0

    class Rewrite(ast.NodeTransformer):
        def generic_visit(self, node):
            nonlocal count
            if predicate(node):
                count += 1
                return ast.copy_location(copy.deepcopy(replacement), node)
            return super().generic_visit(node)

    tree = Rewrite().visit(tree)
    require(count == 1, 'derivation needs exactly one match, got ' + str(count))
    return ast.fix_missing_locations(tree)


def _same(node, expression):
    return ast.dump(node) == ast.dump(ast.parse(expression, mode='eval').body)


def derive(raw_diag, raw_bridge):
    """Reversible AST edits, never textual replacement of guards or inference."""
    diag_tree, bridge_tree = ast.parse(raw_diag), ast.parse(raw_bridge)
    original_factory = next(n for n in diag_tree.body
                            if isinstance(n, ast.FunctionDef) and n.name == '_worker_scratch')
    bridge_class = next(n for n in bridge_tree.body
                        if isinstance(n, ast.ClassDef) and n.name == 'CellBridge')
    original_run = next(n for n in bridge_class.body
                       if isinstance(n, ast.FunctionDef) and n.name == 'run')
    old_roles = '{"reference_cold", *CELL_SPECS}'
    old_type = 'diag._WorkerScratch'
    factory = _replace(copy.deepcopy(original_factory), lambda n: _same(n, old_roles),
                       ast.Name(id='_G2_ROLES', ctx=ast.Load()))
    factory = _replace(factory, lambda n: isinstance(n, ast.Constant)
                       and n.value == 'audattn_v4_numdiag_', ast.Constant(value='audattn_g2_'))
    run = _replace(copy.deepcopy(original_run), lambda n: _same(n, old_type),
                   ast.Name(id='_G2ScratchType', ctx=ast.Load()))
    restored = _replace(copy.deepcopy(factory), lambda n: _same(n, '_G2_ROLES'),
                        ast.parse(old_roles, mode='eval').body)
    restored = _replace(restored, lambda n: isinstance(n, ast.Constant)
                        and n.value == 'audattn_g2_', ast.Constant(value='audattn_v4_numdiag_'))
    restored_run = _replace(copy.deepcopy(run), lambda n: _same(n, '_G2ScratchType'),
                            ast.parse(old_type, mode='eval').body)
    require(ast.dump(restored) == ast.dump(original_factory)
            and ast.dump(restored_run) == ast.dump(original_run), 'unreviewed AST change')
    proof = dict(factory_changes=['role_allowlist', 'job_directory_prefix'],
                 bridge_changes=['exact_scratch_type'], reversible=True,
                 inference_body_otherwise_unchanged=True, production_ready=False)
    return factory, run, proof


class Binding:
    """One source-issued profile, one process and one exclusive scratch scope.

    Enter scope BEFORE loading numeric libraries. Only after that prepare the
    real model using the unchanged derived candidate. This is not authorization
    to run that model or a substitute for new input freeze/worker validation.
    """
    def __init__(self, bridge, diag):
        cold()
        raw_bridge = bridge.read(bridge.__file__, BRIDGE_SHA)
        bridge._check_module(diag)
        profile = diag._G2_PROFILE
        raw_diag = bridge.read(diag.__file__, bridge.CORE_SHAS[profile])
        self.bridge, self.diag, self.profile = bridge, diag, profile
        self.pid, self.home = os.getpid(), os.environ.get('HOME')
        require(type(self.home) is str and Path(self.home).is_absolute(), 'real HOME required')
        self.entered = self.active = False
        paths = diag._WORKER_WRITE_PATHS
        require(paths.get('HOME') == 'home' and len(paths) == 11, 'old write-path contract differs')
        self.paths = types.MappingProxyType({k: v for k, v in paths.items() if k != 'HOME'})
        factory, run, self.proof = derive(raw_diag, raw_bridge)
        check_tree = next(n for n in ast.parse(raw_diag).body
                          if isinstance(n, ast.ClassDef) and n.name == '_WorkerScratch')
        check = next(n for n in check_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'check')
        namespace = dict(vars(diag), _WORKER_WRITE_PATHS=self.paths)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(check)], type_ignores=[])),
                     '<g2-scratch-original-check-private-paths>', 'exec'), namespace)
        original_check = namespace['check']
        binding = self

        class PrivateScratch(diag._WorkerScratch):
            def check(self):
                require(type(self) is PrivateScratch, 'exact private scratch type required')
                binding.check()
                original_check(self)

        self.scratch_type = PrivateScratch
        namespace.update(_G2_ROLES=ROLES, _WorkerScratch=PrivateScratch)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[factory], type_ignores=[])),
                     '<g2-scratch-exclusive-factory>', 'exec'), namespace)
        self._factory = namespace['_worker_scratch']
        run_namespace = dict(vars(bridge), _G2ScratchType=PrivateScratch)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[run], type_ignores=[])),
                     '<g2-scratch-exact-type-bridge>', 'exec'), run_namespace)
        adapted_run = run_namespace['run']

        class BoundBridge(bridge.CellBridge):
            def __init__(self, candidate, *args, **kwargs):
                binding.check()
                require(candidate is diag, 'bridge uses another profile/module')
                super().__init__(candidate, *args, **kwargs)

            def run(self, *, scratch=None, cache_root=None):
                binding.check()
                require(type(scratch) is PrivateScratch and scratch is binding.scratch,
                        'bridge requires its own active scratch')
                return adapted_run(self, scratch=scratch, cache_root=cache_root)

        self.bridge_type = BoundBridge
        self._source_paths = paths
        self.scratch = None

    def check(self):
        require(self.active and os.getpid() == self.pid, 'scope closed or process changed')
        require(os.environ.get('HOME') == self.home, 'real HOME changed')
        require(self.diag._WORKER_WRITE_PATHS is self._source_paths, 'old policy replaced')
        self.bridge._check_module(self.diag)
        self.bridge.read(self.bridge.__file__, BRIDGE_SHA)

    def environment(self, parent, base, job, side):
        """Return isolated cache settings without ever assigning HOME."""
        require(type(job) is str and job.isascii() and job.isdecimal()
                and not job.startswith('0') and len(job) <= 20, 'noncanonical job')
        require(parent.get('SLURM_JOB_ID') == job and parent.get('HOME') == self.home,
                'scheduler job/HOME differs')
        base = Path(base)
        require(base.is_absolute() and '..' not in base.parts
                and base.name == 'audattn_g2_' + job, 'fixed absolute scratch parent required')
        root = base / role_name(self.profile, side)
        result = dict(parent, DIAG_SCRATCH_ROOT=str(base), PYTHONDONTWRITEBYTECODE='1',
                      PYTHONNOUSERSITE='1', PYTHONHASHSEED='0')
        result.update({k: str(root / v) for k, v in self.paths.items()})
        require(result['HOME'] == parent['HOME'], 'HOME must be unchanged')
        return result

    @contextlib.contextmanager
    def scope(self, job, freeze_sha, side):
        cold()
        require(not self.entered and os.getpid() == self.pid, 'scope is single use in its owner process')
        self.entered = True  # failed setup is not permission to retry this worker
        self.active = True
        try:
            self.check()
            args = types.SimpleNamespace(job_id=job, expected_input_freeze_sha256=freeze_sha)
            with self._factory(args, role_name(self.profile, side)) as scratch:
                self.scratch = scratch
                scratch.record.update(g2_profile=self.profile, g2_side=side,
                                      home_policy='real_HOME_preserved', derivation=self.proof)
                scratch.check()
                yield scratch
                scratch.check()
        finally:
            self.active = False
