"""Startup/phase regression checks, synthetic CPU only; no production model."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coordinator
import runtime_environment as runtime
import stage_timing as timing


class RuntimeTests(unittest.TestCase):
    def test_exact_exports_accepted_without_mutation(self):
        env = dict(runtime.FIXED)
        self.assertEqual(runtime.check(env, modules={}), env)
        self.assertEqual(env, dict(runtime.FIXED))

    def test_missing_and_wrong_exports_rejected(self):
        for key in runtime.FIXED:
            for value in (None, 'incorrect'):
                env = dict(runtime.FIXED)
                if value is None:
                    del env[key]
                else:
                    env[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    runtime.check(env, modules={})

    def test_late_numeric_import_rejected(self):
        for name in ('torch', 'torch.nn', 'numpy', 'pandas.core', 'torchaudio'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'before numerical'):
                runtime.check(dict(runtime.FIXED), modules={name: object()})

    def test_other_thread_overrides_rejected(self):
        for key in ('MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'OMP_DYNAMIC'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                runtime.check({**runtime.FIXED, key: '1'}, modules={})

    def test_actual_environment_factory_repairs_only_fixed_exports(self):
        for role in ('reference', 'observed'):
            for extra in ({}, dict(runtime.FIXED), {k: 'wrong' for k in runtime.FIXED}):
                original = {'HOME': '/home/s2510040', 'PATH': '/usr/bin',
                            'UNRELATED_SECRET': 'synthetic', 'MKL_NUM_THREADS': '999', **extra}
                prior = dict(original)
                env = coordinator.child_environment(original, Path('/tmp/unused'), role)
                self.assertEqual(runtime.check(env, modules={}), dict(runtime.FIXED))
                self.assertNotIn('UNRELATED_SECRET', env)
                self.assertNotIn('MKL_NUM_THREADS', env)
                self.assertEqual(env['HOME'], original['HOME'])
                self.assertEqual(original, prior)

    def test_two_fresh_actual_torch_cpu_readbacks(self):
        code = ('import sys,json;sys.path.insert(0,' + repr(str(HERE)) + ');'
                'import runtime_environment as r;r.check(__import__("os").environ);'
                'import torch;v=r.readback(torch);'
                'v.update(cuda_initialized=torch.cuda.is_initialized(),torch=str(torch.__version__));'
                'print(json.dumps(v))')
        for role in ('reference', 'observed'):
            with tempfile.TemporaryDirectory(prefix='fixed-runtime-cpu-') as temporary:
                env = coordinator.child_environment(dict(os.environ), Path(temporary).resolve(), role)
                env['CUDA_VISIBLE_DEVICES'] = ''
                result = subprocess.run([sys.executable, '-I', '-B', '-c', code], env=env,
                                        capture_output=True, timeout=45, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLess(len(result.stdout) + len(result.stderr), 16384)
            record = json.loads(result.stdout)
            self.assertEqual(record['torch_num_threads'], 8)
            self.assertEqual(record['fixed_exports'], dict(runtime.FIXED))
            self.assertFalse(record['cuda_initialized'])

    def test_runner_exports_and_cold_gate(self):
        text = (HERE / 'run_gpu.sbatch').read_text()
        for key, value in runtime.FIXED.items():
            self.assertIn(key + '=' + value, text)
        tree = ast.parse((HERE / 'job_contract.py').read_bytes())
        gate = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'child_cold_gate')
        self.assertEqual(ast.unparse(gate.body[1]), 'runtime_environment.check(env)')


class TimingTests(unittest.TestCase):
    def test_begin_end_are_flushed_and_bounded(self):
        stream = io.StringIO()
        recorder = timing.Recorder(stream)
        with recorder.phase('diag.run_trace_pass', 'pass1', 16):
            self.assertIn('"event": "begin"', stream.getvalue())
        rows = [json.loads(s.split('=', 1)[1]) for s in stream.getvalue().splitlines()]
        self.assertEqual([r['event'] for r in rows], ['begin', 'end'])
        self.assertEqual([r['sequence'] for r in rows], [1, 2])
        self.assertEqual(rows[0]['batch_size'], 16)
        self.assertGreaterEqual(rows[1]['elapsed_seconds'], rows[0]['elapsed_seconds'])

    def test_exceptions_propagate_and_error_not_end(self):
        stream = io.StringIO()
        with self.assertRaisesRegex(ValueError, 'original'):
            with timing.Recorder(stream).phase('self._consume'):
                raise ValueError('original')
        self.assertIn('"error_type": "ValueError"', stream.getvalue())
        self.assertNotIn('"event": "end"', stream.getvalue())

    def test_event_and_byte_overflow_fail_closed(self):
        recorder = timing.Recorder(io.StringIO(), limit=2)
        with recorder.phase('self._live'):
            pass
        with self.assertRaisesRegex(RuntimeError, 'limit'):
            recorder.emit('begin', 'self._live')
        with self.assertRaisesRegex(RuntimeError, 'byte budget'):
            timing.Recorder(io.StringIO()).emit('readback', 'startup_environment', value='x' * 9000)

    def test_logging_failure_not_silently_accepted(self):
        stream = mock.Mock()
        stream.write.side_effect = OSError('fixture log failure')
        with self.assertRaises(OSError):
            with timing.Recorder(stream).phase('self._live'):
                self.fail('body must not execute after begin log failure')

    def test_unknown_phase_and_pass_rejected(self):
        for values in (('unreviewed', None, None), ('self._live', 'pass3', 16), ('self._live', 'pass1', 32)):
            with self.assertRaises(ValueError):
                with timing.Recorder(io.StringIO()).phase(*values):
                    pass

    def test_single_watchdog_cancelled_on_success_or_exception(self):
        for fail in (False, True):
            with mock.patch.object(timing.faulthandler, 'dump_traceback_later') as arm, \
                    mock.patch.object(timing.faulthandler, 'cancel_dump_traceback_later') as cancel:
                try:
                    with timing.Recorder().watchdog():
                        if fail:
                            raise ValueError('fixture')
                except ValueError:
                    pass
                arm.assert_called_once_with(2400, repeat=False, file=sys.stderr, exit=False)
                cancel.assert_called_once_with()

    def test_actual_archived_loop_ast_restoration(self):
        sys.path.insert(0, str(HERE.parent / 'targeted_gpu_pair_20260915_scan'))
        import archive_adapter
        for role in ('reference', 'observed'):
            original, _ = archive_adapter.derive(role)
            tree, count = timing.instrument(original, loop=True)
            self.assertGreater(count, 5)
            self.assertEqual(ast.dump(timing.strip(tree)), ast.dump(original))
            self.assertIn("_timing.phase('_archiver.capture', pass_id, size)", ast.unparse(tree))
            self.assertIn('run_trace_pass', ast.unparse(tree))

    def test_timed_synthetic_loop_preserves_call_order_and_return(self):
        source = '''def run(diag):
    results = []
    for pass_id, size in (("pass1", 16), ("pass2", 1)):
        result = diag.run_trace_pass(pass_id, size)
        results.append(result)
    return results
'''
        tree, _ = timing.instrument(ast.parse(source), loop=True)
        calls = []
        diag = types.SimpleNamespace(run_trace_pass=lambda p, b: calls.append((p, b)) or b)
        stream = io.StringIO()
        ns = {'_timing': timing.Recorder(stream)}
        exec(compile(tree, '<timed-fixture>', 'exec'), ns)
        self.assertEqual(ns['run'](diag), [16, 1])
        self.assertEqual(calls, [('pass1', 16), ('pass2', 1)])
        self.assertEqual(len(stream.getvalue().splitlines()), 4)

    def test_no_new_tensor_or_cuda_operations(self):
        tree = ast.parse((HERE / 'stage_timing.py').read_bytes())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertFalse(any('torch' in ast.unparse(n) or 'numpy' in ast.unparse(n) for n in imports))
        self.assertNotIn('synchronize', (HERE / 'stage_timing.py').read_text().replace('synchronized', ''))


if __name__ == '__main__':
    unittest.main()
