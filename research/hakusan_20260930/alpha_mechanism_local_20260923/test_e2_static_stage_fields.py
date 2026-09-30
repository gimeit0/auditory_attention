import pickle
import unittest
from e2_static_stage_fields import literal_stage_fields

class StaticTests(unittest.TestCase):
    def test_protocols(self):
        for protocol in (2,3,4,5):
            d={'epoch':15,'global_step':27776}
            self.assertEqual(literal_stage_fields(pickle.dumps(d,protocol)),d)
    def test_missing(self):
        with self.assertRaises(ValueError): literal_stage_fields(pickle.dumps({'epoch':0}))
    def test_not_integer(self):
        with self.assertRaises(ValueError): literal_stage_fields(pickle.dumps({'epoch':'0','global_step':0}))
    def test_no_execution(self):
        class Refused:
            def __reduce__(self): return (eval,('1/0',))
        d={'epoch':0,'global_step':0,'opaque':Refused()}
        self.assertEqual(literal_stage_fields(pickle.dumps(d,2)),{'epoch':0,'global_step':0})

if __name__=='__main__': unittest.main()
