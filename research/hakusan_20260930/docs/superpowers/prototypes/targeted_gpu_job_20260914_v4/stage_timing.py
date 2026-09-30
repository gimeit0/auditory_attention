"""Bounded outer phase events and one stack dump; no model hooks or tensor IO.

Times measure host call boundaries, not synchronized CUDA kernel durations.
Original v18 function objects are never changed. Logs use the supervisor's
existing bounded stdout/stderr pipe, not additional remote artifact files.
"""
import ast
import contextlib
import copy
import faulthandler
import json
import os
import sys
import time

CALLS = frozenset({'self._live', 'scratch.check', 'diag.run_trace_pass', 'scratch.spill',
                  'self._consume', 'scratch.verify_spills', '_archiver.before', '_archiver.capture',
                  '_archiver.after', 'self.gate.finish', 'authority.verify', 'writer.finish',
                  'diag._load_worker_inputs', 'diag.prepare_formal40_worker', 'cuda.prepare_production',
                  'cuda.bridge.BaselineBridge', 'diag._revalidate_worker_inputs', 'diag.audit_inputs',
                  'lifetime', "namespace['archived_reference']", "namespace['archived_observed']",
                  'gate._live', 'gate._consume', 'gate.diag.run_trace_pass', 'gate.gate.finish',
                  'lease.check', 'lease.verify_pass'})


class Recorder:
    def __init__(self, stream=None, limit=512):
        if type(limit) is not int or not 2 <= limit <= 512:
            raise ValueError('bounded event limit required')
        self.stream = stream
        self.limit, self.count, self.origin = limit, 0, time.monotonic()

    def emit(self, event, label, **fields):
        if self.count >= self.limit:
            raise RuntimeError('phase event limit reached')
        self.count += 1
        row = {'sequence': self.count, 'pid': os.getpid(), 'event': event, 'phase': label,
               'elapsed_seconds': round(time.monotonic() - self.origin, 6),
               'cpu_seconds': round(time.process_time(), 6), **fields}
        raw = 'PHASE_TIMING=' + json.dumps(row, sort_keys=True, allow_nan=False)
        if len(raw.encode()) > 8192:
            raise RuntimeError('phase event byte budget reached')
        stream = sys.stdout if self.stream is None else self.stream
        stream.write(raw + '\n')
        stream.flush()

    @contextlib.contextmanager
    def phase(self, label, pass_id=None, batch_size=None):
        if label not in CALLS or pass_id not in (None, 'pass1', 'pass2') or batch_size not in (None, 1, 16):
            raise ValueError('unreviewed phase identity')
        fields = {'pass_id': pass_id, 'batch_size': batch_size}
        self.emit('begin', label, **fields)
        try:
            yield
        except BaseException as exc:
            self.emit('error', label, error_type=type(exc).__name__, **fields)
            raise
        else:
            self.emit('end', label, **fields)

    @contextlib.contextmanager
    def watchdog(self):
        # One dump at 40 min, before the unchanged 50 min process deadline.
        # The existing supervisor caps combined logs at 8 MiB and stops overflow.
        faulthandler.dump_traceback_later(2400, repeat=False, file=sys.stderr, exit=False)
        try:
            yield
        finally:
            faulthandler.cancel_dump_traceback_later()


def strip(tree):
    class Strip(ast.NodeTransformer):
        def visit_With(self, node):
            node = self.generic_visit(node)
            if (len(node.items) == 1 and isinstance(node.items[0].context_expr, ast.Call)
                    and ast.unparse(node.items[0].context_expr.func) == '_timing.phase'):
                return node.body
            return node
    return Strip().visit(copy.deepcopy(tree))


def instrument(tree, *, loop=False):
    """Wrap only outer statements, preserving calls/returns and their order."""
    original = copy.deepcopy(tree)
    class Insert(ast.NodeTransformer):
        count = 0
        def wrap(self, node):
            found = [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)
                     and ast.unparse(n.func) in CALLS]
            if not found:
                return node
            self.count += 1
            args = [ast.Constant(found[0])]
            if loop:
                # Outside the loop pass_id is unbound (or its last value); use
                # only calls that are actually nested in the fixed pass loop.
                args += [ast.Constant(None), ast.Constant(None)]
            return ast.With(items=[ast.withitem(context_expr=ast.Call(
                func=ast.Attribute(value=ast.Name(id='_timing', ctx=ast.Load()), attr='phase', ctx=ast.Load()),
                args=args, keywords=[]))], body=[node])
        visit_Assign = wrap
        visit_Expr = wrap
        visit_Return = wrap
    transform = Insert()
    new = transform.visit(copy.deepcopy(tree))
    if loop:
        for node in ast.walk(new):
            if (isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
                    and ast.unparse(node.target) == '(pass_id, size)'):
                for item in ast.walk(node):
                    if (isinstance(item, ast.With) and len(item.items) == 1
                            and isinstance(item.items[0].context_expr, ast.Call)
                            and ast.unparse(item.items[0].context_expr.func) == '_timing.phase'):
                        item.items[0].context_expr.args[1:] = [ast.Name(id='pass_id', ctx=ast.Load()),
                                                               ast.Name(id='size', ctx=ast.Load())]
    if not transform.count or ast.dump(strip(new)) != ast.dump(original):
        raise RuntimeError('timing insertion does not restore original AST exactly')
    return ast.fix_missing_locations(new), transform.count
