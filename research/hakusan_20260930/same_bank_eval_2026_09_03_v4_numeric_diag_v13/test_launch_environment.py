"""Original-runner fixed environment parity and cold exec boundaries; CPU only."""

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PACKAGE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "launch_environment_fixtures", PACKAGE / "test_submit_numeric_diag.py"
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
diag = fixtures.load_diag()
FIXED = {
    "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    "OMP_NUM_THREADS": "8",
    "TOKENIZERS_PARALLELISM": "false",
}


class LaunchEnvironmentTests(unittest.TestCase):
    def environment(self, cell=None, parent=None):
        return diag.child_environment(
            "_child-reference" if cell is None else "_child-cell",
            "123",
            cell,
            "/tmp/audattn_v4_numdiag_123",
            parent or {"SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"},
        )

    def test_original_sha_bound_runner_has_exact_fixed_exports(self):
        original = (
            PACKAGE.parent
            / "same_bank_eval_2026_08_29_v4"
            / "run_locked_same_bank_eval.sbatch"
        )
        raw = original.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), diag.V4_RUNNER_SHA256)
        lines = raw.decode().splitlines()
        for key, value in FIXED.items():
            self.assertEqual(lines.count(f"export {key}={value}"), 1)
        self.assertEqual({k: self.environment().get(k) for k in FIXED}, FIXED)

    def test_all_cold_roles_and_coordinator_receive_fixed_values(self):
        for role in (None, "A2", "A1", "B1", "B2"):
            with self.subTest(role=role):
                env = self.environment(role)
                self.assertEqual({k: env.get(k) for k in FIXED}, FIXED)
        env = diag.coordinator_environment(
            "123",
            "/tmp/audattn_v4_numdiag_123",
            {"SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"},
        )
        self.assertEqual({k: env.get(k) for k in FIXED}, FIXED)

    def test_hostile_parent_cannot_override_fixed_values(self):
        parent = {"SLURM_JOB_ID": "123", "CUDA_VISIBLE_DEVICES": "0"}
        parent.update({k: "BAD\x00VALUE" for k in FIXED})
        parent["UNRELATED_SECRET"] = "DO_NOT_COPY"
        before = dict(parent)
        env = self.environment(parent=parent)
        self.assertEqual({k: env.get(k) for k in FIXED}, FIXED)
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual(parent, before)

    def test_fixed_values_are_not_scheduler_inheritance_keys(self):
        self.assertFalse(set(FIXED) & set(diag._CHILD_SLURM_ENV_KEYS))
        self.assertFalse(set(FIXED) & set(fixtures.bootstrap().SCHEDULER_KEYS))

    def test_every_environment_tamper_or_omission_is_rejected(self):
        expected = self.environment()
        for key in FIXED:
            for replacement in (None, "wrong"):
                changed = dict(expected)
                if replacement is None:
                    changed.pop(key, None)
                else:
                    changed[key] = replacement
                with self.subTest(key=key, value=replacement):
                    with mock.patch.dict(os.environ, changed, clear=True):
                        with self.assertRaisesRegex(diag.DiagnosticError, "allowlist"):
                            diag._check_clean_execution_environment(expected)

    def test_values_exist_in_actual_cold_interpreter_before_science_import(self):
        code = (
            "import json,os,sys; "
            "assert not any(k in sys.modules for k in ('torch','numpy','torchaudio')); "
            f"print(json.dumps({{k:os.environ.get(k) for k in {tuple(FIXED)!r}}}))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            env=self.environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), FIXED)

    def test_launcher_passes_constructed_environment_before_popen(self):
        tree = ast.parse((PACKAGE / "diagnose_batch_invariance.py").read_text())
        launches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func) == "subprocess.Popen"
        ]
        self.assertEqual(len(launches), 1)
        self.assertEqual(
            {kw.arg: ast.unparse(kw.value) for kw in launches[0].keywords}["env"],
            "environment",
        )

    def test_real_bootstrap_exec_environment_and_record_agree(self):
        fixture = fixtures.RunnerContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bootstrap = fixture.b
        freeze = fixture.fixture(
            b"import runner_test_diag; globals().update(vars(runner_test_diag))\n"
        )
        with tempfile.TemporaryDirectory() as scratch_parent:
            parent = pathlib.Path(scratch_parent).resolve()
            scheduler = {
                "SLURM_JOB_ID": "123",
                "CUDA_VISIBLE_DEVICES": "0",
                "SLURM_TMPDIR": str(parent),
                **{k: "bad-parent" for k in FIXED},
            }
            log = io.StringIO()
            with (
                mock.patch.object(bootstrap, "ROOT", fixture.root),
                mock.patch.object(bootstrap, "PYTHON", pathlib.Path(sys.executable)),
                mock.patch.object(diag, "DIAGNOSTIC_ROOT", fixture.root),
                mock.patch.object(
                    diag, "PRODUCTION_PYTHON", pathlib.Path(sys.executable)
                ),
                mock.patch.object(diag, "_validate_freeze_value") as schema,
                mock.patch.object(
                    diag, "_require_local_scratch_mount", return_value={}
                ),
                mock.patch.object(sys, "platform", "linux"),
                mock.patch.object(
                    sys, "argv", ["-", str(fixture.spool), fixture.sha, fixture.nonce]
                ),
                mock.patch.dict(os.environ, scheduler, clear=True),
                mock.patch.object(os, "execve") as execute,
                contextlib.redirect_stderr(log),
            ):
                bootstrap.main()
                self.assertEqual(schema.call_args.args[0], freeze)
                execute.assert_called_once()
                env = execute.call_args.args[2]
                self.assertEqual(env, dict(os.environ))
                self.assertEqual({k: env.get(k) for k in FIXED}, FIXED)
            rows = log.getvalue().splitlines()
            record = next(
                r.split("=", 1)[1]
                for r in rows
                if r.startswith("BOOTSTRAP_ENVIRONMENT=")
            )
            self.assertEqual(json.loads(record)["environment"], env)
            digest = hashlib.sha256((record + "\n").encode()).hexdigest()
            self.assertIn("BOOTSTRAP_ENVIRONMENT_SHA256=" + digest, rows)
            self.assertNotIn("bad-parent", log.getvalue())


if __name__ == "__main__":
    unittest.main()
