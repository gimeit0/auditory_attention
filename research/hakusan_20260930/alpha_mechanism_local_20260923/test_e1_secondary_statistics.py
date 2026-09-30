import unittest
import numpy as np
from e1_secondary_statistics import summarize,collapse,get,control_columns,ALPHAS,NEGATIVES

class SecondaryTests(unittest.TestCase):
    def test_nll_stable_and_tied_classes(self):
        x=np.array([[1000.,999.],[999.,1000.]])
        r=summarize(x,np.full(2,np.log1p(np.exp(-1))),np.array([0,1]))
        self.assertLess(r['nll_float64_recompute_max_abs'],1e-12)
        self.assertEqual(r['most_frequent_classes'],[0,1])
        self.assertEqual(r['accuracy'],1)

    def test_collapse_strict_threshold_and_or(self):
        original=dict(accuracy=.8,logit_max_abs=10)
        self.assertFalse(collapse(dict(accuracy=.4,logit_max_abs=100),original)['collapse'])
        self.assertTrue(collapse(dict(accuracy=.399,logit_max_abs=1),original)['collapse'])
        self.assertTrue(collapse(dict(accuracy=.8,logit_max_abs=100.01),original)['collapse'])
        self.assertFalse(collapse(dict(accuracy=0,logit_max_abs=0),dict(accuracy=0,logit_max_abs=0))['collapse'])

    def test_invalid_labels_and_nonfinite(self):
        for x,n,l in [([[1,2]],[1],[2]),([[np.nan,2]],[1],[0]),([[1,2]],[1],[.5])]:
            with self.assertRaises(ValueError): summarize(x,n,l)

    def test_clean_alignment_and_labels(self):
        a={('clean','alpha_1','correct_cue'):dict(trial_ids=[2,1],logits=np.array([[0,3],[4,0]]),nll=np.array([.2,.1]))}
        correct,n,_=get(a,'clean','alpha_1','correct_cue',[1,2],{1:{'target_label':'0'},2:{'target_label':'1'}})
        np.testing.assert_array_equal(correct,[1,1]); np.testing.assert_array_equal(n,[.1,.2])

    def test_negative_difference_and_residual(self):
        arrays={}; bank={1:{'target_label':'0'},2:{'target_label':'0'}}
        for p in (*ALPHAS,*NEGATIVES):
            for cond in ('correct','shuffled','silent','distractor'):
                pred=[0,0] if cond=='correct' else [1,0]
                if p=='alpha_0': pred=[1,0]
                if p=='uniform_05': pred=[0,0]
                arrays['main',p,cond]=dict(trial_ids=[1,2],logits=np.eye(2)[pred],nll=np.ones(2))
        c=control_columns(arrays,[1,2],bank)
        np.testing.assert_array_equal(c['negative/uniform_05/C_alpha05_minus_C_p_pp'],[100,0])
        np.testing.assert_array_equal(c['D_pp'],[100,0])
        np.testing.assert_array_equal(c['r0_pp'],[0,0])

if __name__=='__main__': unittest.main()
