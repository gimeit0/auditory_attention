"""Upload queue separation, with scheduler/filesystem IO mocked; no network."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import fine_alpha_upload_transport as transport
from publish_fine_alpha_v2 import REVIEWED_JOBS, REMOTE_ROOT


class UploadQueueTests(unittest.TestCase):
    def setUp(self):
        self.expected = REVIEWED_JOBS['754073']
        self.fields = dict(JobId='754073', UserId='s2510040(27831)',
                           **{key: value for key, value in self.expected.items() if key != 'command_sha256'})

    def text(self, fields=None):
        return ' '.join(key+'='+value for key, value in (self.fields if fields is None else fields).items())

    def queue(self, stdout='754073|audattn_numcheck_seed20260928|RUNNING\n', rc=0):
        return SimpleNamespace(returncode=rc, stdout=stdout)

    def test_reviewed_job_is_disjoint(self):
        self.assertEqual(transport.validate_reviewed_job(self.text(), '754073', self.expected['JobName'],
                                                        REMOTE_ROOT, self.expected), self.fields)

    def test_each_identity_field_mismatch_rejected(self):
        for key in self.fields:
            fields = dict(self.fields); fields[key] += '_changed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                transport.validate_reviewed_job(self.text(fields), '754073', self.expected['JobName'],
                                                REMOTE_ROOT, self.expected)

    def test_missing_duplicate_and_noncanonical_paths_rejected(self):
        for text in (self.text().replace('JobId=754073 ', ''), self.text()+' JobId=754073'):
            with self.assertRaisesRegex(ValueError, 'JOB_METADATA_FIELD'):
                transport.validate_reviewed_job(text, '754073', self.expected['JobName'], REMOTE_ROOT, self.expected)
        for value in ('relative/path', '/home/s2510040/x/../target'):
            fields = dict(self.fields, WorkDir=value); expected = dict(self.expected, WorkDir=value)
            with self.assertRaisesRegex(ValueError, 'JOB_PATH'):
                transport.validate_reviewed_job(self.text(fields), '754073', self.expected['JobName'], REMOTE_ROOT, expected)

    def test_overlap_even_if_in_reviewed_record_rejected(self):
        for path in (REMOTE_ROOT, REMOTE_ROOT+'/state', str(Path(REMOTE_ROOT).parent)):
            fields = dict(self.fields, WorkDir=path); expected = dict(self.expected, WorkDir=path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'PATH_CONFLICT'):
                transport.validate_reviewed_job(self.text(fields), '754073', self.expected['JobName'], REMOTE_ROOT, expected)

    def test_legacy_policy_still_blocks_by_name(self):
        with self.assertRaisesRegex(ValueError, 'QUEUE_FAILED_OR_RELATED_JOB'):
            transport.check_upload_queue(REMOTE_ROOT, self.queue())

    def test_failed_query_and_unreviewed_or_malformed_queue_rejected(self):
        for row in (self.queue(rc=1), self.queue('999999|independent|RUNNING\n'), self.queue('bad-format\n')):
            with self.assertRaises(ValueError), patch.object(transport.subprocess, 'run') as run:
                transport.check_upload_queue(REMOTE_ROOT, row, REVIEWED_JOBS)
            run.assert_not_called()

    def test_empty_queue_passes_without_scheduler_query(self):
        with patch.object(transport.subprocess, 'run') as run:
            transport.check_upload_queue(REMOTE_ROOT, self.queue(''), REVIEWED_JOBS)
        run.assert_not_called()

    def test_live_readback_and_command_hash_required(self):
        for returncode, symlink, digest, passes in ((0, False, self.expected['command_sha256'], True),
                (1, False, self.expected['command_sha256'], False),
                (0, True, self.expected['command_sha256'], False), (0, False, '0'*64, False)):
            with self.subTest(returncode=returncode, symlink=symlink, digest=digest), \
                 patch.object(transport.subprocess, 'run', return_value=SimpleNamespace(returncode=returncode, stdout=self.text())) as run, \
                 patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'is_symlink', return_value=symlink), \
                 patch.object(Path, 'read_bytes', return_value=b'reviewed'), patch.object(transport, 'sha', return_value=digest), \
                 patch('builtins.print'):
                if passes:
                    transport.check_upload_queue(REMOTE_ROOT, self.queue(), REVIEWED_JOBS)
                else:
                    with self.assertRaises(ValueError): transport.check_upload_queue(REMOTE_ROOT, self.queue(), REVIEWED_JOBS)
                self.assertEqual(run.call_args.args[0], ['/usr/bin/scontrol', 'show', 'job', '-o', '754073'])


if __name__ == '__main__': unittest.main()
