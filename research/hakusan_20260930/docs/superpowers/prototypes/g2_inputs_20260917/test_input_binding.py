"""Synthetic NEW freeze identities over the real pinned historical data.

This is not a real G2 deployment, input freeze, production capability or GPU run.
The two future launch files use explicitly synthetic byte strings in fixtures.
"""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import input_binding as binding

BRIDGE_PATH = HERE.parent / 'g2_worker_20260916/cell_bridge.py'
bridge_raw = BRIDGE_PATH.read_bytes()
assert hashlib.sha256(bridge_raw).hexdigest() == binding.BRIDGE_SHA
spec = importlib.util.spec_from_file_location('g2_inputs_test_bridge', BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
exec(compile(bridge_raw, str(BRIDGE_PATH), 'exec', dont_inherit=True), vars(bridge))
PARENT = ROOT / 'docs/superpowers/evidence/v18-deployment-artifacts/input_freeze.json'
FIXED = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
PARENT_RAW = PARENT.read_bytes()
assert binding.sha(PARENT_RAW) == binding.PARENT_SHA


def fixture(profile='E'):
    diag = bridge.load_candidate(FIXED / profile / 'diagnose_batch_invariance.py', profile)
    files = {name: (FIXED / profile / name).read_bytes()
             for name in ('diagnose_batch_invariance.py', 'numeric_trace.py')}
    files.update({'submit_numeric_diag.py': b'# synthetic test fixture only; no submission\n',
                  'run_numeric_diag.sbatch': b'# synthetic test fixture only; no execution\n'})
    value = json.loads(PARENT_RAW)
    value['diagnostic_protocol'] = diag.DIAGNOSTIC_PROTOCOL
    value['roots']['diagnostic_root'] = str(diag.DIAGNOSTIC_ROOT)
    for item in value['production_files']:
        raw = files[item['relative_path']]
        item.update(size=len(raw), sha256=binding.sha(raw), mode=0o600,
                    st_dev=1, st_ino=1, st_mtime_ns=1)
    return diag, files, value


class InputsTests(unittest.TestCase):
    def setUp(self):
        self.diag, self.files, self.value = fixture()

    def check(self, value=None, *, files=None, parent=PARENT_RAW):
        raw = binding.canonical(self.value if value is None else value)
        return binding.verify_relation(bridge, self.diag, raw, binding.sha(raw),
                                       self.files if files is None else files, parent)

    def test_all_four_profiles_bind_new_identity_and_old_science(self):
        for profile in 'RCDE':
            diag, files, value = fixture(profile)
            raw = binding.canonical(value)
            actual, report = binding.verify_relation(bridge, diag, raw, binding.sha(raw), files, PARENT_RAW)
            self.assertEqual(actual, value)
            self.assertEqual(report['profile'], profile)
            self.assertTrue(report['parent_is_data_reference_only'])
            self.assertFalse(report['release_authorized'])
            self.assertFalse(report['production_live_inputs_verified'])
            self.assertFalse(report['production_ready'])

    def test_old_freeze_cannot_authorize_new_code(self):
        with self.assertRaisesRegex(ValueError, 'only a data reference'):
            binding.verify_relation(bridge, self.diag, PARENT_RAW, binding.PARENT_SHA, self.files, PARENT_RAW)

    def test_parent_content_change_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SHA differ'):
            self.check(parent=PARENT_RAW + b' ')

    def test_wrong_sha_rejected(self):
        raw = binding.canonical(self.value)
        for digest in ('', 'a' * 64, None, 'A' * 64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                binding.verify_relation(bridge, self.diag, raw, digest, self.files, PARENT_RAW)

    def test_duplicate_noncanonical_and_oversized_json_rejected(self):
        for raw in (b'{"x":1,"x":2}\n', b'{ "x":1}\n', b'null\n', b'x' * (binding.MAX_JSON + 1)):
            with self.assertRaises(ValueError):
                binding.decode(raw, binding.sha(raw))

    def test_nan_and_bool_metadata_rejected(self):
        for raw in (b'{"x":NaN}\n', b'{"x":Infinity}\n'):
            with self.assertRaises(ValueError):
                binding.decode(raw, binding.sha(raw))
        for collection in ('production_files', 'clips', 'snapshot_files'):
            value = copy.deepcopy(self.value)
            value[collection][0]['st_ino'] = True
            with self.subTest(collection=collection), self.assertRaises(ValueError):
                self.check(value)

    def test_only_cross_invocation_stat_identity_is_portable(self):
        for name in ('clips', 'snapshot_files'):
            for item in self.value[name]:
                for key in binding.METADATA:
                    item[key] += 1
        self.check()
        self.value['clips'][0]['size'] += 1
        with self.assertRaisesRegex(ValueError, 'scientific input drift'):
            self.check()

    def test_full_trial_metadata_order_and_bank_position_bound(self):
        for operation in ('order', 'ordinal', 'row', 'label', 'speaker', 'snr'):
            value = copy.deepcopy(self.value)
            if operation == 'order':
                value['trials'].reverse()
            elif operation == 'ordinal':
                value['trials'][0]['ordinal'] = 1
            elif operation == 'row':
                value['trials'][0]['bank_row_index'] += 1
            else:
                key = {'label': 'target_label', 'speaker': 'target_speaker', 'snr': 'snr_bin'}[operation]
                value['trials'][0]['identity'][key] = 'changed'
            with self.subTest(operation=operation), self.assertRaises((ValueError, RuntimeError)):
                self.check(value)

    def test_audio_source_model_and_label_inventory_bound(self):
        edits = [('clips', 'sha256'), ('clips', 'mode'), ('clips', 'uses'),
                 ('snapshot_files', 'sha256'), ('snapshot_files', 'observed_import')]
        for name, field in edits:
            value = copy.deepcopy(self.value)
            value[name][0][field] = 'changed'
            with self.subTest(name=name, field=field), self.assertRaises((ValueError, RuntimeError)):
                self.check(value)
        value = copy.deepcopy(self.value)
        value['v4']['verified_pinned_files'][18]['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'scientific input drift'):
            self.check(value)

    def test_missing_extra_roots_and_keys_rejected(self):
        for value in [dict(self.value, extra=True), {k: v for k, v in self.value.items() if k != 'clips'}]:
            with self.assertRaisesRegex(ValueError, 'field inventory'):
                self.check(value)
        value = copy.deepcopy(self.value)
        value['roots']['diagnostic_root'] = '/wrong/root'
        with self.assertRaises(RuntimeError):
            self.check(value)

    def test_original_code_or_other_profile_not_accepted(self):
        for key in ('diagnose_batch_invariance.py', 'numeric_trace.py'):
            files = dict(self.files)
            files[key] += b'\n'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source differs'):
                self.check(files=files)
        files = dict(self.files)
        files['diagnose_batch_invariance.py'] = (FIXED / 'D/diagnose_batch_invariance.py').read_bytes()
        with self.assertRaises(ValueError):
            self.check(files=files)

    def test_all_four_execution_records_bound(self):
        for name in binding.NAMES:
            value = copy.deepcopy(self.value)
            next(r for r in value['production_files'] if r['relative_path'] == name)['sha256'] = 'b' * 64
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'content/size/mode differs'):
                self.check(value)
        files = dict(self.files)
        files.pop('run_numeric_diag.sbatch')
        with self.assertRaises(ValueError):
            self.check(files=files)

    def test_physical_production_path_required(self):
        raw = binding.canonical(self.value)
        with self.assertRaisesRegex(ValueError, 'declared root'):
            binding.WorkerInputs(bridge, self.diag, binding.sha(raw), self.files, PARENT_RAW)

    def test_original_claim_load_revalidation_calls_retained(self):
        tree = ast.parse((HERE / 'input_binding.py').read_bytes())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WorkerInputs')
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        calls = lambda name: [ast.unparse(n.func) for n in ast.walk(methods[name]) if isinstance(n, ast.Call)]
        self.assertEqual(calls('load').count('self.diag._claim_worker_process'), 1)
        self.assertEqual(calls('load').count('self.diag._load_worker_inputs'), 1)
        self.assertEqual(calls('revalidate').count('self.diag._revalidate_worker_inputs'), 1)
        self.assertFalse(any(isinstance(n, (ast.Import, ast.ImportFrom)) and 'torch' in ast.unparse(n)
                             for n in ast.walk(tree)))

    def test_stable_read_limits_symlink_and_atime(self):
        with tempfile.TemporaryDirectory(prefix='g2-input-read-test-') as temp:
            root = Path(temp).resolve()
            path = root / 'fixture.json'
            path.write_bytes(b'{"synthetic":true}\n')
            self.assertEqual(binding.read_stable(path, 100), path.read_bytes())
            os.utime(path, (1, path.stat().st_mtime))
            self.assertEqual(binding.read_stable(path, 100), path.read_bytes())
            with self.assertRaisesRegex(ValueError, 'bounded'):
                binding.read_stable(path, 1)
            link = root / 'link.json'
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError, 'nonsymlink'):
                binding.read_stable(link, 100)

    def test_live_callable_change_rejected_before_relation(self):
        with mock.patch.object(self.diag, '_load_worker_inputs', lambda *_: {}):
            with self.assertRaisesRegex(RuntimeError, 'source callable changed'):
                self.check()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InputsTests))
    print('G2_INPUT_TEST_REPORT=' + json.dumps(dict(tests=result.testsRun, errors=len(result.errors),
        failures=len(result.failures), skipped=len(result.skipped), scope='LOCAL_RELATION_ONLY',
        actual_production_loader_executed=False, new_remote_freeze_created=False,
        production_model_loaded=False, jobs_submitted=0)), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)
