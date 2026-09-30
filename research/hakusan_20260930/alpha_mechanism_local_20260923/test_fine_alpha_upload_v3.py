"""V3 upload binding and receiver tests, local temporary directories only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fine_alpha_upload_transport import validate_transport, publish
from publish_fine_alpha_v3 import (make_transport, receiver_bootstrap, validate_receipt, validate_remote_check,
                                  HERE, LEGACY, PACKAGE, SHA, SCOPE, REMOTE_ROOT, REVIEWED_JOBS)
import publish_fine_alpha_v2 as v2


class V3UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.manifest, cls.blob = make_transport()

    def test_actual_frozen_v3_transport(self):
        entry = self.manifest['files']['fine_alpha_entry.py']['sha256']
        files = validate_transport(self.blob, SHA, entry, expected_scope=SCOPE)
        self.assertEqual(len(files), 42)
        self.assertEqual(json.loads(files['RELEASE.json'])['scope'], SCOPE)
        self.assertIn('fine_alpha_submission_queue.py', files)

    def test_v1_and_v2_scopes_refuse_v3(self):
        entry = self.manifest['files']['fine_alpha_entry.py']['sha256']
        for scope in (None, v2.SCOPE):
            kwargs = {} if scope is None else dict(expected_scope=scope)
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, 'RELEASE_SCOPE'):
                validate_transport(self.blob, SHA, entry, **kwargs)

    def test_v3_receiver_refuses_v2_before_any_write(self):
        _, blob = v2.make_transport()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()/'base'/'new'
            with self.assertRaisesRegex(ValueError, 'RELEASE_SHA|RELEASE_SCOPE'):
                publish(blob, root, v2.SHA, v2.make_transport()[0]['files']['fine_alpha_entry.py']['sha256'],
                        expected_scope=SCOPE)
            self.assertFalse(root.parent.exists())

    def test_v3_publish_preserves_siblings_and_refuses_overwrite(self):
        entry = self.manifest['files']['fine_alpha_entry.py']['sha256']; old_umask = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory).resolve()/'base'; base.mkdir(mode=0o700)
                for name in ('v1', 'v2'):
                    old = base/name; old.mkdir(); (old/'evidence').write_bytes(b'keep')
                root = base/'v3'; receipt = publish(self.blob, root, SHA, entry, expected_scope=SCOPE)
                self.assertEqual(receipt['files'], 42)
                for name in ('v1', 'v2'): self.assertEqual((base/name/'evidence').read_bytes(), b'keep')
                self.assertEqual((root/'package/RELEASE.json').read_bytes(), (PACKAGE/'RELEASE.json').read_bytes())
                with self.assertRaisesRegex(ValueError, 'TARGET_EXISTS'):
                    publish(self.blob, root, SHA, entry, expected_scope=SCOPE)
        finally: os.umask(old_umask)

    def test_receipt_scope_and_root(self):
        row = dict(status='FINE_ALPHA_FILES_PUBLISHED', root=REMOTE_ROOT, release_sha256=SHA,
                   files=42, manifest_files=41, jobs_submitted=0, checkpoints_loaded=0)
        validate_receipt(row, 42)
        for key, value in (('root', v2.REMOTE_ROOT), ('release_sha256', v2.SHA),
                           ('files', 41), ('jobs_submitted', True), ('checkpoints_loaded', 1)):
            wrong = dict(row); wrong[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_receipt(wrong, 42)

    def test_remote_check_requires_v3_pass(self):
        row = dict(status='FINE_ALPHA_PACKAGE_CHECK_PASS', release_sha256=SHA, predictions=219600,
                   science_predictions=194400, jobs_submitted=0, production_validated=False)
        validate_remote_check(row)
        for key, value in (('release_sha256', v2.SHA), ('predictions', 1), ('jobs_submitted', False),
                           ('production_validated', True), ('status', 'X')):
            wrong = dict(row); wrong[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_remote_check(wrong)

    def test_legacy_bindings(self):
        self.assertEqual(sorted(LEGACY.values()), sorted([v2.V1_SHA, v2.SHA]))
        self.assertNotIn(REMOTE_ROOT+'/package/RELEASE.json', LEGACY)
        self.assertEqual(set(REVIEWED_JOBS), {'754073'})

    def test_bootstrap_binds_only_v3_mutation_target(self):
        source = (HERE/'fine_alpha_upload_transport.py').read_text()
        namespace = {'__name__': 'synthetic_remote'}; calls = []; reads = []
        legacy_bytes = {v2.V1_SHA: (HERE/'release_fine_alpha_20260928_candidate_v1/package/RELEASE.json').read_bytes(),
                        v2.SHA: (HERE/'release_fine_alpha_20260928_candidate_v2/package/RELEASE.json').read_bytes()}
        by_path = {name: legacy_bytes[sha] for name, sha in LEGACY.items()}
        original_exec = exec
        def fake_exec(code, receiver_namespace):
            original_exec(code, receiver_namespace)
            receiver_namespace['main'] = lambda **kwargs: calls.append(kwargs)
        def read_bytes(path): reads.append(str(path)); return by_path[str(path)]
        with patch('builtins.exec', fake_exec), patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'read_bytes', read_bytes):
            original_exec(compile(receiver_bootstrap(source), '<v3-bootstrap>', 'exec'), namespace)
        self.assertEqual(calls, [dict(remote=Path(REMOTE_ROOT), expected_scope=SCOPE, reviewed_jobs=REVIEWED_JOBS)])
        self.assertEqual(sorted(reads), sorted(list(LEGACY)*2))

    def test_bootstrap_rejects_changed_legacy(self):
        source = (HERE/'fine_alpha_upload_transport.py').read_text(); calls = []
        original_exec = exec
        def fake_exec(code, receiver_namespace):
            original_exec(code, receiver_namespace)
            receiver_namespace['main'] = lambda **kwargs: calls.append(kwargs)
        with patch('builtins.exec', fake_exec), patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'read_bytes', return_value=b'x'):
            with self.assertRaisesRegex(ValueError, 'LEGACY_RELEASE_SHA'):
                original_exec(compile(receiver_bootstrap(source), '<v3-bootstrap>', 'exec'), {'__name__': 's'})
        self.assertEqual(calls, [])


if __name__ == '__main__': unittest.main()
