from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
import torch
from e1_inputs import build_contract
from e2_catalog import stage_record,validate_record
from e2_matrix import STAGES,expected_records,prediction_count,verify_stage_arrays
from e2_execution import execute_stage

class E2ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.c=build_contract()
    def records(self,rounds):
        return {k:dict(trial_ids=ids,logits=np.zeros((len(ids),800),np.float32),
                       nll=np.full(len(ids),np.log(800),np.float32)) for k,ids in expected_records(self.c,rounds).items()}
    def test_count(self):
        self.assertEqual(prediction_count(self.c),86400)
        self.assertEqual(sum(len(expected_records(self.c,r)) for r in STAGES),144)
    def test_stage_identity_rejected(self):
        row=stage_record(0); row['sha256']=stage_record(40)['sha256']
        with self.assertRaises(ValueError): validate_record(row)
        with self.assertRaises(ValueError): stage_record(True)
    def test_inventory_accept(self):
        for r in STAGES:
            result=verify_stage_arrays(self.c,r,self.records(r))
            self.assertEqual(result['predictions'],18000 if r in (0,4,16,40) else 3600)
    def test_cross_stage_rejected(self):
        with self.assertRaises(ValueError): verify_stage_arrays(self.c,4,self.records(0))
    def test_missing_rejected(self):
        records=self.records(1); records.pop(next(iter(records)))
        with self.assertRaises(ValueError): verify_stage_arrays(self.c,1,records)
    def test_wrong_trial_order(self):
        records=self.records(1); row=records[next(iter(records))]; row['trial_ids']=row['trial_ids'][::-1]
        with self.assertRaises(ValueError): verify_stage_arrays(self.c,1,records)
    def test_wrong_nll(self):
        records=self.records(1); records[next(iter(records))]['nll'][0]+=1
        with self.assertRaises(ValueError): verify_stage_arrays(self.c,1,records)
    def test_loaded_body_all_stages_synthetic(self):
        base=SimpleNamespace(_tensor_hashes=lambda t:[str(x) for x in t.tolist()])
        core=SimpleNamespace(predict=lambda base,outer,s,c,l,p,d:(
            {'nll':np.full(len(l),np.log(800),np.float32)},np.zeros((len(l),800),np.float32)))
        def provider(domain,bi,condition,ids):
            return torch.tensor(ids),torch.tensor(ids),torch.tensor([self.c['labels'][str(i)] for i in ids]),torch.zeros(len(ids),dtype=torch.int64)
        total=0
        with patch('loaded_model_adapter.pass_context',side_effect=lambda *a:nullcontext()),patch('gain_formula_check.check_installed_gains',return_value={'synthetic':True}):
            for rounds in STAGES:
                records={}
                result=execute_stage(self.c,rounds,core,base,SimpleNamespace(model=None),None,None,provider,'cpu',lambda k,p:records.__setitem__(k,p),seconds=60)
                checked=verify_stage_arrays(self.c,rounds,records)
                self.assertEqual(result['predictions'],checked['predictions'])
                total+=checked['predictions']
        self.assertEqual(total,86400)

if __name__=='__main__': unittest.main()
