"""Synthetic collection and status tests. Never contacts HAKUSAN."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from collect_fine_alpha_753729 import SHA, extract_verified, REMOTE as COLLECT_REMOTE
from status_fine_alpha_753729 import classify, REMOTE as STATUS_REMOTE


class FollowupTests(unittest.TestCase):
    def test_running_and_terminal_accounting(self):
        r = dict(job_id='753729', release_sha256=SHA, markers={}, blocks={b: {'completed_records_observed': 0} for b in 'ABC'},
                 commands=dict(squeue=dict(returncode=0, stdout='753729|RUNNING|None|1:00\n'),
                               sacct=dict(returncode=0, stdout='753729|RUNNING|0:0|00:01:00\n')))
        self.assertFalse(classify(r)['terminal'])
        r['commands']['squeue']['stdout'] = ''
        r['commands']['sacct']['stdout'] = '753729|FAILED|1:0|00:02:00\n'
        self.assertTrue(classify(r)['terminal'])
        self.assertEqual(classify(r)['scheduler_state'], 'FAILED')

    def test_complete_marker_not_scheduler_completion(self):
        r = dict(job_id='753729', release_sha256=SHA, markers={'COMPLETE.json':dict(job_id='753729',release_sha256=SHA,status='FINE_ALPHA_ARTIFACTS_VERIFIED')},
                 blocks={b: {'completed_records_observed': 0} for b in 'ABC'},
                 commands=dict(squeue=dict(returncode=0, stdout='753729|COMPLETING|None|1:00\n'),
                               sacct=dict(returncode=0, stdout='753729|RUNNING|0:0|00:01:00\n')))
        self.assertFalse(classify(r)['terminal'])

    def test_queue_failure_requires_exact_terminal_accounting(self):
        r = dict(job_id='753729', release_sha256=SHA, markers={},
                 blocks={b: {'completed_records_observed': 0} for b in 'ABC'},
                 commands=dict(squeue=dict(returncode=1, stdout='', stderr='queue query failed'),
                               sacct=dict(returncode=0, stdout='753729|FAILED|1:0|01:48:21\n')))
        self.assertTrue(classify(r)['terminal'])
        self.assertEqual(classify(r)['query_warning'], 'SQUEUE_FAILED_TERMINAL_SACCT_FALLBACK')
        for value in ('', '753729|RUNNING|0:0|01:00:00\n', '999|FAILED|1:0|01:00:00\n'):
            r['commands']['sacct']['stdout'] = value
            with self.assertRaisesRegex(ValueError, 'QUERY_FAILED'): classify(r)
        r['commands']['sacct'].update(returncode=1, stdout='753729|FAILED|1:0|01:48:21\n')
        with self.assertRaisesRegex(ValueError, 'QUERY_FAILED:sacct'): classify(r)

    def archive(self, directory, *, unsafe=False, bad_hash=False):
        payload = b'{}'; files = {'attempt/test.json':dict(size=2, sha256='0'*64 if bad_hash else hashlib.sha256(payload).hexdigest())}
        meta = json.dumps(dict(job_id='753729', release_sha256=SHA, files=files)).encode()
        path = directory/'transport.tar'
        with tarfile.open(path, 'w:') as t:
            for name, raw in [('COLLECTION_MANIFEST.json', meta), ('../bad' if unsafe else 'state/attempt/test.json', payload)]:
                m = tarfile.TarInfo(name); m.size = len(raw); t.addfile(m, io.BytesIO(raw))
        return path

    def test_nested_verified_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d); archive = self.archive(directory)
            extract_verified(archive, directory/'out')
            self.assertEqual((directory/'out/state/attempt/test.json').read_bytes(), b'{}')

    def test_bad_hash_and_traversal_rejected(self):
        for kw in ({'unsafe':True}, {'bad_hash':True}):
            with tempfile.TemporaryDirectory() as d:
                directory = Path(d); archive = self.archive(directory, **kw)
                with self.assertRaises(ValueError): extract_verified(archive, directory/'out')

    def test_remote_syntax(self):
        for source in (COLLECT_REMOTE, STATUS_REMOTE): compile(source, '<readonly-remote>', 'exec')


if __name__ == '__main__': unittest.main()
