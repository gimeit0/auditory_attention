"""SYNTHETIC local identities only: never an actual v19 freeze or approval."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import input_binding as binding
import job_contract as contract

relation = binding.relation


def synthetic_freeze():
    value = json.loads(relation.PARENT.read_bytes())
    value['diagnostic_protocol'] = relation.PROTOCOL
    value['roots']['diagnostic_root'] = relation.REMOTE
    for r in value['production_files']:
        raw = (relation.LOCAL / r['relative_path']).read_bytes()
        r.update(size=len(raw), sha256=relation.sha(raw), mode=0o600,
                 st_dev=1, st_ino=1, st_mtime_ns=1)
    return value


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-v19-binding-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.freeze = synthetic_freeze()
        self.raw = relation.canonical(self.freeze)
        self.sha = relation.sha(self.raw)
        (self.root / 'tools').mkdir()
        (self.root / 'input_freeze.json').write_bytes(self.raw)
        (self.root / 'tools/diagnose_batch_invariance.py').write_bytes(
            (relation.LOCAL / 'diagnose_batch_invariance.py').read_bytes())
        self.patch = mock.patch.object(contract, 'V19', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_new_identity_and_old_data_separate(self):
        value, proof = binding.load(self.sha)
        self.assertEqual(value, self.freeze)
        self.assertNotEqual(self.sha, proof['parent_freeze_sha256'])
        self.assertEqual(proof['diagnostic_sha256'], contract.V19_SHA)
        self.assertFalse(proof['production_live_inputs_verified'])
        self.assertFalse(proof['submission_authorized'])

    def test_old_freeze_rejected(self):
        (self.root / 'input_freeze.json').write_bytes(relation.PARENT.read_bytes())
        with self.assertRaises(ValueError):
            binding.load(contract.PARENT_FREEZE_SHA)

    def test_unreviewed_sha_rejected(self):
        for digest in (None, '', 'UNFROZEN', 'a' * 64):
            with self.subTest(digest=digest), self.assertRaises((RuntimeError, ValueError)):
                binding.load(digest)

    def test_changed_freeze_bytes_rejected(self):
        (self.root / 'input_freeze.json').write_bytes(self.raw + b' ')
        with self.assertRaises(RuntimeError):
            binding.load(self.sha)

    def test_changed_real_execution_source_rejected(self):
        (self.root / 'tools/diagnose_batch_invariance.py').write_bytes(b'not the reviewed core')
        with self.assertRaises(RuntimeError):
            binding.load(self.sha)

    def test_scientific_drift_rejected(self):
        self.freeze['trials'].reverse()
        raw = relation.canonical(self.freeze)
        (self.root / 'input_freeze.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'scientific inputs'):
            binding.load(relation.sha(raw))

    def test_old_code_records_rejected(self):
        self.freeze['production_files'] = json.loads(relation.PARENT.read_bytes())['production_files']
        raw = relation.canonical(self.freeze)
        (self.root / 'input_freeze.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'new release'):
            binding.load(relation.sha(raw))

    def test_symlink_freeze_rejected(self):
        path = self.root / 'input_freeze.json'
        path.rename(self.root / 'retained.json')
        path.symlink_to(self.root / 'retained.json')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            binding.load(self.sha)

    def authorization(self):
        return {'approved': True, 'package_sha256': 'a' * 64, 'pair_nonce': 'b' * 32,
                'input_freeze_sha256': self.sha, 'parent_freeze_sha256': contract.PARENT_FREEZE_SHA,
                'diagnostic_sha256': contract.V19_SHA, 'diagnostic_protocol': contract.PROTOCOL,
                'limits': dict(contract.LIMITS), 'scope': 'B2_formal40_v19_cold_reference_observed_pair'}

    def check_authorization(self, value=None, intent=None, input_sha=None):
        value = self.authorization() if value is None else value
        (self.root / 'AUTHORIZATION.json').write_bytes(relation.canonical(value))
        (self.root / 'SUBMIT_INTENT.json').write_bytes(relation.canonical(value if intent is None else intent))
        with mock.patch.object(contract, 'REMOTE', self.root):
            return contract.check_authorization(self.root, 'a' * 64, 'b' * 32,
                                                self.sha if input_sha is None else input_sha)

    def test_exact_new_authorization_schema_only(self):
        self.assertEqual(self.check_authorization(), self.authorization())

    def test_consumed_old_authorization_cannot_authorize_candidate(self):
        old = {'approved': True, 'package_sha256': 'a' * 64, 'pair_nonce': 'b' * 32,
               'limits': dict(contract.LIMITS), 'scope': 'B2_formal40_cold_reference_observed_pair'}
        with self.assertRaisesRegex(RuntimeError, 'resource authorization'):
            self.check_authorization(old)

    def test_authorization_rejects_each_changed_binding(self):
        for key in ('approved', 'package_sha256', 'pair_nonce', 'input_freeze_sha256',
                    'parent_freeze_sha256', 'diagnostic_sha256', 'diagnostic_protocol', 'scope'):
            value = self.authorization()
            value[key] = False if key == 'approved' else 'different'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check_authorization(value)

    def test_raising_limits_rejected(self):
        for key, original in contract.LIMITS.items():
            value = self.authorization()
            value['limits'][key] = original + 1 if type(original) is int else 'GPU-2A'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check_authorization(value)

    def test_boolean_as_integer_limit_rejected(self):
        value = self.authorization()
        value['limits']['jobs'] = True
        with self.assertRaises(RuntimeError):
            self.check_authorization(value)

    def test_intent_must_match_exactly(self):
        value = self.authorization()
        value['input_freeze_sha256'] = 'c' * 64
        with self.assertRaisesRegex(RuntimeError, 'intent'):
            self.check_authorization(intent=value)

    def test_authorization_cannot_use_old_freeze(self):
        with self.assertRaisesRegex(RuntimeError, 'new candidate freeze'):
            self.check_authorization(input_sha=contract.PARENT_FREEZE_SHA)

    @staticmethod
    def diagnostic_double():
        def portable(value):
            result = copy.deepcopy(value)
            for name in ('production_files', 'clips', 'snapshot_files'):
                for record in result[name]:
                    for key in relation.IDENTITY:
                        record.pop(key, None)
            return result
        return types.SimpleNamespace(_portable_worker_audit=portable,
            _freeze_document=lambda value: {**value, 'status': 'INPUTS_FROZEN'})

    def audit(self):
        return relation.canonical({**self.freeze, 'status': 'AUDIT_PASS'})

    def test_audits_bound_to_candidate_freeze(self):
        binding.verify_audits(self.audit(), self.audit(), self.freeze, self.diagnostic_double())

    def test_two_equal_but_wrong_audits_rejected(self):
        wrong = json.loads(self.audit())
        wrong['trials'].reverse()
        raw = relation.canonical(wrong)
        with self.assertRaisesRegex(RuntimeError, 'candidate freeze'):
            binding.verify_audits(raw, raw, self.freeze, self.diagnostic_double())

    def test_changed_postcheck_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'audit bytes'):
            binding.verify_audits(self.audit(), self.audit() + b' ', self.freeze, self.diagnostic_double())

    def test_frozen_or_failed_status_not_a_successful_audit(self):
        for status in ('INPUTS_FROZEN', 'AUDIT_FAILED'):
            raw = relation.canonical({**self.freeze, 'status': status})
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, 'successful worker audit'):
                binding.verify_audits(raw, raw, self.freeze, self.diagnostic_double())

    def pair_arguments(self):
        one = (self.root / 'reference', {}, {'input_sha256': self.sha})
        two = (self.root / 'observed', {}, {'input_sha256': self.sha})
        parent = (contract.WORKSPACE / contract.PARENT).read_bytes()
        archive = types.SimpleNamespace(MAX_JSON=8 * 1024**2,
            verify_content_pair=mock.Mock(return_value={'status': 'SYNTHETIC_CONTENT_DOUBLE_ONLY'}))
        return archive, one, two, parent

    def test_new_binding_preserves_pinned_parent_content_verifier(self):
        archive, one, two, parent = self.pair_arguments()
        value = binding.verify_parent_pair(archive, one, two, parent, self.sha)
        archive.verify_content_pair.assert_called_once()
        self.assertEqual(archive.verify_content_pair.call_args.args, (one, two))
        self.assertEqual(value['parent_contract_sha256'], binding.PARENT_SHA)
        self.assertEqual(value['input_binding']['candidate_freeze_sha256'], self.sha)

    def test_arbitrary_parent_or_old_execution_binding_rejected_before_content(self):
        for change in ('parent', 'reference', 'observed'):
            archive, one, two, parent = self.pair_arguments()
            if change == 'parent':
                parent += b' '
            else:
                (one if change == 'reference' else two)[2]['input_sha256'] = contract.PARENT_FREEZE_SHA
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                binding.verify_parent_pair(archive, one, two, parent, self.sha)
            archive.verify_content_pair.assert_not_called()

    def test_parent_content_error_propagates(self):
        archive, one, two, parent = self.pair_arguments()
        archive.verify_content_pair.side_effect = ValueError('array mismatch')
        with self.assertRaisesRegex(ValueError, 'array mismatch'):
            binding.verify_parent_pair(archive, one, two, parent, self.sha)

    def test_relation_changed_during_pair_rejected(self):
        archive, one, two, parent = self.pair_arguments()
        def change(*_, **__):
            (self.root / 'input_freeze.json').write_bytes(self.raw + b' ')
            return {}
        archive.verify_content_pair.side_effect = change
        with self.assertRaises(RuntimeError):
            binding.verify_parent_pair(archive, one, two, parent, self.sha)

    def test_cold_startup_import_has_no_numeric_modules(self):
        code = ('import sys,json;sys.path.insert(0,' + repr(str(HERE)) + ');'
                'import input_binding,startup;startup.cold_imports();'
                'print(json.dumps({"numeric":sorted(n for n in sys.modules '
                'if n.partition(".")[0] in startup.NUMERIC)}))')
        value = subprocess.run([sys.executable, '-I', '-B', '-c', code],
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(value.returncode, 0, value.stderr)
        self.assertEqual(json.loads(value.stdout), {'numeric': []})

    def test_entry_source_uses_new_loader_and_explicit_freeze_argument(self):
        for filename in ('gpu_child.py', 'coordinator.py'):
            raw = (HERE / filename).read_text()
            self.assertIn('.load_v19(contract.V19', raw)
            self.assertNotIn('load_v18', raw)
            self.assertNotIn('contract.FREEZE_SHA', raw)
            self.assertIn('input_binding.load(input_sha)', raw)
        verify = (HERE / 'verify_results.py').read_text()
        self.assertIn('attestation["diagnostic_protocol"] == contract.PROTOCOL', verify)
        self.assertIn('input_binding.verify_audits', verify)
        self.assertIn('input_binding.verify_parent_pair', (HERE / 'coordinator.py').read_text())


if __name__ == '__main__':
    unittest.main()
