"""Local lifecycle tests; only the Linux mount decision is a labeled test seam."""
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import startup
import entry_adapter
sys.path.insert(0, str(startup.PRIOR))
import coordinator
import gpu_child
import process_runner
import job_contract

SOURCE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v18/diagnose_batch_invariance.py"


@contextlib.contextmanager
def local_scope_test_environment(role="reference"):
    """Do not use this fixture as production mount validation."""
    with tempfile.TemporaryDirectory(prefix="scratch-first-test-") as temp:
        base = Path(temp).resolve()
        parent = base / "audattn_v4_numdiag_7770001"
        parent.mkdir(mode=0o700)
        tool = base / "v18/tools"
        tool.mkdir(parents=True, mode=0o700)
        shutil.copyfile(SOURCE, tool / SOURCE.name)
        contract = types.SimpleNamespace(V18=tool.parent, FREEZE_SHA=job_contract.FREEZE_SHA,
                                         pinned_read=job_contract.pinned_read)
        args = types.SimpleNamespace(job_id="7770001", expected_input_freeze_sha256=contract.FREEZE_SHA)
        child_env = coordinator.child_environment({**os.environ, "SLURM_JOB_ID": args.job_id}, parent, role)
        updates = {k: v for k, v in child_env.items() if k != "HOME"}
        loader = startup.checked_load
        loaded = []

        def test_loader(*args):
            diag = loader(*args)
            diag._require_local_scratch_mount = lambda path: {"scope": "LOCAL_TEST_MOUNT_STUB", "path": str(path)}
            loaded.append(diag)
            return diag

        with mock.patch.dict(os.environ, updates), mock.patch.object(startup, "checked_load", test_loader):
            yield base, parent, contract, args, loaded


