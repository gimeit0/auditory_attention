"""Test-only outer phase logging and a single 30s stack snapshot.

The source package remains byte-identical. Only this in-memory unit-test copy
has logging wrappers. This is diagnostic instrumentation, not a compatibility
pass or proof of numerical transparency. No model hooks or tensor access.
"""
import ast
import contextlib
import copy
import faulthandler
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import unittest

TEST_SHA = '2f35f42126e4eddfdef1c16649d626df98a870cc314d4b021427ce05341d0a35'
CALLS = frozenset({'fixture.expected_contract', 'scratch_adapter.build',
    'scratch_adapter.reference_loop', 'fixture.bridge.BaselineBridge', 'archive.PassArchive',
    'archive_adapter.PassCollector', 'stage_timing.instrument', 'exec',
    "namespace['archived_reference']", 'scratch.verify_spills', 'archive.verify_archive',
    'fixture.diag.decode_pass_evidence', 'writer.close', 'fixture.diag._revoke_attestation'})


class Recorder:
    def __init__(self, stream=None):
        self.stream = sys.stdout if stream is None else stream
        self.origin, self.cpu_origin, self.sequence = time.monotonic(), time.process_time(), 0

    def emit(self, edge, label, **fields):
        self.sequence += 1
        if self.sequence > 128:
            raise RuntimeError('outer diagnostic event limit exceeded')
        row = dict(sequence=self.sequence, pid=os.getpid(), edge=edge, label=label,
            wall=round(time.monotonic() - self.origin, 6),
            cpu=round(time.process_time() - self.cpu_origin, 6), **fields)
        self.stream.write('\nCPU_LOCATE_EVENT=' + json.dumps(row, sort_keys=True) + '\n')
        self.stream.flush()

    @contextlib.contextmanager
    def phase(self, label):
        self.emit('begin', label)
        try:
            yield
        except BaseException as exc:
            self.emit('error', label, error_type=type(exc).__name__)
            raise
        else:
            self.emit('end', label)


class TeeLog(io.StringIO):
    """Preserve getvalue/assertions; also expose existing PHASE_TIMING records."""
    def __init__(self, output=None):
        super().__init__()
        self.output = sys.stdout if output is None else output
        self.forwarded = 0

    def write(self, text):
        self.forwarded += len(text.encode())
        if self.forwarded > 256 * 1024:
            raise RuntimeError('phase mirror byte limit exceeded')
        size = super().write(text)
        self.output.write('\n' + text)
        self.output.flush()
        return size


def strip(tree):
    class Remove(ast.NodeTransformer):
        def visit_With(self, node):
            node = self.generic_visit(node)
            if (len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Call)
                    and ast.unparse(node.items[0].context_expr.func) == '_probe.phase'):
                return node.body
            return node

        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == '_probe_log':
                node.func = ast.Attribute(value=ast.Name(id='io', ctx=ast.Load()), attr='StringIO', ctx=ast.Load())
            return node
    return Remove().visit(copy.deepcopy(tree))


def instrument(tree):
    original = copy.deepcopy(tree)
    class Insert(ast.NodeTransformer):
        mirrored = 0
        wrapped = 0

        def wrap(self, node, label):
            self.wrapped += 1
            new = ast.With(items=[ast.withitem(context_expr=ast.Call(
                func=ast.Attribute(value=ast.Name(id='_probe', ctx=ast.Load()), attr='phase', ctx=ast.Load()),
                args=[ast.Constant(label)], keywords=[]))], body=[node])
            return ast.copy_location(new, node)

        def visit_Assign(self, node):
            if (ast.unparse(node.targets[0]) == 'timing_log' and isinstance(node.value, ast.Call)
                    and ast.unparse(node.value) == 'io.StringIO()'):
                node.value.func = ast.Name(id='_probe_log', ctx=ast.Load())
                self.mirrored += 1
                return node
            return self.statement(node)

        def visit_Expr(self, node):
            return self.statement(node)

        def statement(self, node):
            found = [ast.unparse(n.func) for n in ast.walk(node)
                     if isinstance(n, ast.Call) and ast.unparse(n.func) in CALLS]
            return self.wrap(node, found[0]) if found else node

        def visit_With(self, node):
            has_worker = any(isinstance(n, ast.Call) and ast.unparse(n.func) == 'fixture.worker'
                             for item in node.items for n in ast.walk(item.context_expr))
            node = self.generic_visit(node)
            return self.wrap(node, 'fixture.worker_lifetime') if has_worker else node

    edit = Insert()
    result = edit.visit(copy.deepcopy(tree))
    if edit.mirrored != 1 or edit.wrapped < 10 or ast.dump(strip(result)) != ast.dump(original):
        raise RuntimeError('instrumentation does not restore the complete original AST')
    return ast.fix_missing_locations(result), edit.wrapped


