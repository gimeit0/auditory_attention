import copy
import unittest
import numpy as np
from e0_layout_reference import (make_layout, reference, validate_layout, condition_ids,
                                 bitwise_bridge, validate_logits, validate_prediction_inventory)

class E0ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout=make_layout()
        cls.refs=reference(cls.layout)

    def inventory(self):
        result=[]
        for p in ('A','B'):
            for name in self.layout['passes']+(['alpha_05_observed'] if p=='A' else []):
                for c in ('correct','shuffled','silent','distractor'):
                    result.append(dict(process=p,pass_name=name,condition=c,
                                       trial_ids=condition_ids(self.layout,c)))
                    result[-1]['pass']=result[-1].pop('pass_name')
        return result

    def test_real_historical_reference_and_nll(self):
        self.assertEqual(len(self.layout['trial_ids']),96)
        for c,r in self.refs.items():
            self.assertEqual(len(r['trial_ids']),96 if c=='correct' else 64)
            bitwise_bridge(r,r['trial_ids'],r['logits'].copy())
            validate_logits(r['logits'],r['trial_ids'],r['labels'],r['nll'])

    def test_layout_rejects_reordering_or_changed_label(self):
        for key in ('trial_ids','target_labels'):
            altered=copy.deepcopy(self.layout)
            if key=='trial_ids': altered[key].reverse()
            else: altered[key]['0']+=1
            with self.assertRaisesRegex(ValueError,'LAYOUT_MISMATCH'): validate_layout(altered)

    def test_bridge_rejects_one_bit_dtype_and_order(self):
        r=self.refs['correct']
        changed=r['logits'].copy()
        changed.view(np.uint32)[0,0]^=1
        with self.assertRaisesRegex(ValueError,'BRIDGE_BITS'): bitwise_bridge(r,r['trial_ids'],changed)
        with self.assertRaises(ValueError): bitwise_bridge(r,r['trial_ids'][::-1],r['logits'])
        with self.assertRaises(ValueError): bitwise_bridge(r,r['trial_ids'],r['logits'].astype(np.float64))

    def test_nll_corruption_and_nonfinite(self):
        r=self.refs['correct']
        with self.assertRaisesRegex(ValueError,'NLL_RECOMPUTE'):
            validate_logits(r['logits'],r['trial_ids'],r['labels'],r['nll']+1)
        changed=r['logits'].copy()
        changed[0,0]=np.nan
        with self.assertRaisesRegex(ValueError,'NONFINITE'):
            validate_logits(changed,r['trial_ids'],r['labels'],r['nll'])

    def test_6048_inventory(self):
        self.assertEqual(validate_prediction_inventory(self.layout,self.inventory()),6048)

    def test_inventory_missing_duplicate_mode_order(self):
        for kind in ('missing','duplicate','mode','order'):
            records=self.inventory()
            if kind=='missing': records.pop()
            elif kind=='duplicate': records[-1]=copy.deepcopy(records[0])
            elif kind=='mode': records[0]['pass']='alpha_02'
            else: records[0]['trial_ids'].reverse()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_prediction_inventory(self.layout,records)

if __name__=='__main__': unittest.main()
