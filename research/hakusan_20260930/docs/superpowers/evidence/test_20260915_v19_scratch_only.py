"""Offline continuation checks; never calls SSH or runs the scratch test."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
path = HERE / '2026-09-15-v19-scratch-only.py'
spec = importlib.util.spec_from_file_location('scratch_continuation', path)
continuation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(continuation)
sys.path.insert(0, str(continuation.PROBE))
import test_probe


class ContinuationTests(unittest.TestCase):
    def response(self, mode='NATIVE_CPU'):
        response, request = test_probe.ProbeTests().response(mode)
        response['status'] = 'NATIVE_V19_SCRATCH_ONLY_PASS' if mode == 'NATIVE_CPU' else 'LOCAL_SCRATCH_ONLY_PASS'
        response['groups'] = [response['groups'][-1]]
        response['groups'][0]['process']['elapsed_seconds'] = 10
        return response, request

    def test_derivation_preserves_supervisor_and_time_bounds(self):
        raw = continuation.derived_payload()
        self.assertIn(b"COUNTS = {'scratch_lifetime': 2}", raw)
        self.assertIn(b'WALL_SECONDS = 90', raw)
        self.assertIn(b'seconds=min(50, remaining)', raw)
        self.assertNotIn(b"'NATIVE_V19_CPU_PASS'", raw)
        compile(raw, '<derived-only-check>', 'exec')

    def test_actual_parent_sources_and_failure_verified_read_only(self):
        _, files = continuation.original_driver()
        result = continuation.prior_evidence(files)
        self.assertEqual(result['status'], 'CPU_PROBE_FAILED')
        self.assertEqual(sum(r['record']['tests'] for r in result['remote']['groups'][:4]), 78)

    def test_subset_pass_is_not_a_full_run_pass(self):
        response, request = self.response()
        continuation.check_subset(response, request)
        response['status'] = 'NATIVE_V19_CPU_PASS'
        with self.assertRaises(RuntimeError):
            continuation.check_subset(response, request)

    def test_mode_version_and_affinity_rejected(self):
        for key, value in [('mode', 'LOCAL_HARNESS'), ('python', '3.11.15'),
                           ('torch', '2.12.1'), ('cpu_affinity', [0, 1]), ('cuda_initialized', True)]:
            response, request = self.response()
            response['groups'][0]['record'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                continuation.check_subset(response, request)

    def test_missing_duplicate_or_incomplete_group_rejected(self):
        for mutation in ('empty', 'duplicate', 'incomplete'):
            response, request = self.response()
            if mutation == 'empty':
                response['groups'] = []
            elif mutation == 'duplicate':
                response['groups'] *= 2
            else:
                response['groups'][0]['record'] = None
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                continuation.check_subset(response, request)

    def test_test_failure_is_rejected_with_a_matching_log(self):
        for key, value in [('tests', 1), ('skips', 1), ('errors', 1), ('failures', 1)]:
            response, request = self.response()
            row = response['groups'][0]
            row['record'][key] = value
            raw = ('V19_CPU_CHILD=' + json.dumps(row['record']) + '\n').encode()
            row['log_base64'] = base64.b64encode(raw).decode()
            row['process']['log'].update(size=len(raw), sha256=continuation.sha(raw))
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                continuation.check_subset(response, request)

    def test_nonzero_timeout_and_cleanup_failures_rejected(self):
        for mutation in ('rc', 'child_time', 'total_time', 'cleanup'):
            response, request = self.response()
            if mutation == 'rc':
                response['groups'][0]['process']['returncode'] = -9
            elif mutation == 'child_time':
                response['groups'][0]['process']['elapsed_seconds'] = 50
            elif mutation == 'total_time':
                response['elapsed_seconds'] = 90
            else:
                response['temporary_directory_removed'] = False
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                continuation.check_subset(response, request)

    def test_request_binding_and_scope_rejected(self):
        for key, value in [('request_id', 'x'), ('package_sha256', 'x'), ('child_sha256', 'x'),
                           ('jobs_submitted', 1), ('ready_for_gpu', True), ('automatic_retry', True),
                           ('production_model_loaded', True), ('permanent_files_written', True)]:
            response, request = self.response()
            response[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                continuation.check_subset(response, request)


if __name__ == '__main__':
    unittest.main(verbosity=2)
