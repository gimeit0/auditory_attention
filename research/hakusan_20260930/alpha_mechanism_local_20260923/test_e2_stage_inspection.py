import unittest
import torch
from e2_stage_inspection import stage_summary

class StageTests(unittest.TestCase):
    def data(self, rounds):
        return dict(epoch=max(0, rounds-1), global_step=rounds*1736,
                    state_dict={'weight':torch.ones(2,3)}, loops={})
    def test_all_stages(self):
        for r in (0,1,2,4,8,16,24,40):
            self.assertEqual(stage_summary(self.data(r),r)['completed_epochs'],r)
    def test_wrong_epoch(self):
        d=self.data(16); d['epoch']=16
        with self.assertRaises(ValueError): stage_summary(d,16)
    def test_wrong_step(self):
        d=self.data(4); d['global_step']=1
        with self.assertRaises(ValueError): stage_summary(d,4)
    def test_final_after_fit(self):
        d=self.data(40); d['epoch']=40
        self.assertEqual(stage_summary(d,40,final_after_fit=True)['epoch'],40)
        with self.assertRaises(ValueError): stage_summary(d,40)
    def test_final_scope_rejected(self):
        with self.assertRaises(ValueError): stage_summary(self.data(16),16,final_after_fit=True)
    def test_nonfinite(self):
        d=self.data(4); d['state_dict']['weight'][0,0]=float('nan')
        with self.assertRaises(ValueError): stage_summary(d,4)
    def test_signature_shape(self):
        a=self.data(4); b=self.data(4); b['state_dict']['weight']=torch.ones(6)
        self.assertNotEqual(stage_summary(a,4)['state_signature_sha256'],stage_summary(b,4)['state_signature_sha256'])
    def test_signature_not_weight_digest(self):
        a=self.data(4); b=self.data(4); b['state_dict']['weight']*=2
        self.assertEqual(stage_summary(a,4)['state_signature_sha256'],stage_summary(b,4)['state_signature_sha256'])

if __name__ == '__main__': unittest.main()
