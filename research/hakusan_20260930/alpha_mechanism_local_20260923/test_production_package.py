import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from build_e0_package import build
from e0_entry import verify_package
from e0_archive_harness import layout
from e0_layout_reference import reference,CONDITIONS
from portable_reference import load_reference
from submit_e0_once import submit,argv

class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.package=Path(cls.tmp.name)/'package'
        cls.report=build(cls.package)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_portable_reference_exact_historical_bits(self):
        portable=load_reference(self.package/'reference',layout(),self.report['reference_sha256'])
        original=reference(layout())
        for c in CONDITIONS:
            self.assertEqual(portable[c]['logits'].tobytes(),original[c]['logits'].tobytes())
            self.assertEqual(portable[c]['nll'].tobytes(),original[c]['nll'].astype('float32').tobytes())

    def test_isolated_check_works_outside_project(self):
        result=subprocess.run([sys.executable,'-I','-B',str(self.package/'e0_entry.py'),'check',
                    self.report['release_sha256']],cwd=self.tmp.name,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PACKAGE_BYTES_PASS')

    def test_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            copy=Path(temp)/'package'; shutil.copytree(self.package,copy)
            with (copy/'production_e0.py').open('ab') as f: f.write(b'\n# corrupt\n')
            with self.assertRaisesRegex(ValueError,'PACKAGE_FILE'):
                verify_package(copy,self.report['release_sha256'])

    def test_unknown_python_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            copy=Path(temp)/'package'; shutil.copytree(self.package,copy)
            (copy/'unreviewed.py').touch()
            with self.assertRaisesRegex(ValueError,'INVENTORY'):
                verify_package(copy,self.report['release_sha256'])

    def test_reference_wrong_digest_rejected(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_SHA'):
            load_reference(self.package/'reference',layout(),'0'*64)

    def test_builder_never_overwrites(self):
        with self.assertRaises(FileExistsError): build(self.package)

    @unittest.skipUnless(sys.platform=='darwin','Mac rejection check only')
    def test_native_source_probe_refuses_local_mac(self):
        result=subprocess.run([sys.executable,'-I','-B',str(self.package/'e0_entry.py'),'source-check',
                               self.report['release_sha256']],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('NATIVE_ISOLATED_PREFLIGHT',result.stderr)

class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)/'state'; self.calls=[]

    def execute(self,command):
        self.calls.append(command)
        return dict(returncode=0,stdout='123456\n' if '--hold' in command else '',stderr='')

    def test_exact_budget_held_once(self):
        result=submit(Path('/package'),self.state,'a'*64,self.execute)
        self.assertEqual(result['status'],'SUBMITTED_HELD_NOT_RELEASED')
        command=self.calls[-1]
        for flag in ('--hold','--time=00:30:00','--gres=gpu:nvidia_a100:1','--no-requeue','--cpus-per-task=8','--mem=65536M'):
            self.assertIn(flag,command)
        self.assertFalse(any('release' in str(c) for c in self.calls))
        with self.assertRaisesRegex(ValueError,'NO_RETRY'): submit(Path('/package'),self.state,'a'*64,self.execute)
        self.assertEqual(len(self.calls),3)

    def test_ambiguous_response_preserved_no_receipt(self):
        def execute(command):
            return dict(returncode=0,stdout='unparseable' if '--hold' in command else '',stderr='')
        with self.assertRaisesRegex(ValueError,'UNKNOWN'): submit(Path('/p'),self.state,'a'*64,execute)
        self.assertTrue((self.state/'INTENT.json').exists())
        self.assertFalse((self.state/'SUBMISSION.json').exists())

    def test_timeout_never_retries(self):
        def execute(command):
            if '--hold' in command: raise subprocess.TimeoutExpired(command,60)
            return self.execute(command)
        with self.assertRaises(subprocess.TimeoutExpired): submit(Path('/p'),self.state,'a'*64,execute)
        self.assertTrue((self.state/'SUBMISSION_UNKNOWN.json').exists())
        with self.assertRaises(ValueError): submit(Path('/p'),self.state,'a'*64,execute)

    def test_related_queue_blocks_submission(self):
        def execute(command): return dict(returncode=0,stdout='42|audattn_alpha_e0|PENDING\n',stderr='')
        with self.assertRaisesRegex(ValueError,'QUEUE'): submit(Path('/p'),self.state,'a'*64,execute)
        self.assertFalse((self.state/'INTENT.json').exists())

    def test_test_only_failure_no_submit(self):
        def execute(command):
            if '--test-only' in command: return dict(returncode=1,stdout='',stderr='invalid resources')
            return self.execute(command)
        with self.assertRaisesRegex(ValueError,'TEST_ONLY'): submit(Path('/p'),self.state,'a'*64,execute)
        self.assertFalse((self.state/'INTENT.json').exists())

if __name__=='__main__': unittest.main()
