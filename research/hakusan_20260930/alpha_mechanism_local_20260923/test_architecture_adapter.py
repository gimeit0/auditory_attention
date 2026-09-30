import contextlib
import io
import hashlib
from pathlib import Path
import unittest
import torch
import yaml
from pinned_architecture import load
from architecture_adapter import intervention, InterventionGain, NAMES, MODES

PROJECT = '/Users/gigi/projects/auditory_attention'

class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arch, cls.gain = load(PROJECT)
        torch.set_num_threads(1)

    def setUp(self):
        torch.manual_seed(20260923)
        with contextlib.redirect_stdout(io.StringIO()):
            self.model = self.arch(input_sr=20000, out_channels=[2]*7,
                kernel=[[1,1]]*7, stride=[[1,1]]*7, padding=['same']*7,
                pool_stride=[-1]*7, pool_size=[[3,3]]*7, pool_padding=[[1,1]]*7,
                attn=[1]*7, dropout=0.2, fc_size=4, num_classes={'num_words':3},
                frequency_dim=3, starting_output_len=5, v08=True)
        self.model.double().eval().requires_grad_(False)
        self.cue = torch.randn(2,2,3,5,dtype=torch.float64)
        self.mix = torch.randn_like(self.cue)

    def ctx(self, alpha=0.5, mode='alpha'):
        return intervention(self.model,self.arch,self.gain,alpha,mode)

    def test_alpha_one_bitwise_and_parameter_identity(self):
        for dtype in (torch.float32,torch.float64):
            self.model.to(dtype)
            cue,mix=self.cue.to(dtype),self.mix.to(dtype)
            for mask in (None,[1],torch.tensor([False,True])):
                expected=self.model(cue,mix,mask)
                params={n:id(p) for n,p in self.model.named_parameters()}
                state={n:t.clone() for n,t in self.model.state_dict().items()}
                rng=torch.get_rng_state().clone()
                originals={n:id(self.model.model_dict[n]) for n in NAMES}
                with self.ctx(1) as contract:
                    self.assertEqual(len(contract['replaced_paths']),8)
                    self.assertTrue(torch.equal(expected,self.model(cue,mix,mask)))
                    self.assertEqual(params,{n:id(p) for n,p in self.model.named_parameters()})
                    self.assertEqual(set(state),set(self.model.state_dict()))
                    for n,t in self.model.state_dict().items(): self.assertTrue(torch.equal(t,state[n]))
                self.assertTrue(torch.equal(rng,torch.get_rng_state()))
                self.assertEqual(originals,{n:id(self.model.model_dict[n]) for n in NAMES})

    def test_alpha_zero_matches_scene_only_and_ignores_cue(self):
        expected=self.model(mixture=self.mix)
        with self.ctx(0):
            self.assertTrue(torch.equal(expected,self.model(self.cue,self.mix)))
            self.assertTrue(torch.equal(expected,self.model(self.cue.flip(0)*7,self.mix)))

    def test_all_modes_repeat_without_input_mutation(self):
        cue,mix=self.cue.clone(),self.mix.clone()
        for mode in MODES:
            with self.ctx(0.5,mode):
                a=self.model(cue,mix)
                self.assertTrue(torch.equal(a,self.model(cue,mix)))
                self.assertTrue(torch.isfinite(a).all())
        self.assertTrue(torch.equal(cue,self.cue))
        self.assertTrue(torch.equal(mix,self.mix))

    def test_control_registration(self):
        original=self.model.model_dict['attnfc']
        with self.ctx(0,'conv_only') as c:
            self.assertEqual(len(c['replaced_paths']),7)
            self.assertIs(self.model.model_dict['attnfc'],original)
        with self.ctx(0.5,'fc_mean_preserved'):
            self.assertEqual(self.model.model_dict['attnfc'].mode,'mean_preserved')
            self.assertTrue(all(self.model.model_dict[n].mode=='alpha' for n in NAMES[:-1]))

    def test_restoration_on_exception_and_nested_rejection(self):
        original=self.model.model_dict['attn0']
        with self.assertRaisesRegex(RuntimeError,'intentional'):
            with self.ctx():
                with self.assertRaises(ValueError):
                    with self.ctx(): pass
                raise RuntimeError('intentional')
        self.assertIs(self.model.model_dict['attn0'],original)

    def test_reject_training_or_unfrozen(self):
        self.model.train()
        with self.assertRaisesRegex(ValueError,'FROZEN_EVAL'):
            with self.ctx(): pass
        self.model.eval().requires_grad_(True)
        with self.assertRaisesRegex(ValueError,'FROZEN_EVAL'):
            with self.ctx(): pass

    def test_reject_layout_additive_hooks_and_aliases(self):
        for attr in ('residual_attn','cue_loc_task','dual_task','per_kernel_gain'):
            setattr(self.model,attr,True)
            with self.assertRaises(ValueError):
                with self.ctx(): pass
            setattr(self.model,attr,False)
        gain=self.model.model_dict['attn0']
        gain.additive=True
        with self.assertRaises(ValueError):
            with self.ctx(): pass
        gain.additive=False
        hook=gain.register_forward_hook(lambda *args: None)
        with self.assertRaises(ValueError):
            with self.ctx(): pass
        hook.remove()
        self.model.model_dict['alias']=gain
        with self.assertRaisesRegex(ValueError,'ALIASED'):
            with self.ctx(): pass
        del self.model.model_dict['alias']
        self.model.attn[0]=0
        with self.assertRaisesRegex(ValueError,'LAYOUT'):
            with self.ctx(): pass

    def test_reject_unknown_mode_and_forward_override(self):
        with self.assertRaises(ValueError):
            with self.ctx(mode='unknown'): pass
        self.model.forward=lambda *a: None
        with self.assertRaisesRegex(ValueError,'FORWARD_OVERRIDE'):
            with self.ctx(): pass

    def test_uniform_formula_per_example_not_batch(self):
        gain=self.model.model_dict['attn0']
        ones=torch.ones_like(self.mix)
        original=gain(self.cue,ones,None)
        wrapper=InterventionGain(gain,0.5,'uniform')
        expected=(1-0.5*(1-original)).mean((1,2,3),keepdim=True).expand_as(ones)
        torch.testing.assert_close(wrapper(self.cue,ones),expected,rtol=0,atol=1e-15)
        torch.testing.assert_close(wrapper(self.cue,ones)[:1],wrapper(self.cue[:1],ones[:1]),rtol=0,atol=0)
        self.assertFalse(torch.equal(InterventionGain(gain,1,'uniform')(self.cue,ones),original))

    def test_fc_mean_preserved_formula_and_mask(self):
        gain=self.model.model_dict['attnfc']
        ones=torch.ones_like(self.mix)
        original=gain(self.cue,ones,None)
        for a in (0,0.5,1):
            wrapper=InterventionGain(gain,a,'mean_preserved')
            out=wrapper(self.cue,ones)
            torch.testing.assert_close(out.mean((1,2,3)),original.mean((1,2,3)),rtol=0,atol=1e-15)
            self.assertTrue(torch.equal(wrapper(self.cue,ones,[1])[1],ones[1]))
        self.assertFalse(torch.equal(InterventionGain(gain,0,'mean_preserved')(self.cue,ones),ones))

    def test_degenerate_denominator_rejected(self):
        gain=self.model.model_dict['attnfc']
        gain.bias.fill_(-3)
        wrapper=InterventionGain(gain,0.5,'mean_preserved')
        with self.assertRaisesRegex(ValueError,'DENOMINATOR'):
            wrapper(torch.zeros_like(self.cue),self.mix)

    def test_mask_identity_all_local_controls(self):
        gain=self.model.model_dict['attn0']
        for mode in ('alpha','uniform','mean_preserved'):
            wrapper=InterventionGain(gain,0.5,mode)
            self.assertTrue(torch.equal(wrapper(self.cue,self.mix,[1])[1],self.mix[1]))

    def test_hann_pooling_endpoints_and_controls(self):
        # Real Hann implementation; reduced size, not the production pool schedule.
        pool_scope=load(PROJECT)[0].__init__.__globals__
        pool=pool_scope['HannPooling2d']
        for i in range(7):
            self.model.pool_stride[i]=[1,1]
            self.model.model_dict['hann_pool_'+str(i)]=pool([1,1],[3,3],[1,1]).double().eval()
        baseline=self.model(self.cue,self.mix)
        state={n:t.clone() for n,t in self.model.state_dict().items()}
        with self.ctx(1):
            self.assertTrue(torch.equal(baseline,self.model(self.cue,self.mix)))
        bypass=self.model(mixture=self.mix)
        with self.ctx(0):
            self.assertTrue(torch.equal(bypass,self.model(self.cue,self.mix)))
        for mode in MODES:
            with self.ctx(.5,mode):
                self.assertTrue(torch.isfinite(self.model(self.cue,self.mix)).all())
        for n,t in self.model.state_dict().items(): self.assertTrue(torch.equal(t,state[n]))

    def test_production_config_meta_shapes_only(self):
        path=Path(PROJECT)/'config/binaural_attn/word_task_v10_main_feature_gain_config.yaml'
        raw=path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '9878adc94e8d3e7088948fe363067c14d5c5535c5d2404aa51746a1686955439')
        config=yaml.safe_load(raw)['model']
        # Meta tensors carry shapes only: no production weights or numerical inference.
        with torch.device('meta'):
            model=self.arch(**config).eval().requires_grad_(False)
        model.to('meta')
        x=torch.empty(1,2,40,20000,device='meta')
        expected=model(x,x)
        self.assertEqual(tuple(expected.shape),(1,800))
        for a in (0,1):
            with intervention(model,self.arch,self.gain,a):
                self.assertEqual(tuple(model(x,x).shape),(1,800))

if __name__=='__main__': unittest.main()
