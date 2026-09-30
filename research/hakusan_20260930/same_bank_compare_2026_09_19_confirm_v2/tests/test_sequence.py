"""Local real-process tests; no SSH, scheduler mutation or production inference."""

import copy
import csv
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load("sequence_under_test", HERE / "sequence.py")
W = load("worker_under_test", HERE / "sequence_worker.py")


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.parent = self.root / "attempt"

    def argv(self, stage, operation):
        if operation == "model":
            code = "import os;print('SYNTHETIC_MODEL_PID='+str(os.getpid()))"
        else:
            code = (
                "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); stage=sys.argv[2];"
                "pid=json.loads((p/(stage+'.model.PROCESS.json')).read_text())['pid'];"
                "r=dict(stage=stage,status='RECOMPUTED_NOT_QUALIFIED',model_pid=pid,"
                "artifact_verified=True,full_run_authorized=False,receipt_sha256='a'*64,"
                f"fixed_configuration_logits_equal=True if stage in {tuple(S.GATED)!r} else None,"
                f"repeat_result_table_canary='PASS' if stage in {tuple(S.GATED)!r} else None);"
                "f=(p/(stage+'.review.json')).open('x');json.dump(r,f);f.close()"
            )
        return [sys.executable, "-I", "-B", "-c", code, str(self.parent), stage]

    def run_sequence(self, argv=None, timeout=10):
        return S.execute_sequence(
            self.parent,
            argv or self.argv,
            {"scope": "SYNTHETIC_CPU_ONLY"},
            timeout=timeout,
        )

    def test_four_models_and_four_verifiers_sequential(self):
        result = self.run_sequence()
        self.assertEqual([r["stage"] for r in result["children"]], list(S.STAGES))
        pids = []
        previous_end = ""
        for stage in S.STAGES:
            for operation in ("model", "verify"):
                process = S.read(self.parent / f"{stage}.{operation}.PROCESS.json")
                exit_record = S.read(self.parent / f"{stage}.{operation}.EXIT.json")
                self.assertGreaterEqual(process["started_utc"], previous_end)
                previous_end = exit_record["ended_utc"]
                pids.append(process["pid"])
                self.assertEqual(exit_record["rc"], 0)
        self.assertEqual(len(set(pids)), 2 * len(S.STAGES))
        self.assertNotIn(os.getpid(), pids)
        self.assertFalse(result["full_run_authorized"])

    def test_model_failure_stops_before_verifier_or_next_model(self):
        def argv(stage, op):
            return [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"]

        with self.assertRaisesRegex(ValueError, "rc=7"):
            self.run_sequence(argv)
        self.assertFalse((self.parent / f"{S.STAGES[0]}.verify.INTENT.json").exists())
        self.assertFalse((self.parent / f"{S.STAGES[1]}.model.INTENT.json").exists())
        self.assertTrue((self.parent / "FAILED.json").exists())
        self.assertFalse((self.parent / "COMPLETE.json").exists())

    def test_verifier_failure_stops_next_model(self):
        def argv(stage, op):
            return (
                self.argv(stage, op)
                if op == "model"
                else [sys.executable, "-c", "raise SystemExit(9)"]
            )

        with self.assertRaisesRegex(ValueError, "rc=9"):
            self.run_sequence(argv)
        self.assertFalse((self.parent / f"{S.STAGES[1]}.model.INTENT.json").exists())

    def test_repeat_diff_is_durable_and_blocks_next_stage(self):
        def argv(stage, op):
            result = self.argv(stage, op)
            if op == "verify":
                result[4] = result[4].replace("logits_equal=True", "logits_equal=False")
            return result

        with self.assertRaisesRegex(ValueError, "repeat differs"):
            self.run_sequence(argv)
        self.assertFalse(
            S.read(self.parent / "bridge16.review.json")[
                "fixed_configuration_logits_equal"
            ]
        )
        self.assertFalse((self.parent / f"{S.STAGES[1]}.model.INTENT.json").exists())

    def test_missing_review_is_not_success(self):
        with self.assertRaises(FileNotFoundError):
            self.run_sequence(lambda stage, op: [sys.executable, "-c", "pass"])
        self.assertTrue((self.parent / "FAILED.json").exists())

    def test_wrong_model_pid_is_rejected(self):
        def argv(stage, op):
            result = self.argv(stage, op)
            if op == "verify":
                result[4] = result[4].replace("model_pid=pid", "model_pid=1")
            return result

        with self.assertRaisesRegex(ValueError, "PID"):
            self.run_sequence(argv)

    def test_repeat_is_rejected_before_spawn(self):
        self.run_sequence()
        with patch.object(S.subprocess, "Popen") as spawn:
            with self.assertRaises(FileExistsError):
                self.run_sequence()
            spawn.assert_not_called()

    def test_timeout_kills_model_and_preserves_exit(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_sequence(
                lambda stage, op: [sys.executable, "-c", "import time;time.sleep(5)"],
                timeout=0.08,
            )
        record = S.read(self.parent / "bridge16.model.EXIT.json")
        self.assertTrue(record["interrupted"])
        with self.assertRaises(ProcessLookupError):
            os.kill(record["pid"], 0)
        self.assertFalse((self.parent / f"{S.STAGES[1]}.model.INTENT.json").exists())

    def test_timeout_includes_verifier(self):
        def argv(stage, op):
            if op == "model":
                return self.argv(stage, op)
            return [sys.executable, "-c", "import time;time.sleep(5)"]

        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_sequence(argv, timeout=0.2)
        record = S.read(self.parent / "bridge16.verify.EXIT.json")
        self.assertTrue(record["interrupted"])
        self.assertFalse((self.parent / f"{S.STAGES[1]}.model.INTENT.json").exists())

    def test_total_budget_is_not_reset_for_each_child(self):
        def argv(stage, op):
            command = self.argv(stage, op)
            command[4] = "import time;time.sleep(0.06);" + command[4]
            return command

        with self.assertRaises((TimeoutError, subprocess.TimeoutExpired)):
            self.run_sequence(argv, timeout=0.3)
        self.assertFalse((self.parent / f"{S.STAGES[-1]}.model.INTENT.json").exists())

    def test_interrupt_kills_owned_child_and_restores_handler(self):
        before = signal.getsignal(signal.SIGTERM)
        code = (
            "import os,signal,time;os.kill(os.getppid(),signal.SIGTERM);time.sleep(5)"
        )
        with self.assertRaises(InterruptedError):
            self.run_sequence(lambda stage, op: [sys.executable, "-c", code])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
        record = S.read(self.parent / "bridge16.model.EXIT.json")
        with self.assertRaises(ProcessLookupError):
            os.kill(record["pid"], 0)

    def test_invalid_budget_rejected_before_writes(self):
        for value in (0, -1, float("nan"), float("inf"), 1800, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_sequence(timeout=value)
        self.assertFalse(self.parent.exists())

    def test_spawn_failure_preserved(self):
        with self.assertRaises(FileNotFoundError):
            self.run_sequence(lambda stage, op: [str(self.root / "nonexistent")])
        self.assertEqual(
            S.read(self.parent / "FAILED.json")["error_type"], "FileNotFoundError"
        )

    def test_collect_hashes_and_no_source_mutation(self):
        self.run_sequence()
        before = S.inventory(self.parent)
        target = self.root / "collection"
        result = S.collect(self.parent, S.sha(self.parent / "COMPLETE.json"), target)
        self.assertEqual(result["status"], "COLLECTED_NOT_QUALIFIED")
        self.assertEqual(before, S.inventory(self.parent))
        self.assertEqual(before, S.inventory(target / "archive"))

    def test_failed_attempt_can_be_collected_not_relabelled_success(self):
        with self.assertRaises(ValueError):
            self.run_sequence(lambda *a: [sys.executable, "-c", "raise SystemExit(2)"])
        result = S.collect(
            self.parent, S.sha(self.parent / "FAILED.json"), self.root / "failed-copy"
        )
        self.assertEqual(result["terminal_status"], "EXECUTION_FAILED")
        self.assertFalse(result["full_run_authorized"])

    def test_collection_rejects_wrong_hash_and_existing_destination(self):
        self.run_sequence()
        with self.assertRaisesRegex(ValueError, "terminal SHA"):
            S.collect(self.parent, "0" * 64, self.root / "new")
        self.assertFalse((self.root / "new").exists())
        with self.assertRaises(FileExistsError):
            S.collect(self.parent, S.sha(self.parent / "COMPLETE.json"), self.root)

    def test_modified_extra_and_symlink_artifacts_rejected(self):
        self.run_sequence()
        digest = S.sha(self.parent / "COMPLETE.json")
        file = self.parent / "bridge16.model.stdout.log"
        original = file.read_bytes()
        file.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "inventory"):
            S.collect(self.parent, digest, self.root / "new")
        file.write_bytes(original)
        (self.parent / "extra").write_text("extra")
        with self.assertRaisesRegex(ValueError, "inventory"):
            S.collect(self.parent, digest, self.root / "new")
        (self.parent / "link").symlink_to(file)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            S.collect(self.parent, digest, self.root / "new")

    def test_collect_inside_source_rejected(self):
        self.run_sequence()
        with self.assertRaisesRegex(ValueError, "inside source"):
            S.collect(
                self.parent, S.sha(self.parent / "COMPLETE.json"), self.parent / "copy"
            )


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "contract.json"

    def contract(self):
        return {
            "protocol": S.PROTOCOL,
            "status": "USER_APPROVED_FOR_ALLOCATED_JOB",
            "limits": copy.deepcopy(S.LIMITS),
            "stages": list(S.STAGES),
            "nonce": "a" * 32,
            "job_id": "123456",
            "baseline_receipts": {k: v[1] for k, v in S.BASELINES.items()},
            "files": {n: S.sha(S.PROJECT / n) for n in set(S.PINNED) | S.OWN_FILES},
        }

    def check(self, value):
        # Test-generated approval records are confined to temporary directories.
        self.path.write_bytes(S.wire(value))
        return S.check_contract(self.path, S.sha(self.path))

    def test_contract_binds_all_sources_and_layouts(self):
        c = self.contract()
        self.assertEqual(self.check(c), c)

    def test_unapproved_scope_budget_and_source_rejected(self):
        c = self.contract()
        for mutate in (
            lambda x: x.update(status="DRAFT"),
            lambda x: x["limits"].update(jobs=2),
            lambda x: x["limits"].update(gpus=True),
            lambda x: x["stages"].reverse(),
            lambda x: x["files"].pop(next(iter(S.PINNED))),
            lambda x: x["files"].update({next(iter(S.OWN_FILES)): "0" * 64}),
        ):
            changed = copy.deepcopy(c)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.check(changed)

    def test_run_cannot_start_on_mac(self):
        with patch.object(S.sys, "platform", "darwin"):
            with self.assertRaisesRegex(ValueError, "Native Linux"):
                S.native_context(self.path, "0" * 64)

    def test_allocation_exact_a100_and_limits_required(self):
        common = S.load_module(
            S.PROJECT
            / "checkpoint_compare_workflow_20260917/submission/remote_control.py",
            "test_allocation_common",
        )
        c = self.contract()
        raw = (
            f"JobId=123456 JobName=audattn_eager_p07conf Partition=GPU-1A Account=student "
            f"NumCPUs=8 NumTasks=1 CPUs/Task=8 TimeLimit=00:30:00 JobState=RUNNING Requeue=0 Restarts=0 "
            f"WorkDir={S.REMOTE_ROOT} Command={S.HERE / 'run_layouts.sbatch'} Comment=p07conf-{'a' * 32} "
            "UserId=s2510040(1000) NumNodes=1 "
            "ReqTRES=cpu=8,mem=64G,node=1,gres/gpu=1,gres/gpu:nvidia_a100=1 "
            "AllocTRES=cpu=8,mem=64G,node=1,gres/gpu=1,gres/gpu:nvidia_a100=1"
        )
        S.validate_allocation(common, raw, c)
        for old, new in (
            ("nvidia_a100", "nvidia_h100"),
            ("TimeLimit=00:30:00", "TimeLimit=01:00:00"),
            ("Restarts=0", "Restarts=1"),
            ("cpu=8", "cpu=16"),
            ("JobId=123456", "JobId=654321"),
        ):
            with (
                self.subTest(change=old),
                self.assertRaises((ValueError, RuntimeError)),
            ):
                S.validate_allocation(common, raw.replace(old, new), c)

    def test_worker_gate_preserves_numeric_diff(self):
        report = {
            "status": "NUMERIC_SENSITIVITY_RECORDED",
            "full_run_authorized": False,
            "by_model_condition": {
                f"{m}__{c}": {
                    "logits_bitwise_equal": False,
                    "nll_abs_diff": {"maximum": 3e-3},
                    "logits_abs_diff": {"maximum": 1e-3},
                }
                for m in ("formal40", "author_external", "valbest33")
                for c in ("correct", "shuffled", "silent", "distractor")
            },
            "legacy_v4_result_table_canary_1e_6": {"status": "DIFF"},
        }
        summary = W.summarize_reports("bridge16", 123, "a" * 64, {"repeat": report})
        self.assertFalse(summary["fixed_configuration_logits_equal"])
        with self.assertRaisesRegex(ValueError, "repeat differs"):
            S.check_gate(summary, "bridge16")
        with self.assertRaisesRegex(ValueError, "repeat differs"):
            S.check_gate(
                W.summarize_reports("conf32rep16", 123, "a" * 64, {"vs_conf256": report}),
                "conf32rep16",
            )
        summary = W.summarize_reports(
            "conf32b1", 123, "a" * 64, {"vs_conf256": report, "vs_conf32rep16": report}
        )
        # Envelope exceedance is recorded, never repaired or used to block durably.
        S.check_gate(summary, "conf32b1")
        self.assertFalse(summary["envelope"]["vs_conf256"]["within_envelope"])
        self.assertEqual(len(summary["envelope"]["vs_conf256"]["exceeded"]), 12)
        self.assertFalse(summary["full_run_authorized"])

    def test_incomplete_reports_cannot_vacuously_pass(self):
        with self.assertRaisesRegex(ValueError, "Incomplete comparison"):
            W.summarize_reports("bridge16", 123, "a" * 64, {})
        with self.assertRaisesRegex(ValueError, "Incomplete model"):
            W.summarize_reports(
                "bridge16", 123, "a" * 64, {"repeat": {"by_model_condition": {}}}
            )


class WorkerIntegrationTests(unittest.TestCase):
    """Real synthetic disk-checkpoint/forward/archive/worker-review path, CPU only."""

    def test_all_stage_reviews_and_csv_are_independently_recomputed(self):
        new_fixture = load("sequence_new_fixture", HERE / "tests/test_layouts.py")
        v1_fixture = load(
            "sequence_v1_fixture",
            HERE.parent / "same_bank_compare_2026_09_18_layout_v1/tests/test_layouts.py",
        )
        new = new_fixture.ReviewTests("test_pinned_core")
        new.setUp()
        self.addCleanup(new.doCleanups)
        v1 = v1_fixture.ReviewTests("test_pinned_core")
        v1.setUp()
        self.addCleanup(v1.doCleanups)
        baseline16, sha16, layout16 = v1.archive("bridge16")
        parent = new.fixture.root / "sequence"
        parent.mkdir()
        counts = {"bridge16": 159, "conf256": 0, "conf32rep16": 159, "conf32b1": 318}
        with (
            patch.object(W.S, "BASELINE_ROOT", v1.fixture.root),
            patch.object(W.S, "BASELINES", {"bridge16": (baseline16.name, sha16)}),
            patch.object(W.S, "BASELINE_LAYOUT_SHAS", {"bridge16": layout16}),
            patch.object(W.platform, "node", return_value="synthetic-test-only"),
        ):
            for stage in S.STAGES:
                artifact = new.archive(
                    stage, modify_run=lambda r: r.update(pid=r["pid"] + 100)
                )
                output, digest, _ = artifact
                output.rename(parent / stage)
                pid = S.read(parent / stage / "RUN.json")["pid"]
                S.write(parent / f"{stage}.model.PROCESS.json", {"pid": pid})
                S.write(
                    parent / f"{stage}.model.EXIT.json",
                    {"pid": pid, "rc": 0, "interrupted": False},
                )
                args = SimpleNamespace(
                    parent=parent, stage=stage, receipt_sha256=digest
                )
                W.verify(args, {"job_id": "123456"})
                summary = S.read(parent / f"{stage}.review.json")
                S.check_gate(summary, stage)
                with (parent / f"{stage}.paired_nll.csv").open(newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), counts[stage])
                for row in rows:
                    self.assertAlmostEqual(
                        float(row["diff"]),
                        float(row["left_nll"]) - float(row["right_nll"]),
                    )

    def test_model_command_uses_distinct_scratch_and_fixed_layouts(self):
        with tempfile.TemporaryDirectory() as directory:
            commands = []

            def capture(path, run_name):
                commands.append(list(W.sys.argv))

            with (
                patch.object(W.runpy, "run_path", side_effect=capture),
                patch.object(W.sys, "argv", ["synthetic"]),
            ):
                for stage in S.STAGES:
                    W.model(SimpleNamespace(parent=Path(directory), stage=stage))
            scratch_paths = []
            for stage, command in zip(S.STAGES, commands):
                self.assertEqual(command[command.index("--layout") + 1], stage)
                self.assertEqual(
                    command[command.index("--expected-layout-sha256") + 1],
                    S.LAYOUT_SHAS[stage],
                )
                scratch = command[command.index("--scratch-parent") + 1]
                scratch_paths.append(scratch)
                self.assertFalse(Path(scratch).exists())
            self.assertEqual(len(set(scratch_paths)), len(S.STAGES))


if __name__ == "__main__":
    unittest.main()
