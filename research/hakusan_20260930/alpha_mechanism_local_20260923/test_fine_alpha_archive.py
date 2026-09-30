"""Manufactured archives test the real reread; no real model or Slurm calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from architecture_adapter import NAMES
from e1_inputs import FORMAL_SHA
from e1_artifacts import identity
from fine_alpha_contract import BLOCKS, BUDGET, inventory, contract
from fine_alpha_execution import verify_arrays
from fine_alpha_archive import verify, contract_sha
from test_fine_alpha import tiny_layout, arrays, reference

def write(p, v): p.write_text(json.dumps(v))
def command(b): return ['SYNTHETIC', b]

def fixture(root, layout=None):
    c = tiny_layout() if layout is None else layout; ref = reference(c); workers = []
    for index, b in enumerate(BLOCKS):
        d = root/b; out = d/'output'; out.mkdir(parents=True)
        start = f'2026-09-28T00:0{index}:00+00:00'; end = f'2026-09-28T00:0{index}:30+00:00'
        launch = dict(argv=command(b), pid=100+index, launch_requested_utc=start)
        process = dict(**launch, status='CHILD_COMPLETE', returncode=0, automatic_retry=False,
                       exit_observed_utc=end, elapsed_seconds=30)
        write(d/'LAUNCH.json', launch); write(d/'PROCESS.json', process)
        workers.append(dict(block=b, lifecycle=process))
        (d/'stdout.log').write_text('SYNTHETIC\n'); (d/'stderr.log').write_text('')
        records = arrays(c, b); rows = []
        for key, p in records.items():
            path = out/f'{len(rows):03d}.npz'
            np.savez(path, trial_ids=np.array(p['trial_ids'], np.int64), logits=p['logits'], nll=p['nll'])
            rows.append(dict(key=list(key), file=path.name, **identity(path)))
        wanted = sorted({(k[1], k[2]) for k in records}); reports = []; resources = []
        for domain, name in wanted:
            checks = [dict(path='model_dict.'+n, mixture=m, masked=mask, max_abs=0., mean_max_abs=0.)
                      for n in NAMES for m in ('ones', 'signed') for mask in (False, True)]
            reports.append(dict(domain=domain, pass_name=name, report=dict(status='G5_FIXED_FEATURE_PASS',
                pass_name=name, reference='numpy_float64_independent', atol=2e-6, rtol=2e-6, checks=checks)))
            resources.append(dict(domain=domain, pass_name=name, started_utc=start, finished_utc=end,
                elapsed_seconds=.1, cuda_max_memory_allocated_bytes=None, cuda_max_memory_reserved_bytes=None,
                host_max_rss_ru_maxrss=1024, ru_maxrss_unit='bytes'))
        summary = dict(process_started_utc=start, process_finished_utc=end, pass_resources=resources,
                       runtime_values={}, gain_formula_reports=reports, predictions=sum(map(len, inventory(c, b).values())),
                       input_identity_sha256='0'*64, historical_bridge_completed=True)
        load = dict(loaded_trainable_numel_ratio=1., trainable_numel=62622520, loaded_trainable_numel=62622520,
                    prefix_rule='exact', missing_keys=[], unexpected_keys=[], shape_mismatches={}, dtype_mismatches={},
                    native_preprocessing='selftrain_singleton_per_example_leveling')
        env = dict(python='SYNTHETIC', torch='SYNTHETIC', cuda=None, cudnn=None, device_name=None,
                   hostname='SYNTHETIC', slurm_job_id='123', slurm_cpus_per_task='8')
        write(out/'ENVIRONMENT_PRECHECK.json', dict(
            status='FINE_ENVIRONMENT_PRECHECK_PASS_NOT_INFERENCE_VERIFIED',
            job_id='123', pid=100+index, release_sha256='sha', environment=env, runtime_values={}))
        write(out/'WORKER.json', dict(status='FINE_WORKER_FINISHED_NOT_JOB_VERIFIED', block=b, job_id='123', pid=100+index,
              release_sha256='sha', checkpoint_sha256=FORMAL_SHA, contract_sha256=contract_sha(c),
              source_input_postchecks_completed=True, outputs=rows, execution=summary, environment=env,
              environment_precheck=identity(out/'ENVIRONMENT_PRECHECK.json'),
              load_report=load, array_check=verify_arrays(c, records, b, reference=ref)))
    write(root/'RUN.json', dict(status='FINE_ALPHA_RUNNING', started_utc='2026-09-28T00:00:00+00:00',
          release_sha256='sha', job_id='123', budget=BUDGET, blocks=list(BLOCKS), automatic_retry=False))
    write(root/'VERIFY_REQUEST.json', dict(blocks=list(BLOCKS), release_sha256='sha', job_id='123', workers=workers))
    return c, ref

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.layout, self.ref = fixture(self.root)
    def check(self, production=False):
        return verify(self.root, self.layout, 'sha', '123', command, self.ref, production=production)
    def mutate(self, relative, change, pattern):
        p = self.root/relative; v = json.loads(p.read_text()); change(v); write(p, v)
        with self.assertRaisesRegex(ValueError, pattern): self.check()
    def test_complete(self):
        result, records = self.check()
        self.assertEqual(result['status'], 'SYNTHETIC_FINE_ALPHA_ARCHIVE_PASS')
        self.assertEqual(result['predictions'], 238); self.assertEqual(len(records), 204)
        self.assertEqual(result['cold_processes'], 2); self.assertEqual(result['anchor_job'], '756262')
        self.assertEqual(result['anchor_check'], 'NOT_IN_JOB_OFFLINE_PENDING')
        self.assertFalse(result['scientific_report_complete'])
    def test_synthetic_cannot_pass_production(self):
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_PRODUCTION_ENVIRONMENT'): self.check(production=True)
    def test_argv(self):
        self.mutate('B/PROCESS.json', lambda v: v.update(argv=['wrong']), 'LIFECYCLE_ARGV')
    def test_job(self):
        self.mutate('A/output/WORKER.json', lambda v: v.update(job_id='124'), 'WORKER_BINDING')
    def test_missing_formula(self):
        self.mutate('A/output/WORKER.json', lambda v: v['execution']['gain_formula_reports'].pop(), 'FORMULA_INVENTORY')
    def test_missing_resources(self):
        self.mutate('A/output/WORKER.json', lambda v: v['execution']['pass_resources'].pop(), 'PASS_RESOURCES')
    def test_missing_provenance(self):
        self.mutate('A/output/WORKER.json', lambda v: v['environment'].pop('torch'), 'PROVENANCE_ENVIRONMENT')
    def test_bad_load(self):
        self.mutate('A/output/WORKER.json', lambda v: v['load_report'].update(loaded_trainable_numel=1), 'LOAD_COVERAGE')
    def test_window(self):
        self.mutate('A/output/WORKER.json', lambda v: v['execution'].update(process_started_utc='2026-09-27T00:00:00+00:00'), 'PROCESS_WINDOW')
    def test_input_binding(self):
        self.mutate('B/output/WORKER.json', lambda v: v['execution'].update(input_identity_sha256='1'*64), 'COLD_PROCESS_OR_INPUTS')
    def test_metadata_prediction_count(self):
        self.mutate('A/output/WORKER.json', lambda v: v['execution'].update(predictions=1), 'EXECUTION_REPORT')
    def test_file_changed(self):
        p = self.root/'A/output/000.npz'; p.write_bytes(p.read_bytes()+b'wrong')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_SHA'): self.check()
    def test_failed_marker(self):
        write(self.root/'FAILED.json', {})
        with self.assertRaisesRegex(ValueError, 'FAILED_ROOT'): self.check()
    def test_request_reorder(self):
        self.mutate('VERIFY_REQUEST.json', lambda v: v['workers'].reverse(), 'PROCESS_BINDING')
    def test_symlink(self):
        (self.root/'link').symlink_to(self.root/'RUN.json')
        with self.assertRaisesRegex(ValueError, 'SYMLINK'): self.check()
    def test_extra_files(self):
        (self.root/'B/output/extra').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FILES'): self.check()
    def test_precheck_missing(self):
        (self.root/'A/output/ENVIRONMENT_PRECHECK.json').unlink()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FILES'): self.check()
    def test_precheck_modified(self):
        p = self.root/'A/output/ENVIRONMENT_PRECHECK.json'
        p.write_text(p.read_text()+' ')
        with self.assertRaisesRegex(ValueError, 'PRECHECK_SHA'): self.check()
    def test_precheck_wrong_job_even_with_updated_hash(self):
        p = self.root/'A/output/ENVIRONMENT_PRECHECK.json'
        v = json.loads(p.read_text()); v['job_id'] = '456'; write(p, v)
        self.mutate('A/output/WORKER.json', lambda m: m.update(environment_precheck=identity(p)), 'PRECHECK_BINDING')

if __name__ == '__main__': unittest.main()
