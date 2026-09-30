"""Explicit orchestration doubles plus original validation of saved synthetic arrays."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import runtime as r
import evidence

ARCHIVE=HERE.parents[3]/'docs/superpowers/evidence/g2-archive-local-20260917T034258Z-47rh9pu7/D'
JOB='7770017'
RELEASE='a'*64
FREEZES={p:str(i)*64 for i,p in enumerate(r.ORDER,1)}


def observation(profile,status='NUMERIC_ACCEPT'):
    return dict(status='G2_WORKER_EVIDENCE_VERIFIED',execution_valid=True,
        job_id=JOB,profile=profile,pid=100+r.ORDER.index(profile),release_sha256=RELEASE,
        input_freeze_sha256=FREEZES[profile],trial_identity_sha256='f'*64,
        numeric=dict(status=status,atol=1e-6,scientific_acceptance=False),
        production_interference_validated=False,ready_for_full_evaluation=False)


class MatrixTests(unittest.TestCase):
    def setup_callbacks(self,statuses=None):
        self.launched=[]
        self.saved={}
        self.values={p:observation(p,(statuses or {}).get(p,'NUMERIC_ACCEPT')) for p in r.ORDER}
        def launch(p,seconds):
            self.launched.append(p)
            self.assertGreater(seconds,0)
            self.assertLessEqual(seconds,1800)
            return dict(pid=self.values[p]['pid'],returncode=0,error=None,elapsed_seconds=1.)
        self.launch=launch
        self.verify=lambda p,process,remaining:self.values[p]
        self.persist=lambda p,v:self.saved.setdefault(p,copy.deepcopy(v))

    def run_matrix(self):
        return r.run_matrix(job=JOB,release_sha=RELEASE,freezes=FREEZES,
                           launch=self.launch,verify=self.verify,persist=self.persist)

    def test_fixed_order_and_preference(self):
        self.setup_callbacks()
        result=self.run_matrix()
        self.assertEqual(self.launched,list(r.ORDER))
        self.assertEqual(result['candidate'],'E')
        self.assertFalse(result['ready_for_full_evaluation'])

    def test_numeric_diff_does_not_stop(self):
        self.setup_callbacks({'R':'NUMERIC_DIFF','E':'NUMERIC_DIFF'})
        result=self.run_matrix()
        self.assertEqual(self.launched,list(r.ORDER))
        self.assertEqual(result['candidate'],'C')

    def test_no_acceptable_cell_no_relaxation(self):
        self.setup_callbacks({p:'NUMERIC_DIFF' for p in r.ORDER})
        result=self.run_matrix()
        self.assertTrue(result['execution_valid'])
        self.assertIsNone(result['candidate'])
        self.assertEqual(result['decision'],'NO_NUMERIC_CANDIDATE')

    def test_nonzero_exit_stops_remaining(self):
        self.setup_callbacks()
        real=self.launch
        self.launch=lambda p,s:dict(real(p,s),returncode=2 if p=='C' else 0)
        result=self.run_matrix()
        self.assertEqual(self.launched,['R','C'])
        self.assertEqual(result['cells']['D']['status'],'NOT_RUN')
        self.assertIsNone(result['candidate'])

    def test_deadline_stops_remaining(self):
        self.setup_callbacks()
        real=self.launch
        self.launch=lambda p,s:dict(real(p,s),elapsed_seconds=1800.)
        result=self.run_matrix()
        self.assertEqual(self.launched,['R'])
        self.assertEqual(result['status'],'EXECUTION_INVALID')

    def test_total_deadline_before_launch(self):
        self.setup_callbacks()
        with mock.patch.object(r.time,'monotonic',side_effect=[0.,10000.,10000.]):
            result=self.run_matrix()
        self.assertEqual(self.launched,[])
        self.assertEqual(result['decision'],'STOP_EXECUTION_INVALID')

    def test_verify_failure_stops(self):
        self.setup_callbacks()
        self.verify=mock.Mock(side_effect=ValueError('invalid artifact'))
        result=self.run_matrix()
        self.assertEqual(self.launched,['R'])
        self.assertEqual(result['cells']['C']['status'],'NOT_RUN')

    def test_content_gate_not_execution_gate(self):
        self.setup_callbacks()
        self.values['R']['status']='G2_ARCHIVE_CONTENT_VERIFIED'
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')

    def test_worker_pid_reuse(self):
        self.setup_callbacks()
        self.values['C']['pid']=self.values['R']['pid']
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')
        self.assertEqual(self.launched,['R','C'])

    def test_trial_identity_drift(self):
        self.setup_callbacks()
        self.values['C']['trial_identity_sha256']='e'*64
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')

    def test_wrong_freeze(self):
        self.setup_callbacks()
        self.values['R']['input_freeze_sha256']='0'*64
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')

    def test_wrong_release(self):
        self.setup_callbacks()
        self.values['R']['release_sha256']='0'*64
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')

    def test_relaxed_atol_rejected(self):
        self.setup_callbacks()
        self.values['R']['numeric']['atol']=1e-2
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')

    def test_persistence_failure_stops(self):
        self.setup_callbacks()
        def persist(p,v):
            if p!='MATRIX': raise OSError('disk full')
            self.saved[p]=v
        self.persist=persist
        self.assertEqual(self.run_matrix()['status'],'EXECUTION_INVALID')
        self.assertEqual(self.launched,['R'])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='g2-runtime-double-')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        (self.root/'attempts').mkdir(mode=0o700)
        self.diag=types.SimpleNamespace(DIAGNOSTIC_ROOT=self.root,_G2_PROFILE='D')
        self.post=mock.Mock()
        self.env=mock.patch.dict(os.environ,SLURM_JOB_ID=JOB)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.options=dict(job=JOB,freeze_sha='1'*64,production_bytes={},parent_path=self.root/'fake',
                          release_sha=RELEASE,source_check=self.post)

    def execute(self,celltype,consumer):
        # Explicit local doubles: never call the native run path or forge real
        # capability. The public worker API contains no CPU/hermetic flag.
        with mock.patch.object(r.sys,'platform','linux'),mock.patch.object(r.sys,'version','3.11.5 synthetic'),\
             mock.patch.object(r.cell_api.scratch_api,'cold'),mock.patch.object(r.cell_api,'ProductionCell',celltype),\
             mock.patch.object(r.store,'bind',return_value={}),mock.patch.object(r.store,'Consumer',consumer):
            return r.run_worker(None,self.diag,**self.options)

    def fake(self,*,after_archive_failure=False):
        root=self.root
        class Cell:
            def __init__(self,*args,**kwargs): self.inputs=types.SimpleNamespace(freeze={'trials':[]})
            def run(self,consume):
                receipt=consume({'trust_domain':'production'},{})
                if after_archive_failure: raise RuntimeError('cleanup failed')
                return dict(status='G2_PRODUCTION_CELL_STORED_CANDIDATE',archive_receipt=receipt)
        class Sink:
            def __init__(self,path,*args,**kwargs):
                self.path=path
                path.mkdir(mode=0o700)
            def __call__(self,value,meta):
                r.process_api.write_once(self.path/'manifest.json',dict(scope='CONTROL_FLOW_DOUBLE_ONLY'))
                return dict(status='SYNTHETIC_RECEIPT_NO_EXECUTION_AUTHORITY')
        return Cell,Sink

    def test_callback_writes_then_success_after_close(self):
        result=self.execute(*self.fake())
        self.assertEqual(result['status'],'G2_WORKER_STORED')
        self.assertFalse(result['independent_results_verified'])
        self.assertTrue((self.root/'attempts'/('slurm-'+JOB)/'ARCHIVE_RECEIPT.json').exists())
        self.assertEqual(self.post.call_count,2)

    def test_cleanup_failure_keeps_archive_but_no_success(self):
        result=self.execute(*self.fake(after_archive_failure=True))
        self.assertEqual(result['status'],'EXECUTION_INVALID')
        self.assertIsNone(result['result'])
        self.assertIn('ARCHIVE_RECEIPT.json',result['inventory'])

    def test_attempt_never_reused(self):
        self.execute(*self.fake())
        with self.assertRaises(FileExistsError): self.execute(*self.fake())

    def test_constructor_failure_terminal(self):
        result=self.execute(mock.Mock(side_effect=ValueError('input changed')),None)
        self.assertEqual(result['status'],'EXECUTION_INVALID')
        self.assertEqual(set(result['inventory']),{'STARTED.json'})

    def test_postcheck_failure_terminal(self):
        self.post.side_effect=[None,ValueError('source changed')]
        result=self.execute(*self.fake())
        self.assertEqual(result['status'],'EXECUTION_INVALID')
        self.assertFalse(result['source_postcheck'])


class EnvironmentTests(unittest.TestCase):
    def environment(self,**changes):
        binding=object.__new__(r.cell_api.scratch_api.Binding)
        binding.home='/home/s2510040'
        binding.profile='R'
        binding.paths={'TMPDIR':'tmp','TORCHINDUCTOR_CACHE_DIR':'torchinductor'}
        source=dict(HOME=binding.home,PATH='/usr/bin:/bin',USER='s2510040',
                    SLURM_JOB_ID=JOB,SLURM_CPUS_PER_TASK='8',CUDA_VISIBLE_DEVICES='0',
                    PYTHONPATH='/untrusted',LD_PRELOAD='/untrusted',CUBLAS_WORKSPACE_CONFIG='wrong',**changes)
        return r.worker_environment(binding,source,'/tmp/audattn_g2_'+JOB,JOB)

    def test_only_declared_environment(self):
        result=self.environment()
        self.assertNotIn('PYTHONPATH',result)
        self.assertNotIn('LD_PRELOAD',result)
        self.assertEqual(result['CUBLAS_WORKSPACE_CONFIG'],':4096:8')
        self.assertEqual(result['CUDA_VISIBLE_DEVICES'],'0')

    def test_real_home_and_private_profile_cache(self):
        result=self.environment()
        self.assertEqual(result['HOME'],'/home/s2510040')
        self.assertEqual(result['TORCHINDUCTOR_CACHE_DIR'],'/tmp/audattn_g2_'+JOB+'/R-observed/torchinductor')

    def test_cpu_count_missing_rejected(self):
        binding=mock.Mock()
        with self.assertRaises(RuntimeError):
            r.worker_environment(binding,dict(SLURM_JOB_ID=JOB,CUDA_VISIBLE_DEVICES='0'),'/tmp/audattn_g2_'+JOB,JOB)
        binding.environment.assert_not_called()

    def test_wrong_role_root_rejected(self):
        binding=object.__new__(r.cell_api.scratch_api.Binding)
        binding.home='/home/s2510040'
        binding.profile='R'
        binding.paths={}
        with self.assertRaises(RuntimeError):
            r.worker_environment(binding,dict(HOME=binding.home,SLURM_JOB_ID=JOB,SLURM_CPUS_PER_TASK='8',
                                              CUDA_VISIBLE_DEVICES='0'),'/tmp/not-this-job',JOB)


class SavedSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=HERE.parent/'g2_worker_20260916/cell_bridge.py'
        raw=r.store.pinned(path,'9b7e033ac8796e142782ea4dcc59ec527bd97538f51ccf8d4bea0caa1cd7d59d')
        spec=importlib.util.spec_from_file_location('g2_runtime_semantic_bridge',path)
        cls.bridge=importlib.util.module_from_spec(spec)
        exec(compile(raw,str(path),'exec'),vars(cls.bridge))
        fixed=HERE.parents[3]/'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
        cls.diag=cls.bridge.load_candidate(fixed/'D/diagnose_batch_invariance.py','D')

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='g2-semantic-negative-')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()/'arrays'
        shutil.copytree(ARCHIVE/'arrays',self.root)
        self.receipt=json.loads((ARCHIVE/'RECEIPT.json').read_bytes())

    def verify(self):
        return evidence.pass_semantics(self.root,self.receipt,bridge=self.bridge,diag=self.diag)

    def tamper(self,mutate):
        path=self.root/'manifest.json'
        doc=json.loads(path.read_bytes())
        original=doc['passes'][0]['original_pass_evidence']
        mutate(original['payload'])
        # Deliberate re-signing in corruption tests only, never the writer.
        original['commitment']['binding_sha256']=r.store.sha(r.store.canonical(original['payload']))
        self.receipt['pass_commitments'][0]=original['commitment']['binding_sha256']
        raw=r.store.canonical(doc)
        path.write_bytes(raw)
        self.receipt.update(archive_manifest_sha256=r.store.sha(raw),archive_manifest_size=len(raw))

    def test_saved_original_pass_checks(self):
        result=self.verify()
        self.assertEqual(result['status'],'G2_ORIGINAL_PASS_SEMANTICS_VERIFIED')
        self.assertFalse(result['live_model_authority_issued'])

    def test_runtime_drift_rejected(self):
        self.tamper(lambda p:p['boundaries']['metadata']['runtime'].update(cudnn_benchmark=True))
        with self.assertRaises(RuntimeError): self.verify()

    def test_load_report_rejected(self):
        self.tamper(lambda p:p['boundaries']['metadata']['load_report'].update(missing_keys=['weight']))
        with self.assertRaises(RuntimeError): self.verify()

    def test_changed_mutation_guard_rejected(self):
        self.tamper(lambda p:p['boundaries']['scene_features']['guards'][0]['after'].update(object_id=0))
        with self.assertRaises(RuntimeError): self.verify()

    def test_wrong_pass_batch_rejected(self):
        self.tamper(lambda p:p.update(batch_size=1))
        with self.assertRaises(RuntimeError): self.verify()

    def test_wrong_state_claim_rejected(self):
        self.receipt['cell_summary']['state']['rng']['rng_changed']=True
        with self.assertRaises(RuntimeError): self.verify()

    def test_binder_is_narrow_copy(self):
        method=evidence._binder(self.bridge,self.diag)
        self.assertNotIn('HOME',method.__globals__['_WORKER_WRITE_PATHS'])
        self.assertIn('HOME',self.diag._WORKER_WRITE_PATHS)


if __name__=='__main__':
    os.umask(0o077)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in
                            (MatrixTests,WorkerTests,EnvironmentTests,SavedSemanticsTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print('G2_RUNTIME_TEST_REPORT='+json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
         errors=len(result.errors),skipped=len(result.skipped),
         scope='CONTROL_FLOW_DOUBLES_AND_SAVED_SYNTHETIC_PASS_SEMANTICS',
         production_model_loaded=False,jobs_submitted=0,remote_operations=0),sort_keys=True),flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)
