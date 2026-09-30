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
README = pathlib.Path(__file__).with_name("README.md")


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


def readme_compute_json_parser_program() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(
        r"COMPUTE_JSON_PARSER_OUTPUT=\$\(printf '%s\\n' "
        r'"\$COMPUTE_CHECK_JSON" \| "\$PYTHON" -I -c \'\n'
        r"(?P<program>.*?)\n'\)\n[ \t]*COMPUTE_JSON_PARSER_RC=\$\?",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("could not locate README compute JSON parser program")
    return match.group("program")


def readme_bash_block_after(marker: str) -> str:
    text = README.read_text(encoding="utf-8")
    if marker not in text:
        raise AssertionError(f"could not locate README marker: {marker}")
    remainder = text.split(marker, 1)[1]
    match = re.search(r"\n```bash\n(?P<program>.*?)\n```", remainder, flags=re.DOTALL)
    if match is None:
        raise AssertionError(f"could not locate README bash block after: {marker}")
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
    PROTOCOL_ID = "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
    IDENTITY_POLICY = "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"

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
                "protocol_id": self.PROTOCOL_ID,
                "filesystem_identity_policy": self.IDENTITY_POLICY,
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
            self.PROTOCOL_ID,
            self.IDENTITY_POLICY,
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
            self.assertEqual(record["protocol_id"], self.PROTOCOL_ID)
            self.assertEqual(
                record["filesystem_identity_policy"], self.IDENTITY_POLICY
            )

    def test_protocol_and_identity_policy_must_be_independently_bound(self) -> None:
        for field, replacement in (
            ("protocol_id", "unreviewed_protocol"),
            ("filesystem_identity_policy", "unreviewed_identity_policy"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary_directory:
                root = pathlib.Path(temporary_directory)
                arguments, _, _ = self.create_fixture(root)
                manifest = pathlib.Path(arguments[4])
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                payload[field] = replacement
                mutated = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                manifest.write_bytes(mutated)
                arguments[5] = hashlib.sha256(mutated).hexdigest()

                result = subprocess.run(
                    arguments,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0, result.stdout)

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


class ReadmeComputeJsonParserTests(unittest.TestCase):
    PROTOCOL_ID = "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
    IDENTITY_POLICY = "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"

    def run_parser(self, output: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", "-c", readme_compute_json_parser_program()],
            input=output,
            check=False,
            capture_output=True,
            text=True,
        )

    def check_output(self, nested_policy: str) -> str:
        payload = {
            "status": "CHECK_PASS",
            "protocol_id": self.PROTOCOL_ID,
            "filesystem_identity_policy": self.IDENTITY_POLICY,
            "verification": {
                "filesystem_identity_policy": nested_policy,
                "verified_files": 24,
            },
        }
        return "\n".join(
            (
                "Using explicit dim specification for demeaning in audio transforms",
                "Using explicit dim specification for demeaning in audio transforms",
                json.dumps(payload, indent=2, sort_keys=True),
            )
        )

    def test_parser_accepts_model_preamble_before_trailing_json(self) -> None:
        result = self.run_parser(self.check_output(self.IDENTITY_POLICY))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "COMPUTE JSON: CHECK_PASS; verified_files=24",
        )

    def test_parser_rejects_nested_identity_policy_mismatch(self) -> None:
        result = self.run_parser(self.check_output("unreviewed_identity_policy"))

        self.assertNotEqual(result.returncode, 0, result.stdout)


class ReadmeOperationalGateTests(unittest.TestCase):
    def test_failed_compute_prerequisite_does_not_invoke_srun(self) -> None:
        block = readme_bash_block_after("然后提交一个短 compute allocation")
        with tempfile.TemporaryDirectory() as temporary_directory:
            called = pathlib.Path(temporary_directory) / "srun-called"
            prelude = r'''
srun () { printf 'called\n' > "$CALLED_PATH"; return 0; }
COMPUTE_PREREQUISITE_GATE=2
V4_TREE_IDENTITY_BEFORE_RC=0
V4_FILE_CONTENT_BEFORE_RC=0
V4_TREE_IDENTITY_BEFORE=reviewed-tree
V4_FILE_CONTENT_BEFORE=reviewed-content
'''
            result = subprocess.run(
                ["/bin/bash", "-c", prelude + "\n" + block],
                check=False,
                capture_output=True,
                text=True,
                env={"CALLED_PATH": str(called), "HOME": temporary_directory},
            )

            self.assertFalse(called.exists(), (result.stdout, result.stderr))

    def test_active_v4_job_prevents_duplicate_smoke_submission(self) -> None:
        block = readme_bash_block_after("## 6. 提交 smoke")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            for relative in ("logs", "submitted_runners", "state"):
                (root / relative).mkdir()
            called = root / "sbatch-called"
            prelude = r'''
verify_reviewed_static_inputs () { return 0; }
verify_external_root_boundary () { return 0; }
verify_reviewed_manifest () { return 0; }
squeue () { printf '999|RUNNING|audattn_samebank_v4\n'; return 0; }
sbatch () { printf 'called\n' > "$CALLED_PATH"; printf '12345\n'; return 0; }
COMPUTE_ZERO_WRITE_GATE=0
EVAL_ROOT="$TEST_ROOT"
MANIFEST="$TEST_ROOT/input_freeze.json"
EXPECTED_MANIFEST_SHA256=reviewed
RUNNER="$TEST_ROOT/tools/run_locked_same_bank_eval.sbatch"
'''
            result = subprocess.run(
                ["/bin/bash", "-c", prelude + "\n" + block],
                check=False,
                capture_output=True,
                text=True,
                env={
                    "CALLED_PATH": str(called),
                    "HOME": temporary_directory,
                    "TEST_ROOT": str(root),
                    "USER": "review-user",
                },
            )

            self.assertFalse(called.exists(), (result.stdout, result.stderr))

    def test_active_v4_job_prevents_duplicate_audit_submission(self) -> None:
        block = readme_bash_block_after("## 7. 提交完整 10k audit")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = pathlib.Path(temporary_directory)
            (root / "state").mkdir()
            (root / "state" / "SMOKE_PASS.json").write_text(
                "{}\n", encoding="utf-8"
            )
            called = root / "sbatch-called"
            prelude = r'''
verify_reviewed_static_inputs () { return 0; }
verify_external_root_boundary () { return 0; }
verify_reviewed_manifest () { return 0; }
check_only () { return 0; }
squeue () { printf '999|RUNNING|audattn_samebank_v4\n'; return 0; }
sbatch () { printf 'called\n' > "$CALLED_PATH"; printf '12345\n'; return 0; }
EVAL_ROOT="$TEST_ROOT"
MANIFEST="$TEST_ROOT/input_freeze.json"
EXPECTED_MANIFEST_SHA256=reviewed
RUNNER="$TEST_ROOT/tools/run_locked_same_bank_eval.sbatch"
PYTHON=check_only
TOOL=ignored
'''
            result = subprocess.run(
                ["/bin/bash", "-c", prelude + "\n" + block],
                check=False,
                capture_output=True,
                text=True,
                env={
                    "CALLED_PATH": str(called),
                    "HOME": temporary_directory,
                    "TEST_ROOT": str(root),
                    "USER": "review-user",
                },
            )

            self.assertFalse(called.exists(), (result.stdout, result.stderr))

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
        self.assertNotIn("--export=" + "ALL", runner_text)
        self.assertNotIn("--export=" + "ALL", readme_text)
        self.assertNotIn("--export=" + "NONE,", runner_text)
        self.assertNotIn("--export=" + "NONE,", readme_text)

    def test_upload_bootstrap_is_one_shot_hash_checked_and_no_overwrite(self) -> None:
        readme_text = RUNNER.with_name("README.md").read_text(encoding="utf-8")
        expected_evaluator_sha256 = (
            "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
        )
        expected_runner_sha256 = (
            "b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495"
        )
        self.assertNotIn(
            'mkdir -p "$HOME/audattn_external_eval/same_bank_2026-08-29_v4/tools"',
            readme_text,
        )
        self.assertNotIn(
            "s2510040@hakusan1:audattn_external_eval/same_bank_2026-08-29_v4/tools/",
            readme_text,
        )
        self.assertIn("dated evaluation root already exists; do not reuse it", readme_text)
        self.assertIn('mkdir "$EVAL_ROOT/.upload-staging"', readme_text)
        self.assertIn(
            'ln "$STAGING/locked_same_bank_eval.py" '
            '"$EVAL_ROOT/tools/locked_same_bank_eval.py"',
            readme_text,
        )
        self.assertIn(expected_evaluator_sha256, readme_text)
        self.assertIn(expected_runner_sha256, readme_text)
        self.assertEqual(
            hashlib.sha256(EVALUATOR.read_bytes()).hexdigest(),
            expected_evaluator_sha256,
        )
        self.assertEqual(
            hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
            expected_runner_sha256,
        )
        self.assertNotIn("WAIT-" + "FOR-FINAL", readme_text)

    def test_v4_remote_root_and_prior_failure_evidence_boundaries_are_explicit(self) -> None:
        runner_text = RUNNER.read_text(encoding="utf-8")
        readme_text = RUNNER.with_name("README.md").read_text(encoding="utf-8")
        v4_root = "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4"
        self.assertIn(f"#SBATCH --chdir={v4_root}", runner_text)
        self.assertIn(f"#SBATCH --output={v4_root}/logs/%x_%j.log", runner_text)
        self.assertIn("#SBATCH -J audattn_samebank_v4", runner_text)
        self.assertIn(
            'readonly EXPECTED_EXTERNAL_ROOT="$USER_HOME/'
            'audattn_external_eval/same_bank_2026-08-29_v4"',
            runner_text,
        )
        self.assertIn(
            '[ "$EXTERNAL_ROOT" != "$EXPECTED_EXTERNAL_ROOT" ]', runner_text
        )
        self.assertIn("runner 在执行首个外部命令前", readme_text)
        self.assertIn("任何 v1、v2、v3 或其他根", readme_text)
        self.assertNotIn("same_bank_2026-08-29/logs", runner_text)
        self.assertIn("v2 失败根", readme_text)
        self.assertIn("Job `637966`", readme_text)
        self.assertIn("`FAILED 2:0`", readme_text)
        self.assertIn("logs/audattn_samebank_v2_637966.log", readme_text)
        self.assertIn("submitted_runners/637966.environment.json", readme_text)
        self.assertIn("submitted_runners/637966.sbatch", readme_text)
        self.assertIn(
            "f98220239dd61542b557c536d213715a60338b158d1225ae530ed7ca5c5b4683",
            readme_text,
        )
        self.assertIn(
            "3f0687eae80701cb95b222f6e90e3f4213cf340037fad0b0bd12c41da126356b",
            readme_text,
        )
        self.assertIn("禁止删除、retry、覆盖、重新 freeze", readme_text)
        self.assertIn("v1 失败根", readme_text)
        self.assertIn("v3 失败根", readme_text)
        self.assertIn("Job `642803`", readme_text)
        self.assertIn("`FAILED 1:0`", readme_text)
        self.assertIn("attempts/smoke/slurm-642803/", readme_text)
        self.assertIn("SMOKE_PASS.json` 不存在", readme_text)
        self.assertIn(
            "38493aa274bc9f707ab11fb195bcfa9d10dd68cde95f83d47ed1c3744bc0dc15",
            readme_text,
        )
        self.assertIn("same_bank_2026-08-29_v4", readme_text)
        self.assertIn("Locked v4", runner_text)
        for expected in (
            "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1",
            "cross_invocation_path_size_sha_exact__dev_inode_diagnostic",
        ):
            self.assertIn(expected, runner_text)
            self.assertIn(expected, readme_text)
        self.assertIn("SNR_IDENTITY_ATOL_DB = 1e-12", readme_text)
        self.assertIn("secrets.token_hex(32)", readme_text)
        self.assertIn("64 个小写十六进制字符", readme_text)
        self.assertIn("`external_root` 必须精确等于 v4 根", readme_text)
        self.assertIn("mixed_rows=9000", readme_text)
        self.assertIn("clean_rows=1000", readme_text)
        self.assertIn("exact_mismatch_count=56", readme_text)
        self.assertIn("max_abs=8.881784197001252e-16", readme_text)
        self.assertIn("rtol=0", readme_text)
        self.assertIn("atol=1e-12", readme_text)
        self.assertIn("计算节点零写入 `check-only`", readme_text)
        self.assertIn("COMPUTE_CHECK_JSON=$(srun", readme_text)
        self.assertIn("COMPUTE_CHECK_RC=$?", readme_text)
        self.assertIn("COMPUTE_JSON_PARSER_RC=$?", readme_text)
        self.assertIn("V4_TREE_IDENTITY_BEFORE_RC=$?", readme_text)
        self.assertIn("V4_TREE_IDENTITY_AFTER_RC=$?", readme_text)
        self.assertIn("COMPUTE_ZERO_WRITE_GATE=2", readme_text)
        self.assertIn("COMPUTE_ZERO_WRITE_GATE=0", readme_text)
        self.assertIn("%P\\t%y\\t%m\\t%s\\t%T@\\t%D\\t%i\\t%l\\0", readme_text)
        self.assertIn('printf \'%s\\n\' "$COMPUTE_CHECK_JSON"', readme_text)
        self.assertIn("24 条 frozen/current", readme_text)
        self.assertIn('get("verified_files") != 24', readme_text)
        self.assertIn(
            "compute check-only failed or changed the v4 tree", readme_text
        )
        compute_section = readme_text.split(
            "### 5.1 计算节点零写入 `check-only`", 1
        )[1].split("## 6. 提交 smoke", 1)[0]
        self.assertNotIn("|| " + "false", compute_section)
        self.assertIn("明确禁止继续执行第 6 节", compute_section)
        self.assertIn(
            '[ "${COMPUTE_ZERO_WRITE_GATE:-2}" -eq 0 ]', readme_text
        )
        self.assertIn("SMOKE_SUBMISSION_GATE=2", readme_text)
        self.assertIn("if SMOKE_JOB_RAW=$(sbatch --parsable", readme_text)
        self.assertIn(
            "same-session compute gate or smoke submission prerequisites failed",
            readme_text,
        )
        self.assertIn("verify_reviewed_static_inputs", readme_text)
        self.assertIn("verify_reviewed_manifest", readme_text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
