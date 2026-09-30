import json
import unittest
import numpy as np
import torch
import test_loaded_model_adapter as fixtures
from loaded_model_adapter import pass_context
from gain_observer import GainObserver
from model_stage_driver import execute_stages
from e0_layout_reference import HERE

def fixture():
    fixtures.LoadedAdapterTests.setUpClass()
    f=fixtures.LoadedAdapterTests('test_accept_metadata_without_claiming_provenance')
    f.setUp()
    return f

def provider(spec):
    def batch(index,condition,ids):
        # Small synthetic features, deterministic and independent of global RNG.
        grid=torch.arange(30,dtype=torch.float32).reshape(1,2,3,5)
        scene=(grid+torch.tensor(ids,dtype=torch.float32)[:,None,None,None])%19/10
        cue=scene.flip(-1)+{'correct':.1,'shuffled':.2,'silent':0.,'distractor':.3}[condition]
        if condition=='silent': cue=torch.zeros_like(cue)
        cue=cue.clone()
        cue[torch.tensor([i>=9000 for i in ids])]=0
        labels=torch.tensor([spec['target_labels'][str(i)] for i in ids])
        return scene,cue,labels,labels.clone()
    return batch

class ObserverTests(unittest.TestCase):
    def setUp(self): self.f=fixture()
    def context(self):
        f=self.f
        return pass_context(f.core,f.outer,f.arch,f.gain,'alpha_05')
    def predict(self):
        f=self.f
        return f.core.predict(f.base,f.outer,f.scene,f.cue,f.labels,f.labels,f.device)

    def test_eight_records_bitwise_no_tensor_retention(self):
        baseline=self.f.run_pass('alpha_05')
        with self.context():
            with GainObserver(self.f.outer.model) as obs:
                with obs.batch(0,'correct',[1,2]): actual=self.predict()
            self.assertEqual(len(obs.records),8)
            self.assertEqual(len(json.loads(json.dumps(obs.records))),8)
            self.assertEqual(actual[1].tobytes(),baseline[1].tobytes())
            self.assertEqual(actual[0]['nll'].tobytes(),baseline[0]['nll'].tobytes())
        self.assertTrue(all(not m._forward_hooks for m in self.f.outer.modules()))

    def test_cleanup_on_body_error(self):
        with self.assertRaisesRegex(RuntimeError,'test error'):
            with self.context():
                with GainObserver(self.f.outer.model) as obs:
                    with obs.batch(0,'correct',[1,2]): raise RuntimeError('test error')
        self.assertTrue(all(not m._forward_hooks for m in self.f.outer.modules()))

    def test_event_and_byte_budgets(self):
        for kw in ({'max_events':7},{'max_bytes':100}):
            with self.assertRaisesRegex(ValueError,'BUDGET'):
                with self.context():
                    with GainObserver(self.f.outer.model,**kw) as obs:
                        with obs.batch(0,'correct',[1,2]): self.predict()
            self.assertTrue(all(not m._forward_hooks for m in self.f.outer.modules()))

    def test_missing_and_out_of_order_events(self):
        with self.assertRaisesRegex(ValueError,'MISSING_EVENT'):
            with self.context():
                with GainObserver(self.f.outer.model) as obs:
                    with obs.batch(0,'correct',[1,2]): pass
        with self.assertRaisesRegex(ValueError,'EVENT_ORDER'):
            with self.context():
                with GainObserver(self.f.outer.model) as obs:
                    with obs.batch(0,'correct',[1,2]):
                        self.f.outer.model.model_dict['attnfc'](self.f.cue,self.f.scene,None)

    def test_existing_hook_and_reuse_rejected(self):
        with self.context():
            m=self.f.outer.model.model_dict['attn0']
            h=m.register_forward_hook(lambda *args:None)
            try:
                with self.assertRaisesRegex(ValueError,'HOOK'):
                    with GainObserver(self.f.outer.model): pass
            finally: h.remove()
            obs=GainObserver(self.f.outer.model)
            with obs: pass
            with self.assertRaisesRegex(ValueError,'SINGLE_USE'):
                with obs: pass

    def test_nonfinite_and_large_tensor_rejected(self):
        obs=GainObserver(self.f.outer.model,max_tensor_numel=10)
        with self.assertRaisesRegex(ValueError,'OBSERVER_TENSOR'): obs.summary(self.f.scene)
        obs=GainObserver(self.f.outer.model)
        with self.assertRaisesRegex(ValueError,'NONFINITE'): obs.summary(self.f.scene*float('nan'))

class StageTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture()
        self.spec=json.loads((HERE/'E0_LAYOUT_96.json').read_text())

    def execute(self,process,sink,batch=None,**kwargs):
        f=self.f
        return execute_stages(f.core,f.base,f.outer,f.arch,f.gain,self.spec,process,
                              provider(self.spec) if batch is None else batch,f.device,sink,**kwargs)

    def test_21_model_forward_passes_and_observer(self):
        outputs={}
        def sink(p,n,data,events):
            outputs[p,n]=data
            if n=='alpha_05_observed':
                self.assertEqual(len(events),144)
                self.assertLess(len(json.dumps(events).encode()),262144)
        a=self.execute('A',sink)
        self.f=fixture()  # independent model object, same Python process: not cold-process evidence
        b=self.execute('B',sink)
        self.assertEqual(a['predictions']+b['predictions'],6048)
        for name in self.spec['passes']:
            for c in ('correct','shuffled','silent','distractor'):
                self.assertEqual(outputs['A',name][c]['logits'].tobytes(),outputs['B',name][c]['logits'].tobytes())
        self.assertFalse(a['production_verified'])

    def test_stage_deadline_stops_before_sink(self):
        times=iter([0,2])
        with self.assertRaisesRegex(TimeoutError,'STAGE_DEADLINE'):
            self.execute('A',lambda *args:self.fail('sink must not run'),deadline_seconds=1,clock=lambda:next(times))

    def test_sink_error_stops_and_hooks_restored(self):
        calls=[]
        def sink(p,n,data,events):
            calls.append(n)
            raise RuntimeError('sink failed')
        with self.assertRaisesRegex(RuntimeError,'sink failed'): self.execute('A',sink)
        self.assertEqual(calls,['original'])
        self.assertTrue(all(not m._forward_hooks for m in self.f.outer.modules()))

    def test_label_mismatch_stops(self):
        fn=provider(self.spec)
        def wrong(*args):
            s,c,l,p=fn(*args)
            return s,c,l+1,p
        with self.assertRaisesRegex(ValueError,'STAGE_LABELS'):
            self.execute('A',lambda *args:None,wrong)

    def test_input_changes_across_pass_rejected(self):
        fn=provider(self.spec)
        count=0
        def changing(*args):
            nonlocal count
            count+=1
            s,c,l,p=fn(*args)
            return s+(1 if count>18 else 0),c,l,p
        with self.assertRaisesRegex(ValueError,'STAGE_INPUT_CHANGED'):
            self.execute('A',lambda *args:None,changing)

if __name__=='__main__': unittest.main()
