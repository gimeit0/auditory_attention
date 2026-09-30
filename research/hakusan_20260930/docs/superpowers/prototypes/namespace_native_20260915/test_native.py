"""Offline source, payload and response rejection tests. Never opens SSH."""
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
import run_native as probe


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver, cls.files, cls.payload, cls.own = probe.sources()
        cls.spec = cls.driver.make_spec('LOCAL_HARNESS', cls.files)
        cls.spec.update(child_source=base64.b64encode(cls.own['child.py']).decode(), child_sha256=probe.sha(cls.own['child.py']))
        cls.module = {'__name__': 'namespace_supervisor_unit_only'}
        exec(compile(cls.payload, '<namespace-supervisor-unit>', 'exec'), cls.module)

    def example(self, mode='NATIVE_CPU'):
        spec = {k: v for k, v in self.spec.items() if k not in ('files', 'child_source')}
        spec['mode'] = mode
        ids = (['test_namespace.make_suite.<locals>.NamespaceTests.test_' + str(i) for i in range(15)]
            + ['namespace_overlay_test_binding_scan.BindingTests.test_' + str(i) for i in range(5)]
            + ['namespace_overlay_test_module_name_classification.ClassificationTests.test_' + str(i) for i in range(13)])
        timings = [{'namespace_keys': n, 'calls_per_repeat': 2000, 'repeats': 6,
            'unprofiled_seconds': {'original': [0.2] * 6, 'candidate': [0.1] * 6},
            'median_seconds': {'original': 0.2, 'candidate': 0.1}, 'speedup': 2.0} for n in (8, 256, 3000)]
        value = {'status': 'SYNTHETIC_CPU_SUITE_PASS', 'group': 'namespace_subset', 'mode': mode, 'pid': 123,
            'tests': 33, 'test_ids': ids, 'errors': 0, 'failures': 0, 'skips': 0,
            'python': '3.11.5', 'torch': '2.1.1+cu118', 'cpu_affinity': [0], 'cuda_initialized': False,
            'assembled_sha256': probe.ASSEMBLED_SHA, 'microbenchmark': timings,
            'production_model_loaded': False, 'production_snapshot_loaded': False,
            'full_expected_contract_executed': False, 'original_native_compatibility_verified': False,
            'jobs_submitted': 0, 'ready_for_gpu': False}
        row = {'group': 'namespace_subset', 'record': value,
               'process': {'pid': 123, 'returncode': 0, 'error': None}}
        self.relog(row)
        remote = {**spec, 'status': 'NATIVE_NAMESPACE_SUBSET_PASS' if mode == 'NATIVE_CPU' else 'LOCAL_NAMESPACE_SUBSET_PASS',
            'groups': [row], 'error': None, 'temporary_directory_removed': True, 'permanent_files_written': False,
            'jobs_submitted': 0, 'production_model_loaded': False, 'ready_for_gpu': False,
            'candidate_input_freeze_sha256': None, 'automatic_retry': False, 'elapsed_seconds': 8}
        return remote, spec

    @staticmethod
    def relog(row):
        raw = ('NAMESPACE_CPU_CHILD=' + json.dumps(row['record']) + '\n').encode()
        row['log_base64'] = base64.b64encode(raw).decode()
        row['process']['log'] = {'name': 'namespace_subset.log', 'size': len(raw), 'sha256': probe.sha(raw)}

    def test_fixed_166_file_payload_and_child(self):
        files, child, manifest = self.module['unpack'](self.spec)
        self.assertEqual(files, self.files)
        self.assertEqual(child, self.own['child.py'])
        self.assertEqual(len(manifest['files']), 162)
        self.assertEqual(self.module['WALL_SECONDS'], 90)
        self.assertEqual(self.module['COUNTS'], {'namespace_subset': 33})
        self.assertIn(b'seconds=min(50, remaining)', self.payload)

    def test_path_escapes_rejected(self):
        for name in ('/absolute', '../escape', 'a/../b', './a', 'a//b', 'a\\b', ''):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.module['member'](name)

    def test_missing_extra_or_changed_candidate_rejected(self):
        name = str((probe.CANDIDATE / 'candidate.py').relative_to(probe.ROOT))
        for action in ('missing', 'extra', 'changed'):
            spec = copy.deepcopy(self.spec)
            if action == 'missing': del spec['files'][name]
            if action == 'extra': spec['files']['unexpected.py'] = ''
            if action == 'changed': spec['files'][name] = base64.b64encode(b'changed').decode()
            with self.subTest(action=action), self.assertRaises(RuntimeError):
                self.module['unpack'](spec)

    def test_wrong_mode_parent_or_child_rejected(self):
        for key, value in (('mode', 'GPU'), ('package_sha256', '0' * 64), ('child_sha256', '1' * 64)):
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.module['unpack'](spec)

    def test_environment_has_one_cpu_no_gpu_and_unchanged_home(self):
        before = dict(os.environ)
        with tempfile.TemporaryDirectory(prefix='namespace-env-unit-') as directory:
            env = self.module['child_environment'](Path(directory))
        self.assertEqual(env['HOME'], before['HOME'])
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '')
        for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
            self.assertEqual(env[key], '1')
        self.assertFalse(any(k.startswith('SLURM_') for k in env))
        self.assertEqual(dict(os.environ), before)

    def test_valid_subset_response(self):
        for mode in ('NATIVE_CPU', 'LOCAL_HARNESS'):
            remote, spec = self.example(mode)
            self.assertEqual(probe.response(remote, spec)['tests'], 33)

    def test_nonzero_or_timeout_not_accepted_as_pass(self):
        for code in (2, -9):
            remote, spec = self.example()
            remote['groups'][0]['process']['returncode'] = code
            with self.assertRaises(RuntimeError): probe.response(remote, spec)

    def test_wrong_identity_or_cleanup_rejected(self):
        for key, value in (('request_id', 'wrong'), ('package_sha256', '0' * 64), ('child_sha256', '1' * 64),
            ('temporary_directory_removed', False), ('permanent_files_written', True), ('jobs_submitted', 1),
            ('ready_for_gpu', True), ('production_model_loaded', True), ('automatic_retry', True),
            ('candidate_input_freeze_sha256', 'a' * 64), ('elapsed_seconds', 90)):
            remote, spec = self.example()
            remote[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): probe.response(remote, spec)

    def test_native_version_scope_and_test_count_rejected(self):
        for key, value in (('python', '3.11.15'), ('torch', '2.12.1'), ('cpu_affinity', [0, 1]),
            ('cuda_initialized', True), ('tests', 32), ('skips', 1), ('assembled_sha256', '0' * 64),
            ('original_native_compatibility_verified', True), ('full_expected_contract_executed', True)):
            remote, spec = self.example()
            remote['groups'][0]['record'][key] = value
            self.relog(remote['groups'][0])
            with self.subTest(key=key), self.assertRaises(RuntimeError): probe.response(remote, spec)

    def test_missing_duplicate_or_relabelled_test_ids_rejected(self):
        for action in ('missing', 'duplicate', 'changed'):
            remote, spec = self.example()
            ids = remote['groups'][0]['record']['test_ids']
            expected = list(ids)
            if action == 'missing': ids.pop()
            if action == 'duplicate': ids[-1] = ids[0]
            if action == 'changed': ids[-1] += '_renamed'
            self.relog(remote['groups'][0])
            with self.subTest(action=action), self.assertRaises(RuntimeError): probe.response(remote, spec, expected)

    def test_log_corruption_rejected(self):
        remote, spec = self.example()
        remote['groups'][0]['log_base64'] = base64.b64encode(b'changed').decode()
        with self.assertRaises(RuntimeError): probe.response(remote, spec)

    def test_microbenchmark_scope_and_summary_rejected(self):
        for key, value in (('namespace_keys', 999), ('calls_per_repeat', 1), ('repeats', 1), ('speedup', 999)):
            remote, spec = self.example()
            remote['groups'][0]['record']['microbenchmark'][0][key] = value
            self.relog(remote['groups'][0])
            with self.subTest(key=key), self.assertRaises(RuntimeError): probe.response(remote, spec)


if __name__ == '__main__':
    unittest.main(verbosity=2)
