import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
import torch
from native_batch_provider import NativeBatchProvider
from two_process_supervisor import run_pair
from audited_model_session import audited_session
from test_loaded_model_adapter import SyntheticBase

class NativeTests(unittest.TestCase):
    def make(self,fault=None):
        bank=pd.DataFrame(dict(trial_id=[0,1],target_label=[3,4],scene_kind=['mixed','clean'],
                               distractor_1_label=[7,0],control_subset=[1,0]))
        layout={'batches':[[0,1]],'condition_batches':{'correct':[[0,1]],'shuffled':[[0]],'silent':[[0]],'distractor':[[0]]}}
        base=SyntheticBase()
        scene=torch.tensor([[1.,2.],[3.,4.]])
        hashes=dict(enumerate(base._tensor_hashes(scene)))
        if fault=='hash': hashes[0]='wrong'
        class Cache:
            def __init__(self,max_items): self.max_items=max_items
        def raw(frame,cache,clips,snr_errors):
            snr_errors.append(float('nan') if fault=='snr' else 0.)
            return scene.clone()
        def correct(frame,*args):
            if fault=='mutation': frame.loc[frame.index[0],'target_label']=99
            return torch.tensor([[5.,6.],[0.,0.]])
        def role(frame,name,*args): return torch.full((len(frame),2),8. if name=='shuffled_cue' else 9.)
        return NativeBatchProvider(base,bank,hashes,layout,Path('/unused'),Cache,raw,correct,role)

    def test_native_order_controls_and_regeneration(self):
        p=self.make()
        for repeat in range(2):
            s,c,l,probes=p(0,'correct',[0,1])
            self.assertEqual(probes.tolist(),[7,0])
            for condition,value in [('shuffled',8.),('silent',0.),('distractor',9.)]:
                raw,cue,labels,pr=p(0,condition,[0])
                self.assertTrue(torch.equal(raw,s[:1]))
                self.assertTrue(torch.equal(cue,torch.full_like(cue,value)))
        self.assertEqual(p.regenerated_batches,2)

    def test_hash_snr_mutation_fail_closed(self):
        for fault in ('hash','snr','mutation'):
            with self.subTest(fault=fault),self.assertRaises(ValueError): self.make(fault)(0,'correct',[0,1])

    def test_wrong_order(self):
        with self.assertRaisesRegex(ValueError,'CALL_ORDER'): self.make()(0,'silent',[0])

class PairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'attempt'

    def commands(self,label,directory):
        return [sys.executable,'-B','-c','import os; print(os.getpid())']

    def test_two_real_distinct_processes(self):
        def verify(root,records):
            self.assertEqual(len(records),2)
            for r in records:
                self.assertEqual(int((root/r['label']/'stdout.log').read_text()),r['pid'])
                self.assertNotEqual(r['pid'],os.getpid())
            return {'verified':True,'scope':'synthetic_process_smoke_only'}
        result=run_pair(self.root,self.commands,verify,timeout_seconds=10)
        self.assertFalse(result['production_verified'])
        with self.assertRaises(FileExistsError): run_pair(self.root,self.commands,verify)

    def test_first_failure_no_second_no_retry(self):
        def commands(label,directory): return [sys.executable,'-c','raise RuntimeError("injected")']
        with self.assertRaisesRegex(ValueError,'WORKER_NONZERO'):
            run_pair(self.root,commands,lambda *a:self.fail('no verification'),timeout_seconds=10)
        self.assertFalse((self.root/'B').exists())
        self.assertTrue((self.root/'FAILED.json').is_file())

    def test_timeout_preserves_failure(self):
        def commands(label,directory): return [sys.executable,'-c','import time; time.sleep(10)']
        with self.assertRaisesRegex(TimeoutError,'PAIR_DEADLINE'):
            run_pair(self.root,commands,lambda *a:self.fail('no verification'),timeout_seconds=.2)
        self.assertFalse((self.root/'B').exists())
        self.assertTrue((self.root/'FAILED.json').exists())

    def test_verifier_failure_never_completes(self):
        with self.assertRaisesRegex(ValueError,'NOT_VERIFIED'):
            run_pair(self.root,self.commands,lambda *a:{'verified':False},timeout_seconds=10)
        self.assertFalse((self.root/'PAIR_EXECUTION.json').exists())

    def test_loading_gate_precedes_checkpoint_access(self):
        with patch.dict(os.environ,{'SLURM_JOB_ID':''}):
            with self.assertRaisesRegex(ValueError,'ALLOCATED_LINUX'):
                with audited_session({}): self.fail('must not load')

if __name__=='__main__': unittest.main()
