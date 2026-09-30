import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from e2_process import run_child

class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'child'
    def record(self): return json.loads((self.path/'PROCESS.json').read_text())
    def test_complete(self):
        r=run_child([sys.executable,'-c','print(123)'],self.path,5)
        self.assertEqual(r['status'],'CHILD_COMPLETE')
        self.assertLessEqual(r['launch_requested_utc'],r['exit_observed_utc'])
        self.assertEqual(r['returncode'],0)
    def test_nonzero_archived(self):
        with self.assertRaises(RuntimeError): run_child([sys.executable,'-c','raise SystemExit(2)'],self.path,5)
        self.assertEqual(self.record()['returncode'],2)
        self.assertIsNotNone(self.record()['exit_observed_utc'])
    def test_timeout_archived(self):
        with self.assertRaises(subprocess.TimeoutExpired): run_child([sys.executable,'-c','import time; time.sleep(10)'],self.path,.1)
        self.assertEqual(self.record()['status'],'CHILD_TIMEOUT')
        self.assertIsNotNone(self.record()['returncode'])
    def test_launch_failure(self):
        with self.assertRaises(FileNotFoundError): run_child(['/not/an/executable'],self.path,1)
        self.assertIsNone(self.record()['pid'])
    def test_existing_directory_refused(self):
        self.path.mkdir()
        with self.assertRaises(FileExistsError): run_child([sys.executable,'-c','pass'],self.path,1)

if __name__=='__main__': unittest.main()
