import io
from pathlib import PosixPath
import pickle
import unittest
from unittest.mock import patch
import torch
import torch._weights_only_unpickler as w
from e2_restricted_load import restricted_checkpoint_load, path_metadata_scope

def encode(value):
    buf=io.BytesIO(); torch.save(value,buf); return buf.getvalue()

class BadReducer:
    def __reduce__(self): return (eval,('1/0',))

class RestrictedTests(unittest.TestCase):
    def setUp(self):
        existing=torch.serialization.get_safe_globals()
        torch.serialization.clear_safe_globals()
        self.addCleanup(torch.serialization.add_safe_globals,existing)
        self.addCleanup(torch.serialization.clear_safe_globals)
    def test_path_and_weights_preserved(self):
        value={'path':PosixPath('/not/accessed'),'state_dict':{'weight':torch.arange(6)}}
        loaded=restricted_checkpoint_load(encode(value))
        self.assertEqual(loaded['path'],value['path'])
        self.assertTrue(torch.equal(loaded['state_dict']['weight'],value['state_dict']['weight']))
        self.assertEqual(torch.serialization.get_safe_globals(),[])
    def test_bad_reduce_denied_and_scope_restored(self):
        with self.assertRaises(pickle.UnpicklingError): restricted_checkpoint_load(encode(BadReducer()))
        self.assertEqual(torch.serialization.get_safe_globals(),[])
    def test_legacy_scope_exact_and_restored(self):
        old=w._get_allowed_globals; baseline=dict(old())
        with patch('builtins.hasattr', side_effect=lambda obj,name: False if obj is torch.serialization and name=='safe_globals' else original_hasattr(obj,name)), patch.object(torch,'__version__','2.1.1+cu118'):
            with path_metadata_scope():
                self.assertEqual(set(w._get_allowed_globals())-set(baseline),{'pathlib.PosixPath'})
                self.assertIs(w._get_allowed_globals()['pathlib.PosixPath'],PosixPath)
            self.assertIs(w._get_allowed_globals,old)
            with self.assertRaises(ValueError):
                with path_metadata_scope(): raise ValueError('synthetic')
            self.assertIs(w._get_allowed_globals,old)
    def test_thread_rejected(self):
        with patch('threading.active_count',return_value=2),self.assertRaises(RuntimeError):
            restricted_checkpoint_load(encode({'x':1}))

original_hasattr=hasattr
if __name__=='__main__': unittest.main()
