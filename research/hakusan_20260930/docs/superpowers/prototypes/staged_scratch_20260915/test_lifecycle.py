"""Offline refusal/derivation checks; no torch import, network or model."""
import ast
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lifecycle as task


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.request = {'scope': task.SCOPE, 'session_id': 'synthetic-offline-session', 'source_binding': {'fixed': 'test'}}
        self.records = []
        for stage in ('A2', 'B2'):
            contract = {'production_authority': False, 'trials': [{'ordinal': i, 'trial_id': i} for i in range(32)],
                        'cells': {stage: {'autocast_enabled': stage == 'A2', 'passes': {
                            'pass1': {'batch_size': 16}, 'pass2': {'batch_size': 1}}}}}
            self.records.append({**self.request, 'stage': stage, 'status': 'LOCAL_STAGE_PASS', 'parents': [],
                                 'production_model_loaded': False, 'ready_for_gpu': False, 'jobs_submitted': 0,
                                 'cuda_initialized': False, 'home_unchanged': True, 'source_postcheck': True,
                                 'environment': {'python': 'fake', 'torch': 'fake'}, 'contract': contract,
                                 'contract_sha256': task.sha(task.canonical(contract))})

    def merged(self):
        return task.merge_cells(*self.records, self.request)

    def test_valid_merge_keeps_two_cells_without_alias(self):
        merged = self.merged()
        self.assertEqual(set(merged['cells']), {'A2', 'B2'})
        merged['cells']['A2']['passes']['pass1']['batch_size'] = 8
        self.assertEqual(self.records[0]['contract']['cells']['A2']['passes']['pass1']['batch_size'], 16)

    def test_session_mix_rejected(self):
        self.records[1]['session_id'] = 'other'
        with self.assertRaisesRegex(RuntimeError, 'session_id'):
            self.merged()

    def test_source_mix_rejected(self):
        self.records[1]['source_binding'] = {'fixed': 'other'}
        with self.assertRaisesRegex(RuntimeError, 'source_binding'):
            self.merged()

    def test_environment_mix_rejected(self):
        self.records[1]['environment']['torch'] = 'other'
        with self.assertRaisesRegex(RuntimeError, 'environment'):
            self.merged()

    def test_duplicate_cell_rejected(self):
        self.records[1] = copy.deepcopy(self.records[0])
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            self.merged()

    def test_output_tampering_rejected(self):
        self.records[0]['contract']['cells']['A2']['passes']['pass1']['extra'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'content binding'):
            self.merged()

    def test_missing_trial_rejected(self):
        self.records[0]['contract']['trials'].pop()
        with self.assertRaisesRegex(RuntimeError, 'trial coverage'):
            self.merged()

    def test_wrong_trial_identity_even_rehashed_rejected(self):
        r = self.records[1]
        r['contract']['trials'][0]['trial_id'] = 99
        r['contract_sha256'] = task.sha(task.canonical(r['contract']))
        with self.assertRaisesRegex(RuntimeError, 'header identities'):
            self.merged()

    def test_wrong_batch_and_autocast_rejected(self):
        for field, changed in (('autocast_enabled', False), ('passes', {'pass1': {'batch_size': 1}, 'pass2': {'batch_size': 16}})):
            saved = copy.deepcopy(self.records)
            self.records[0]['contract']['cells']['A2'][field] = changed
            with self.assertRaisesRegex(RuntimeError, 'schedule'):
                self.merged()
            self.records = saved

    def test_success_and_scope_flags_required(self):
        for name, value in (('status', 'FAILED'), ('ready_for_gpu', True), ('production_model_loaded', True),
                            ('cuda_initialized', True), ('home_unchanged', False), ('source_postcheck', False)):
            saved = self.records[0][name]
            self.records[0][name] = value
            with self.assertRaises(RuntimeError):
                self.merged()
            self.records[0][name] = saved

    def test_parent_sha_and_canonical_bytes_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'test.json'
            path.write_bytes(task.canonical({'value': 1}))
            digest = task.sha(path.read_bytes())
            self.assertEqual(task.read_bound(path, digest), {'value': 1})
            with self.assertRaisesRegex(RuntimeError, 'SHA'):
                task.read_bound(path, '0' * 64)
            path.write_bytes(b'{"value": 1}\n')
            with self.assertRaisesRegex(RuntimeError, 'canonical'):
                task.read_bound(path, task.sha(path.read_bytes()))

    def test_symlink_parent_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'data').write_bytes(b'{}\n')
            (root / 'alias').symlink_to(root / 'data')
            with self.assertRaisesRegex(RuntimeError, 'non-symlink'):
                task.read_bound(root / 'alias', task.sha(b'{}\n'))

    def test_exact_ast_only_outer_cell_selection(self):
        raw = task.read(task.WORKER / 'test_baseline_bridge.py')
        for cell in ('A2', 'B2'):
            tree = task.derive_cell(raw, cell)
            function = tree.body[0]
            loop = next(n for n in ast.walk(function) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'cell')
            self.assertEqual(ast.literal_eval(loop.iter), (cell,))
            self.assertIn("('pass1', 16), ('pass2', 1)", ast.unparse(tree))
            self.assertIn("assert evaluator.calls.count('model') == 34", ast.unparse(tree))
        with self.assertRaisesRegex(RuntimeError, 'exact cell'):
            task.derive_cell(raw, 'B1')

    def test_original_scratch_assertions_and_structure_preserved(self):
        raw = task.read(task.JOB / 'test_scratch_integration.py')
        tree = task.derive_scratch(raw)
        original = next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'ScratchTests')
        def assertions(node):
            return [ast.dump(n) for n in ast.walk(node) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
        self.assertEqual(assertions(tree), assertions(original))
        self.assertGreater(len(assertions(tree)), 15)
        self.assertEqual(len(tree.body[0].body), 2)

    def test_derivation_shape_change_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'one outer cell'):
            task.derive_cell(b'def expected_contract():\n    return {}\n', 'A2')
        with self.assertRaisesRegex(RuntimeError, 'one expected-data'):
            task.derive_scratch(b'class ScratchTests:\n    pass\n')

    def test_parent_path_checked_before_read(self):
        for parents in ([{'name': '../outside.json'}], [{'name': '/etc/passwd'}],
                        [{'name': 'B2/result.json'}, {'name': 'A2/result.json'}], []):
            with self.assertRaisesRegex(RuntimeError, 'exact oracle'):
                task.parent_names({'stage': 'mmap', 'parents': parents})
        self.assertEqual(task.parent_names({'stage': 'A2', 'parents': []}), [])

    def test_missing_complete_stage_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'four complete'):
            task.complete({}, self.request)


if __name__ == '__main__':
    unittest.main(verbosity=2)
