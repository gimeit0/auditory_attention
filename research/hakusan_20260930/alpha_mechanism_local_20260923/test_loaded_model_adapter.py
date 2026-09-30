import hashlib
import unittest
from unittest.mock import patch
import torch
from torch import nn
from pinned_architecture import load
from loaded_model_adapter import (pinned_core,explicit_bypass,accept_loaded_formal40,
                                  predict_loaded_pass,pass_context,PASS_MAP,FORMAL_SHA)

class Features(nn.Module):
    def forward(self,x,unused): return x,None

class Outer(nn.Module):
    def __init__(self,model):
        super().__init__()
        self.model=model
        self.coch_gram=nn.Module()
        self.coch_gram.full_rep=Features()
    def forward(self,cue,scene,mask): return self.model(cue,scene,mask)

class SyntheticBase:
    """Identity preprocessing spy, not the production audio implementation."""
    def __init__(self): self.calls=[]
    def singleton_native_preprocess(self,model,x):
        self.calls.append(x)
        return x
    def _tensor_hashes(self,x):
        return [hashlib.sha256(r.numpy().tobytes()).hexdigest() for r in x]

class LoadedAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core=pinned_core()
        cls.arch,cls.gain=load('/Users/gigi/projects/auditory_attention')
        torch.set_num_threads(1)

    def setUp(self):
        torch.manual_seed(24)
        model=self.arch(input_sr=20000,out_channels=[2]*7,kernel=[[1,1]]*7,
            stride=[[1,1]]*7,padding=['same']*7,pool_stride=[-1]*7,
            pool_size=[[3,3]]*7,pool_padding=[[1,1]]*7,attn=[1]*7,
            dropout=0,fc_size=4,num_classes={'num_words':800},frequency_dim=3,
            starting_output_len=5,v08=True)
        self.outer=Outer(model).eval().requires_grad_(False)
        self.base=SyntheticBase()
        self.scene=torch.randn(2,2,3,5)
        self.cue=torch.randn_like(self.scene)
        self.labels=torch.tensor([1,2])
        self.device=torch.device('cpu')
        n=sum(p.numel() for p in self.outer.parameters())
        self.report=dict(loaded_trainable_numel_ratio=1.0,loaded_trainable_numel=n,
                         trainable_numel=n,native_preprocessing='selftrain_singleton_per_example_leveling')

    def run_pass(self,name,cue=None):
        return predict_loaded_pass(self.core,self.base,self.outer,self.arch,self.gain,
               name,self.scene,self.cue if cue is None else cue,self.labels,self.labels,self.device)

    def test_accept_metadata_without_claiming_provenance(self):
        r=accept_loaded_formal40(self.core,self.outer,self.report,'formal40',FORMAL_SHA,self.arch,self.gain)
        self.assertFalse(r['production_provenance_verified'])
        self.assertFalse(r['eager_unwrap']['known_wrapper_removed'])

    def test_reject_wrong_model_or_load_coverage(self):
        for model_id,sha,report in [('author_external',FORMAL_SHA,self.report),
                ('formal40','0'*64,self.report),('formal40',FORMAL_SHA,dict(self.report,loaded_trainable_numel=1))]:
            with self.assertRaises(ValueError):
                accept_loaded_formal40(self.core,self.outer,report,model_id,sha,self.arch,self.gain)

    def test_alpha_one_reuses_pinned_prediction_and_preprocess_order(self):
        original=self.run_pass('original')
        adapted=self.run_pass('alpha_1')
        self.assertEqual(original[1].tobytes(),adapted[1].tobytes())
        for k in original[0]: self.assertEqual(original[0][k].tobytes(),adapted[0][k].tobytes())
        self.assertEqual(len(self.base.calls),4)
        self.assertIs(self.base.calls[0],self.scene)
        self.assertIs(self.base.calls[1],self.cue)

    def test_independent_bypass_does_not_use_alpha_adapter(self):
        with patch('loaded_model_adapter.intervention',side_effect=AssertionError('must not call alpha')):
            bypass=self.run_pass('explicit_bypass')[1]
        zero=self.run_pass('alpha_0')[1]
        different=self.run_pass('alpha_0',self.cue.flip(0)*3)[1]
        self.assertEqual(bypass.tobytes(),zero.tobytes())
        self.assertEqual(zero.tobytes(),different.tobytes())

    def test_bypass_restores_on_exception_and_keeps_parameter_identity(self):
        original=self.outer.model.model_dict['attn0']
        params={n:id(p) for n,p in self.outer.named_parameters()}
        with self.assertRaisesRegex(RuntimeError,'synthetic failure'):
            with explicit_bypass(self.outer.model,self.arch,self.gain):
                self.assertEqual(params,{n:id(p) for n,p in self.outer.named_parameters()})
                raise RuntimeError('synthetic failure')
        self.assertIs(self.outer.model.model_dict['attn0'],original)

    def test_all_declared_unobserved_passes_finite(self):
        for name in PASS_MAP:
            with self.subTest(name=name):
                values,out=self.run_pass(name)
                self.assertEqual(out.shape,(2,800))
                self.assertTrue(torch.isfinite(torch.from_numpy(out)).all())

    def test_unimplemented_observer_and_unknown_pass_rejected(self):
        for name in ('alpha_05_observed','other'):
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_PASS'): self.run_pass(name)

    def test_state_mutation_rejected_after_restore(self):
        original=self.outer.model.model_dict['attn0']
        with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):
            with pass_context(self.core,self.outer,self.arch,self.gain,'alpha_05'):
                original.bias.add_(.1)
        self.assertIs(self.outer.model.model_dict['attn0'],original)

    def test_rng_mutation_rejected(self):
        with self.assertRaisesRegex(ValueError,'RNG_CHANGED'):
            with pass_context(self.core,self.outer,self.arch,self.gain,'original'):
                torch.rand(1)

    def test_invalid_input_dtype_rejected_and_restored(self):
        self.scene=self.scene.double()
        original=self.outer.model.model_dict['attn0']
        with self.assertRaisesRegex(RuntimeError,'FP32'): self.run_pass('alpha_05')
        self.assertIs(self.outer.model.model_dict['attn0'],original)

    def test_runtime_change_rejected(self):
        old=torch.backends.cudnn.benchmark
        try:
            with self.assertRaisesRegex(ValueError,'RUNTIME_CHANGED'):
                with pass_context(self.core,self.outer,self.arch,self.gain,'original'):
                    torch.backends.cudnn.benchmark=not old
        finally:
            torch.backends.cudnn.benchmark=old

    def test_outer_preprocessing_training_rejected(self):
        self.outer.coch_gram.train()
        with self.assertRaisesRegex(RuntimeError,'Training-mode'):
            self.run_pass('alpha_05')

if __name__=='__main__': unittest.main()
