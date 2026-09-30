"""Local record validation only; these tests never invoke SSH."""
import copy
import json
import unittest
from preflight_fine_alpha import BOOTSTRAP, SHA, SNAPSHOT_SHA, validate_record


class PreflightTests(unittest.TestCase):
    def source(self):
        return dict(status='NATIVE_SOURCE_ONLY_IMPORT_PASS', jobs_submitted=0,
                    checkpoint_loaded=False, cuda_initialized=False,
                    snapshot=dict(manifest_sha256=SNAPSHOT_SHA, files=96, existing_bytecode_files=24,
                                  required_import_policy='hash_checked_source_only'))

    def check(self):
        return dict(status='FINE_ALPHA_PACKAGE_CHECK_PASS', jobs_submitted=0, release_sha256=SHA,
                    science_predictions=194400, predictions=219600, production_validated=False)

    def raw(self, row):
        return ('optional native import diagnostic\n'+json.dumps(row)+'\n').encode()

    def test_valid_source_and_package(self):
        for mode, row in (('source-check', self.source()), ('check', self.check())):
            self.assertEqual(validate_record(self.raw(row), mode), row)

    def test_scope_drift_or_missing_rejected(self):
        for key in ('checkpoint_loaded', 'cuda_initialized', 'jobs_submitted'):
            for value in (True, None, 'false'):
                row = self.source(); row[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_record(self.raw(row), 'source-check')
            row = self.source(); del row[key]
            with self.assertRaises(ValueError): validate_record(self.raw(row), 'source-check')

    def test_snapshot_identity_rejected(self):
        for key, value in (('manifest_sha256', '0'*64), ('files', 95), ('required_import_policy', 'cached')):
            row = self.source(); row['snapshot'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record(self.raw(row), 'source-check')

    def test_package_identity_and_status_rejected(self):
        good = self.check()
        for key, value in (('release_sha256', '0'*64), ('status', 'OTHER'), ('predictions', 0),
                           ('science_predictions', 0), ('production_validated', True)):
            row = copy.deepcopy(good); row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record(self.raw(row), 'check')

    def test_invalid_mode_and_unstructured_output(self):
        with self.assertRaises(ValueError): validate_record(self.raw(self.source()), 'run')
        with self.assertRaises(ValueError): validate_record(b'not a JSON result\n', 'source-check')

    def test_bootstrap_syntax(self):
        compile(BOOTSTRAP, '<remote-preflight>', 'exec')


if __name__ == '__main__':
    unittest.main()
