import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from build_e2_package import build
from e2_entry import verify_package

class PackageTests(unittest.TestCase):
    def test_pilot_package_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'package'; result=build(root,'pilot')
            completed=subprocess.run([sys.executable,'-I','-B',str(root/'e2_entry.py'),'check',result['release_sha256']],
                                     cwd=d,capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)
            report=json.loads(completed.stdout)
            self.assertEqual(report['predictions'],2709)
            self.assertEqual(report['profile'],'pilot')
            self.assertNotIn('@REMOTE_ROOT@',(root/'run_e2.sbatch').read_text())
    def test_isolated_package_and_mutation_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'package'; result=build(root); sha=result['release_sha256']
            completed=subprocess.run([sys.executable,'-I','-B',str(root/'e2_entry.py'),'check',sha],
                                     cwd=d,capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)
            report=json.loads(completed.stdout)
            self.assertEqual(report['predictions'],91134)
            self.assertFalse(report['production_ready'])
            p=root/'e2_catalog.py'; p.write_bytes(p.read_bytes()+b'\n# changed\n')
            with self.assertRaises(ValueError): verify_package(root,sha)

if __name__=='__main__': unittest.main()
