"""V3 source-check binding tests; subprocess and remote filesystem are mocked."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import preflight_fine_alpha as shared
import preflight_fine_alpha_v3 as v3


class V3PreflightTests(unittest.TestCase):
    def setUp(self): self.receipt = json.loads(v3.PUBLICATION.read_text())

    def test_actual_upload_receipt(self):
        self.assertEqual(v3.identity(v3.PUBLICATION)['sha256'], v3.PUBLICATION_SHA)
        v3.validate_publication(self.receipt)

    def test_v1_or_incomplete_receipt_rejected(self):
        import preflight_fine_alpha_v2 as v2
        for key, value in (('release_sha256', shared.SHA), ('remote_root', shared.REMOTE_ROOT),
                           ('release_sha256', v2.SHA), ('remote_root', v2.REMOTE_ROOT),
                           ('status', 'STOPPED_INSPECT_EVIDENCE_NO_RETRY'), ('jobs_submitted', True),
                           ('gpu_authorized', True), ('legacy_releases_unchanged', False), ('legacy_releases', {})):
            row = copy.deepcopy(self.receipt); row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): v3.validate_publication(row)
        row = copy.deepcopy(self.receipt); row['publication']['files'] = 41
        with self.assertRaises(ValueError): v3.validate_publication(row)

    def test_v3_package_record_bound_to_v3_only(self):
        row = self.receipt['remote_check']; raw = json.dumps(row).encode()
        self.assertEqual(shared.validate_record(raw, 'check', expected_sha=v3.SHA), row)
        with self.assertRaises(ValueError): shared.validate_record(raw, 'check')
        row = dict(row, release_sha256=shared.SHA)
        with self.assertRaises(ValueError): shared.validate_record(json.dumps(row).encode(), 'check', expected_sha=v3.SHA)

    def test_wrapper_binds_only_v3_and_one_evidence_directory(self):
        with patch.object(shared, 'main') as run:
            v3.main()
        args = run.call_args.kwargs
        self.assertEqual(args['package'], v3.PACKAGE)
        self.assertEqual(args['remote_root'], v3.REMOTE_ROOT)
        self.assertEqual(args['digest'], v3.SHA)
        self.assertEqual(args['evidence_name'], 'source-check-v3-once')
        self.assertEqual(args['publication']['sha256'], v3.PUBLICATION_SHA)
        self.assertEqual(args['bootstrap'], v3.bootstrap_v3())

    def test_template_drift_rejected(self):
        with patch.object(shared, 'BOOTSTRAP', 'unexpected source'):
            with self.assertRaisesRegex(ValueError, 'TEMPLATE_CHANGED'): v3.bootstrap_v3()

    def run_bootstrap(self, mode):
        bootstrap = v3.bootstrap_v3()
        entry = v3.identity(v3.PACKAGE/'fine_alpha_entry.py')['sha256']
        files = {name: (v3.PACKAGE/name).read_bytes() for name in ('RELEASE.json', 'fine_alpha_entry.py')}
        with patch.object(sys, 'argv', ['probe', v3.SHA, entry, mode]), \
             patch.object(sys, 'platform', 'linux'), patch.object(sys, 'flags', SimpleNamespace(isolated=True)), \
             patch.object(sys, 'dont_write_bytecode', True), \
             patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='s2510040')), \
             patch.object(Path, 'is_dir', return_value=True), patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'is_symlink', return_value=False), \
             patch.object(Path, 'read_bytes', lambda p: files[p.name]), \
             patch.object(subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            if mode in ('check', 'source-check'):
                with self.assertRaises(SystemExit) as exited: exec(compile(bootstrap, '<test-bootstrap>', 'exec'), {})
                self.assertEqual(exited.exception.code, 0)
                argv = run.call_args.args[0]
                self.assertEqual(argv[1:], ['-I', '-B', v3.REMOTE_ROOT+'/package/fine_alpha_entry.py', mode, v3.SHA])
                env = run.call_args.kwargs['env']
                self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '')
                self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')
                self.assertEqual(env['OMP_NUM_THREADS'], '1')
                self.assertEqual(run.call_args.kwargs['timeout'], 180)
            else:
                with self.assertRaisesRegex(ValueError, 'READ_ONLY_MODE_REQUIRED'):
                    exec(compile(bootstrap, '<test-bootstrap>', 'exec'), {})
                run.assert_not_called()

    def test_exact_read_only_remote_argv_and_cpu_environment(self):
        for mode in ('check', 'source-check'): self.run_bootstrap(mode)

    def test_worker_run_verify_and_submit_modes_rejected(self):
        for mode in ('worker', 'run', 'verify', 'submit'): self.run_bootstrap(mode)


if __name__ == '__main__': unittest.main()
