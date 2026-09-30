"""Portable input tests, no torch import required by the production reader."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from e1_inputs import HERE, build_contract

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('E1_DATA_FREEZE_20260926_v1.json', 'E1_CANDIDATE_2000_20260926.json', 'e1_inputs.py'):
            shutil.copyfile(HERE/name, self.root/name)
        shutil.copyfile(HERE.parent/'docs/superpowers/evidence/p05-confirmation-set-20260919/frozen_bank.tsv', self.root/'frozen_bank.tsv')

    def test_portable_equals_workspace(self):
        self.assertEqual(build_contract(self.root), build_contract())

    def test_isolated_stdlib_import(self):
        code = ('import sys,json;sys.path.insert(0,sys.argv[1]);'
                'from e1_inputs import build_contract;'
                'c=build_contract(sys.argv[1]);'
                'assert "torch" not in sys.modules;'
                'assert "select_e1" not in sys.modules;'
                'print(json.dumps(c,sort_keys=True))')
        result = subprocess.run([sys.executable,'-I','-B','-c',code,str(self.root)],
                                capture_output=True,text=True,timeout=15,check=True,cwd='/')
        self.assertEqual(json.loads(result.stdout),build_contract())

    def test_missing_no_fallback(self):
        (self.root/'frozen_bank.tsv').unlink()
        with self.assertRaisesRegex(ValueError,'E1_INPUT_FILE'):
            build_contract(self.root)

    def test_input_cli(self):
        reader_sha=hashlib.sha256((self.root/'e1_inputs.py').read_bytes()).hexdigest()
        raw=(json.dumps(build_contract(),ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        argv=[sys.executable,'-I','-B',str(HERE/'e1_input_check.py'),str(self.root),
              '--expected-reader-sha256',reader_sha,'--expected-contract-sha256',hashlib.sha256(raw).hexdigest()]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=15,check=True,cwd='/')
        self.assertEqual(json.loads(result.stdout)['status'],'E1_PORTABLE_INPUT_CHECK_PASS')
        argv[-1]='0'*64
        result=subprocess.run(argv,capture_output=True,text=True,timeout=15,cwd='/')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CONTRACT_SHA',result.stderr)

    def test_changed_rejected(self):
        with (self.root/'frozen_bank.tsv').open('ab') as f: f.write(b'\n')
        with self.assertRaisesRegex(ValueError,'E1_INPUT_SHA'):
            build_contract(self.root)

    def test_symlink_rejected(self):
        path=self.root/'frozen_bank.tsv'
        target=self.root/'bank-copy.tsv'
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'E1_INPUT_FILE'):
            build_contract(self.root)

if __name__=='__main__': unittest.main()
