import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from rehearse_model_pair import verify
import rehearse_model_pair
from two_process_supervisor import run_pair

class PairArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)/'original'
        cls.result=run_pair(cls.root,lambda label,d:[sys.executable,'-B',str(Path(rehearse_model_pair.__file__).resolve()),
                  'worker',label,str(d)],verify,timeout_seconds=60)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_complete_two_model_processes(self):
        self.assertEqual(self.result['verification']['predictions'],6048)
        self.assertNotEqual(*[r['pid'] for r in self.result['workers']])

    def test_corrupt_output_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            copy=Path(t)/'copy'
            shutil.copytree(self.root,copy)
            p=copy/'A/00_original.npz'
            data=bytearray(p.read_bytes()); data[-1]^=1; p.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'OUTPUT_SHA'): verify(copy,self.result['workers'])

    def test_missing_g5_report_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            copy=Path(t)/'copy'
            shutil.copytree(self.root,copy)
            (copy/'B/STAGES.json').unlink()
            with self.assertRaises(ValueError): verify(copy,self.result['workers'])

    def test_wrong_worker_pid_rejected(self):
        records=[dict(r,pid=r['pid']+1) for r in self.result['workers']]
        with self.assertRaisesRegex(ValueError,'WORKER_IDENTITY'): verify(self.root,records)

if __name__=='__main__': unittest.main()
