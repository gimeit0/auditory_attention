"""Local contract/negative tests only; no checkpoint, torch, SSH or forward."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import probe_cpu as probe
import run_real_binding as driver


ROOT = Path(__file__).resolve().parents[4]
PLAN = ROOT / 'docs/superpowers/prototypes/targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json'
FREEZE = ROOT / 'docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json'


class BindingInputTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(probe.pinned(PLAN, probe.PLAN_SHA))
        self.freeze = json.loads(probe.pinned(FREEZE, probe.FREEZE_SHA))

    def reject(self):
        with self.assertRaises(RuntimeError):
            probe.validate_plan(self.plan, self.freeze)

    def test_actual_plan_and_freeze(self):
        ids = probe.validate_plan(self.plan, self.freeze)
        self.assertEqual(len(ids), 32)
        self.assertEqual(ids[0], 9000)
        self.assertEqual(ids[28], 4126)

    def test_parent_job(self):
        self.plan['parent_job_id'] = '680910'
        self.reject()

    def test_protocol(self):
        self.freeze['diagnostic_protocol'] = 'v19'
        self.reject()

    def test_trial_reorder(self):
        self.plan['trials'][0], self.plan['trials'][1] = self.plan['trials'][1], self.plan['trials'][0]
        self.reject()

    def test_trial_metadata(self):
        self.plan['trials'][0]['identity']['target_label'] += 1
        self.reject()

    def test_target_metric(self):
        self.plan['targets']['B2'][0]['metric'] = 'nll'
        self.reject()

    def test_target_metadata(self):
        self.plan['targets']['B2'][0]['trial']['identity']['target_label'] += 1
        self.reject()

    def test_same_bank_but_wrong_target(self):
        self.plan['targets']['A2'][0]['trial'] = copy.deepcopy(self.plan['trials'][1])
        self.reject()

    def test_shared_branch_relabel(self):
        self.plan['post_hook_stages'][0]['branch'] = 'mixture'
        self.reject()

    def test_batch_policy(self):
        self.plan['pass_batch_sizes'] = [1, 1]
        self.reject()

    def test_autocast_policy(self):
        self.plan['autocast_enabled']['B2'] = True
        self.reject()

    def test_pin_content_size_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data'
            path.write_bytes(b'fixed')
            sha = hashlib.sha256(b'fixed').hexdigest()
            self.assertEqual(probe.pinned(path, sha), b'fixed')
            with self.assertRaises(RuntimeError):
                probe.pinned(path, sha, 4)
            with self.assertRaises(RuntimeError):
                probe.pinned(path, '0' * 64)
            link = path.with_name('link')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                probe.pinned(link, sha)

    def test_state_bytes_and_cross_process_metadata(self):
        row = {'kind': 'parameter', 'name': 'weight', 'shape': [3], 'dtype': 'torch.float32',
               'sha256': 'a' * 64, 'identity': 1, 'device': 'cpu', 'version': 1}
        other = dict(row, identity=2, device='cuda:0', version=2)
        self.assertEqual(probe.comparable_state([row]), probe.comparable_state([other]))
        other['sha256'] = 'b' * 64
        self.assertNotEqual(probe.comparable_state([row]), probe.comparable_state([other]))
        with self.assertRaises(RuntimeError):
            probe.comparable_state([row, row])

    def test_receipt_rejects_missing_wrong_or_overstated_evidence(self):
        record = {'rc': 0, 'source_sha256': dict(driver.PINS), 'temporary_directory_removed': True,
                  'production_files_published': False, 'jobs_submitted': 0,
                  'summary': dict(driver.EXPECTED_SUMMARY)}
        self.assertTrue(driver.verified_result(0, [record]))
        self.assertFalse(driver.verified_result(2, [record]))
        self.assertFalse(driver.verified_result(0, []))
        self.assertFalse(driver.verified_result(0, [record, record]))
        for key, value in driver.EXPECTED_SUMMARY.items():
            broken = copy.deepcopy(record)
            del broken['summary'][key]
            self.assertFalse(driver.verified_result(0, [broken]), key)
            broken['summary'][key] = not value if type(value) is bool else 'wrong'
            self.assertFalse(driver.verified_result(0, [broken]), key)
        record['temporary_directory_removed'] = False
        self.assertFalse(driver.verified_result(0, [record]))

    def test_payload_sources_compile_and_match_pins(self):
        sources = {}
        for relative, sha in driver.PINS.items():
            sources[relative] = probe.pinned(PLAN.parent.parent / relative, sha).decode()
        compile(driver.bootstrap(sources), '<bootstrap-check>', 'exec')


if __name__ == '__main__':
    unittest.main(verbosity=2)
