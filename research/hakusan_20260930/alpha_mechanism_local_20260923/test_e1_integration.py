import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import torch
from e1_supervisor import run_e1
from e1_provider import E1Provider

class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'attempt'
    def worker(self,label,d): return [sys.executable,'-B','-c','print("synthetic worker")']
    def verifier(self,root,d,records):
        return [sys.executable,'-B','-c',
                'import json,sys; from pathlib import Path; (Path(sys.argv[1])/"VERIFIED.json").write_text(json.dumps({"verified":True,"scope":"synthetic only"}))',str(d)]
    def test_three_process_pipeline(self):
        r=run_e1(self.root,self.worker,self.verifier,seconds=5)
        self.assertEqual(len({x['pid'] for x in r['records']}),3)
        self.assertTrue((self.root/'PROCESS_COMPLETE.json').is_file())
        with self.assertRaises(FileExistsError): run_e1(self.root,self.worker,self.verifier,seconds=5)
    def test_first_failure_stops_B(self):
        with self.assertRaisesRegex(ValueError,'CHILD_NONZERO'):
            run_e1(self.root,lambda *a:[sys.executable,'-c','raise SystemExit(2)'],self.verifier,seconds=5)
        self.assertFalse((self.root/'B').exists())
        self.assertFalse(json.loads((self.root/'FAILED.json').read_text())['retry_attempted'])
    def test_worker_timeout(self):
        with self.assertRaisesRegex(TimeoutError,'TOTAL_DEADLINE'):
            run_e1(self.root,lambda *a:[sys.executable,'-c','import time; time.sleep(20)'],self.verifier,seconds=.2)
        self.assertFalse((self.root/'B').exists())
    def test_verifier_timeout(self):
        with self.assertRaisesRegex(TimeoutError,'TOTAL_DEADLINE'):
            run_e1(self.root,self.worker,lambda *a:[sys.executable,'-c','import time; time.sleep(20)'],seconds=.5)
        self.assertTrue((self.root/'FAILED.json').exists())
        self.assertFalse((self.root/'PROCESS_COMPLETE.json').exists())
    def test_missing_verifier_record(self):
        with self.assertRaisesRegex(ValueError,'VERIFY_RECORD'):
            run_e1(self.root,self.worker,lambda *a:[sys.executable,'-c','pass'],seconds=5)

class ProviderTests(unittest.TestCase):
    def make(self):
        c=dict(main_batches=[[1]],control_batches=[[]],clean_batches=[[2]])
        with patch('e1_provider.NativeBatchProvider') as main,patch('e1_provider.CleanBatchProvider') as clean:
            pair={k:(torch.ones(1,2),torch.ones(1,2)*v,torch.tensor([4]))
                  for k,v in [('target_only_correct_cue',1),('target_only_zero_cue',0)]}
            clean.return_value.return_value=pair
            p=E1Provider(None,None,None,c,None,lambda **k:None,None,None,None)
            p.main.return_value='main_result'
        return p
    def test_pair_and_routing(self):
        p=self.make(); self.assertEqual(p('main',0,'correct',[1]),'main_result')
        self.assertTrue(torch.any(p('clean',0,'correct_cue',[2])[1]))
        self.assertFalse(torch.any(p('clean',0,'zero_cue',[2])[1]))
        self.assertIsNone(p.clean_pending)
    def test_wrong_pair_order(self):
        p=self.make()
        with self.assertRaisesRegex(ValueError,'PAIR_ORDER'): p('clean',0,'zero_cue',[2])
        p('clean',0,'correct_cue',[2])
        with self.assertRaisesRegex(ValueError,'PAIR_IDS'): p('clean',0,'zero_cue',[3])
    def test_incomplete_pair(self):
        p=self.make(); p('clean',0,'correct_cue',[2])
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'): p('main',0,'correct',[1])
    def test_session_gate_no_load(self):
        from e1_audited_session import audited_e1_session
        with patch('e1_audited_session.launch_gate',side_effect=ValueError('NATIVE_GATE')):
            with self.assertRaisesRegex(ValueError,'NATIVE_GATE'):
                with audited_e1_session({}): self.fail('must not load')

if __name__=='__main__': unittest.main()
