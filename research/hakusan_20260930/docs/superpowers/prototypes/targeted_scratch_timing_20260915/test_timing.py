"""Offline tests of test-only timing insertion and bounded evidence parsing."""
import ast
import base64
import io
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timing_child as child
import run_timing as run


class TimingTests(unittest.TestCase):
    def test_complete_original_ast_and_assertions_restored(self):
        path = HERE.parent / 'targeted_gpu_job_20260915_v5/test_scratch_integration.py'
        source = path.read_bytes()
        self.assertEqual(run.sha(source), child.TEST_SHA)
        original = ast.parse(source)
        changed, count = child.instrument(original)
        self.assertGreaterEqual(count, 10)
        self.assertEqual(ast.dump(child.strip(changed)), ast.dump(original))
        compile(changed, '<instrumented-test-only>', 'exec')

    def test_unknown_test_layout_rejected(self):
        with self.assertRaises(RuntimeError):
            child.instrument(ast.parse('x = 1'))

    def test_mirror_preserves_getvalue(self):
        output = io.StringIO()
        mirror = child.TeeLog(output)
        self.assertEqual(mirror.write('PHASE_TIMING={"test":1}\n'), 24)
        self.assertEqual(mirror.getvalue(), 'PHASE_TIMING={"test":1}\n')
        self.assertEqual(output.getvalue(), '\n' + mirror.getvalue())

    def test_mirror_and_event_caps(self):
        with self.assertRaises(RuntimeError):
            child.TeeLog(io.StringIO()).write('x' * (256 * 1024 + 1))
        recorder = child.Recorder(io.StringIO())
        recorder.sequence = 128
        with self.assertRaises(RuntimeError):
            recorder.emit('begin', 'x')

    def test_phase_exception_propagates(self):
        stream = io.StringIO()
        recorder = child.Recorder(stream)
        with self.assertRaisesRegex(ValueError, 'original'):
            with recorder.phase('unchanged_call'):
                raise ValueError('original')
        rows = [json.loads(line.split('=', 1)[1]) for line in stream.getvalue().splitlines() if line]
        self.assertEqual([r['edge'] for r in rows], ['begin', 'error'])
        self.assertEqual(rows[-1]['error_type'], 'ValueError')

    def response(self, timeout=False):
        spec = dict(mode='NATIVE_CPU', request_id='a' * 32, package_sha256='b' * 64, child_sha256='c' * 64)
        env = dict(sequence=1, pid=100, edge='environment', label='instrumented_cpu_only', wall=0, cpu=0,
            mode='NATIVE_CPU', python='3.11.5', torch='2.1.1+cu118', cpu_affinity=[0],
            jobs_submitted=0, production_model_loaded=False, stack_after_seconds=30)
        ready = dict(sequence=2, pid=100, edge='prepared', label='original_ast_restored', wall=1, cpu=1)
        text = ''.join('CPU_LOCATE_EVENT=' + json.dumps(row) + '\n' for row in (env, ready))
        record = None if timeout else dict(status='INSTRUMENTED_TESTS_FINISHED', mode='NATIVE_CPU',
            pid=100, tests=2, errors=0, failures=0, skips=0, cuda_initialized=False,
            diagnostic_only=True, original_compatibility_verified=False)
        if record:
            text += 'CPU_LOCATE_CHILD=' + json.dumps(record) + '\n'
        else:
            text += 'Timeout (0:00:30)!\nThread ...\n'
        raw = text.encode()
        process = dict(pid=100, returncode=-9 if timeout else 0,
            error={'type': 'TimeoutError', 'message': 'child deadline reached'} if timeout else None,
            log=dict(name='scratch_lifetime.log', size=len(raw), sha256=run.sha(raw)))
        remote = dict(**spec, status='V19_CPU_CHECK_FAILED' if timeout else 'NATIVE_TIMING_TESTS_FINISHED',
            error={'message': 'timeout'} if timeout else None, elapsed_seconds=50.3 if timeout else 10,
            temporary_directory_removed=True, permanent_files_written=False, jobs_submitted=0,
            production_model_loaded=False, ready_for_gpu=False, candidate_input_freeze_sha256=None,
            automatic_retry=False, groups=[dict(group='scratch_lifetime', process=process, record=record,
                log_base64=base64.b64encode(raw).decode())])
        return remote, spec

    def test_completed_instrumentation_never_claims_compatibility(self):
        result = run.check_capture(*self.response())
        self.assertTrue(result['instrumented_tests_completed'])
        self.assertFalse(result['original_native_compatibility_verified'])

    def test_bounded_timeout_is_evidence_not_a_test_pass(self):
        result = run.check_capture(*self.response(timeout=True))
        self.assertFalse(result['instrumented_tests_completed'])
        self.assertIsNotNone(result['stack_snapshot'])

    def test_missing_dump_environment_or_sequence_rejected(self):
        remote, spec = self.response(timeout=True)
        raw = base64.b64decode(remote['groups'][0]['log_base64'])
        for changed in (raw.split(b'Timeout')[0], raw.replace(b'"sequence": 2', b'"sequence": 5'),
                        raw.replace(b'2.1.1+cu118', b'2.12.1')):
            row = remote['groups'][0]
            row['log_base64'] = base64.b64encode(changed).decode()
            row['process']['log'].update(size=len(changed), sha256=run.sha(changed))
            with self.assertRaises(RuntimeError):
                run.check_capture(remote, spec)

    def test_cleanup_and_hash_mismatch_rejected(self):
        remote, spec = self.response()
        remote['temporary_directory_removed'] = False
        with self.assertRaises(RuntimeError):
            run.check_capture(remote, spec)
        remote, spec = self.response()
        remote['groups'][0]['process']['log']['sha256'] = 'bad'
        with self.assertRaises(RuntimeError):
            run.check_capture(remote, spec)

    def test_exact_derived_supervisor_bounds_unchanged(self):
        _, files, derived, sources = run.sources()
        self.assertEqual(len(files), 163)
        self.assertEqual(len(sources), 3)
        self.assertIn(b'WALL_SECONDS = 90', derived)
        self.assertIn(b'seconds=min(50, remaining)', derived)
        self.assertIn(b'CPU_LOCATE_CHILD=', derived)


if __name__ == '__main__':
    unittest.main(verbosity=2)
