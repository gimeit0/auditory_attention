import unittest
import numpy as np
from e1_cluster_statistics import bootstrap,paired_columns,SEED,REPLICATES

class ClusterTests(unittest.TestCase):
    def test_trial_alignment_not_positional(self):
        from analyze_e1_primary import align
        np.testing.assert_array_equal(align([8,3,1],[1,8],np.array([80,30,10])),[10,80])
        for ids,wanted,v in [([1,1],[1],[1,2]),([1],[2],[1]),([1],[1,1],[1])]:
            with self.assertRaises(ValueError): align(ids,wanted,np.array(v))

    def test_independent_scalar_oracle(self):
        speakers=['b','a','a','c','c','c']
        x=np.array([5.,0.,2.,1.,3.,8.])
        result=bootstrap(speakers,{'x':x,'double':2*x,'constant':np.full(6,7.)})
        rng=np.random.default_rng(SEED)
        groups=[x[np.array(speakers)==s] for s in sorted(set(speakers))]
        oracle=[]
        for _ in range(REPLICATES):
            indices=rng.integers(0,3,size=3)
            oracle.append(np.concatenate([groups[i] for i in indices]).mean())
        np.testing.assert_array_equal(result['metrics']['x']['ci95'],np.quantile(oracle,[.025,.975],method='linear'))
        self.assertEqual(result['metrics']['x']['estimate'],x.mean())
        np.testing.assert_array_equal(result['metrics']['double']['ci95'],2*np.array(result['metrics']['x']['ci95']))
        self.assertEqual(result['metrics']['constant']['ci95'],[7.,7.])

    def test_trial_weight_not_equal_cluster_mean(self):
        r=bootstrap(['a','a','a','b'],{'x':[0,0,0,1]})
        self.assertEqual(r['metrics']['x']['estimate'],.25)
        self.assertEqual(r['info']['cluster_size_max'],3)

    def test_reordering_trials_preserves_integer_metrics(self):
        a=bootstrap(['b','a','a'],{'x':[1,0,2]})
        b=bootstrap(['a','b','a'],{'x':[2,1,0]})
        self.assertEqual(a,b)

    def test_one_cluster_no_ci(self):
        r=bootstrap(['a','a'],{'x':[0,1]})
        self.assertIsNone(r['metrics']['x']['ci95'])
        self.assertEqual(r['status'],'CI_NOT_COMPUTED_FEWER_THAN_TWO_CLUSTERS')

    def test_missing_and_nonfinite_rejected(self):
        for speakers,columns in [([],{'x':[]}),(['a',''],{'x':[0,1]}),(['a'],{'x':[float('nan')]}),(['a'],{'x':[1,2]}),(['a'],{})]:
            with self.assertRaises(ValueError): bootstrap(speakers,columns)

    def test_residual_is_not_forced_zero(self):
        t={k:dict(accuracy_difference=[0,1,-1],nll_difference=[.1,.2,.3]) for k in ('alpha_0','alpha_05','alpha_075','alpha_875','alpha_1')}
        t['alpha_1']['accuracy_difference']=[1,0,-1]
        r=paired_columns(t)
        np.testing.assert_array_equal(r['D_pp'],[100,-100,0])
        np.testing.assert_array_equal(r['r0_pp'],[0,100,-100])
        np.testing.assert_array_equal(r['alpha_0/D_pp'],[0,0,0])

    def test_invalid_grid_and_indicators_rejected(self):
        with self.assertRaises(ValueError): paired_columns({})
        t={k:dict(accuracy_difference=[2],nll_difference=[0]) for k in ('alpha_0','alpha_05','alpha_075','alpha_875','alpha_1')}
        with self.assertRaises(ValueError): paired_columns(t)

if __name__=='__main__': unittest.main()
