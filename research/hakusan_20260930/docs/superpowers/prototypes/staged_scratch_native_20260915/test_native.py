"""Offline adversarial transport/result checks. Mock responses are NOT native evidence."""
import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import run_native as probe


def encoded(raw):
    return base64.b64encode(raw).decode('ascii')


class NativeStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task, cls.driver, cls.files, cls.own = probe.sources()
        cls.binding = cls.task.sources()
        cls.samples = {stage: cls.task.decode(probe.read(probe.BASELINE / stage / 'result.json'))
                       for stage in probe.STAGES}
        cls.run_id = cls.samples['A2']['session_id']

    def make(self, stage='A2', native=False):
        mode = 'NATIVE_CPU' if native else 'LOCAL_HARNESS'
        parents = {s + '/result.json': encoded(probe.wire(self.samples[s])) for s in ('A2', 'B2')} if stage == 'mmap' else {}
        request = dict(stage=stage, session_id=self.run_id, scope=self.task.SCOPE,
                       source_binding=copy.deepcopy(self.binding),
                       parents=[{'name': n, 'sha256': probe.sha(base64.b64decode(v))} for n, v in parents.items()])
        spec = self.driver.make_spec(mode, self.files)
        spec.update(stage=stage, run_id=self.run_id, parents=parents,
                    stage_request_base64=encoded(probe.wire(request)), stage_request_sha256=probe.sha(probe.wire(request)),
                    child_source=encoded(self.own['child.py']), child_sha256=probe.sha(self.own['child.py']))
        value = copy.deepcopy(self.samples[stage])
        value['parents'] = request['parents']
        if native:
            value['environment'] = {'python': '3.11.5', 'torch': '2.1.1+cu118'}
        return spec, value, self.response(spec, value)

    def response(self, spec, value):
        record = dict(status='STAGED_COMPONENT_PASS', stage=spec['stage'], group=spec['stage'], mode=spec['mode'],
                      run_id=spec['run_id'], pid=value['pid'], tests=value.get('tests', 0), errors=0, failures=0, skips=0,
                      **value['environment'], cpu_affinity=[0] if spec['mode'] == 'NATIVE_CPU' else None,
                      request_sha256=spec['stage_request_sha256'], result_sha256=probe.sha(probe.wire(value)),
                      cuda_initialized=False, production_model_loaded=False, jobs_submitted=0,
                      ready_for_gpu=False, original_native_monolithic_passed=False)
        log = ('STAGED_CPU_CHILD=' + json.dumps(record) + '\n').encode()
        process = dict(pid=value['pid'], returncode=0, error=None, elapsed_seconds=10,
                       log=dict(name=spec['stage'] + '.log', size=len(log), sha256=probe.sha(log)))
        row = dict(group=spec['stage'], process=process, record=record, log_base64=encoded(log),
                   stage_result_base64=encoded(probe.wire(value)))
        return dict(status='NATIVE_STAGED_COMPONENT_PASS' if spec['mode'] == 'NATIVE_CPU' else 'LOCAL_STAGED_COMPONENT_PASS',
                    error=None, **{k: spec[k] for k in ('mode', 'request_id', 'package_sha256', 'child_sha256')},
                    temporary_directory_removed=True, permanent_files_written=False, production_model_loaded=False,
                    ready_for_gpu=False, jobs_submitted=0, candidate_input_freeze_sha256=None,
                    automatic_retry=False, elapsed_seconds=12, groups=[row])

    def supervisor(self, spec):
        namespace = {'SPEC': spec, '__name__': 'offline_supervisor_inspection'}
        exec(compile(probe.derive_payload(), '<offline-supervisor>', 'exec'), namespace)
        return namespace

    def test_unchanged_sources_and_derivation(self):
        spec, _, _ = self.make()
        scope = self.supervisor(spec)
        self.assertEqual(scope['COUNTS'], {'A2': 0})
        self.assertEqual(scope['WALL_SECONDS'], 90)
        self.assertEqual(scope['CAP_BYTES'], 16 * 1024**2)
        files, child, _ = scope['unpack'](spec)
        self.assertEqual(files, self.files)
        self.assertEqual(child, self.own['child.py'])
        source = probe.derive_payload().decode()
        for required in ('seconds=min(50, remaining)', 'os.sched_setaffinity(0, {min(allowed)})',
                         "'HOME'", 'source_check(package, files)', 'TemporaryDirectory'):
            self.assertIn(required, source)
        self.assertNotIn('sbatch(', source)

    def test_pinned_supervisor_mutation_rejected(self):
        with mock.patch.object(probe, 'read', return_value=b'changed'):
            with self.assertRaisesRegex(RuntimeError, 'supervisor differs'):
                probe.derive_payload()

    def test_exact_temporary_package(self):
        spec, _, _ = self.make()
        spec['files']['unexpected.py'] = encoded(b'')
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.supervisor(spec)['unpack'](spec)

    def test_pinned_fixture_tamper_rejected(self):
        spec, _, _ = self.make()
        spec['files'][str((probe.STAGED / 'lifecycle.py').relative_to(probe.ROOT))] = encoded(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'digest'):
            self.supervisor(spec)['unpack'](spec)

    def test_stage_data_exact_parents(self):
        spec, _, _ = self.make('mmap')
        raw, parents = self.supervisor(spec)['stage_data'](spec)
        self.assertEqual(self.task.decode(raw)['stage'], 'mmap')
        self.assertEqual(set(parents), {'A2/result.json', 'B2/result.json'})

    def test_parent_path_escape_rejected_before_materialization(self):
        spec, _, _ = self.make('mmap')
        request = self.task.decode(base64.b64decode(spec['stage_request_base64']))
        request['parents'][0]['name'] = '../escape'
        spec['parents']['../escape'] = spec['parents'].pop('A2/result.json')
        spec.update(stage_request_base64=encoded(probe.wire(request)), stage_request_sha256=probe.sha(probe.wire(request)))
        with self.assertRaisesRegex(RuntimeError, 'inventory'):
            self.supervisor(spec)['stage_data'](spec)

    def test_parent_bytes_digest_rejected(self):
        spec, _, _ = self.make('mmap')
        spec['parents']['A2/result.json'] = encoded(b'{}\n')
        with self.assertRaisesRegex(RuntimeError, 'digest'):
            self.supervisor(spec)['stage_data'](spec)

    def test_stage_request_digest_rejected(self):
        spec, _, response = self.make()
        spec['stage_request_sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'request digest'):
            probe.validate(response, spec, self.task)

    def test_rehashed_wrong_source_and_session_rejected(self):
        for key, replacement in (('source_binding', {}), ('session_id', 'f' * 32), ('scope', 'production')):
            with self.subTest(key=key):
                spec, value, _ = self.make()
                request = self.task.decode(base64.b64decode(spec['stage_request_base64']))
                request[key] = replacement
                value[key] = replacement
                spec.update(stage_request_base64=encoded(probe.wire(request)), stage_request_sha256=probe.sha(probe.wire(request)))
                with self.assertRaisesRegex(RuntimeError, 'source/session/scope'):
                    probe.validate(self.response(spec, value), spec, self.task)

    def test_successful_oracles_and_mmap_are_distinct_scopes(self):
        for stage in probe.STAGES:
            spec, value, response = self.make(stage)
            self.assertEqual(probe.validate(response, spec, self.task)[1], value)
            self.assertFalse(response['ready_for_gpu'])

    def test_mock_native_result_cannot_bypass_versions(self):
        spec, value, response = self.make(native=True)
        probe.validate(response, spec, self.task)  # Mock schema validation, no native execution.
        for version in ('2.12.1', '2.1.0+cu118'):
            value['environment']['torch'] = version
            with self.assertRaisesRegex(RuntimeError, 'native environment'):
                probe.validate(self.response(spec, value), spec, self.task)

    def test_cpu_affinity_rejected(self):
        spec, _, response = self.make(native=True)
        response['groups'][0]['record']['cpu_affinity'] = [0, 1]
        with self.assertRaisesRegex(RuntimeError, 'native environment'):
            probe.validate(response, spec, self.task)

    def test_failed_response_cleanup_deadline_scope_rejected(self):
        bad = {'status': 'STAGED_COMPONENT_FAILED', 'error': {}, 'temporary_directory_removed': False,
               'permanent_files_written': True, 'jobs_submitted': 1, 'production_model_loaded': True,
               'ready_for_gpu': True, 'candidate_input_freeze_sha256': 'new', 'automatic_retry': True,
               'elapsed_seconds': 90}
        for key, replacement in bad.items():
            with self.subTest(key=key):
                spec, _, response = self.make()
                response[key] = replacement
                with self.assertRaises(RuntimeError):
                    probe.validate(response, spec, self.task)

    def test_child_failure_timeout_pid_rejected(self):
        for key, replacement in (('returncode', 2), ('error', {}), ('elapsed_seconds', 51), ('pid', -1)):
            with self.subTest(key=key):
                spec, _, response = self.make()
                response['groups'][0]['process'][key] = replacement
                with self.assertRaisesRegex(RuntimeError, 'child outcome'):
                    probe.validate(response, spec, self.task)

    def test_missing_group_rejected(self):
        spec, _, response = self.make()
        response['groups'] = []
        with self.assertRaisesRegex(RuntimeError, 'one stage'):
            probe.validate(response, spec, self.task)

    def test_child_scope_and_counts_rejected(self):
        for key, replacement in (('tests', 1), ('skips', 1), ('cuda_initialized', True),
                                 ('original_native_monolithic_passed', True)):
            spec, _, response = self.make()
            response['groups'][0]['record'][key] = replacement
            with self.assertRaises(RuntimeError):
                probe.validate(response, spec, self.task)

    def test_result_and_log_tampering_rejected(self):
        for key in ('log_base64', 'stage_result_base64'):
            spec, _, response = self.make()
            response['groups'][0][key] = encoded(b'changed')
            with self.assertRaises(RuntimeError):
                probe.validate(response, spec, self.task)

    def test_mmap_wrong_contract_rejected_even_when_resigned(self):
        spec, value, _ = self.make('mmap')
        value['consumed_contract_sha256'] = 'f' * 64
        with self.assertRaisesRegex(RuntimeError, 'consumed contract'):
            probe.validate(self.response(spec, value), spec, self.task)

    def test_mmap_consumer_environment_mismatch(self):
        spec, value, _ = self.make('mmap')
        value['environment']['torch'] = 'other'
        with self.assertRaisesRegex(RuntimeError, 'consumer environment'):
            probe.validate(self.response(spec, value), spec, self.task)

    def test_ast_and_preserved_scientific_scope_rejected(self):
        for key, replacement in (('original_ast_restored_exactly', False), ('production_model_loaded', True),
                                 ('source_postcheck', False), ('home_unchanged', False)):
            spec, value, _ = self.make()
            value[key] = replacement
            with self.assertRaises(RuntimeError):
                probe.validate(self.response(spec, value), spec, self.task)

    def test_rehashed_oracle_contract_mismatch_rejected(self):
        spec, value, _ = self.make()
        value['contract_sha256'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'oracle result'):
            probe.validate(self.response(spec, value), spec, self.task)

    def test_requires_local_review_before_ssh(self):
        with mock.patch.object(probe, 'sources', return_value=(self.task, self.driver, self.files, self.own)):
            with self.assertRaisesRegex(RuntimeError, 'local payload'):
                probe.operate('NATIVE_CPU', None)

    def test_symlink_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name).resolve()
            (folder / 'target').write_bytes(b'x')
            (folder / 'alias').symlink_to(folder / 'target')
            with self.assertRaises(RuntimeError):
                probe.read(folder / 'alias')

    def test_runtime_and_parent_sources_remain_unchanged(self):
        self.assertEqual(probe.sources()[2], self.files)


if __name__ == '__main__':
    unittest.main()
