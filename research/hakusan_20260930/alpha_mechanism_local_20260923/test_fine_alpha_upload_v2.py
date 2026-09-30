"""V2 upload binding and receiver tests, local temporary directories only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fine_alpha_upload_transport import validate_transport, publish
from publish_fine_alpha_v2 import (make_transport, receiver_bootstrap, validate_receipt,
                                  HERE, PACKAGE, SHA, SCOPE, REMOTE_ROOT, REVIEWED_JOBS)
from test_fine_alpha_upload import fixture


class V2UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.manifest, cls.blob = make_transport()

    def test_actual_frozen_v2_transport(self):
        entry = self.manifest['files']['fine_alpha_entry.py']['sha256']
        files = validate_transport(self.blob, SHA, entry, expected_scope=SCOPE)
        self.assertEqual(len(files), 41)
        self.assertEqual(json.loads(files['RELEASE.json'])['scope'], SCOPE)
        self.assertIn('reference/WORKER.json', files)

    def test_default_v1_receiver_refuses_v2(self):
        with self.assertRaisesRegex(ValueError, 'RELEASE_SCOPE'):
            validate_transport(self.blob, SHA, self.manifest['files']['fine_alpha_entry.py']['sha256'])

    def test_v2_receiver_refuses_v1_before_any_write(self):
        blob, digest, entry = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'base'/'new'
            with self.assertRaisesRegex(ValueError, 'RELEASE_SCOPE'):
                publish(blob, root, digest, entry, expected_scope=SCOPE)
            self.assertFalse(root.parent.exists())

    def test_v2_publish_preserves_sibling_and_refuses_overwrite(self):
        entry = self.manifest['files']['fine_alpha_entry.py']['sha256']; old_umask = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()/'base'; base.mkdir(mode=0o700)
                old = base/'v1'; old.mkdir(); (old/'evidence').write_bytes(b'keep')
                root = base/'v2'; receipt = publish(self.blob, root, SHA, entry, expected_scope=SCOPE)
                self.assertEqual(receipt['files'], 41)
                self.assertEqual((old/'evidence').read_bytes(), b'keep')
                self.assertFalse((root/'.upload-staging').exists())
                self.assertEqual((root/'package/RELEASE.json').read_bytes(), (PACKAGE/'RELEASE.json').read_bytes())
                with self.assertRaisesRegex(ValueError, 'TARGET_EXISTS'):
                    publish(self.blob, root, SHA, entry, expected_scope=SCOPE)
        finally: os.umask(old_umask)

    def test_receipt_scope_and_root(self):
        row = dict(status='FINE_ALPHA_FILES_PUBLISHED', root=REMOTE_ROOT, release_sha256=SHA,
                   files=41, manifest_files=40, jobs_submitted=0, checkpoints_loaded=0)
        validate_receipt(row, 41)
        for key, value in (('root', REMOTE_ROOT[:-1]+'1'), ('release_sha256', '0'*64),
                           ('files', 40), ('jobs_submitted', True), ('checkpoints_loaded', 1)):
            wrong = dict(row); wrong[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_receipt(wrong, 41)

    def test_bootstrap_binds_only_v2_mutation_target(self):
        source = (HERE/'fine_alpha_upload_transport.py').read_text()
        namespace = {'__name__': 'synthetic_remote'}; calls = []
        # Execute the exact bootstrap, replacing only the IO/main entry after
        # library initialization to check which target and scope it receives.
        original_exec = exec
        def fake_exec(code, receiver_namespace):
            original_exec(code, receiver_namespace)
            receiver_namespace['main'] = lambda **kwargs: calls.append(kwargs)
        with patch('builtins.exec', fake_exec), patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'read_bytes', return_value=(HERE/'release_fine_alpha_20260928_candidate_v1/package/RELEASE.json').read_bytes()):
            original_exec(compile(receiver_bootstrap(source), '<v2-bootstrap>', 'exec'), namespace)
        self.assertEqual(calls, [dict(remote=Path(REMOTE_ROOT), expected_scope=SCOPE,
                                     reviewed_jobs=REVIEWED_JOBS)])


if __name__ == '__main__': unittest.main()
