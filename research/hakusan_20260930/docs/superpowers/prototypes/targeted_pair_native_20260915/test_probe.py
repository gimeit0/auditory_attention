"""Offline rejection tests for the CPU-only transport/harness; no SSH."""
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import driver
import payload


class ProbeTests(unittest.TestCase):
    def test_source_path_escape_and_noncanonical_names_rejected(self):
        for name in ('/absolute', '../escape', 'a/../b', './a', 'a//b', 'a\\b', ''):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                payload.member(name)
        self.assertEqual(str(payload.member('a/b.py')), 'a/b.py')

    def test_fixed_mode_and_inventory_rejected_before_writes(self):
        for spec in ({'mode': 'GPU', 'package_sha256': payload.PACKAGE_SHA},
                     {'mode': 'NATIVE_CPU', 'package_sha256': 'a' * 64},
                     {'mode': 'NATIVE_CPU', 'package_sha256': payload.PACKAGE_SHA,
                      'request_id': 'b' * 32, 'files': {}}):
            with self.assertRaises(RuntimeError):
                payload.unpack(spec)

    def test_cpu_environment_preserves_home_and_removes_scheduler_and_secrets(self):
        old = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix='native-env-unit-') as directory:
            env = payload.child_environment(Path(directory))
        self.assertEqual(env['HOME'], old['HOME'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '')
        for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
            self.assertEqual(env[name], '1')
        self.assertFalse(any(n.startswith('SLURM_') for n in env))
        self.assertEqual(dict(os.environ), old)

    def response(self, mode='NATIVE_CPU'):
        spec = {'mode': mode, 'request_id': 'a' * 32, 'package_sha256': payload.PACKAGE_SHA, 'child_sha256': 'b' * 64}
        rows = []
        for index, (name, count) in enumerate(driver.COUNTS.items()):
            record = {'status': 'SYNTHETIC_CPU_SUITE_PASS', 'mode': mode, 'group': name, 'pid': 100 + index,
                'tests': count, 'errors': 0, 'failures': 0, 'skips': 0, 'cuda_initialized': False,
                'production_model_loaded': False, 'jobs_submitted': 0, 'python': '3.11.5',
                'torch': '2.1.1+cu118', 'cpu_affinity': [0]}
            raw = ('V19_CPU_CHILD=' + json.dumps(record) + '\n').encode()
            rows.append({'group': name, 'record': record, 'process': {'pid': 100 + index, 'returncode': 0,
                'error': None, 'log': {'name': name + '.log', 'size': len(raw), 'sha256': driver.sha(raw)}},
                'log_base64': base64.b64encode(raw).decode()})
        result = {**spec, 'status': 'NATIVE_V19_CPU_PASS' if mode == 'NATIVE_CPU' else 'LOCAL_NATIVE_HARNESS_PASS',
            'error': None, 'temporary_directory_removed': True, 'permanent_files_written': False,
            'production_model_loaded': False, 'ready_for_gpu': False, 'jobs_submitted': 0,
            'candidate_input_freeze_sha256': None, 'automatic_retry': False, 'elapsed_seconds': 5, 'groups': rows}
        return result, spec

    def test_complete_synthetic_response_is_bound(self):
        result, spec = self.response()
        self.assertEqual(driver.check_response(result, spec), 80)

    def test_nonzero_process_not_hidden_by_pass_string(self):
        result, spec = self.response()
        result['groups'][0]['process']['returncode'] = -9
        with self.assertRaises(RuntimeError):
            driver.check_response(result, spec)

    def test_missing_or_duplicate_suite_rejected(self):
        for duplicate in (False, True):
            result, spec = self.response()
            result['groups'] = result['groups'][:-1] if not duplicate else [result['groups'][0]] * 5
            with self.assertRaises(RuntimeError):
                driver.check_response(result, spec)

    def test_mode_request_source_identity_must_match(self):
        for key in ('mode', 'request_id', 'package_sha256', 'child_sha256'):
            result, spec = self.response()
            result[key] = 'different'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                driver.check_response(result, spec)

    def test_cleanup_or_gpu_scope_rejected(self):
        for key, value in (('temporary_directory_removed', False), ('permanent_files_written', True),
                           ('production_model_loaded', True), ('ready_for_gpu', True), ('jobs_submitted', 1),
                           ('candidate_input_freeze_sha256', 'c' * 64), ('automatic_retry', True)):
            result, spec = self.response()
            result[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                driver.check_response(result, spec)

    def test_native_version_affinity_and_cuda_are_required(self):
        for key, value in (('python', '3.11.15'), ('torch', '2.12.1'), ('cpu_affinity', [0, 1]),
                           ('cuda_initialized', True), ('skips', 1), ('tests', 0)):
            result, spec = self.response()
            result['groups'][0]['record'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                driver.check_response(result, spec)

    def test_log_corruption_or_record_disagreement_rejected(self):
        result, spec = self.response()
        result['groups'][0]['log_base64'] = base64.b64encode(b'corrupt').decode()
        with self.assertRaisesRegex(RuntimeError, 'log identity'):
            driver.check_response(result, spec)
        result, spec = self.response()
        raw = b'V19_CPU_CHILD={}\n'
        row = result['groups'][0]
        row['log_base64'] = base64.b64encode(raw).decode()
        row['process']['log'].update(size=len(raw), sha256=driver.sha(raw))
        with self.assertRaisesRegex(RuntimeError, 'bound child result'):
            driver.check_response(result, spec)

    def test_timeout_or_reused_pid_rejected(self):
        result, spec = self.response()
        result['elapsed_seconds'] = 90
        with self.assertRaisesRegex(RuntimeError, 'deadline'):
            driver.check_response(result, spec)
        result, spec = self.response()
        result['groups'][1]['record']['pid'] = result['groups'][0]['record']['pid']
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            driver.check_response(result, spec)

    def test_local_success_cannot_be_labeled_native(self):
        result, spec = self.response('LOCAL_HARNESS')
        spec['mode'] = 'NATIVE_CPU'
        with self.assertRaises(RuntimeError):
            driver.check_response(result, spec)


if __name__ == '__main__':
    unittest.main(verbosity=2)
