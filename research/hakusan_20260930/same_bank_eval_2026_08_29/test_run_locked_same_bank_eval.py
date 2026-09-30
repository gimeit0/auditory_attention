#!/usr/bin/env python3
"""Tests for the exclusive spool-copy program embedded in the sbatch file."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest


RUNNER = pathlib.Path(__file__).with_name("run_locked_same_bank_eval.sbatch")
EVALUATOR = pathlib.Path(__file__).with_name("locked_same_bank_eval.py")


def embedded_copy_program() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(
        r"readonly EXCLUSIVE_COPY_PROGRAM='\n(?P<program>.*?)\n'\n"
        r'"\$PYTHON" -I -c "\$EXCLUSIVE_COPY_PROGRAM"',
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("could not locate embedded exclusive-copy program")
    return match.group("program")


def embedded_trust_bootstrap_program() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(
        r"readonly TRUST_BOOTSTRAP_PROGRAM='\n(?P<program>.*?)\n'\n"
        r"TRUST_BOOTSTRAP_RECORD=",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("could not locate embedded trust-bootstrap program")
    return match.group("program")


def embedded_json_archive_program() -> str:
    text = RUNNER.read_text(encoding="utf-8")
    match = re.search(
        r"readonly EXCLUSIVE_JSON_PROGRAM='\n(?P<program>.*?)\n'\n"
        r"ENVIRONMENT_ARCHIVE_SHA256=",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("could not locate embedded JSON-archive program")
    return match.group("program")


def run_copy(source: pathlib.Path, destination: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", embedded_copy_program(), str(source), str(destination)],
        check=False,
        capture_output=True,
        text=True,
    )


class ExclusiveSubmittedRunnerCopyTests(unittest.TestCase):
    def test_preexisting_target_bytes_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            source = root / "source.sbatch"
            destination = root / "submitted.sbatch"
            source.write_bytes(b"new runner bytes\n")
            original = b"reviewed existing evidence\n"
            destination.write_bytes(original)

            result = run_copy(source, destination)

            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(root.glob(".submitted.sbatch.tmp.*")), [])

    def test_concurrent_publish_has_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            first_source = root / "first.sbatch"
            second_source = root / "second.sbatch"
            destination = root / "submitted.sbatch"
            first_bytes = b"first runner\n" * 100_000
            second_bytes = b"second runner\n" * 100_000
            first_source.write_bytes(first_bytes)
            second_source.write_bytes(second_bytes)
            program = embedded_copy_program()

            first = subprocess.Popen(
                [sys.executable, "-c", program, str(first_source), str(destination)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            second = subprocess.Popen(
                [sys.executable, "-c", program, str(second_source), str(destination)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            first_stdout, first_stderr = first.communicate(timeout=30)
            second_stdout, second_stderr = second.communicate(timeout=30)

            self.assertEqual(
                sorted([first.returncode, second.returncode]),
                [0, 73],
                (first_stdout, first_stderr, second_stdout, second_stderr),
            )
            self.assertIn(destination.read_bytes(), {first_bytes, second_bytes})
            self.assertEqual(list(root.glob(".submitted.sbatch.tmp.*")), [])


class TrustBootstrapTests(unittest.TestCase):
    ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
    CONFIRMATION = "formal40-primary__valbest33-secondary__author-external"

    def create_fixture(self, root: pathlib.Path) -> tuple[list[str], pathlib.Path, pathlib.Path]:
        tools = root / "tools"
        tools.mkdir()
        runner = tools / "run_locked_same_bank_eval.sbatch"
        evaluator = tools / "locked_same_bank_eval.py"
        runner.write_bytes(b"reviewed runner\n")
        evaluator.write_bytes(b"reviewed evaluator\n")

        def record(path: pathlib.Path) -> dict[str, object]:
            payload = path.read_bytes()
            return {
                "path": str(path),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        manifest = root / "input_freeze.json"
        manifest_payload = json.dumps(
            {
                "schema_version": 1,
                "status": "FROZEN",
                "evaluation_role": self.ROLE,
                "role_confirmation": self.CONFIRMATION,
                "roots": {"external_root": str(root)},
                "inputs": {
                    "sbatch": record(runner),
                    "evaluator": record(evaluator),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest.write_bytes(manifest_payload)
        manifest_sha = hashlib.sha256(manifest_payload).hexdigest()
        arguments = [
            sys.executable,
            "-I",
            "-c",
            embedded_trust_bootstrap_program(),
            str(manifest),
            manifest_sha,
            str(root),
            str(runner),
            str(evaluator),
            self.ROLE,
            self.CONFIRMATION,
        ]
        return arguments, runner, evaluator

    def test_reviewed_manifest_binds_runner_and_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            arguments, _, _ = self.create_fixture(root)

            result = subprocess.run(arguments, check=False, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record["manifest_sha256"], arguments[5])

    def test_runner_or_evaluator_tampering_is_rejected(self) -> None:
        for target_name in ("runner", "evaluator"):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as temporary_directory:
                root = pathlib.Path(temporary_directory)
                arguments, runner, evaluator = self.create_fixture(root)
                target = runner if target_name == "runner" else evaluator
                target.write_bytes(b"tampered after freeze\n")

                result = subprocess.run(
                    arguments,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_unreviewed_manifest_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            arguments, _, _ = self.create_fixture(root)
            arguments[5] = "0" * 64

            result = subprocess.run(arguments, check=False, capture_output=True, text=True)

            self.assertNotEqual(result.returncode, 0, result.stdout)


class ExclusiveEnvironmentArchiveTests(unittest.TestCase):
    def run_archive(
        self, payload: str, destination: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                embedded_json_archive_program(),
                payload,
                str(destination),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_archive_is_canonical_newline_terminated_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = pathlib.Path(temporary_directory) / "123.environment.json"
            result = self.run_archive('{"z":2, "a":1}', destination)

            expected = b'{"a":1,"z":2}\n'
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_bytes(), expected)
            self.assertEqual(result.stdout.strip(), hashlib.sha256(expected).hexdigest())

    def test_preexisting_environment_record_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = pathlib.Path(temporary_directory) / "123.environment.json"
            original = b'{"reviewed":true}\n'
            destination.write_bytes(original)

            result = self.run_archive('{"new":true}', destination)

            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(destination.parent.glob(".123.environment.json.tmp.*")), [])

    def test_concurrent_environment_publish_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = pathlib.Path(temporary_directory) / "123.environment.json"
            program = embedded_json_archive_program()
            first_payload = '{"source":"first"}'
            second_payload = '{"source":"second"}'
            first = subprocess.Popen(
                [sys.executable, "-I", "-c", program, first_payload, str(destination)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            second = subprocess.Popen(
                [sys.executable, "-I", "-c", program, second_payload, str(destination)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            first_stdout, first_stderr = first.communicate(timeout=30)
            second_stdout, second_stderr = second.communicate(timeout=30)

            self.assertEqual(
                sorted([first.returncode, second.returncode]),
                [0, 73],
                (first_stdout, first_stderr, second_stdout, second_stderr),
            )
            self.assertIn(
                destination.read_bytes(),
                {b'{"source":"first"}\n', b'{"source":"second"}\n'},
            )
            self.assertEqual(list(destination.parent.glob(".123.environment.json.tmp.*")), [])


class RunnerCliContractTests(unittest.TestCase):
    RUN_FLAGS = {
        "--external-root",
        "--manifest",
        "--expected-manifest-sha256",
        "--attempt-id",
        "--confirm-role",
        "--job-id",
        "--submitted-runner",
        "--submitted-runner-sha256",
        "--environment-fingerprint",
        "--environment-fingerprint-sha256",
    }

    def test_runner_arguments_are_accepted_by_both_gpu_commands(self) -> None:
        runner_text = RUNNER.read_text(encoding="utf-8")
        for flag in self.RUN_FLAGS:
            self.assertIn(flag, runner_text)
        for command in ("smoke", "run-audit"):
            result = subprocess.run(
                [sys.executable, str(EVALUATOR), command, "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for flag in self.RUN_FLAGS:
                self.assertIn(flag, result.stdout, (command, flag))

    def test_submission_examples_do_not_export_the_caller_environment(self) -> None:
        runner_text = RUNNER.read_text(encoding="utf-8")
        readme_text = RUNNER.with_name("README.md").read_text(encoding="utf-8")
        self.assertNotIn("--export=ALL", runner_text)
        self.assertNotIn("--export=ALL", readme_text)
        self.assertNotIn("--export=NONE,", runner_text)
        self.assertNotIn("--export=NONE,", readme_text)

    def test_upload_bootstrap_is_one_shot_hash_checked_and_no_overwrite(self) -> None:
        readme_text = RUNNER.with_name("README.md").read_text(encoding="utf-8")
        self.assertNotIn(
            'mkdir -p "$HOME/audattn_external_eval/same_bank_2026-08-29/tools"',
            readme_text,
        )
        self.assertNotIn(
            "s2510040@hakusan1:audattn_external_eval/same_bank_2026-08-29/tools/",
            readme_text,
        )
        self.assertIn("dated evaluation root already exists; do not reuse it", readme_text)
        self.assertIn('mkdir "$EVAL_ROOT/.upload-staging"', readme_text)
        self.assertIn(
            'ln "$STAGING/locked_same_bank_eval.py" '
            '"$EVAL_ROOT/tools/locked_same_bank_eval.py"',
            readme_text,
        )
        self.assertIn(
            "221096ef601e63ddc5e0a14833b687c810d36095b2c6bc2d66f380ab90bf0040",
            readme_text,
        )
        self.assertIn(
            "3d35b416b4ece19459742d74e83cb3268d732cf25006c3f539878b5407affa21",
            readme_text,
        )
        for published_tool in (EVALUATOR, RUNNER):
            self.assertIn(
                hashlib.sha256(published_tool.read_bytes()).hexdigest(),
                readme_text,
                f"README upload digest is stale for {published_tool.name}",
            )

if __name__ == "__main__":
    unittest.main(verbosity=2)
