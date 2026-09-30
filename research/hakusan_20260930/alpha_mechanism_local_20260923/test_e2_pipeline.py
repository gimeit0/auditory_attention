import json
from pathlib import Path
import sys
import tempfile
import unittest
from e2_pipeline import coordinate,WORKERS
from e2_verify_pipeline import verify_lifecycle
from e2_matrix import expected_records,stage_jobs
from e1_inputs import build_contract

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'run'
    def test_counts_and_cold_scope(self):
        c=build_contract()
        self.assertEqual(len(WORKERS),9)
        self.assertEqual(sum(map(len,expected_records(c,40,'cold_alpha1').values())),3600)
        with self.assertRaises(ValueError): list(stage_jobs(c,16,'cold_alpha1'))
    def test_sequential_synthetic_processes(self):
        def worker(r,m,out): return [sys.executable,'-c','pass']
        def verifier(root):
            code='from pathlib import Path; import json; Path('+repr(str(root/'VERIFY/VERIFIED.json'))+').write_text(json.dumps({"status":"E2_ARTIFACTS_VERIFIED","synthetic":True}))'
            return [sys.executable,'-c',code]
        result=coordinate(self.root,worker,verifier,seconds=20)
        self.assertEqual(len(result['workers']),9)
        self.assertTrue(result['verification']['synthetic'])
        for row in result['workers']:
            d=self.root/row['label']
            verify_lifecycle(row['lifecycle'],json.loads((d/'LAUNCH.json').read_text()),worker(0,'',None))
    def test_nonzero_stops_before_next_stage(self):
        with self.assertRaises(RuntimeError):
            coordinate(self.root,lambda *a:[sys.executable,'-c','raise SystemExit(3)'],lambda *a:[],seconds=5)
        self.assertTrue((self.root/'FAILED.json').exists())
        self.assertFalse((self.root/'stage_0').exists())
        self.assertEqual(json.loads((self.root/'stage_40/PROCESS.json').read_text())['returncode'],3)
    def test_bad_verifier_not_complete(self):
        with self.assertRaises(FileNotFoundError):
            coordinate(self.root,lambda *a:[sys.executable,'-c','pass'],lambda *a:[sys.executable,'-c','pass'],seconds=20)
        self.assertFalse((self.root/'COMPLETE.json').exists())
    def test_argv_mismatch(self):
        with self.assertRaises(ValueError): verify_lifecycle({'argv':['wrong']},{'argv':['right']},['right'])
    def test_postcheck_failure_never_creates_complete(self):
        def verifier(root):
            return [sys.executable,'-c','from pathlib import Path; Path('+repr(str(root/'VERIFY/VERIFIED.json'))+').write_text(\'{"status":"E2_ARTIFACTS_VERIFIED"}\')']
        def changed(): raise ValueError('PACKAGE_CHANGED')
        with self.assertRaisesRegex(ValueError,'PACKAGE_CHANGED'):
            coordinate(self.root,lambda *a:[sys.executable,'-c','pass'],verifier,seconds=20,final_check=changed)
        self.assertTrue((self.root/'FAILED.json').exists())
        self.assertFalse((self.root/'COMPLETE.json').exists())

if __name__=='__main__': unittest.main()
