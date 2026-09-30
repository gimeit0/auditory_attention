"""Live-object and worker-seam regression; never loads weights or uses CUDA/SSH."""
from contextlib import contextmanager, ExitStack
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch.torch_version import TorchVersion
import e1_worker_archive as provenance
import fine_alpha_archive as archive
from test_fine_alpha import tiny_layout, arrays, reference


def production_environment():
    return dict(python='3.11.5', torch='2.1.1+cu118', cuda='11.8', cudnn=8700,
                device_name='NVIDIA A100 synthetic fixture', hostname='synthetic',
                slurm_job_id='123', slurm_cpus_per_task='8')


def summary_for(records):
    start = '2026-09-28T00:00:00+00:00'
    end = '2026-09-28T00:00:01+00:00'
    return dict(process_started_utc=start, process_finished_utc=end,
                predictions=sum(len(r['trial_ids']) for r in records.values()),
                runtime_values=dict(provenance.EXPECTED_RUNTIME), pass_resources=[
                    dict(domain=d, pass_name=p, started_utc=start, finished_utc=end,
                         elapsed_seconds=1., cuda_max_memory_allocated_bytes=1,
                         cuda_max_memory_reserved_bytes=2, host_max_rss_ru_maxrss=1,
                         ru_maxrss_unit='KiB') for d, p in sorted({(k[1], k[2]) for k in records})])


class EnvironmentTests(unittest.TestCase):
    def test_real_torch_version_producer_is_plain_string_without_json_roundtrip(self):
        self.assertIsInstance(torch.__version__, str)
        with patch.object(torch.cuda, 'is_available', return_value=False):
            env = provenance.environment_record()
        self.assertIs(type(env['torch']), str)
        self.assertEqual(env['torch'], str(torch.__version__))

    def test_torchversion_direct_provenance_matches_json_roundtrip(self):
        with patch.object(torch, '__version__', TorchVersion('2.1.1+cu118')), \
             patch.object(torch.cuda, 'is_available', return_value=False):
            env = provenance.environment_record()
        metadata = dict(environment=env, job_id='123')
        summary = summary_for({})
        provenance.verify_provenance(metadata, summary, set(), production=False)
        provenance.verify_provenance(json.loads(json.dumps(metadata)), summary, set(), production=False)

    def test_invalid_version_is_not_stringified(self):
        for version in (None, 211, True, [], object()):
            with self.subTest(version=type(version).__name__), \
                 patch.object(torch, '__version__', version), \
                 patch.object(torch.cuda, 'is_available', return_value=False):
                with self.assertRaisesRegex(ValueError, 'PROVENANCE_TORCH_VERSION'):
                    provenance.environment_record()

    def test_validator_remains_strict_for_unnormalized_metadata(self):
        env = production_environment(); env['torch'] = TorchVersion('2.1.1+cu118')
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_ENVIRONMENT'):
            provenance.verify_provenance(dict(environment=env, job_id='123'), summary_for({}), set())

    def test_production_requirements_remain_enforced(self):
        for key, value in (('torch', ''), ('cuda', None), ('cudnn', True),
                           ('device_name', 'H100'), ('slurm_job_id', '456'), ('slurm_cpus_per_task', '4')):
            env = production_environment(); env[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                provenance.verify_provenance(dict(environment=env, job_id='123'), summary_for({}), set())


class NativeProbeTests(unittest.TestCase):
    def payload(self):
        here = Path(__file__).parent
        names = ('e0_layout_reference.py', 'e1_execution.py', 'e1_worker_archive.py')
        return dict(release_sha256='synthetic', sources={
            n: dict(source=(here/n).read_text(), identity=archive.identity(here/n)) for n in names})

    def test_exact_function_cpu_probe_and_negative_cases(self):
        from fine_alpha_provenance_cpu_probe import probe
        result = probe(self.payload())
        self.assertEqual(result['status'], 'FINE_ALPHA_PROVENANCE_CPU_TYPE_CHECK_PASS')
        self.assertFalse(result['production_validated'])
        self.assertFalse(result['cuda_initialized'])
        self.assertEqual(result['invalid_versions_rejected'], 4)
        self.assertEqual(result['recorded_version_type'], 'str')

    def test_changed_source_hash_rejected(self):
        from fine_alpha_provenance_cpu_probe import probe
        payload = self.payload(); payload['sources']['e1_worker_archive.py']['source'] += '\n'
        with self.assertRaisesRegex(ValueError, 'PROBE_SOURCE_SHA'): probe(payload)

    def test_missing_definition_and_remote_syntax(self):
        from fine_alpha_provenance_cpu_probe import select
        from check_fine_alpha_v2_native_cpu import BOOTSTRAP
        with self.assertRaisesRegex(ValueError, 'MISSING_PROBE_DEFINITION'): select('x = 1', ('environment_record',))
        compile(BOOTSTRAP, '<cpu-remote>', 'exec')

    def test_invalid_native_scope_rejected(self):
        from fine_alpha_provenance_cpu_probe import probe
        from check_fine_alpha_v2_native_cpu import validate
        payload = self.payload(); result = probe(payload)
        result.update(python='3.11.5', torch='2.1.1+cu118', raw_version_type='torch.torch_version.TorchVersion')
        validate(result, payload)
        for key in ('cuda_initialized', 'production_checkpoint_loaded', 'remote_source_files_written', 'production_validated'):
            bad = dict(result); bad[key] = True
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'CPU_SCOPE'): validate(bad, payload)


class WorkerPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'output'; self.events = []
        self.layout = tiny_layout(); self.records = arrays(self.layout, 'A')
        self.summary = summary_for(self.records)
        self.ctx = dict(core=SimpleNamespace(runtime_values=lambda: dict(provenance.EXPECTED_RUNTIME)),
                        outer=None, load_report={}, checkpoint_sha='sha', architecture_type=None, gain_type=None)

    def run_worker(self, *, env=None, runtime=None, postcheck_error=False, execution_error=False):
        @contextmanager
        def session(layout):
            self.events.append('session_enter')
            try:
                yield self.ctx
            finally:
                self.events.append('session_postcheck')
                if postcheck_error: raise ValueError('SYNTHETIC_POSTCHECK_FAILED')

        def execute(layout, block, ctx, sink, **kwargs):
            self.events.append('execute')
            self.assertTrue((self.root/'ENVIRONMENT_PRECHECK.json').is_file())
            if execution_error: raise ValueError('SYNTHETIC_EXECUTION_FAILED')
            for key, row in self.records.items(): sink(key, row)
            return copy.deepcopy(self.summary)

        if runtime is not None: self.ctx['core'].runtime_values = lambda: runtime
        with ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', SLURM_JOB_ID='123'))
            stack.enter_context(patch.object(archive, 'build_contract', return_value=self.layout))
            stack.enter_context(patch('e1_audited_session.audited_e1_session', session))
            stack.enter_context(patch('loaded_model_adapter.accept_loaded_formal40'))
            stack.enter_context(patch('e2_history_bridge.read_reference', return_value=reference(self.layout)))
            environment = stack.enter_context(patch.object(archive, 'environment_record',
                side_effect=env if isinstance(env, list) else None,
                return_value=production_environment() if env is None else env))
            stack.enter_context(patch.object(archive, 'execute', execute))
            archive.run_worker(self.root, 'A', 'synthetic-release', Path('synthetic-reference'))
        return environment

    def test_success_checks_before_forward_and_keeps_bound_precheck(self):
        observed = self.run_worker()
        self.assertEqual(observed.call_count, 2)
        worker = json.loads((self.root/'WORKER.json').read_text())
        precheck = json.loads((self.root/'ENVIRONMENT_PRECHECK.json').read_text())
        self.assertEqual(worker['environment_precheck'], archive.identity(self.root/'ENVIRONMENT_PRECHECK.json'))
        self.assertEqual(precheck['environment'], worker['environment'])
        self.assertEqual(precheck['job_id'], '123')
        self.assertEqual(precheck['release_sha256'], 'synthetic-release')
        self.assertEqual(len(worker['outputs']), 102)   # V4 block A: 17 passes x 6 conditions
        self.assertTrue(worker['source_input_postchecks_completed'])
        self.assertEqual(self.events, ['session_enter', 'execute', 'session_postcheck'])

    def test_bad_environment_stops_before_inference(self):
        env = production_environment(); env['device_name'] = 'H100'
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_PRODUCTION_ENVIRONMENT'):
            self.run_worker(env=env)
        self.assertNotIn('execute', self.events)
        self.assertEqual(list(self.root.glob('*.npz')), [])
        failed = json.loads((self.root/'FAILED.json').read_text())
        self.assertEqual(failed['phase'], 'environment_precheck')
        self.assertEqual(failed['completed_records'], 0)
        self.assertFalse((self.root/'WORKER.json').exists())

    def test_bad_runtime_stops_before_inference(self):
        runtime = dict(provenance.EXPECTED_RUNTIME, matmul_tf32=True)
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_RUNTIME'):
            self.run_worker(runtime=runtime)
        self.assertNotIn('execute', self.events)

    def test_environment_drift_rejected(self):
        before = production_environment(); after = dict(before, hostname='changed')
        with self.assertRaisesRegex(ValueError, 'FINE_ENVIRONMENT_CHANGED'):
            self.run_worker(env=[before, after])
        self.assertFalse((self.root/'WORKER.json').exists())

    def test_session_postcheck_failure_never_publishes_worker(self):
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC_POSTCHECK_FAILED'):
            self.run_worker(postcheck_error=True)
        self.assertFalse((self.root/'WORKER.json').exists())
        self.assertTrue((self.root/'FAILED.json').exists())

    def test_execution_failure_does_not_become_precheck_success(self):
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC_EXECUTION_FAILED'):
            self.run_worker(execution_error=True)
        self.assertFalse((self.root/'WORKER.json').exists())
        self.assertEqual(json.loads((self.root/'FAILED.json').read_text())['phase'], 'execution')


if __name__ == '__main__': unittest.main()
