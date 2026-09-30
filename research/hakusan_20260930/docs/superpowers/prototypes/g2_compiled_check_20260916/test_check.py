"""Unit contract tests; real four-process local checks are run separately."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import protocol as p
import support as s
EVIDENCE = Path(sys.argv.pop()).resolve() if len(sys.argv) == 2 else None


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        for dtype in (np.float32, np.int64):
            a = np.arange(8, dtype=dtype).reshape(2, 4)
            np.testing.assert_array_equal(p.decode(p.encode(a)), a)

    def test_bad_digest(self):
        value = p.encode(np.zeros(32, dtype=np.float32)); value['sha256'] = '0'*64
        with self.assertRaises(RuntimeError): p.decode(value)

    def test_dtype_shape_and_budget(self):
        for key, bad in (('dtype', '<f8'), ('shape', [True]), ('shape', [801]), ('nbytes', 2**21)):
            value = p.encode(np.zeros(32, dtype=np.float32)); value[key] = bad
            with self.assertRaises(RuntimeError): p.decode(value)

    def test_nonfinite(self):
        for bad in (np.inf, -np.inf, np.nan):
            with self.assertRaises(RuntimeError): p.encode(np.array([bad], dtype=np.float32))

    def test_full_identity_shape(self):
        rows = p.trials()
        self.assertEqual(len(rows), 32)
        self.assertEqual(rows[0]['trial_id'], 100)
        self.assertEqual(rows[-1]['bank_row_index'], 51)
        self.assertEqual(len(rows[0]['identity']), 10)

    def test_source_pins(self):
        rows = s.inventory()
        self.assertEqual(len(rows), len(s.FILES))
        self.assertTrue(set(s.PINS).issubset(rows))

    def test_write_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'record.json'
            s.write(path, b'old')
            with self.assertRaises(FileExistsError): s.write(path, b'new')
            self.assertEqual(s.read(path), b'old')

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            s.write(root / 'file', b'data')
            (root / 'link').symlink_to(root / 'file')
            with self.assertRaises(RuntimeError): s.read(root / 'link')

    def test_other_runtime_claim_rejected(self):
        with self.assertRaises(RuntimeError):
            p.child({}, profile='D', role='observed', native=True, release_sha='x', nonce='x')


class PairTests(unittest.TestCase):
    def setUp(self):
        self.terminal = json.loads(s.read(EVIDENCE / 'TERMINAL.json'))
        self.left = json.loads(s.read(EVIDENCE / 'D-reference.json'))
        self.right = json.loads(s.read(EVIDENCE / 'D-observed.json'))

    def pair(self):
        return p.pair(self.left, self.right, native=False,
                      release_sha=self.terminal['release_sha256'], nonce=self.terminal['nonce'])

    def test_actual_pair_and_readonly_receipt(self):
        import run_check
        run_check.verify(EVIDENCE)
        self.assertTrue(self.pair()['bit_exact'])

    def test_rehashed_endpoint_change(self):
        # A freshly recomputed byte hash does not excuse an endpoint difference.
        part = self.right['passes'][0]['outputs']
        a = p.decode(part['nll']).copy(); a[0] += .001
        part['nll'] = p.encode(a)
        with self.assertRaisesRegex(RuntimeError, 'endpoint differs'): self.pair()

    def test_class_flip(self):
        part = self.right['passes'][1]['outputs']
        a = p.decode(part['pred_label']).copy(); a[0] = (a[0]+1) % 800
        part['pred_label'] = p.encode(a)
        with self.assertRaisesRegex(RuntimeError, 'endpoint differs'): self.pair()

    def test_identity_order_partial(self):
        original = copy.deepcopy(self.right)
        for kind in ('identity', 'order', 'partial'):
            self.right = copy.deepcopy(original)
            if kind == 'identity': self.right['trials'][0]['identity']['target_label'] = 799
            elif kind == 'order': self.right['trials'].reverse()
            else: self.right['passes'].pop()
            with self.assertRaises(RuntimeError): self.pair()

    def test_pid_and_cache_reuse(self):
        original = copy.deepcopy(self.right)
        for key in ('pid', 'cache_root'):
            self.right = copy.deepcopy(original); self.right[key] = self.left[key]
            with self.assertRaises(RuntimeError): self.pair()

    def test_runtime_amp_and_scope(self):
        original = copy.deepcopy(self.right)
        for key, value in (('amp_enabled', True), ('runtime', {}), ('ready_for_gpu', True),
                           ('production_model_loaded', True), ('fixture_seed', 20260829),
                           ('production_load_chronology_validated', True)):
            self.right = copy.deepcopy(original); self.right[key] = value
            with self.assertRaises(RuntimeError): self.pair()

    def test_state_rng_release_nonce_binding(self):
        original = copy.deepcopy(self.right)
        for key, value in (('model_state_after', {}), ('rng_after', {}),
                           ('release_sha256', '0'*64), ('nonce', 'forged')):
            self.right = copy.deepcopy(original); self.right[key] = value
            with self.assertRaises(RuntimeError): self.pair()

    def test_local_cannot_claim_compiler_evidence(self):
        self.right['compiler_lifecycle_verified'] = True
        with self.assertRaises(RuntimeError): self.pair()

    def test_native_child_wrong_version_stops_before_model(self):
        with tempfile.TemporaryDirectory(prefix='g2-native-version-rejection-') as temp:
            root = Path(temp).resolve()
            command = [sys.executable, '-I', '-B', str(EVIDENCE / 'package' / s.SELF / 'child.py'),
                       'native', 'R', 'observed', str(root / 'result.json'),
                       self.terminal['release_sha256'], self.terminal['nonce']]
            result = s.runner().run_process(command, dict(os.environ, CUDA_VISIBLE_DEVICES='',
                OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1'), root / 'version.log', seconds=20)
            self.assertIsNone(result['error'])
            self.assertNotEqual(result['returncode'], 0)
            self.assertFalse((root / 'result.json').exists())
            log = s.read(root / 'version.log').decode()
            self.assertIn('native version differs; no model executed', log)
            self.assertNotIn('G2_CHECK_PHASE=', log)


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(ProtocolTests)
    if EVIDENCE is not None:
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(PairTests))
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    print(log.getvalue(), end='')
    if EVIDENCE is not None:
        report = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                      skipped=len(result.skipped), source_sha256=s.sha(s.read(Path(__file__))),
                      release_sha256=s.sha(s.read(EVIDENCE / 'RELEASE.json')), log=log.getvalue(),
                      native_compiled_bridge_verified=False, remote_operations=0, jobs_submitted=0)
        s.write(EVIDENCE / 'UNIT_TESTS.json', s.wire(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
