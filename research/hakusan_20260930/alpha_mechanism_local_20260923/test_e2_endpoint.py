from contextlib import contextmanager
from types import SimpleNamespace
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import torch
from e1_inputs import build_contract
from e2_endpoint import check_endpoint,probe_spec,verify_saved_endpoint
from e1_artifacts import identity

class EndpointTests(unittest.TestCase):
    def run_probe(self,changed=False):
        c=build_contract(); active=['original']
        @contextmanager
        def context(*args):
            active[0]=args[-1]; yield
        def provider(d,b,cond,ids):
            return None,None,torch.tensor([c['labels'][str(i)] for i in ids]),None
        def predict(base,model,s,cue,labels,p,device):
            logits=np.zeros((len(labels),800),np.float32)
            if changed and active[0]=='alpha_1': logits+=1 # NLL unchanged, logits changed.
            return {'nll':np.full(len(labels),np.log(800),np.float32)},logits
        ctx=dict(core=SimpleNamespace(predict=predict),outer=None,architecture_type=None,
                 gain_type=None,base=None,device='cpu',batch_provider=provider)
        with patch('e2_endpoint.pass_context',context): return check_endpoint(c,ctx)
    def test_pass(self): self.assertEqual(self.run_probe()['status'],'E2_STAGE_ENDPOINT_BITS_PASS')
    def test_bits_rejected(self):
        with self.assertRaises(ValueError): self.run_probe(changed=True)
    def test_spec_fixed(self):
        specs=probe_spec(build_contract())
        self.assertEqual(len(specs),6)
        self.assertTrue(all(ids for *_,ids in specs))

    def saved_fixture(self,root):
        layout=build_contract(); inventory=[]
        for mode in ('original','alpha_1'):
            for domain,bi,condition,ids in probe_spec(layout):
                name=f'{len(inventory):03d}.npz'
                np.savez(root/name,trial_ids=np.asarray(ids,np.int64),
                         logits=np.zeros((len(ids),800),np.float32),
                         nll=np.full(len(ids),np.log(800),np.float32))
                inventory.append(dict(key=[mode,domain,condition],file=name,**identity(root/name)))
        return layout,inventory

    def test_saved_endpoint_and_hash_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); layout,rows=self.saved_fixture(root)
            self.assertTrue(verify_saved_endpoint(root,layout,rows))
            p=root/rows[0]['file']; p.write_bytes(p.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'ENDPOINT_FILE_SHA'):
                verify_saved_endpoint(root,layout,rows)

    def test_saved_endpoint_rehashed_changed_logits(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); layout,rows=self.saved_fixture(root)
            row=rows[-1]; p=root/row['file']
            with np.load(p,allow_pickle=False) as z:
                values={k:z[k].copy() for k in z.files}
            values['logits']+=1 # Shift leaves NLL valid but violates endpoint equality.
            np.savez(p,**values); row.update(identity(p))
            with self.assertRaisesRegex(ValueError,'ENDPOINT_SAVED_BITS'):
                verify_saved_endpoint(root,layout,rows)

    def test_saved_endpoint_missing_and_extra(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); layout,rows=self.saved_fixture(root)
            with self.assertRaisesRegex(ValueError,'ENDPOINT_MISSING_OR_EXTRA'):
                verify_saved_endpoint(root,layout,rows[:-1])
            (root/'unexpected').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError,'ENDPOINT_MISSING_OR_EXTRA'):
                verify_saved_endpoint(root,layout,rows)

if __name__=='__main__': unittest.main()
