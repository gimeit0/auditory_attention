import hashlib
import io
import pickle
from pathlib import PosixPath
import unittest
import numpy as np
import torch
from e2_archive_loader import load_bound_archive,latin1_bytes,posix_path

class Bad:
    def __reduce__(self): return (eval,('1/0',))

class ArchiveTests(unittest.TestCase):
    def encode(self,value):
        b=io.BytesIO(); torch.save(value,b,pickle_protocol=2); return b.getvalue()
    def load(self,raw): return load_bound_archive(raw,hashlib.sha256(raw).hexdigest())
    def test_rng_path_tensor_roundtrip(self):
        value=dict(path=PosixPath('/not/accessed'),rng=np.random.RandomState(17).get_state(),
                   state_dict={'weight':torch.arange(12,dtype=torch.float32).reshape(3,4)})
        actual=self.load(self.encode(value))
        self.assertEqual(actual['path'],value['path'])
        np.testing.assert_array_equal(actual['rng'][1],value['rng'][1])
        self.assertTrue(torch.equal(actual['state_dict']['weight'],value['state_dict']['weight']))
    def test_global_denied(self):
        with self.assertRaises(pickle.UnpicklingError): self.load(self.encode(Bad()))
    def test_sha_denied(self):
        with self.assertRaises(ValueError): load_bound_archive(self.encode({}),'0'*64)
    def test_codec_denied(self):
        with self.assertRaises(pickle.UnpicklingError): latin1_bytes('abc','utf-8')
    def test_path_object_denied(self):
        with self.assertRaises(pickle.UnpicklingError): posix_path(PosixPath('/tmp'))
    def test_parameter_value_preserved(self):
        x=torch.tensor([float('nan')],dtype=torch.float32)
        self.assertTrue(torch.isnan(self.load(self.encode({'x':x}))['x']).all())
        # Finiteness rejection belongs to stage_summary, not silent loader repair.

if __name__=='__main__': unittest.main()
