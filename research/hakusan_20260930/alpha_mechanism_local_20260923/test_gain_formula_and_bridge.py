import unittest
import json
from unittest.mock import patch
import numpy as np
import torch
from architecture_adapter import InterventionGain,NAMES
from loaded_model_adapter import pass_context,PASS_MAP
from gain_formula_check import check_installed_gains,reference
from loaded_worker_bridge import bridging_sink,run_loaded_worker
from test_gain_observer_and_stages import fixture
from test_gain_observer_and_stages import provider
from e0_layout_reference import CONDITIONS,HERE,condition_ids
from loaded_model_adapter import FORMAL_SHA

class FormulaTests(unittest.TestCase):
    def setUp(self): self.f=fixture()

    def test_all_passes_parameters_and_rng_unchanged(self):
        f=self.f
        before=f.core.state_digest(f.outer)
        rng=f.core.rng_digest()
        for name in ('original','explicit_bypass',*PASS_MAP):
            with pass_context(f.core,f.outer,f.arch,f.gain,name):
                report=check_installed_gains(f.outer.model,name)
                self.assertEqual(len(report['checks']),32)
        self.assertEqual(before,f.core.state_digest(f.outer))
        self.assertEqual(rng,f.core.rng_digest())

    def test_wrong_formula_rejected_and_modules_restored(self):
        f=self.f
        originals=[f.outer.model.model_dict[n] for n in NAMES]
        original=InterventionGain.forward
        def wrong(m,*args): return original(m,*args)+.01
        with self.assertRaisesRegex(ValueError,'G5_FORMULA_MISMATCH'):
            with pass_context(f.core,f.outer,f.arch,f.gain,'alpha_05'):
                with patch.object(InterventionGain,'forward',wrong):
                    check_installed_gains(f.outer.model,'alpha_05')
        self.assertEqual(originals,[f.outer.model.model_dict[n] for n in NAMES])

    def test_swapped_control_formula_rejected(self):
        f=self.f
        with pass_context(f.core,f.outer,f.arch,f.gain,'uniform_05'):
            f.outer.model.model_dict['attn0'].mode='alpha'
            with self.assertRaisesRegex(ValueError,'G5_FORMULA_MISMATCH'):
                check_installed_gains(f.outer.model,'uniform_05')

    def test_undefined_denominator_rejected(self):
        x=np.zeros((2,2,3,5))
        with self.assertRaisesRegex(ValueError,'CONTROL_UNDEFINED'):
            reference(x,x,-3.,0.,0.,.5,'mean_preserved',None)

    def test_fc_control_wrong_mode_rejected(self):
        f=self.f
        with pass_context(f.core,f.outer,f.arch,f.gain,'fc_mean_preserved_05'):
            f.outer.model.model_dict['attnfc'].mode='alpha'
            with self.assertRaisesRegex(ValueError,'G5_FORMULA_MISMATCH'):
                check_installed_gains(f.outer.model,'fc_mean_preserved_05')

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.refs={c:dict(trial_ids=[7],logits=np.zeros((1,800),np.float32),
                         nll=np.array([6.6846117],np.float32)) for c in CONDITIONS}
        self.payload={c:{k:v.copy() for k,v in data.items()} for c,data in self.refs.items()}
        self.calls=[]
        self.checks=[]
        self.sink=bridging_sink(self.refs,lambda *args:self.calls.append(args),self.checks)

    def test_both_endpoints(self):
        for name in ('original','alpha_1'): self.sink('A',name,self.payload,[])
        self.assertEqual(len(self.checks),2)

    def test_one_bit_and_nll_change_fail_before_sink(self):
        for field in ('logits','nll'):
            self.setUp()
            arr=self.payload['correct'][field]
            arr.flat[0]=np.nextafter(arr.flat[0],np.float32(np.inf))
            with self.assertRaises(ValueError): self.sink('A','original',self.payload,[])
            self.assertEqual(self.calls,[])

    def test_order_change_rejected(self):
        self.payload['silent']['trial_ids']=[8]
        with self.assertRaisesRegex(ValueError,'BRIDGE_ORDER'): self.sink('B','alpha_1',self.payload,[])

    def test_nonendpoint_not_compared_to_original(self):
        self.payload['correct']['logits']+=1
        self.sink('A','alpha_05',self.payload,[])
        self.assertEqual(self.checks,[])
        self.assertEqual(len(self.calls),1)

    def test_worker_wrong_identity_fails_before_reference_or_forward(self):
        with patch('loaded_worker_bridge.reference',side_effect=AssertionError('no reference')):
            with self.assertRaisesRegex(ValueError,'WORKER_MODEL_IDENTITY'):
                run_loaded_worker(None,None,None,'wrong',None,None,None,None,None,None,None)

    def test_worker_seam_with_explicit_synthetic_reference(self):
        # Test-only patch. Not historical validation or checkpoint provenance.
        f=fixture()
        layout=json.loads((HERE/'E0_LAYOUT_96.json').read_text())
        batch=provider(layout)
        refs={}
        for c in CONDITIONS:
            outputs=[]
            losses=[]
            for k,ids in enumerate(layout['condition_batches'][c]):
                if not ids: continue
                scene,cue,labels,probes=batch(k,c,ids)
                values,logits=f.core.predict(f.base,f.outer,scene,cue,labels,probes,f.device)
                outputs.append(logits)
                losses.append(values['nll'])
            refs[c]=dict(trial_ids=condition_ids(layout,c),logits=np.concatenate(outputs),nll=np.concatenate(losses))
        calls=[]
        with patch('loaded_worker_bridge.reference',return_value=refs):
            result=run_loaded_worker(f.base,f.outer,f.report,FORMAL_SHA,f.arch,f.gain,
                                     layout,'A',batch,f.device,lambda *a:calls.append(a))
        self.assertEqual(len(calls),11)
        self.assertEqual(len(result['historical_checks']),2)
        self.assertFalse(result['production_verified'])

if __name__=='__main__': unittest.main()
