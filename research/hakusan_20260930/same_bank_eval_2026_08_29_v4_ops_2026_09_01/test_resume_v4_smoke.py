from __future__ import annotations

import copy
import json
import multiprocessing
import pathlib
import subprocess
import tempfile
import unittest

import resume_v4_smoke as target


MANIFEST_SHA = "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
PROTOCOL = "fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1"
POLICY = "cross_invocation_path_size_sha_exact__dev_inode_diagnostic"


def hold_journal_lock(state_root: str, connection: object) -> None:
    journal = target.SubmissionJournal(pathlib.Path(state_root))
    with journal.exclusive():
        connection.send("LOCKED")
        connection.recv()


def valid_check_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "filesystem_identity_policy": POLICY,
        "status": "CHECK_PASS",
        "manifest": (
            "/home/s2510040/audattn_external_eval/"
            "same_bank_2026-08-29_v4/input_freeze.json"
        ),
        "manifest_sha256": MANIFEST_SHA,
        "verification": {
            "filesystem_identity_policy": POLICY,
            "fresh_recovery_status": "CHECK_PASS",
            "verified_files": 24,
        },
        "layout": {},
        "strict_loads": {},
        "publications": {},
    }


def encoded_check(
    payload: dict[str, object] | None = None, *, preamble: bool = True
) -> bytes:
    value = valid_check_payload() if payload is None else payload
    prefix = (
        "Using explicit dim specification for demeaning in audio transforms\n"
        "diagnostic containing {not-json}\n"
        if preamble
        else ""
    )
    return (prefix + json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class ParseCheckOutputTests(unittest.TestCase):
    def test_accepts_one_trailing_object_after_realistic_preamble(self) -> None:
        parsed = target.parse_check_output(encoded_check(), MANIFEST_SHA)

        self.assertEqual(parsed["status"], "CHECK_PASS")
        self.assertEqual(parsed["verification"]["verified_files"], 24)

    def test_accepts_one_trailing_object_without_preamble(self) -> None:
        parsed = target.parse_check_output(encoded_check(preamble=False), MANIFEST_SHA)

        self.assertEqual(parsed["protocol_id"], PROTOCOL)

    def test_rejects_empty_truncated_non_object_and_non_utf8_output(self) -> None:
        invalid_values = (
            b"",
            b"diagnostic only\n",
            b'diagnostic\n{"status": "CHECK_PASS"',
            b"[1, 2, 3]\n",
            b"\xff\xfe",
        )

        for raw in invalid_values:
            with self.subTest(raw=raw):
                with self.assertRaises(target.GateError):
                    target.parse_check_output(raw, MANIFEST_SHA)

    def test_rejects_trailing_garbage_and_multiple_top_level_objects(self) -> None:
        one = json.dumps(valid_check_payload(), indent=2, sort_keys=True)
        invalid_values = (
            (one + "\ntrailing text\n").encode(),
            (json.dumps({"diagnostic": True}) + "\n" + one + "\n").encode(),
            ("  " + json.dumps({"diagnostic": True}) + "\n" + one + "\n").encode(),
            (json.dumps({"diagnostic": True}) + "\n]\n" + one + "\n").encode(),
        )

        for raw in invalid_values:
            with self.subTest(raw=raw[:80]):
                with self.assertRaises(target.GateError):
                    target.parse_check_output(raw, MANIFEST_SHA)

    def test_accepts_objects_nested_inside_the_one_final_document(self) -> None:
        payload = valid_check_payload()
        payload["verification"]["diagnostic_objects"] = [
            {"device_match": True},
            {"inode_match": True},
        ]

        parsed = target.parse_check_output(encoded_check(payload), MANIFEST_SHA)

        self.assertEqual(
            parsed["verification"]["diagnostic_objects"],
            [{"device_match": True}, {"inode_match": True}],
        )

    def test_rejects_duplicate_keys_and_nonfinite_numbers(self) -> None:
        duplicate = (
            encoded_check()
            .decode()
            .replace(
                '"status": "CHECK_PASS",',
                '"status": "CHECK_PASS",\n  "status": "CHECK_PASS",',
            )
        )
        nonfinite = encoded_check().decode().replace('"schema_version": 1', '"x": NaN')

        for raw in (duplicate.encode(), nonfinite.encode()):
            with self.subTest(raw=raw[-120:]):
                with self.assertRaises(target.GateError):
                    target.parse_check_output(raw, MANIFEST_SHA)

    def test_rejects_each_mutated_semantic_gate(self) -> None:
        mutations = {
            "status": lambda value: value.__setitem__("status", "AUDIT_PASS"),
            "protocol": lambda value: value.__setitem__("protocol_id", "v3"),
            "top_policy": lambda value: value.__setitem__(
                "filesystem_identity_policy", "wrong"
            ),
            "manifest": lambda value: value.__setitem__("manifest_sha256", "0" * 64),
            "verification": lambda value: value.__setitem__("verification", []),
            "nested_policy": lambda value: value["verification"].__setitem__(
                "filesystem_identity_policy", "wrong"
            ),
            "files_bool": lambda value: value["verification"].__setitem__(
                "verified_files", True
            ),
            "files_count": lambda value: value["verification"].__setitem__(
                "verified_files", 23
            ),
            "recovery": lambda value: value["verification"].__setitem__(
                "fresh_recovery_status", "FAIL"
            ),
        }

        for name, mutate in mutations.items():
            payload = copy.deepcopy(valid_check_payload())
            mutate(payload)
            with self.subTest(name=name):
                with self.assertRaises(target.GateError):
                    target.parse_check_output(encoded_check(payload), MANIFEST_SHA)


class FakeGateway:
    def __init__(self) -> None:
        good = encoded_check()
        self.login = target.CommandOutcome(0, good, b"")
        self.compute = target.CommandOutcome(0, good, b"")
        self.fingerprints = [
            target.Fingerprint("a" * 64, "b" * 64),
            target.Fingerprint("a" * 64, "b" * 64),
        ]
        self.active = target.CommandOutcome(0, b"", b"")
        self.evidence: tuple[str, ...] = ()
        self.submission = target.CommandOutcome(0, b"642999;hakusan\n", b"")
        self.submitted_argv: list[tuple[str, ...]] = []
        self.verify_fail_at: int | None = None
        self.verify_count = 0
        self.state_root: pathlib.Path | None = None
        self.submit_exception: BaseException | None = None

    def verify_trust(self) -> None:
        self.verify_count += 1
        if self.verify_fail_at == self.verify_count:
            raise target.GateError("trust changed")

    def run_login_check(self) -> target.CommandOutcome:
        return self.login

    def fingerprint(self) -> target.Fingerprint:
        return self.fingerprints.pop(0)

    def run_compute_check(self) -> target.CommandOutcome:
        return self.compute

    def query_active_jobs(self) -> target.CommandOutcome:
        return self.active

    def smoke_evidence(self) -> tuple[str, ...]:
        return self.evidence

    def submit_smoke(self, intent_nonce: str) -> target.CommandOutcome:
        self.submitted_argv.append((intent_nonce,))
        if self.state_root is not None:
            intent = json.loads((self.state_root / "intent.json").read_text())
            if intent["intent_nonce"] != intent_nonce:
                raise AssertionError(
                    "submit was called before the matching durable intent"
                )
        if self.submit_exception is not None:
            raise self.submit_exception
        return self.submission


class SmokeWorkflowTests(unittest.TestCase):
    def make_workflow(
        self, gateway: FakeGateway, state_root: pathlib.Path
    ) -> target.SmokeWorkflow:
        return target.SmokeWorkflow(
            gateway=gateway,
            journal=target.SubmissionJournal(state_root),
            expected_manifest_sha256=MANIFEST_SHA,
        )

    def test_happy_path_submits_once_and_persists_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            gateway = FakeGateway()
            workflow = self.make_workflow(gateway, pathlib.Path(raw))

            result = workflow.execute()

            self.assertEqual(result.status, "SMOKE_SUBMITTED")
            self.assertEqual(result.job_id, "642999")
            self.assertEqual(len(gateway.submitted_argv), 1)
            receipt = json.loads((pathlib.Path(raw) / "receipt.json").read_text())
            self.assertEqual(receipt["job_id"], "642999")
            self.assertEqual(receipt["status"], "SMOKE_SUBMITTED")

    def test_completed_receipt_blocks_a_second_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            first_gateway = FakeGateway()
            first = self.make_workflow(first_gateway, state_root).execute()
            second_gateway = FakeGateway()

            second = self.make_workflow(second_gateway, state_root).execute()

            self.assertEqual(first.job_id, "642999")
            self.assertEqual(second.status, "ALREADY_SUBMITTED")
            self.assertEqual(second.job_id, "642999")
            self.assertEqual(second_gateway.submitted_argv, [])

    def test_receipt_without_matching_intent_is_rejected_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            journal = target.SubmissionJournal(state_root)
            journal.begin("c" * 64)
            journal.record_receipt("c" * 64, "642999", "642999;hakusan")
            (state_root / "intent.json").unlink()
            gateway = FakeGateway()

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, state_root).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_mismatched_intent_and_receipt_are_rejected_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            journal = target.SubmissionJournal(state_root)
            journal.begin("c" * 64)
            receipt = {
                "created_utc": "2026-09-01T00:00:00+00:00",
                "intent_nonce": "d" * 64,
                "job_id": "642999",
                "manifest_sha256": MANIFEST_SHA,
                "protocol_id": PROTOCOL,
                "sbatch_stdout": "642999;hakusan",
                "status": "SMOKE_SUBMITTED",
            }
            (state_root / "receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
            )
            gateway = FakeGateway()

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, state_root).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_receipt_job_id_must_match_recorded_sbatch_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            journal = target.SubmissionJournal(state_root)
            journal.begin("c" * 64)
            receipt = {
                "created_utc": "2026-09-01T00:00:00+00:00",
                "intent_nonce": "c" * 64,
                "job_id": "642999",
                "manifest_sha256": MANIFEST_SHA,
                "protocol_id": PROTOCOL,
                "sbatch_stdout": "777777;hakusan",
                "status": "SMOKE_SUBMITTED",
            }
            (state_root / "receipt.json").write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
            )
            gateway = FakeGateway()

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, state_root).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_record_receipt_requires_the_matching_durable_intent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            journal = target.SubmissionJournal(pathlib.Path(raw))
            journal.begin("c" * 64)

            with self.assertRaises(target.GateError):
                journal.record_receipt("d" * 64, "642999", "642999;hakusan")

    def test_unresolved_intent_blocks_all_future_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            target.SubmissionJournal(state_root).begin("c" * 64)
            gateway = FakeGateway()

            with self.assertRaises(target.AmbiguousSubmissionError):
                self.make_workflow(gateway, state_root).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_journal_lock_rejects_a_concurrent_orchestrator(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = target.SubmissionJournal(pathlib.Path(raw))
            second = target.SubmissionJournal(pathlib.Path(raw))

            with first.exclusive():
                with self.assertRaises(target.GateError):
                    with second.exclusive():
                        self.fail("second journal unexpectedly acquired the lock")

    def test_journal_lock_rejects_a_separate_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            process = context.Process(target=hold_journal_lock, args=(raw, child))
            process.start()
            try:
                self.assertEqual(parent.recv(), "LOCKED")
                contender = target.SubmissionJournal(pathlib.Path(raw))
                with self.assertRaises(target.GateError):
                    with contender.exclusive():
                        self.fail("second process unexpectedly shared the journal lock")
            finally:
                parent.send("RELEASE")
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)

    def test_nonzero_check_rc_blocks_submission_even_with_valid_json(self) -> None:
        for phase in ("login", "compute"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as raw:
                gateway = FakeGateway()
                setattr(
                    gateway, phase, target.CommandOutcome(1, encoded_check(), b"failed")
                )

                with self.assertRaises(target.GateError):
                    self.make_workflow(gateway, pathlib.Path(raw)).execute()

                self.assertEqual(gateway.submitted_argv, [])

    def test_empty_compute_stdout_blocks_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            gateway = FakeGateway()
            gateway.compute = target.CommandOutcome(0, b"", b"")

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, pathlib.Path(raw)).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_changed_fingerprint_blocks_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            gateway = FakeGateway()
            gateway.fingerprints[1] = target.Fingerprint("c" * 64, "b" * 64)

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, pathlib.Path(raw)).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_active_job_or_existing_evidence_blocks_submission(self) -> None:
        cases = (
            (b"642998|RUNNING|audattn_samebank_v4\n", ()),
            (b"", ("attempts/smoke/slurm-642998",)),
        )
        for active, evidence in cases:
            with (
                self.subTest(active=active, evidence=evidence),
                tempfile.TemporaryDirectory() as raw,
            ):
                gateway = FakeGateway()
                gateway.active = target.CommandOutcome(0, active, b"")
                gateway.evidence = evidence

                with self.assertRaises(target.GateError):
                    self.make_workflow(gateway, pathlib.Path(raw)).execute()

                self.assertEqual(gateway.submitted_argv, [])

    def test_failed_or_non_utf8_active_job_query_blocks_submission(self) -> None:
        outcomes = (
            target.CommandOutcome(1, b"", b"squeue failed"),
            target.CommandOutcome(0, b"\xff", b""),
        )
        for outcome in outcomes:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as raw:
                gateway = FakeGateway()
                gateway.active = outcome

                with self.assertRaises(target.GateError):
                    self.make_workflow(gateway, pathlib.Path(raw)).execute()

                self.assertEqual(gateway.submitted_argv, [])

    def test_last_moment_trust_change_blocks_submission(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            gateway = FakeGateway()
            gateway.verify_fail_at = 3

            with self.assertRaises(target.GateError):
                self.make_workflow(gateway, pathlib.Path(raw)).execute()

            self.assertEqual(gateway.submitted_argv, [])

    def test_invalid_sbatch_result_leaves_unresolved_intent_and_never_retries(
        self,
    ) -> None:
        invalid_results = (
            target.CommandOutcome(1, b"", b"scheduler error"),
            target.CommandOutcome(0, b"", b""),
            target.CommandOutcome(0, b"not-a-job\n", b""),
            target.CommandOutcome(0, b"642999\n643000\n", b""),
        )
        for outcome in invalid_results:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as raw:
                state_root = pathlib.Path(raw)
                gateway = FakeGateway()
                gateway.submission = outcome

                with self.assertRaises(target.AmbiguousSubmissionError):
                    self.make_workflow(gateway, state_root).execute()

                self.assertEqual(len(gateway.submitted_argv), 1)
                self.assertTrue((state_root / "intent.json").is_file())
                self.assertFalse((state_root / "receipt.json").exists())

                second_gateway = FakeGateway()
                with self.assertRaises(target.AmbiguousSubmissionError):
                    self.make_workflow(second_gateway, state_root).execute()
                self.assertEqual(second_gateway.submitted_argv, [])

    def test_interrupted_sbatch_keeps_intent_and_blocks_retry(self) -> None:
        exceptions = (
            KeyboardInterrupt(),
            subprocess.TimeoutExpired(cmd=("/usr/bin/sbatch",), timeout=120),
        )
        for exception in exceptions:
            with (
                self.subTest(exception=type(exception).__name__),
                tempfile.TemporaryDirectory() as raw,
            ):
                state_root = pathlib.Path(raw)
                gateway = FakeGateway()
                gateway.state_root = state_root
                gateway.submit_exception = exception

                with self.assertRaises(target.AmbiguousSubmissionError):
                    self.make_workflow(gateway, state_root).execute()

                self.assertEqual(len(gateway.submitted_argv), 1)
                self.assertTrue((state_root / "intent.json").is_file())
                self.assertFalse((state_root / "receipt.json").exists())

                second_gateway = FakeGateway()
                with self.assertRaises(target.AmbiguousSubmissionError):
                    self.make_workflow(second_gateway, state_root).execute()
                self.assertEqual(second_gateway.submitted_argv, [])

    def test_receipt_write_failure_keeps_intent_and_blocks_retry(self) -> None:
        class FailingReceiptJournal(target.SubmissionJournal):
            def record_receipt(self, nonce: str, job_id: str, raw_stdout: str) -> None:
                raise OSError("injected receipt write failure")

        with tempfile.TemporaryDirectory() as raw:
            state_root = pathlib.Path(raw)
            gateway = FakeGateway()
            gateway.state_root = state_root
            workflow = target.SmokeWorkflow(
                gateway=gateway,
                journal=FailingReceiptJournal(state_root),
                expected_manifest_sha256=MANIFEST_SHA,
            )

            with self.assertRaises(target.AmbiguousSubmissionError):
                workflow.execute()

            self.assertEqual(len(gateway.submitted_argv), 1)
            self.assertTrue((state_root / "intent.json").is_file())
            self.assertFalse((state_root / "receipt.json").exists())

            second_gateway = FakeGateway()
            with self.assertRaises(target.AmbiguousSubmissionError):
                self.make_workflow(second_gateway, state_root).execute()
            self.assertEqual(second_gateway.submitted_argv, [])


class CommandContractTests(unittest.TestCase):
    def test_reviewed_sbatch_command_has_only_four_frozen_exports(self) -> None:
        contract = target.ReviewedContract.production()

        argv = contract.sbatch_argv("d" * 64)

        self.assertEqual(
            argv,
            (
                "/usr/bin/sbatch",
                "--parsable",
                "--comment=audattn-v4-smoke-resume-dddddddddddd",
                "--export=EVAL_ACTION=smoke,EXTERNAL_ROOT=/home/s2510040/"
                "audattn_external_eval/same_bank_2026-08-29_v4,INPUT_MANIFEST="
                "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/"
                "input_freeze.json,EXPECTED_MANIFEST_SHA256=" + MANIFEST_SHA,
                "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/"
                "tools/run_locked_same_bank_eval.sbatch",
            ),
        )

    def test_srun_client_uses_a_minimal_reviewed_environment(self) -> None:
        contract = target.ReviewedContract.production()

        self.assertEqual(
            contract.scheduler_client_environment(),
            {
                "HOME": "/home/s2510040",
                "LC_ALL": "C",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "USER": "s2510040",
            },
        )

    def test_operations_state_must_be_outside_frozen_root(self) -> None:
        external = pathlib.Path(
            "/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4"
        )
        approved_ops = pathlib.Path(
            "/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01"
        )

        target.validate_operations_location(
            approved_ops / "resume_v4_smoke.py",
            approved_ops,
            external,
        )
        with self.assertRaises(target.GateError):
            target.validate_operations_location(
                external / "resume_v4_smoke.py",
                external,
                external,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