def main():
    if len(sys.argv) != 4:
        raise RuntimeError('fixed CPU diagnostic arguments required')
    root, group, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if group != 'scratch_lifetime' or mode not in ('NATIVE_CPU', 'LOCAL_HARNESS'):
        raise RuntimeError('fixed CPU diagnostic arguments required')
    if not sys.flags.isolated or not sys.dont_write_bytecode or os.environ.get('CUDA_VISIBLE_DEVICES') != '':
        raise RuntimeError('isolated CPU diagnostic required')
    if any(os.environ.get(k) != '1' for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')):
        raise RuntimeError('one-thread CPU settings required')
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    python, torch_version = sys.version.split()[0], importlib.metadata.version('torch')
    if mode == 'NATIVE_CPU' and (python != '3.11.5' or torch_version != '2.1.1+cu118' or len(affinity) != 1):
        raise RuntimeError('native CPU environment differs')
    recorder = Recorder()
    recorder.emit('environment', 'instrumented_cpu_only', mode=mode, python=python, torch=torch_version,
        cpu_affinity=affinity, jobs_submitted=0, production_model_loaded=False, stack_after_seconds=30)
    path = root / 'docs/superpowers/prototypes/targeted_gpu_job_20260915_v5/test_scratch_integration.py'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TEST_SHA:
        raise RuntimeError('original test source changed')
    tree, wrapped = instrument(ast.parse(raw, filename=str(path)))
    recorder.emit('prepared', 'original_ast_restored', wrappers=wrapped, original_test_sha256=TEST_SHA)
    module = types.ModuleType('test_scratch_integration')
    module.__file__ = str(path)
    module._probe = recorder
    module._probe_log = TeeLog
    sys.modules[module.__name__] = module
    faulthandler.dump_traceback_later(30, repeat=False, file=sys.stderr, exit=False)
    try:
        with recorder.phase('imports_and_fixture_definitions'):
            exec(compile(tree, str(path), 'exec'), vars(module))
        with recorder.phase('two_original_unit_tests'):
            suite = unittest.defaultTestLoader.loadTestsFromModule(module)
            outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        faulthandler.cancel_dump_traceback_later()
    torch = sys.modules.get('torch')
    cuda = bool(torch is not None and torch.cuda.is_initialized())
    passed = outcome.wasSuccessful() and outcome.testsRun == 2 and not outcome.skipped and not cuda
    record = dict(status='INSTRUMENTED_TESTS_FINISHED' if passed else 'INSTRUMENTED_TESTS_FAILED',
        group=group, mode=mode, pid=os.getpid(), tests=outcome.testsRun, errors=len(outcome.errors),
        failures=len(outcome.failures), skips=len(outcome.skipped), python=python, torch=torch_version,
        cpu_affinity=affinity, cuda_initialized=cuda, jobs_submitted=0, production_model_loaded=False,
        diagnostic_only=True, original_compatibility_verified=False)
    print('CPU_LOCATE_CHILD=' + json.dumps(record, sort_keys=True), flush=True)
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
