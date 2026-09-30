import json
from pathlib import Path
import tempfile
import unittest
from e0_archive_harness import run,verify

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='e0-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'attempt'

    def test_full_6048_archive_and_readback(self):
        result=run(self.root)
        self.assertEqual(result,verify(self.root))
        self.assertEqual(result['predictions'],6048)
        self.assertFalse(result['production_gates_passed'])
        self.assertFalse((self.root/'FAILED.json').exists())

    def test_existing_attempt_never_overwritten(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError): run(self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_worker_failure_preserves_partial_no_complete(self):
        with self.assertRaisesRegex(ValueError,'WORKER_NONZERO'): run(self.root,fault='worker_error')
        self.assertEqual(len(list(self.root.glob('*.npz'))),2)
        self.assertFalse((self.root/'SYNTHETIC_COMPLETE.json').exists())
        self.assertFalse(json.loads((self.root/'FAILED.json').read_text())['retry_attempted'])
        with self.assertRaisesRegex(ValueError,'FAILED_ATTEMPT'): verify(self.root)

    def test_deadline_kills_worker_and_records_failure(self):
        with self.assertRaises(TimeoutError): run(self.root,timeout_seconds=.1,fault='hang')
        self.assertTrue((self.root/'FAILED.json').exists())
        self.assertFalse((self.root/'SYNTHETIC_COMPLETE.json').exists())

    def test_endpoint_failure_cannot_complete(self):
        with self.assertRaisesRegex(ValueError,'ENDPOINT_BITS'): run(self.root,fault='endpoint')
        self.assertTrue((self.root/'FAILED.json').exists())
        self.assertFalse((self.root/'SYNTHETIC_COMPLETE.json').exists())

    def test_corrupt_artifact_rejected(self):
        run(self.root)
        path=next(self.root.glob('*.npz'))
        with path.open('r+b') as f: f.write(b'CORRUPT')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SHA'): verify(self.root)

    def test_missing_file_rejected(self):
        run(self.root)
        next(self.root.glob('*.npz')).unlink()  # synthetic temporary fixture only
        with self.assertRaisesRegex(ValueError,'INVALID_ARTIFACT'): verify(self.root)

    def test_complete_marker_scope_tamper_rejected(self):
        run(self.root)
        path=self.root/'SYNTHETIC_COMPLETE.json'
        result=json.loads(path.read_text())
        result['production_gates_passed']=True
        path.write_text(json.dumps(result))  # synthetic temporary corruption fixture
        with self.assertRaisesRegex(ValueError,'COMPLETE_MISMATCH'): verify(self.root)

if __name__=='__main__': unittest.main()
