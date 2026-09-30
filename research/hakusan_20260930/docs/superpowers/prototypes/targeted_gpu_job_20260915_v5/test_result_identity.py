"""Verifier unit doubles ONLY; simulated provenance is NOT a production result."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_results as verify
import input_binding
import job_contract as contract
from test_input_binding import synthetic_freeze


class ResultIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/synthetic-verifier-only/reference')
        self.freeze = synthetic_freeze()
        self.sha = input_binding.relation.sha(input_binding.relation.canonical(self.freeze))
        self.inputs = {'candidate_freeze_sha256': self.sha, 'synthetic_unit_double': True}
        self.result = {'status': 'GPU_CHILD_CANDIDATE_COMPLETE', 'role': 'reference', 'job_id': '7770001',
            'worker_pid': 100, 'package_sha256': 'a' * 64, 'pair_nonce': 'b' * 32,
            'input_sha256': self.sha, 'diagnostic_protocol': contract.PROTOCOL,
            'diagnostic_sha256': contract.V19_SHA, 'cell': 'B2', 'production_model_loaded': True,
            'cuda_initialized': True, 'input_checks_unchanged': True, 'error': None,
            'cleanup_errors': [], 'hooks_removed': True, 'lifetime': {'archive': {}}}
        self.software = {'worker_pid': 100, 'slurm_job_id': '7770001', 'python': '3.11.5',
            'torch': '2.1.1+cu118', 'gpu_name': 'SYNTHETIC_A100_UNIT_DOUBLE',
            'startup_runtime': {'fixed_exports': dict(verify.runtime_environment.FIXED),
                'torch_num_threads': 8, 'torch_num_interop_threads': 1, 'cpu_affinity': [0]}}
        self.audit = {**self.freeze, 'status': 'AUDIT_PASS'}
        self.documents = {'CHILD.json': self.result, 'STARTED.json': copy.deepcopy(self.result),
            'INPUT_BINDING.json': self.inputs, 'ENVIRONMENT.json': self.software,
            'PRECHECK.json': self.audit, 'POSTCHECK.json': self.audit}
        arr = np.array([1], dtype='<f4')
        desc = {'sha256': hashlib.sha256(arr.tobytes()).hexdigest(), 'shape': [1], 'dtype': '<f4'}
        source = {'aggregate': {**desc, 'dtype': 'torch.float32'}}
        metadata = {'worker_pid': 100, 'worker_nonce': 'synthetic-worker', 'model_nonce': 'synthetic-model',
            'load_report_sha256': 'c' * 64, 'runtime': {'synthetic': True}, 'autocast_enabled': False}
        metadata['attestation'] = {**metadata, 'trust_domain': 'production', 'diagnostic_protocol': contract.PROTOCOL}
        self.parts, self.payloads = [], {}
        for part, size in (('pass1', 16), ('pass2', 1)):
            self.parts.append({'pass_id': part, 'batch_size': size, 'trial_ids': [1],
                'original_pass_evidence': part, 'official_outputs': {'nll': desc},
                'boundaries': {name: desc for name in verify.archive.COARSE + verify.archive.DERIVED}})
            payload = {'pass_id': part, 'batch_size': size, 'trial_ids': [1],
                'boundaries': {**{name: source for name in verify.archive.COARSE},
                    'derived': {name: source for name in verify.archive.DERIVED}, 'metadata': copy.deepcopy(metadata)},
                'model_snapshots': {'before': 'same', 'after': 'same'},
                'rng_snapshots': {'before': 'same', 'after': 'same'}}
            self.payloads[part] = {'payload': payload, 'outputs': {'nll': arr}}
        self.parent = {'cells': {'B2': {'passes': {p: {'runtime': {'synthetic': True}} for p in self.payloads}}}}
        self.names = {'INPUT_BINDING.json', 'STARTED.json', 'CHILD.json', 'PRECHECK.json',
            'POSTCHECK.json', 'ENVIRONMENT.json', 'arrays/manifest.json', *(f'arrays/{i:03d}.bin' for i in range(40))}
        self.diag = types.SimpleNamespace(decode_pass_evidence=lambda part: self.payloads[part])
        patches = [mock.patch.object(input_binding, 'load', return_value=(self.freeze, self.inputs)),
            mock.patch.object(input_binding, 'verify_audits'),
            mock.patch.object(contract, 'pinned_read', side_effect=lambda p, *a, **k:
                input_binding.relation.canonical(self.documents[Path(p).name])),
            mock.patch.object(verify, 'inventory', side_effect=lambda _: {'files': dict.fromkeys(self.names), 'directories': ['arrays']}),
            mock.patch.object(verify.archive, 'verify_archive', return_value={'passes': self.parts})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def check(self):
        return verify.verify_child(self.root, {'pid': 100}, role='reference', job='7770001',
            package_sha='a' * 64, nonce='b' * 32, input_sha=self.sha, diag=self.diag, parent=self.parent)

    def test_complete_synthetic_verifier_path_checks_bindings_and_commitments(self):
        self.assertTrue(self.check()['original_pass_commitments_verified'])
        input_binding.verify_audits.assert_called_once()
        self.assertEqual(verify.archive.verify_archive.call_args.args[2]['input_sha256'], self.sha)

    def test_wrong_result_identity_rejected(self):
        for key in ('input_sha256', 'diagnostic_sha256', 'diagnostic_protocol', 'worker_pid', 'job_id'):
            old = self.result[key]
            self.result[key] = 'wrong'
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'identity/completion'):
                self.check()
            self.result[key] = old

    def test_started_identity_rejected(self):
        self.documents['STARTED.json']['input_sha256'] = contract.PARENT_FREEZE_SHA
        with self.assertRaisesRegex(RuntimeError, 'started identity'):
            self.check()

    def test_wrong_relationship_record_rejected(self):
        self.documents['INPUT_BINDING.json'] = {'different': True}
        with self.assertRaisesRegex(RuntimeError, 'relationship'):
            self.check()

    def test_old_protocol_in_original_commitment_rejected(self):
        self.payloads['pass1']['payload']['boundaries']['metadata']['attestation']['diagnostic_protocol'] = 'formal40_batch_invariance_diag_20260903_v18'
        with self.assertRaisesRegex(RuntimeError, 'provenance'):
            self.check()

    def test_hermetic_provenance_cannot_pass_production_gate(self):
        self.payloads['pass1']['payload']['boundaries']['metadata']['attestation']['trust_domain'] = 'hermetic-test'
        with self.assertRaisesRegex(RuntimeError, 'provenance'):
            self.check()

    def test_cleanup_error_is_not_a_result(self):
        self.result['cleanup_errors'] = ['synthetic']
        with self.assertRaisesRegex(RuntimeError, 'identity/completion'):
            self.check()

    def test_missing_artifact_is_not_complete(self):
        self.names.remove('arrays/039.bin')
        with self.assertRaisesRegex(RuntimeError, 'coverage'):
            self.check()

    def test_postcheck_failure_propagates(self):
        input_binding.verify_audits.side_effect = RuntimeError('synthetic audit rejection')
        with self.assertRaisesRegex(RuntimeError, 'audit rejection'):
            self.check()

    def test_modified_official_output_rejected(self):
        self.payloads['pass2']['outputs']['nll'] = np.array([2], dtype='<f4')
        with self.assertRaisesRegex(RuntimeError, 'official output'):
            self.check()

    def test_model_or_rng_mutation_rejected(self):
        for family in ('model_snapshots', 'rng_snapshots'):
            self.payloads['pass2']['payload'][family]['after'] = 'changed'
            with self.subTest(family=family), self.assertRaisesRegex(RuntimeError, 'state/RNG'):
                self.check()
            self.payloads['pass2']['payload'][family]['after'] = 'same'


if __name__ == '__main__':
    unittest.main()
