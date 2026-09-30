"""Synthetic fixtures for production orchestration; never checkpoint evidence."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from e0_archive_harness import layout
from e0_layout_reference import CONDITIONS,condition_ids
from loaded_model_adapter import FORMAL_SHA
from test_gain_observer_and_stages import fixture,provider
import production_e0

class WorkerBodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.spec=layout()
        f=fixture(); batch=provider(self.spec)
        self.refs={}
        for c in CONDITIONS:
            outputs=[]; losses=[]
            for k,ids in enumerate(self.spec['condition_batches'][c]):
                if not ids: continue
                s,cue,l,p=batch(k,c,ids)
                values,out=f.core.predict(f.base,f.outer,s,cue,l,p,f.device)
                outputs.append(out); losses.append(values['nll'])
            self.refs[c]=dict(trial_ids=condition_ids(self.spec,c),logits=np.concatenate(outputs),nll=np.concatenate(losses))

    @contextmanager
    def session(self,spec):
        f=fixture()
        yield dict(base=f.base,outer=f.outer,load_report=f.report,checkpoint_sha=FORMAL_SHA,
                   architecture_type=f.arch,gain_type=f.gain,batch_provider=provider(spec),device=f.device)

    def test_body_archive_and_offline_bridge(self):
        records=[]; release={'reference_sha256':'synthetic-test-reference'}
        with patch('audited_model_session.audited_session',self.session),patch.dict(os.environ,{'SLURM_JOB_ID':'synthetic'}),\
             patch('portable_reference.load_reference',return_value=self.refs),\
             patch('production_e0.load_reference',return_value=self.refs):
            for label in ('A','B'):
                d=self.root/label; d.mkdir()
                for name in ('stdout.log','stderr.log','LAUNCH.json'): (d/name).touch()
                production_e0.worker(self.root,label,d,release)
                records.append({'label':label,'pid':os.getpid()})
            report=production_e0.verify(self.root,records,self.root,release,'synthetic')
        self.assertEqual(report['predictions'],6048)
        # This test intentionally uses one PID; independent processes are tested elsewhere.

    def test_postcheck_failure_never_publishes_worker_success(self):
        @contextmanager
        def failed_session(spec):
            with self.session(spec) as context: yield context
            raise ValueError('INJECTED_POSTCHECK_FAILURE')
        d=self.root/'A'; d.mkdir()
        with patch('audited_model_session.audited_session',failed_session),\
             patch('portable_reference.load_reference',return_value=self.refs):
            with self.assertRaisesRegex(ValueError,'POSTCHECK'):
                production_e0.worker(self.root,'A',d,{'reference_sha256':'synthetic'})
        self.assertFalse((d/'WORKER.json').exists())
        self.assertTrue(list(d.glob('*.npz')))

    def test_real_bridge_mismatch_stops_first_pass(self):
        self.refs['correct']['logits'][0,0]+=1
        d=self.root/'A'; d.mkdir()
        with patch('audited_model_session.audited_session',self.session),\
             patch('portable_reference.load_reference',return_value=self.refs):
            with self.assertRaisesRegex(ValueError,'BRIDGE_BITS'):
                production_e0.worker(self.root,'A',d,{'reference_sha256':'synthetic'})
        self.assertFalse((d/'WORKER.json').exists())
        self.assertEqual(list(d.glob('*.npz')),[])

if __name__=='__main__': unittest.main()