class StartupTests(unittest.TestCase):
    def test_original_factory_precedes_import_and_preserves_home(self):
        original_home = os.environ.get("HOME")
        for role, leaf in (("reference", "reference_cold"), ("observed", "B2")):
            with self.subTest(role=role), local_scope_test_environment(role) as (_, parent, contract, args, _):
                self.assertFalse((parent / leaf).exists())
                with startup.open_scratch(contract, role) as lease:
                    self.assertEqual(lease.scratch.root, parent / leaf)
                    self.assertTrue(lease.scratch.record["caches_initially_empty"])
                    for directory in (parent / leaf).iterdir():
                        self.assertTrue(directory.is_dir())
                        self.assertEqual(list(directory.iterdir()), [])
                    self.assertTrue((parent / leaf / "torchinductor").is_dir())
                    self.assertEqual(os.environ.get("HOME"), original_home)
                    lease.check()
                self.assertFalse(lease.active)
                self.assertTrue(all(not a.chain for a, *_ in lease.anchor_ids))
        self.assertEqual(os.environ.get("HOME"), original_home)

    def test_existing_role_is_never_adopted(self):
        with local_scope_test_environment() as (_, parent, contract, _, _):
            (parent / "reference_cold").mkdir(mode=0o700)
            with self.assertRaises(FileExistsError):
                with startup.open_scratch(contract, "reference"):
                    self.fail("existing role entered")

    def test_role_symlink_rejected_without_touching_target(self):
        with local_scope_test_environment() as (base, parent, contract, _, _):
            target = base / "unrelated"
            target.mkdir()
            (parent / "reference_cold").symlink_to(target, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                with startup.open_scratch(contract, "reference"):
                    self.fail("symlink role entered")
            self.assertEqual(list(target.iterdir()), [])

    def test_parent_mode_and_environment_rejected(self):
        with local_scope_test_environment() as (_, parent, contract, _, _):
            os.chmod(parent, 0o755)
            with self.assertRaisesRegex(RuntimeError, "0700"):
                with startup.open_scratch(contract, "reference"):
                    pass
            self.assertFalse((parent / "reference_cold").exists())
        with local_scope_test_environment() as (_, parent, contract, _, _):
            with mock.patch.dict(os.environ, {"TMPDIR": str(parent / "wrong")}):
                with self.assertRaisesRegex(RuntimeError, "environment"):
                    with startup.open_scratch(contract, "reference"):
                        pass

    def test_already_imported_numeric_module_rejected(self):
        with local_scope_test_environment() as (_, parent, contract, _, _):
            with mock.patch.dict(sys.modules, {"numpy": types.ModuleType("numpy")}):
                with self.assertRaisesRegex(RuntimeError, "precede numeric imports"):
                    with startup.open_scratch(contract, "reference"):
                        pass
            self.assertFalse((parent / "reference_cold").exists())

    def test_changed_bootstrap_source_rejected_before_directory_creation(self):
        with local_scope_test_environment() as (_, parent, contract, _, _):
            path = contract.V18 / "tools/diagnose_batch_invariance.py"
            path.write_bytes(path.read_bytes() + b"\n# synthetic corruption\n")
            with self.assertRaisesRegex(RuntimeError, "SHA"):
                with startup.open_scratch(contract, "reference"):
                    pass
            self.assertFalse((parent / "reference_cold").exists())

    def test_lease_cannot_cross_process_boundary(self):
        with local_scope_test_environment() as (_, _, contract, _, _):
            with startup.open_scratch(contract, "reference") as lease:
                with mock.patch.object(startup.os, "getpid", return_value=lease.owner_pid + 1):
                    with self.assertRaisesRegex(RuntimeError, "another process"):
                        lease.check()
                lease.check()

    def test_import_failure_closes_anchors_and_restores_temp_state(self):
        old_prefix = sys.pycache_prefix
        with local_scope_test_environment() as (_, parent, contract, _, _):
            # TemporaryDirectory itself may initialize tempfile.tempdir.
            before_temp, before_prefix = tempfile.tempdir, sys.pycache_prefix
            with self.assertRaisesRegex(ImportError, "synthetic import"):
                with startup.open_scratch(contract, "reference") as lease:
                    raise ImportError("synthetic import")
            self.assertFalse(lease.active)
            self.assertTrue(all(not a.chain for a, *_ in lease.anchor_ids))
            self.assertEqual((tempfile.tempdir, sys.pycache_prefix), (before_temp, before_prefix))
            self.assertTrue((parent / "reference_cold").is_dir())  # not silently reused or deleted
        self.assertEqual(sys.pycache_prefix, old_prefix)

    def test_same_live_directories_bound_once(self):
        with local_scope_test_environment() as (_, parent, contract, args, loaded):
            with startup.open_scratch(contract, "reference") as boot:
                (boot.scratch.root / "mpl" / "synthetic-cache").write_bytes(b"after-import")
                bridge = types.SimpleNamespace(_require_module=mock.Mock())
                private, scope, _ = startup.bind_scope(boot, loaded[0], bridge)
                bridge._require_module.assert_called_once_with(loaded[0])
                with scope(args, "reference_cold") as scratch:
                    self.assertIs(type(scratch), private)
                    self.assertIs(scratch.anchors, boot.scratch.anchors)
                    self.assertEqual(scratch.root, boot.scratch.root)
                    self.assertTrue(scratch.record["caches_initially_empty"])
                    self.assertEqual((scratch.root / "mpl/synthetic-cache").read_bytes(), b"after-import")
                    scratch.check()
                with self.assertRaisesRegex(RuntimeError, "already bound"):
                    startup.bind_scope(boot, loaded[0], bridge)
                with self.assertRaisesRegex(RuntimeError, "reentered"):
                    with scope(args, "reference_cold"):
                        pass

    def test_binding_requires_original_loader_issuance(self):
        with local_scope_test_environment() as (_, _, contract, _, loaded):
            with startup.open_scratch(contract, "reference") as boot:
                bridge = types.SimpleNamespace(_require_module=mock.Mock(side_effect=RuntimeError("not issued")))
                with self.assertRaisesRegex(RuntimeError, "not issued"):
                    startup.bind_scope(boot, loaded[0], bridge)
                self.assertFalse(boot.bound)

    def test_wrong_job_role_freeze_and_closed_lease_rejected(self):
        with local_scope_test_environment() as (_, _, contract, args, loaded):
            with startup.open_scratch(contract, "reference") as boot:
                _, scope, _ = startup.bind_scope(boot, loaded[0], types.SimpleNamespace(_require_module=lambda _: None))
                for test_args, role in ((args, "B2"),
                    (types.SimpleNamespace(job_id="7770002", expected_input_freeze_sha256=contract.FREEZE_SHA), "reference_cold"),
                    (types.SimpleNamespace(job_id=args.job_id, expected_input_freeze_sha256="0" * 64), "reference_cold")):
                    with self.assertRaisesRegex(RuntimeError, "job/role/freeze"):
                        with scope(test_args, role):
                            pass
            with self.assertRaisesRegex(RuntimeError, "closed"):
                with scope(args, "reference_cold"):
                    pass

    def test_replaced_directory_and_cache_environment_rejected(self):
        with local_scope_test_environment() as (_, _, contract, _, _):
            with startup.open_scratch(contract, "reference") as lease:
                with mock.patch.dict(os.environ, {"TMPDIR": "/invalid/synthetic"}):
                    with self.assertRaisesRegex(RuntimeError, "cache environment"):
                        lease.check()
                folder = lease.scratch.root / "mpl"
                saved = lease.scratch.root / "mpl.saved"
                folder.rename(saved)
                folder.mkdir(mode=0o700)
                try:
                    with self.assertRaisesRegex(RuntimeError, "namespace changed"):
                        lease.check()
                finally:
                    folder.rmdir()
                    saved.rename(folder)


class EntryTests(unittest.TestCase):
    def test_restoring_changes_recovers_complete_original_ast(self):
        tree, audit = entry_adapter.derive()
        self.assertTrue(audit["original_run_ast_restored_exactly"])
        self.assertFalse(audit["scientific_runtime_or_tolerances_changed"])
        attempt = next(n for n in tree.body[0].body if isinstance(n, ast.Try))
        self.assertIn("enter_context", ast.unparse(attempt.body[0]))
        self.assertIsInstance(attempt.body[3], ast.Import)

    def test_actual_derived_run_import_error_recorded_and_cleanup_called(self):
        events = []
        @contextlib.contextmanager
        def scope(*_):
            events.append("scratch_enter")
            try:
                yield object()
            finally:
                events.append("scratch_exit")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "artifacts").mkdir()
            contract = types.SimpleNamespace(child_cold_gate=lambda _: events.append("cold_gate"),
                require=startup.require, check_sources=lambda _: None, check_authorization=lambda *_: None,
                REMOTE=root, FREEZE_SHA="a" * 64)
            namespace = {**vars(gpu_child), "contract": contract}
            fake_startup = types.SimpleNamespace(open_scratch=scope)
            run, _ = entry_adapter.bind(namespace, fake_startup)
            native = __import__
            def importing(name, *args, **kwargs):
                if name == "cuda_registration":
                    events.append("numeric_import")
                    raise ImportError("synthetic numeric import failure")
                return native(name, *args, **kwargs)
            with mock.patch.dict(os.environ, {"SLURM_JOB_ID": "7770001"}), mock.patch("builtins.__import__", importing):
                self.assertEqual(run("reference", "0" * 64, "1" * 32), 2)
            record = json.loads((root / "artifacts/reference/CHILD.json").read_bytes())
            self.assertEqual(record["error"]["type"], "ImportError")
            self.assertEqual(record["cleanup_errors"], [])
            self.assertEqual(events, ["cold_gate", "scratch_enter", "numeric_import", "scratch_exit"])

    def test_actual_derived_run_scratch_collision_recorded_before_import(self):
        events = []
        @contextlib.contextmanager
        def scope(*_):
            events.append("exclusive_directory_rejected")
            raise FileExistsError(17, "File exists", "reference_cold")
            yield  # contextmanager which fails at entry, before numeric import
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "artifacts").mkdir()
            contract = types.SimpleNamespace(child_cold_gate=lambda _: None, require=startup.require,
                check_sources=lambda _: None, check_authorization=lambda *_: None,
                REMOTE=root, FREEZE_SHA="a" * 64)
            run, _ = entry_adapter.bind({**vars(gpu_child), "contract": contract},
                                        types.SimpleNamespace(open_scratch=scope))
            native = __import__
            def importing(name, *args, **kwargs):
                if name == "cuda_registration":
                    events.append("UNEXPECTED_NUMERIC_IMPORT")
                    raise AssertionError("numeric import reached after directory collision")
                return native(name, *args, **kwargs)
            with mock.patch.dict(os.environ, {"SLURM_JOB_ID": "7770001"}), mock.patch("builtins.__import__", importing):
                self.assertEqual(run("reference", "0" * 64, "1" * 32), 2)
            record = json.loads((root / "artifacts/reference/CHILD.json").read_bytes())
            self.assertEqual(record["error"]["type"], "FileExistsError")
            self.assertEqual(record["cleanup_errors"], [])
            self.assertEqual(events, ["exclusive_directory_rejected"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
