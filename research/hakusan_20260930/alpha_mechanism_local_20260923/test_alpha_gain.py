import unittest
from pathlib import Path
import tempfile
import torch
from alpha_gain import original_gain_class, alpha_gain_class

SOURCE = Path('/Users/gigi/projects/auditory_attention/src/spatial_attn_architecture.py')
Original = original_gain_class(SOURCE)
Alpha = alpha_gain_class(Original)

class AlphaTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(20260923)
        self.cue = torch.randn(3,2,4,5,dtype=torch.float64)
        self.mix = torch.randn(3,2,4,7,dtype=torch.float64)
        self.base = Original(4,2).double()
        self.model = Alpha(4,2).double()
        with torch.no_grad():
            self.base.bias.fill_(0.13)
            self.base.slope.fill_(1.4)
            self.base.threshold.fill_(-0.2)
        self.model.load_state_dict(self.base.state_dict(), strict=True)

    def test_one_original_bitwise_and_mask(self):
        for dtype in (torch.float32, torch.float64):
            self.base.to(dtype); self.model.to(dtype)
            c,m = self.cue.to(dtype),self.mix.to(dtype)
            for mask in (None, [1], torch.tensor([False,True,False])):
                self.assertTrue(torch.equal(self.base(c,m,mask),self.model(c,m,mask)))

    def test_zero_bypass_and_cue_independence(self):
        self.model.alpha=0
        self.assertIs(self.model(self.cue,self.mix),self.mix)
        self.assertTrue(torch.equal(self.model(self.cue*99,self.mix),self.mix))

    def test_interior_formula_and_mask(self):
        g=self.base.bias+(1-self.base.bias)*torch.sigmoid((self.cue.mean(-1,keepdim=True)-self.base.threshold)*self.base.slope)
        for a in (.25,.5,.75):
            self.model.alpha=a
            expected=self.mix*(1-a*(1-g))
            expected[1]=self.mix[1]
            self.assertTrue(torch.equal(self.model(self.cue,self.mix,[1]),expected))

    def test_inputs_state_rng_unchanged(self):
        for a in (0,.5,1):
            self.model.alpha=a
            state={k:v.clone() for k,v in self.model.state_dict().items()}
            c,m,rng=self.cue.clone(),self.mix.clone(),torch.get_rng_state().clone()
            self.model.eval(); out=self.model(self.cue,self.mix)
            self.assertTrue(torch.isfinite(out).all())
            self.assertTrue(torch.equal(c,self.cue) and torch.equal(m,self.mix))
            self.assertTrue(torch.equal(rng,torch.get_rng_state()))
            self.assertTrue(all(torch.equal(v,self.model.state_dict()[k]) for k,v in state.items()))

    def test_state_dict_keys_unchanged(self):
        self.assertEqual(set(self.model.state_dict()),{'bias','slope','threshold'})
        self.assertEqual(set(self.model.state_dict()),set(self.base.state_dict()))

    def test_reject_invalid_alpha(self):
        for value in (-1,1.1,float('nan'),float('inf'),True,torch.tensor(.5)):
            with self.assertRaises(ValueError): Alpha(4,2,alpha=value)
        self.model.alpha=-2
        with self.assertRaises(ValueError): self.model(self.cue,self.mix)

    def test_reject_additive_and_changed_source(self):
        with self.assertRaises(ValueError): Alpha(4,2,additive=True)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.py';path.write_text('class SimpleAttentionalGain: pass')
            with self.assertRaises(ValueError): original_gain_class(path)

    def test_gradcheck_inputs(self):
        self.model.alpha=.5
        c=self.cue.clone().requires_grad_();m=self.mix.clone().requires_grad_()
        self.assertTrue(torch.autograd.gradcheck(lambda c,m:self.model(c,m), (c,m)))

    def test_one_parameter_gradient_matches_original(self):
        self.base(self.cue,self.mix,None).sum().backward()
        self.model(self.cue,self.mix).sum().backward()
        for p,q in zip(self.base.parameters(),self.model.parameters()):
            self.assertTrue(torch.equal(p.grad,q.grad))

    def test_zero_gradients(self):
        self.model.alpha=0
        c=self.cue.clone().requires_grad_();m=self.mix.clone().requires_grad_()
        self.model(c,m).sum().backward()
        self.assertIsNone(c.grad)
        self.assertTrue(torch.equal(m.grad,torch.ones_like(m)))
        self.assertTrue(all(p.grad is None for p in self.model.parameters()))

    def test_eight_gain_synthetic_chain(self):
        models=[Alpha(4,2,alpha=0).double().eval() for _ in range(8)]
        def run(c):
            x=self.mix
            for gain in models: x=torch.tanh(gain(c,x))
            return x
        reference=self.mix
        for _ in models: reference=torch.tanh(reference)
        self.assertTrue(torch.equal(run(self.cue),reference))
        self.assertTrue(torch.equal(run(self.cue*4),reference))

if __name__ == '__main__': unittest.main()
