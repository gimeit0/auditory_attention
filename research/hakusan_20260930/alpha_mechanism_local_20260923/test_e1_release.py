"""Local candidate release and fake scheduler tests; never uses SSH or Slurm."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from build_e1_package import build
from e1_entry import verify_package,load_contract,check_receipt,canonical,identity
from submit_e1_once import submit

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.package=self.root/'package'
        self.result=build(self.package);self.digest=self.result['release_sha256']

    def test_isolated_check_import_closure(self):
        argv=[sys.executable,'-I','-B',str(self.package/'e1_entry.py'),'check',self.digest]
        r=subprocess.run(argv,cwd='/',capture_output=True,text=True,timeout=20,check=True)
        self.assertEqual(json.loads(r.stdout)['status'],'E1_PACKAGE_BYTES_AND_INPUTS_PASS')
        code='import sys;sys.path.insert(0,sys.argv[1]);import production_e1,e1_audited_session;print("IMPORT_PASS")'
        r=subprocess.run([sys.executable,'-I','-B','-c',code,str(self.package)],cwd='/',capture_output=True,text=True,timeout=30,check=True)
        self.assertEqual(r.stdout.strip(),'IMPORT_PASS')

    def test_builder_no_overwrite(self):
        with self.assertRaises(FileExistsError):build(self.package)
        self.assertFalse((self.package/'rehearse_e1_release.py').exists())
        self.assertFalse((self.package/'e0_archive_harness.py').exists())
        self.assertFalse(any(self.package.glob('test_*.py')))

    def test_isolated_submit_help(self):
        r=subprocess.run([sys.executable,'-I','-B',str(self.package/'submit_e1_once.py'),'--help'],
                         cwd='/',capture_output=True,text=True,timeout=15,check=True)
        self.assertIn('SUBMIT_E1_HELD_ONCE_3_GPU_HOURS',r.stdout)
        self.assertFalse((self.root/'state').exists())

    def test_tampered_source(self):
        with (self.package/'e1_inputs.py').open('ab') as f:f.write(b'\n')
        with self.assertRaisesRegex(ValueError,'PACKAGE_FILE'):verify_package(self.package,self.digest)

    def test_extra_file(self):
        (self.package/'unexpected.py').touch()
        with self.assertRaisesRegex(ValueError,'INVENTORY'):verify_package(self.package,self.digest)

    def test_symlink(self):
        (self.package/'extra').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):verify_package(self.package,self.digest)

    def test_invalid_release_hash(self):
        with self.assertRaisesRegex(ValueError,'RELEASE_SHA'):verify_package(self.package,'0'*64)

    def fake(self,commands,response='123456\n',fail_test=False,ambiguous=False):
        def execute(argv):
            commands.append(argv)
            if '--hold' in argv:
                if ambiguous:raise TimeoutError('synthetic transport timeout')
                return dict(returncode=0,stdout=response,stderr='')
            return dict(returncode=int(fail_test and '--test-only' in argv),stdout='',stderr='')
        return execute

    def test_submit_once_receipt(self):
        commands=[];state=self.root/'state'
        r=submit(self.package,state,self.digest,self.fake(commands))
        self.assertEqual(r['job_id'],'123456')
        self.assertEqual(sum('--hold' in a for a in commands),1)
        self.assertIn('--time=03:00:00',commands[-1])
        self.assertEqual(check_receipt(state,self.digest,'123456'),r)
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):submit(self.package,state,self.digest,self.fake(commands))
        self.assertEqual(len(commands),3)
        with self.assertRaisesRegex(ValueError,'JOB_RECEIPT'):check_receipt(state,self.digest,'other')

    def test_ambiguous_no_retry(self):
        state=self.root/'state';commands=[]
        with self.assertRaises(TimeoutError):submit(self.package,state,self.digest,self.fake(commands,ambiguous=True))
        self.assertTrue(json.loads((state/'STOPPED.json').read_text())['submission_may_have_happened'])
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):submit(self.package,state,self.digest,self.fake(commands))
        self.assertEqual(len(commands),3)

    def test_test_only_failure(self):
        commands=[]
        with self.assertRaisesRegex(ValueError,'TEST_ONLY_FAILED'):
            submit(self.package,self.root/'state',self.digest,self.fake(commands,fail_test=True))
        self.assertFalse(any('--hold' in a for a in commands))

    def test_malformed_response(self):
        with self.assertRaisesRegex(ValueError,'SUBMISSION_UNKNOWN'):
            submit(self.package,self.root/'state',self.digest,self.fake([],response='not-a-job'))

    def test_receipt_tamper(self):
        state=self.root/'state';submit(self.package,state,self.digest,self.fake([]))
        with (state/'INTENT.json').open('ab') as f:f.write(b' ')
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHAIN'):check_receipt(state,self.digest,'123456')

    def test_local_run_rejected(self):
        r=subprocess.run([sys.executable,'-I','-B',str(self.package/'e1_entry.py'),'run',self.digest],
                         cwd='/',capture_output=True,text=True,timeout=20)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('NATIVE_ACCOUNT',r.stderr)
        self.assertFalse((self.root/'state').exists())

if __name__=='__main__':unittest.main()
