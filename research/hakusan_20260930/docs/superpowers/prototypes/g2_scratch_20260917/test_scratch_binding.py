"""Filesystem/interface tests only: Linux mount check is explicitly stubbed.

No torch import, checkpoint load, GPU inference, SSH or job submission.
"""
import ast
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import scratch_binding as subject

BRIDGE_PATH = HERE.parent / 'g2_worker_20260916/cell_bridge.py'
raw = BRIDGE_PATH.read_bytes()
assert hashlib.sha256(raw).hexdigest() == subject.BRIDGE_SHA
spec = importlib.util.spec_from_file_location('g2_scratch_test_bridge', BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
exec(compile(raw, str(BRIDGE_PATH), 'exec', dont_inherit=True), vars(bridge))
FIXED = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu'
JOB, FREEZE = '7770017', 'a' * 64


def make_binding(profile='E'):
    diag = bridge.load_candidate(FIXED / profile / 'diagnose_batch_invariance.py', profile)
    return subject.Binding(bridge, diag)


@contextlib.contextmanager
def sandbox(profile='E', side='observed'):
    with tempfile.TemporaryDirectory(prefix='g2-scratch-interface-test-') as temp:
        root = Path(temp).resolve() / ('audattn_g2_' + JOB)
        root.mkdir(mode=0o700)
        binding = make_binding(profile)
        env = binding.environment(dict(os.environ, SLURM_JOB_ID=JOB), root, JOB, side)
        updates = {k: v for k, v in env.items() if k != 'HOME'}
        # The real mount guard is retained in production. This test does NOT
        # certify a macOS temporary folder as a production Linux local mount.
        namespace = binding._factory.__wrapped__.__globals__
        stub = lambda p: dict(scope='LOCAL_TEST_MOUNT_STUB', path=str(p))
        with mock.patch.dict(namespace, {'_require_local_scratch_mount': stub}), \
                mock.patch.dict(os.environ, updates):
            yield binding, root


class BindingTests(unittest.TestCase):
    def test_all_profiles_and_sides_preserve_home_and_originals(self):
        home = os.environ.get('HOME')
        original_run = bridge.CellBridge.run
        for profile in subject.PROFILES:
            for side in subject.SIDES:
                with self.subTest(profile=profile, side=side), sandbox(profile, side) as (b, root):
                    paths = dict(b.diag._WORKER_WRITE_PATHS)
                    with b.scope(JOB, FREEZE, side) as scratch:
                        self.assertIs(type(scratch), b.scratch_type)
                        self.assertEqual(scratch.root, root / (profile + '-' + side))
                        self.assertEqual(scratch.record['mount']['scope'], 'LOCAL_TEST_MOUNT_STUB')
                        self.assertTrue(scratch.record['caches_initially_empty'])
                        self.assertEqual(os.environ.get('HOME'), home)
                        self.assertNotIn('HOME', b.paths)
                        self.assertFalse((scratch.root / 'home').exists())
                        self.assertTrue(all(not list(p.iterdir()) for p in scratch.root.iterdir()))
                        scratch.check()
                    self.assertFalse(b.active)
                    self.assertEqual(dict(b.diag._WORKER_WRITE_PATHS), paths)
                    self.assertIs(bridge.CellBridge.run, original_run)
                    bridge._check_module(b.diag)
        self.assertEqual(os.environ.get('HOME'), home)

    def test_derivation_restores_all_other_ast(self):
        b = make_binding()
        factory, run, proof = subject.derive(Path(b.diag.__file__).read_bytes(), raw)
        self.assertEqual(proof['factory_changes'], ['role_allowlist', 'job_directory_prefix'])
        self.assertEqual(proof['bridge_changes'], ['exact_scratch_type'])
        self.assertTrue(proof['inference_body_otherwise_unchanged'])
        self.assertFalse(proof['production_ready'])
        self.assertIn('diag.run_trace_pass', ast.unparse(run))
        self.assertIn('_require_local_scratch_mount', ast.unparse(factory))
        self.assertIn('os.O_EXCL', Path(b.diag.__file__).read_text())

    def test_source_recipe_drift_rejected(self):
        b = make_binding()
        changed = raw.replace(b'type(scratch) is diag._WorkerScratch', b'isinstance(scratch, diag._WorkerScratch)')
        # The recipe itself is not a source verifier. The pinned constructor
        # rejects changed source, and recipe changes must also fail on structure.
        changed = changed.replace(b'diag._WorkerScratch', b'object')
        with self.assertRaisesRegex(RuntimeError, 'exactly one match'):
            subject.derive(Path(b.diag.__file__).read_bytes(), changed)

    def test_bound_source_callable_mutation_rejected(self):
        with sandbox() as (b, root):
            with mock.patch.object(b.diag, 'run_trace_pass', lambda *a: None):
                with self.assertRaisesRegex(RuntimeError, 'source callable changed'):
                    with b.scope(JOB, FREEZE, 'observed'):
                        pass
            self.assertFalse((root / 'E-observed').exists())
            self.assertFalse(b.active)

    def test_cold_numeric_import_gate(self):
        with mock.patch.dict(sys.modules, {'numpy': types.ModuleType('numpy')}):
            with self.assertRaisesRegex(RuntimeError, 'precede numeric imports'):
                make_binding()
        with sandbox() as (b, root):
            with mock.patch.dict(sys.modules, {'torch': types.ModuleType('torch')}):
                with self.assertRaisesRegex(RuntimeError, 'precede numeric imports'):
                    with b.scope(JOB, FREEZE, 'observed'):
                        pass
            self.assertFalse((root / 'E-observed').exists())

    def test_existing_directory_not_adopted(self):
        with sandbox() as (b, root):
            (root / 'E-observed').mkdir(mode=0o700)
            with self.assertRaises(FileExistsError):
                with b.scope(JOB, FREEZE, 'observed'):
                    pass
            self.assertFalse(b.active)
            with self.assertRaisesRegex(RuntimeError, 'single use'):
                with b.scope(JOB, FREEZE, 'observed'):
                    pass

    def test_symlink_not_followed(self):
        with sandbox() as (b, root):
            target = root / 'unrelated'
            target.mkdir(mode=0o700)
            (root / 'E-observed').symlink_to(target, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                with b.scope(JOB, FREEZE, 'observed'):
                    pass
            self.assertEqual(list(target.iterdir()), [])

    def test_bad_parent_mode_rejected(self):
        with sandbox() as (b, root):
            root.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, '0700'):
                with b.scope(JOB, FREEZE, 'observed'):
                    pass
            self.assertFalse((root / 'E-observed').exists())

    def test_bad_job_freeze_side_and_environment(self):
        for job, freeze, side in [('07770017', FREEZE, 'observed'),
                                  (JOB, 'broken', 'observed'), (JOB, FREEZE, '../R'),
                                  ('7770018', FREEZE, 'observed')]:
            with self.subTest(job=job, side=side), sandbox() as (b, root):
                with self.assertRaises(RuntimeError):
                    with b.scope(job, freeze, side):
                        pass
                self.assertFalse((root / 'E-observed').exists())
        with sandbox() as (b, root):
            with mock.patch.dict(os.environ, {'TMPDIR': str(root / 'wrong')}):
                with self.assertRaisesRegex(RuntimeError, 'environment'):
                    with b.scope(JOB, FREEZE, 'observed'):
                        pass

    def test_cache_environment_change_detected(self):
        with sandbox() as (b, root), b.scope(JOB, FREEZE, 'observed') as scratch:
            with mock.patch.dict(os.environ, {'TORCHINDUCTOR_CACHE_DIR': str(root / 'wrong')}):
                with self.assertRaisesRegex(RuntimeError, 'environment'):
                    scratch.check()
            scratch.check()

    def test_directory_replacement_detected(self):
        with sandbox() as (b, _), b.scope(JOB, FREEZE, 'observed') as scratch:
            live = scratch.root / 'torchinductor'
            saved = scratch.root / 'saved'
            live.rename(saved)
            live.mkdir(mode=0o700)
            try:
                with self.assertRaisesRegex(RuntimeError, 'namespace changed'):
                    scratch.check()
            finally:
                live.rmdir()
                saved.rename(live)
            scratch.check()

    def test_scope_exit_preserves_failure_files_closes_fds(self):
        with sandbox() as (b, root):
            before = tempfile.tempdir, sys.pycache_prefix
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                with b.scope(JOB, FREEZE, 'observed') as scratch:
                    raise ValueError('synthetic failure')
            self.assertEqual((tempfile.tempdir, sys.pycache_prefix), before)
            self.assertTrue((root / 'E-observed').is_dir())
            self.assertTrue(all(not a.chain for a in scratch.anchors))
            with self.assertRaisesRegex(RuntimeError, 'scope closed'):
                scratch.check()

    def test_owner_process_and_home_expectation_checked(self):
        with sandbox() as (b, _), b.scope(JOB, FREEZE, 'observed') as scratch:
            with mock.patch.object(b, 'pid', b.pid + 1):
                with self.assertRaisesRegex(RuntimeError, 'process changed'):
                    scratch.check()
            # Alter the stored expectation, never the actual HOME variable.
            with mock.patch.object(b, 'home', '/invalid/expected-home'):
                with self.assertRaisesRegex(RuntimeError, 'HOME changed'):
                    scratch.check()
            scratch.check()

    def test_bound_bridge_accepts_only_own_active_type(self):
        class ReachedGuardedScope(RuntimeError):
            pass

        def stop_before_inference():
            raise ReachedGuardedScope('interface test stops before inference')

        with sandbox() as (b, _), b.scope(JOB, FREEZE, 'observed') as scratch:
            obj = object.__new__(b.bridge_type)
            obj.used, obj.hermetic_test, obj.diag = False, False, b.diag
            obj.context = dict(scratch_root=str(scratch.root), cache_roots=scratch.cache_roots)
            obj.profile = bridge.profiles.profile('E')
            obj.attestation = object()  # NOT an issued production model
            obj._scope = stop_before_inference
            with self.assertRaisesRegex(RuntimeError, 'own active scratch'):
                obj.run(scratch=object())
            with self.assertRaisesRegex(bridge.BridgeError, 'coordinator-owned pinned scratch'):
                bridge.CellBridge.run(obj, scratch=scratch)
            obj.used = False
            with self.assertRaises(ReachedGuardedScope):
                obj.run(scratch=scratch)
            self.assertTrue(obj.used)
            with self.assertRaisesRegex(bridge.BridgeError, 'single use'):
                obj.run(scratch=scratch)

    def test_environment_builder_rejects_path_job_and_home_mismatch(self):
        b = make_binding()
        env = dict(os.environ, SLURM_JOB_ID=JOB)
        for base, job in [('/tmp/wrong', JOB), ('relative/audattn_g2_' + JOB, JOB),
                          ('/tmp/../audattn_g2_' + JOB, JOB), ('/tmp/audattn_g2_0', '0')]:
            with self.assertRaises(RuntimeError):
                b.environment(env, base, job, 'observed')
        with self.assertRaisesRegex(RuntimeError, 'scheduler job/HOME differs'):
            b.environment(dict(env, SLURM_JOB_ID='7770018'), '/tmp/audattn_g2_' + JOB, JOB, 'observed')


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BindingTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print('G2_SCRATCH_TEST_REPORT=' + json.dumps(dict(
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), scope='LOCAL_FILESYSTEM_AND_INTERFACE_ONLY',
        linux_mount_test_stub=True, production_model_loaded=False,
        gpu_validated=False, jobs_submitted=0)), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 2)
