import tempfile
import unittest
import numpy as np
from e2_history_bridge import read_reference,verify_history

class BridgeTests(unittest.TestCase):
    def test_real_reference_selfcheck_not_gpu(self):
        self.assertEqual(verify_history(read_reference())['predictions'],3600)
    def test_logit_bit_change_rejected(self):
        records=read_reference(); row=next(iter(records.values()))
        row['logits'][0,0]=np.nextafter(row['logits'][0,0],np.float32(np.inf))
        with self.assertRaisesRegex(ValueError,'BRIDGE_BITS'): verify_history(records)
    def test_missing_rejected(self):
        records=read_reference(); records.pop(next(iter(records)))
        with self.assertRaises(ValueError): verify_history(records)
    def test_no_fallback_for_explicit_directory(self):
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError): read_reference(d)

if __name__=='__main__': unittest.main()
