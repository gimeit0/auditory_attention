"""Synthetic archives only: no checkpoint, CUDA or remote execution."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from e0_archive_harness import identity, write_json
from e0_layout_reference import canonical
from e1_execution import contract, inventory
from e1_worker_archive import verify_archive,verify_g5_report,EXPECTED_RUNTIME,verify_provenance
from architecture_adapter import NAMES

def synthetic_formula(p):
    return dict(status='G5_FIXED_FEATURE_PASS',pass_name=p,atol=2e-6,rtol=2e-6,
                reference='numpy_float64_independent',checks=[
                    dict(path='model_dict.'+n,mixture=m,masked=b,max_abs=0.,mean_max_abs=0.)
                    for n in NAMES for m in ('ones','signed') for b in (False,True)])


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = contract()
        self.workers = [dict(label=p, pid=i+100, returncode=0)
                        for i, p in enumerate(('A', 'B'))]
        self.metadata = {}
        for w in self.workers:
            d = self.root / w['label']
            d.mkdir()
            for name in ('stdout.log', 'stderr.log', 'LAUNCH.json'):
                (d / name).write_text('')
            rows, passes, count = [], set(), 0
            for key, ids in inventory(self.c).items():
                if key[0] != w['label']:
                    continue
                name = f'{len(rows):03d}.npz'
                np.savez(d/name, trial_ids=np.array(ids, dtype=np.int64),
                         logits=np.zeros((len(ids), 800), np.float32),
                         nll=np.full(len(ids), np.log(800), np.float32))
                rows.append(dict(key=list(key), file=name, **identity(d/name)))
                passes.add((key[1], key[2]))
                count += len(ids)
            formulas = [dict(domain=domain, pass_name=p, report=synthetic_formula(p))
                        for domain,p in sorted(passes)]
            resources=[dict(domain=domain,pass_name=p,started_utc='2026-09-27T00:00:00+00:00',finished_utc='2026-09-27T00:00:01+00:00',
                            elapsed_seconds=1.0,cuda_max_memory_allocated_bytes=1024,cuda_max_memory_reserved_bytes=2048,
                            host_max_rss_ru_maxrss=1,ru_maxrss_unit='KiB') for domain,p in sorted(passes)]
            write_json(d/'STAGES.json', dict(predictions=count, gain_formula_reports=formulas,
                       process_started_utc='2026-09-27T00:00:00+00:00',process_finished_utc='2026-09-27T00:00:02+00:00',
                       runtime_values=dict(EXPECTED_RUNTIME),pass_resources=resources))
            m = dict(process=w['label'], pid=w['pid'], job_id='900001',
                     environment=dict(python='3.11.5',torch='2.1.1+cu118',cuda='11.8',cudnn=8700,device_name='A100 synthetic fixture',
                                      hostname='synthetic',slurm_job_id='900001',slurm_cpus_per_task='8'),
                     contract_sha256=hashlib.sha256(canonical(self.c)).hexdigest(),
                     checkpoint_sha256=self.c['checkpoint_sha256'], postchecks_completed=True,
                     load_report=dict(loaded_trainable_numel_ratio=1,
                                      trainable_numel=10, loaded_trainable_numel=10),
                     outputs=rows, stages=identity(d/'STAGES.json'))
            write_json(d/'WORKER.json', m)
            self.metadata[w['label']] = m

    def verify(self):
        return verify_archive(self.root, self.c, self.workers, '900001')

    def test_roundtrip(self):
        self.assertTrue(self.verify()['verified'])

    def test_array_tamper(self):
        with (self.root/'A/000.npz').open('ab') as f:
            f.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_SHA'):
            self.verify()

    def test_process_identity(self):
        self.workers[0]['pid'] += 42
        with self.assertRaisesRegex(ValueError, 'WORKER_BINDING'):
            self.verify()

    def test_stage_tamper(self):
        (self.root/'A/STAGES.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'STAGES_SHA'):
            self.verify()

    def test_extra_file(self):
        (self.root/'A/unexpected').touch()
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_INVENTORY'):
            self.verify()

    def rewrite(self, label, stages=None, worker=None):
        d = self.root/label
        if stages is not None:
            s = json.loads((d/'STAGES.json').read_text()); stages(s)
            (d/'STAGES.json').write_bytes(canonical(s))
            self.metadata[label]['stages'] = identity(d/'STAGES.json')
        m = self.metadata[label]
        if worker is not None: worker(m)
        (d/'WORKER.json').write_bytes(canonical(m))

    def test_missing_environment_rejected(self):
        self.rewrite('A', worker=lambda m: m.pop('environment'))
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_ENVIRONMENT'):
            self.verify()

    def test_missing_pass_resources_rejected(self):
        self.rewrite('A', stages=lambda s: s.pop('pass_resources'))
        with self.assertRaisesRegex(ValueError, 'PROVENANCE_FIELDS'):
            self.verify()

    def test_pass_resource_pass_set_rejected(self):
        self.rewrite('B', stages=lambda s: s['pass_resources'].pop())
        with self.assertRaisesRegex(ValueError, 'PASS_RESOURCES'):
            self.verify()

    def test_pass_resource_memory_type_rejected(self):
        def bad(s): s['pass_resources'][0]['cuda_max_memory_allocated_bytes'] = 'a lot'
        self.rewrite('A', stages=bad)
        with self.assertRaisesRegex(ValueError, 'PASS_RESOURCE_MEMORY'):
            self.verify()

    def test_null_runtime_rejected(self):
        self.rewrite('A',stages=lambda s:s.update(runtime_values=None))
        with self.assertRaisesRegex(ValueError,'PROVENANCE_RUNTIME'): self.verify()

    def test_wrong_runtime_rejected(self):
        self.rewrite('A',stages=lambda s:s['runtime_values'].update(matmul_tf32=True))
        with self.assertRaisesRegex(ValueError,'PROVENANCE_RUNTIME'): self.verify()

    def test_null_gpu_rejected(self):
        self.rewrite('A',worker=lambda m:m['environment'].update(device_name=None))
        with self.assertRaisesRegex(ValueError,'PRODUCTION_ENVIRONMENT'): self.verify()

    def test_empty_version_rejected(self):
        self.rewrite('A',worker=lambda m:m['environment'].update(torch=''))
        with self.assertRaisesRegex(ValueError,'PRODUCTION_ENVIRONMENT'): self.verify()

    def test_null_gpu_memory_rejected(self):
        self.rewrite('A',stages=lambda s:s['pass_resources'][0].update(cuda_max_memory_allocated_bytes=None))
        with self.assertRaisesRegex(ValueError,'PRODUCTION_MEMORY'): self.verify()

    def test_invalid_timestamp_rejected(self):
        self.rewrite('A',stages=lambda s:s.update(process_started_utc='bad'))
        with self.assertRaisesRegex(ValueError,'TIMESTAMPS'): self.verify()

    def test_reversed_time_rejected(self):
        self.rewrite('A',stages=lambda s:s.update(process_finished_utc='2026-09-26T00:00:00+00:00'))
        with self.assertRaisesRegex(ValueError,'TIME_ORDER'): self.verify()

    def test_cpu_fixture_mode_is_explicit(self):
        m=self.metadata['A'];s=json.loads((self.root/'A/STAGES.json').read_text())
        s['runtime_values']=None;m['environment']['device_name']=None
        verify_provenance(m,s,{(r['domain'],r['pass_name']) for r in s['pass_resources']},production=False)
        with self.assertRaises(ValueError):
            verify_provenance(m,s,{(r['domain'],r['pass_name']) for r in s['pass_resources']})


class FormulaReportTests(unittest.TestCase):
    def test_valid(self): verify_g5_report(synthetic_formula('alpha_1'),'alpha_1')
    def test_empty(self):
        r=synthetic_formula('alpha_1');r['checks']=[{}]*32
        with self.assertRaises(ValueError): verify_g5_report(r,'alpha_1')
    def test_duplicate(self):
        r=synthetic_formula('alpha_1');r['checks'][0]=r['checks'][1]
        with self.assertRaisesRegex(ValueError,'G5_CHECK_IDENTITY'): verify_g5_report(r,'alpha_1')
    def test_nan(self):
        r=synthetic_formula('alpha_1');r['checks'][0]['max_abs']=float('nan')
        with self.assertRaisesRegex(ValueError,'G5_ERROR_VALUE'): verify_g5_report(r,'alpha_1')

if __name__ == '__main__':
    unittest.main()
