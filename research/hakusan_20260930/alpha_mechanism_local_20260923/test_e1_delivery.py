import unittest
from build_e1_delivery import REQUIRED,completion_gate

class DeliveryTests(unittest.TestCase):
    def test_missing_requirement_rejected(self):
        with self.assertRaises(ValueError): completion_gate({})
    def test_partial_time_blocks_completion(self):
        m={k:{'status':'PASS'} for k in REQUIRED}; m['P5']['status']='PARTIAL_EXECUTION_WINDOW_ONLY'
        r=completion_gate(m)
        self.assertFalse(r['E1_DEV_COMPLETE']); self.assertEqual(r['unclosed_requirements'],['P5'])
        self.assertEqual(r['scientific_labels'],[])
    def test_unknown_status_is_not_pass(self):
        m={k:{'status':'PASS'} for k in REQUIRED}; m['primary']['status']='probably fine'
        self.assertFalse(completion_gate(m)['E1_DEV_COMPLETE'])

if __name__=='__main__': unittest.main()
