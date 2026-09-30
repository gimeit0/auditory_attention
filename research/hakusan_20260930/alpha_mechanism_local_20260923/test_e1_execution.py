import unittest
import numpy as np
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
import torch
import json
from pathlib import Path
from e1_execution import (contract,inventory,verify_arrays,jobs,execution_spec,ALPHAS,ALPHA_GRID,
                          E0_CORRECT_TRIAL_IDS,pilot_exposure,PASS_ALPHA_MODE,MAIN,CLEAN)
from loaded_model_adapter import PASS_MAP
from gain_formula_check import check_installed_gains

class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=contract()
    def outputs(self):
        # Constant synthetic predictions: these are NOT research results.
        return {k:dict(trial_ids=ids,logits=np.zeros((len(ids),800),np.float32),
                       nll=np.full(len(ids),np.log(800),np.float32)) for k,ids in inventory(self.c).items()}
    def test_counts(self):
        inv=inventory(self.c)
        self.assertEqual(sum(map(len,inv.values())),38400)
        self.assertEqual(len(inv),60)
        self.assertEqual(sum(len(ids) for k,ids in inv.items() if k[0]=='B'),3600)
    def test_pass(self):
        self.assertEqual(verify_arrays(self.c,self.outputs())['predictions'],38400)
    def test_nonzero_batch_residual_preserved(self):
        from e1_execution import paired_readout
        r=self.outputs()
        trial=r[('A','main','alpha_0','shuffled')]['trial_ids'][0]
        target=self.c['labels'][str(trial)]
        for name in ('explicit_bypass','alpha_0'):
            row=r[('A','main',name,'correct')]
            pos=row['trial_ids'].index(trial)
            row['logits'][pos,:]=0
            row['logits'][pos,(target+1)%800]=2
            row=r[('A','main',name,'shuffled')]
            row['logits'][0,:]=0;row['logits'][0,target]=2
        read=paired_readout(self.c,r)
        self.assertEqual(read['terms']['alpha_0']['accuracy_difference'][0],-1)
        self.assertEqual(read['D'][0],1)
        self.assertEqual(read['D_alpha']['alpha_0'][0],0)
    def test_decision_b_grid(self):
        # Decision B (2026-09-27): .875 replaces .25; formula, controls and count unchanged.
        self.assertEqual(ALPHAS,['alpha_0','alpha_05','alpha_075','alpha_875','alpha_1'])
        self.assertEqual(ALPHA_GRID,[0,.5,.75,.875,1])
        spec=execution_spec(self.c)
        self.assertEqual(spec['alpha_grid'],ALPHA_GRID)
        self.assertEqual(spec['alpha_grid_revision']['previous'],[0,.25,.5,.75,1])
        self.assertNotIn('alpha_025',MAIN); self.assertNotIn('alpha_025',CLEAN)
        for name in MAIN+CLEAN:
            self.assertIn(name,PASS_ALPHA_MODE)
            if name not in ('original','explicit_bypass'): self.assertEqual(PASS_MAP[name][0],PASS_ALPHA_MODE[name][0])
        self.assertEqual(PASS_MAP['alpha_875'],(.875,'alpha'))
        self.assertEqual(spec['pass_map']['alpha_875'],dict(alpha=.875,mode='alpha'))
    def test_pilot_exposure_matches_e0_layout(self):
        layout=json.loads((Path(__file__).resolve().parent/'E0_LAYOUT_96.json').read_text())
        self.assertEqual(E0_CORRECT_TRIAL_IDS,[i for b in layout['condition_batches']['correct'] for i in b])
        e=pilot_exposure(self.c)
        self.assertEqual((e['overlap_count'],e['overlap_clean_count'],e['e0_job_id']),(19,5,'746603'))
        self.assertEqual(e['overlap_trial_ids'],sorted(set(E0_CORRECT_TRIAL_IDS)&{int(k) for k in self.c['labels']}))
        self.assertEqual(execution_spec(self.c)['pilot_exposure'],e)
    def test_missing(self):
        r=self.outputs(); r.pop(next(iter(r)))
        with self.assertRaisesRegex(ValueError,'INVENTORY'): verify_arrays(self.c,r)
    def test_reorder(self):
        r=self.outputs(); k=next(iter(r)); r[k]['trial_ids']=r[k]['trial_ids'][::-1]
        with self.assertRaisesRegex(ValueError,'IDS'): verify_arrays(self.c,r)
    def test_wrong_nll(self):
        r=self.outputs(); r[next(iter(r))]['nll'][0]+=1
        with self.assertRaisesRegex(ValueError,'NLL_RECOMPUTE'): verify_arrays(self.c,r)
    def test_wrong_cold_repeat(self):
        r=self.outputs(); p=r[('B','clean','alpha_1','correct_cue')]
        p['logits'][0,:]=1 # softmax and NLL unchanged, bits must still fail
        with self.assertRaisesRegex(ValueError,'BITS'): verify_arrays(self.c,r)
    def test_wrong_clean_cue_independence(self):
        r=self.outputs()
        for name in ('explicit_bypass','alpha_0'):
            r[('A','clean',name,'correct_cue')]['logits'][0,:]=1
        with self.assertRaisesRegex(ValueError,'BITS'): verify_arrays(self.c,r)
    def test_nonfinite(self):
        r=self.outputs(); r[next(iter(r))]['logits'][0,0]=np.nan
        with self.assertRaisesRegex(ValueError,'NONFINITE'): verify_arrays(self.c,r)

    def body(self,wrong_labels=False,seconds=5,clock=None):
        from e1_execution import execute_loaded
        base=SimpleNamespace(_tensor_hashes=lambda x:[str(v) for v in x.tolist()])
        def provider(domain,bi,condition,ids):
            labels=torch.tensor([self.c['labels'][str(i)] for i in ids])
            if wrong_labels: labels=(labels+1)%800
            return torch.tensor(ids),torch.tensor(ids),labels,torch.zeros(len(ids),dtype=torch.int64)
        core=SimpleNamespace(predict=lambda base,outer,s,c,l,p,d:(dict(nll=np.full(len(l),np.log(800),np.float32)),np.zeros((len(l),800),np.float32)))
        records={}
        def sink(k,p): records[k]=p
        kwargs=dict(seconds=seconds)
        if clock is not None: kwargs['clock']=clock
        with patch('loaded_model_adapter.pass_context',side_effect=lambda *a:nullcontext()),patch('gain_formula_check.check_installed_gains',return_value={'synthetic':True}):
            result=execute_loaded(self.c,'B',core,base,SimpleNamespace(model=None),None,None,provider,'cpu',sink,**kwargs)
        return result,records
    def test_loaded_body_synthetic_schedule(self):
        result,records=self.body()
        self.assertEqual(result['predictions'],3600)
        self.assertEqual(set(records),{k for k in inventory(self.c) if k[0]=='B'})
        rows=result['pass_resources']
        self.assertEqual({(r['domain'],r['pass_name']) for r in rows},{('main','alpha_1'),('clean','alpha_1')})
        for r in rows:
            self.assertIsNone(r['cuda_max_memory_allocated_bytes']); self.assertIsNone(r['cuda_max_memory_reserved_bytes'])
            self.assertGreaterEqual(r['host_max_rss_ru_maxrss'],0); self.assertIn(r['ru_maxrss_unit'],('KiB','bytes'))
            self.assertGreaterEqual(r['elapsed_seconds'],0)
        self.assertTrue(result['process_started_utc']<=result['process_finished_utc'])
        self.assertIsNone(result['runtime_values'])  # SimpleNamespace core has no runtime_values
    def test_loaded_body_wrong_labels(self):
        with self.assertRaisesRegex(ValueError,'E1_LABELS'): self.body(wrong_labels=True)
    def test_loaded_body_deadline(self):
        times=iter([0,2])
        with self.assertRaisesRegex(TimeoutError,'DEADLINE'): self.body(seconds=1,clock=lambda:next(times))

if __name__=='__main__': unittest.main()
