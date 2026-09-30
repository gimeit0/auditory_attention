import unittest
import numpy as np
from audit_e1_statistics_independent import check_values,independent_ci,Raw

class AuditTests(unittest.TestCase):
    def test_independent_error_roles(self):
        from audit_e1_errors_independent import rebuild
        r=dict(target_label='1',distractor_count='1',distractor_1_label='2',scene_kind='mixed',
               correct_cue_label='3',shuffled_cue_label='2',probe_distractor_cue_label='4')
        self.assertEqual(rebuild(r,2,'main','shuffled')['category'],'distractor')
        self.assertTrue(rebuild(r,2,'main','shuffled')['distractor_cue_overlap_hit'])
        r['distractor_1_label']='1'
        self.assertEqual(rebuild(r,9,'main','correct')['category'],'label_collision')
        r.update(distractor_count='0',scene_kind='clean')
        self.assertEqual(rebuild(r,3,'main','correct')['category'],'other')
        self.assertEqual(rebuild(r,3,'clean','correct_cue')['category'],'cue_word')

    def test_corruption_is_not_a_pass(self):
        for a,b in [([1],[1.01]),([1],[1,2]),([float('nan')],[0])]:
            with self.assertRaises(ValueError): check_values(a,b,'mutated')
    def test_constant_and_paired_draws(self):
        ci,_,counts=independent_ci(['a','a','b'],np.array([[1,2],[2,4],[3,6.]]))
        np.testing.assert_allclose(ci[:,1],ci[:,0]*2)
        np.testing.assert_array_equal(counts,[2,1])
    def test_zero_single_cluster(self):
        ci,digest,_=independent_ci(['a'],np.zeros((1,1)))
        self.assertIsNone(ci); self.assertIsNone(digest)
    def test_reversed_order_join(self):
        a={('main','alpha_1','correct'):dict(trial_ids=np.array([2,1]),logits=np.array([[0,1],[1,0]]),nll=np.array([2.,1.]))}
        r=Raw({1:{'target_label':'0'},2:{'target_label':'0'}},a)
        np.testing.assert_array_equal(r.metric('alpha_1/accuracy_pp',[1,2],'main'),[100,0])
        np.testing.assert_array_equal(r.metric('alpha_1/nll',[1,2],'main'),[1,2])

if __name__=='__main__': unittest.main()
