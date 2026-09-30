import unittest
import torch
from e2_stage_loading import apply_exact_state

class LoadTests(unittest.TestCase):
    def test_exact_and_frozen(self):
        m=torch.nn.Linear(3,2); state={k:torch.full_like(v,2) for k,v in m.state_dict().items()}
        r=apply_exact_state(m,state)
        self.assertEqual(r['loaded_trainable_numel_ratio'],1)
        self.assertFalse(m.training)
        self.assertTrue(all(not p.requires_grad for p in m.parameters()))
        for k,v in m.state_dict().items(): self.assertTrue(torch.equal(v,state[k]))
    def test_missing_key(self):
        m=torch.nn.Linear(3,2)
        with self.assertRaises(ValueError): apply_exact_state(m,{'weight':m.weight.detach()})
    def test_dtype(self):
        m=torch.nn.Linear(3,2); s=m.state_dict(); s['weight']=s['weight'].double()
        with self.assertRaises(ValueError): apply_exact_state(m,s)
    def test_shape(self):
        m=torch.nn.Linear(3,2); s=m.state_dict(); s['weight']=torch.ones(3,2)
        with self.assertRaises(ValueError): apply_exact_state(m,s)
    def test_nonfinite(self):
        m=torch.nn.Linear(3,2); s=m.state_dict(); s['bias'][0]=float('inf')
        with self.assertRaises(ValueError): apply_exact_state(m,s)

if __name__=='__main__': unittest.main()
