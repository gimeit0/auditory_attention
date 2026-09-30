"""Fabricated completion metadata tests, not execution/production evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import test_e1_worker_archive as fixtures
from build_e1_package import build
from e1_entry import REMOTE_ROOT,canonical,identity,verify_package
from production_e1 import verify_bound_archive,verify_completed

class CompletedTests(unittest.TestCase):
    def setUp(self):
        fixtures.ArchiveTests.setUp(self)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.package=Path(tmp.name)/'package'
        self.digest=build(self.package)['release_sha256']
        self.release=verify_package(self.package,self.digest)
        for r in self.workers:
            r['argv']=['/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',
                       str(REMOTE_ROOT/'package/e1_entry.py'),'worker',self.digest,r['label']]
            d=self.root/r['label']
            (d/'LAUNCH.json').write_bytes(canonical({k:r[k] for k in ('label','pid','argv')}))
            m=self.metadata[r['label']]
            m.update(release_sha256=self.digest,launch=identity(d/'LAUNCH.json'),job_id='900001')
            m['load_report']['native_preprocessing']='selftrain_singleton_per_example_leveling'
            (d/'WORKER.json').write_bytes(canonical(m))
        result=verify_bound_archive(self.root,self.c,self.workers,self.package,self.release,self.digest,'900001')
        (self.root/'VERIFY').mkdir()
        r=dict(label='VERIFY',pid=999,returncode=0,argv=[
            '/home/s2510040/miniconda3/envs/attn/bin/python','-I','-B','-u',
            str(REMOTE_ROOT/'package/e1_entry.py'),'verify',self.digest])
        (self.root/'VERIFY/LAUNCH.json').write_bytes(canonical({k:r[k] for k in ('label','pid','argv')}))
        (self.root/'VERIFY/VERIFIED.json').write_bytes(canonical(result))
        (self.root/'VERIFY_REQUEST.json').write_bytes(canonical(dict(records=self.workers,release_sha256=self.digest,job_id='900001')))
        (self.root/'PROCESS_COMPLETE.json').write_bytes(canonical(dict(records=self.workers+[r],verification=result,elapsed_seconds=1)))
        (self.root/'E1_COMPLETE.json').write_bytes(canonical(dict(
            status='E1_EXECUTION_VERIFIED_ANALYSIS_PENDING',job_id='900001',release_sha256=self.digest,
            contract_sha256=self.release['contract_sha256'],pipeline=identity(self.root/'PROCESS_COMPLETE.json'),verification=result)))

    def verify(self):
        return verify_completed(self.root,self.c,self.package,self.release,self.digest,'900001')

    def test_bound_roundtrip(self): self.assertTrue(self.verify()['verified'])
    def test_failed_marker(self):
        (self.root/'FAILED.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'FAILED_ATTEMPT'):self.verify()
    def test_wrong_release(self):
        p=self.root/'A/WORKER.json';m=json.loads(p.read_bytes());m['release_sha256']='0'*64;p.write_bytes(canonical(m))
        with self.assertRaisesRegex(ValueError,'WORKER_RELEASE'):self.verify()
    def test_request_tamper(self):
        (self.root/'VERIFY_REQUEST.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'VERIFY_REQUEST_BINDING'):self.verify()
    def test_report_tamper(self):
        (self.root/'VERIFY/VERIFIED.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'OFFLINE_REPORT'):self.verify()

if __name__=='__main__':unittest.main()
