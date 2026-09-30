"""Manufactured CPU archives exercise the REAL verifier, not real GPU claims."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from architecture_adapter import NAMES
from e1_artifacts import identity
from e1_inputs import build_contract
from e1_worker_archive import EXPECTED_RUNTIME
from e2_catalog import stage_record
from e2_endpoint import probe_spec
from e2_history_bridge import read_reference,verify_history
from e2_matrix import expected_records
from e2_pipeline import PILOT_WORKERS,WORKERS
from e2_stage_archive import archive_stage
from e2_verify_pipeline import verify_pipeline

START='2026-09-28T00:00:00+00:00'
END='2026-09-28T00:01:00+00:00'
def command(r,m,out=None): return ['synthetic-worker',str(r),m]
def write(p,v): p.write_text(json.dumps(v))

def fixture(root,pilot=True):
    c=build_contract(); ref=read_reference(); workers=PILOT_WORKERS if pilot else WORKERS; rows=[]
    for index,(label,r,mode) in enumerate(workers):
        d=root/label; out=d/'output'; out.mkdir(parents=True)
        for name in ('stdout.log','stderr.log'): (d/name).write_bytes(b'SYNTHETIC FIXTURE\n')
        launch=dict(argv=command(r,mode),pid=index+100,launch_requested_utc=START)
        lifecycle=dict(**launch,returncode=0,status='CHILD_COMPLETE',automatic_retry=False,
                       exit_observed_utc=END,elapsed_seconds=60)
        write(d/'LAUNCH.json',launch); write(d/'PROCESS.json',lifecycle)
        rows.append(dict(label=label,completed_epochs=r,mode=mode,lifecycle=lifecycle))
        records={}
        for key,ids in expected_records(c,r,mode).items():
            value=dict(trial_ids=ids,logits=np.zeros((len(ids),800),np.float32),nll=np.full(len(ids),np.log(800),np.float32))
            if r==40 and key[2]=='alpha_1':
                old=ref[key]; indices=[old['trial_ids'].index(i) for i in ids]
                value.update(logits=old['logits'][indices],nll=old['nll'][indices])
            records[key]=value
        passes=sorted({(k[1],k[2]) for k in records})
        summary=dict(process_started_utc=START,process_finished_utc=END,runtime_values=EXPECTED_RUNTIME,
            predictions=sum(len(v['trial_ids']) for v in records.values()),pass_resources=[],gain_formula_reports=[])
        for domain,name in passes:
            summary['pass_resources'].append(dict(domain=domain,pass_name=name,started_utc=START,finished_utc=END,
                elapsed_seconds=60,cuda_max_memory_allocated_bytes=1024,cuda_max_memory_reserved_bytes=2048,
                host_max_rss_ru_maxrss=4096,ru_maxrss_unit='KiB'))
            checks=[dict(path='model_dict.'+n,mixture=m,masked=b,max_abs=0.,mean_max_abs=0.)
                    for n in NAMES for m in ('ones','signed') for b in (False,True)]
            summary['gain_formula_reports'].append(dict(domain=domain,pass_name=name,report=dict(
                status='G5_FIXED_FEATURE_PASS',pass_name=name,reference='numpy_float64_independent',atol=2e-6,rtol=2e-6,checks=checks)))
        load=dict(checkpoint_sha256=stage_record(r)['sha256'],completed_epochs=r,production_provenance_verified=True,
                  loaded_trainable_numel_ratio=1.,trainable_numel=62622520,loaded_trainable_numel=62622520,strict=True,key_rewrite=False)
        metadata=archive_stage(out/'archive',c,r,records,load,summary,mode)
        ep=out/'endpoint'; ep.mkdir(); inventory=[]
        for name in ('original','alpha_1'):
            for domain,bi,condition,ids in probe_spec(c):
                file=f'{len(inventory):02d}.npz'
                np.savez(ep/file,trial_ids=np.array(ids,np.int64),logits=np.zeros((len(ids),800),np.float32),nll=np.full(len(ids),np.log(800),np.float32))
                inventory.append(dict(file=file,key=[name,domain,condition],**identity(ep/file)))
        env=dict(python='3.11.5',torch='2.1.1+cu118',cuda='11.8',cudnn=8700,device_name='SYNTHETIC A100',hostname='SYNTHETIC',slurm_job_id='777',slurm_cpus_per_task='8')
        endpoint=dict(status='E2_STAGE_ENDPOINT_BITS_PASS',predictions=126,
            batches=[dict(domain=d,batch_index=b,condition=k,trial_ids=ids) for d,b,k,ids in probe_spec(c)])
        write(out/'RESULT.json',dict(status='E2_STAGE_WORKER_COMPLETE_NOT_EXPERIMENT_VERIFIED',stage=stage_record(r),
            mode=mode,environment=env,endpoint=endpoint,endpoint_files=inventory,array_check=metadata['array_check'],
            history_bridge=verify_history(records,pilot=pilot) if r==40 else None))
    write(root/'VERIFY_REQUEST.json',dict(workers=rows))
    return c

class FullVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.root=Path(cls.tmp.name); cls.c=fixture(cls.root)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def verify(self): return verify_pipeline(self.root,self.c,command,job_id='777',pilot=True)
    def test_complete_synthetic_pilot_archive(self):
        result=self.verify(); self.assertEqual(result['predictions'],2709)
        self.assertEqual(result['scope'],'native_pilot_not_trajectory')
        self.assertFalse(result['scientific_report_complete'])
    def mutate(self,relative,change,pattern):
        path=self.root/relative; raw=path.read_bytes(); value=json.loads(raw); change(value); write(path,value)
        try:
            with self.assertRaisesRegex(ValueError,pattern): self.verify()
        finally: path.write_bytes(raw)
    def test_wrong_job(self):
        self.mutate('stage_40/output/RESULT.json',lambda v:v['environment'].update(slurm_job_id='778'),'RESULT_JOB')
    def test_incomplete_loading(self):
        self.mutate('stage_40/output/archive/STAGE.json',lambda v:v['load_report'].update(loaded_trainable_numel=1),'LOAD_COVERAGE')
    def test_missing_environment(self):
        self.mutate('stage_40/output/RESULT.json',lambda v:v['environment'].pop('torch'),'PROVENANCE_ENVIRONMENT')
    def test_wrong_runtime(self):
        self.mutate('stage_40/output/archive/STAGE.json',lambda v:v['execution']['runtime_values'].update(matmul_tf32=True),'PROVENANCE_RUNTIME')
    def test_missing_resources(self):
        self.mutate('stage_40/output/archive/STAGE.json',lambda v:v['execution']['pass_resources'].pop(),'PASS_RESOURCES')
    def test_missing_formula(self):
        self.mutate('stage_40/output/archive/STAGE.json',lambda v:v['execution']['gain_formula_reports'].pop(),'FORMULA_INVENTORY')
    def test_endpoint_report_changed(self):
        self.mutate('stage_40/output/RESULT.json',lambda v:v['endpoint'].update(predictions=1),'ENDPOINT_REPORT')
    def test_wrong_stage(self):
        self.mutate('stage_40/output/RESULT.json',lambda v:v.update(stage=stage_record(0)),'RESULT_STAGE')
    def test_process_window(self):
        self.mutate('stage_40/LAUNCH.json',lambda v:v.update(pid=999),'LIFECYCLE_PID')
    def test_wrong_worker_order(self):
        self.mutate('VERIFY_REQUEST.json',lambda v:v['workers'].reverse(),'WORKER_ORDER')
    def test_full_matrix_real_verifier_synthetic_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); c=fixture(root,pilot=False)
            self.assertEqual(verify_pipeline(root,c,command,job_id='777')['predictions'],91134)

if __name__=='__main__': unittest.main()
