"""Synthetic disk checkpoints/archives only; no remote or production model."""

import copy
import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


O = load("offline_test", HERE / "offline_review.py")  # noqa: E741 - offline module alias
W = load("offline_fixture_worker", HERE / "sequence_worker.py")


class OfflineTests(unittest.TestCase):
    def setUp(self):
        new_module = load("offline_new_fixture", HERE / "tests/test_layouts.py")
        old_module = load(
            "offline_old_fixture",
            HERE.parent
            / "checkpoint_compare_workflow_20260917/tests/test_review_runs.py",
        )
        self.new = new_module.ReviewTests("test_pinned_core")
        self.new.setUp()
        self.addCleanup(self.new.doCleanups)
        self.old = old_module.ReviewTests("test_pinned_core_load")
        self.old.setUp()
        self.addCleanup(self.old.doCleanups)
        b16, h16 = self.old.archive(batch=16)
        b1, h1 = self.old.archive(batch=1)
        baselines = {"bridge16": (b16.name, h16), "cold1": (b1.name, h1)}
        for target, name, value in (
            (O.S, "BASELINES", baselines),
            (W.S, "BASELINES", baselines),
            (W.S, "BASELINE_ROOT", self.old.fixture.root),
        ):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(W.platform, "node", return_value="synthetic-test-only")
        p.start()
        self.addCleanup(p.stop)
        self.root = self.new.fixture.root
        self.source = self.root / "attempt"
        self.source.mkdir()
        self.release = dict(
            protocol=O.M.PROTOCOL,
            status="EXPLICITLY_APPROVED",
            limits=O.S.LIMITS,
            stages=list(O.S.STAGES),
            nonce="b" * 32,
            baseline_receipts={k: v[1] for k, v in baselines.items()},
            files={n: O.S.sha(O.S.PROJECT / n) for n in O.M.FILES},
            authorization=dict(
                single_held_submission=True,
                conditional_release=True,
                resource_repair=False,
                automatic_retry=False,
                user_approval_record="SYNTHETIC TEST ONLY",
            ),
        )
        self.release_file = self.root / "release.json"
        O.S.write(self.release_file, self.release)
        self.release_sha = O.S.sha(self.release_file)
        self.children = []
        start = dt.datetime(2026, 9, 18, tzinfo=dt.timezone.utc)
        for index, stage in enumerate(O.S.STAGES):
            path, receipt, _ = self.new.archive(
                stage, modify_run=lambda r: r.update(pid=r["pid"] + 100)
            )
            path.rename(self.source / stage)
            pid = O.S.read(self.source / stage / "RUN.json")["pid"]
            for op_index, operation in enumerate(("model", "verify")):
                record = dict(
                    pid=pid if operation == "model" else pid + 10000,
                    started_utc=(
                        start + dt.timedelta(seconds=index * 4 + op_index * 2)
                    ).isoformat(),
                )
                O.S.write(self.source / f"{stage}.{operation}.PROCESS.json", record)
                O.S.write(
                    self.source / f"{stage}.{operation}.EXIT.json",
                    dict(
                        record,
                        rc=0,
                        interrupted=False,
                        ended_utc=(
                            start + dt.timedelta(seconds=index * 4 + op_index * 2 + 1)
                        ).isoformat(),
                    ),
                )
            W.verify(
                SimpleNamespace(
                    parent=self.source, stage=stage, receipt_sha256=receipt
                ),
                {"job_id": "123456"},
            )
            self.children.append(
                dict(
                    stage=stage,
                    model_pid=pid,
                    receipt_sha256=receipt,
                    review_sha256=O.S.sha(self.source / (stage + ".review.json")),
                )
            )
        self.terminal = dict(
            protocol=O.S.PROTOCOL,
            status="EXECUTION_COMPLETE_NOT_QUALIFIED",
            children=self.children,
            provenance=dict(
                job_id="123456",
                contract_sha256=O.M.digest(
                    O.S.wire(O.M.contract(self.release, "123456"))
                ),
            ),
            full_run_authorized=False,
            inventory=O.S.inventory(self.source),
        )
        O.S.write(self.source / "COMPLETE.json", self.terminal)
        self.terminal_sha = O.S.sha(self.source / "COMPLETE.json")
        self.status_file = self.root / "status.json"
        O.S.write(
            self.status_file,
            dict(
                rc=0,
                action="status",
                release_sha256=self.release_sha,
                response=dict(
                    ok=True,
                    result=dict(
                        job_id="123456",
                        accounting=dict(
                            rc=0,
                            stdout="123456|COMPLETED|0:0|00:03:00|synthetic-test-only\n",
                        ),
                    ),
                ),
            ),
        )

    def run_review(self, **changes):
        arguments = dict(
            source=self.source,
            terminal_sha=self.terminal_sha,
            release_file=self.release_file,
            release_sha=self.release_sha,
            job="123456",
            baseline_root=self.old.fixture.root,
            status_file=self.status_file,
            status_sha=O.S.sha(self.status_file),
            output=self.root / "review",
        )
        arguments.update(changes)
        return O.recompute(**arguments)

    def test_full_offline_recompute_seven_pairs_987_rows(self):
        before = O.S.inventory(self.source)
        result = self.run_review()
        self.assertEqual(len(result["comparisons"]), 7)
        self.assertEqual(result["paired_rows"], 987)
        self.assertFalse(result["full_run_authorized"])
        self.assertEqual(O.S.inventory(self.source), before)
        self.assertEqual(
            len((self.root / "review/paired_nll.csv").read_text().splitlines()), 988
        )

    def test_wrong_external_sha_and_job(self):
        for changes in (
            {"terminal_sha": "a" * 64},
            {"release_sha": "a" * 64},
            {"status_sha": "a" * 64},
            {"job": "999"},
        ):
            with self.assertRaises(ValueError):
                self.run_review(**changes)
        self.assertFalse((self.root / "review").exists())

    def test_damaged_source_rejected(self):
        (self.source / "tail17/results.csv").write_text("tampered")
        with self.assertRaises(ValueError):
            self.run_review()

    def test_failed_accounting_cannot_pass_complete(self):
        record = O.S.read(self.status_file)
        record["response"]["result"]["accounting"]["stdout"] = (
            "123456|FAILED|2:0|00:00:01|synthetic-test-only\n"
        )
        self.status_file.write_bytes(O.S.wire(record))
        with self.assertRaises(ValueError):
            self.run_review()
        self.assertTrue((self.root / "review/REVIEW_FAILED.json").exists())
        self.assertFalse((self.root / "review/REPORT.json").exists())

    def test_existing_output_and_inside_source_rejected(self):
        with self.assertRaises(ValueError):
            self.run_review(output=self.source / "review")
        (self.root / "review").mkdir()
        with self.assertRaises(FileExistsError):
            self.run_review()

    def test_missing_duplicate_stage_rejected(self):
        terminal = copy.deepcopy(self.terminal)
        terminal["children"][-1] = terminal["children"][0]
        with self.assertRaises(ValueError):
            O.compare_all(
                self.source, self.old.fixture.root, terminal, "123456", self.root
            )

    def test_forged_saved_summary_rejected(self):
        path = self.source / "bridge16.review.json"
        changed = O.S.read(path)
        changed["scientific_qualification"] = "PASS"
        path.write_bytes(O.S.wire(changed))
        terminal = copy.deepcopy(self.terminal)
        terminal["children"][0]["review_sha256"] = O.S.sha(path)
        with self.assertRaisesRegex(ValueError, "Saved summary differs"):
            O.compare_all(
                self.source, self.old.fixture.root, terminal, "123456", self.root
            )

    def test_overlapping_process_times_rejected(self):
        path = self.source / "bridge16.verify.PROCESS.json"
        record = O.S.read(path)
        record["started_utc"] = "2026-09-17T00:00:00+00:00"
        path.write_bytes(O.S.wire(record))
        with self.assertRaisesRegex(ValueError, "Processes not sequential"):
            O.compare_all(
                self.source, self.old.fixture.root, self.terminal, "123456", self.root
            )

    def test_failed_terminal_never_numeric_success(self):
        # Synthetic transition for testing only, not a production record rewrite.
        old_marker = self.source / "COMPLETE.json"
        old_marker.rename(self.root / "preserved_complete.json")
        terminal = copy.deepcopy(self.terminal)
        terminal["status"] = "EXECUTION_FAILED"
        terminal["children"] = []
        terminal["inventory"] = O.S.inventory(self.source)
        O.S.write(self.source / "FAILED.json", terminal)
        record = O.S.read(self.status_file)
        record["response"]["result"]["accounting"]["stdout"] = (
            "123456|FAILED|2:0|00:00:01|synthetic-test-only\n"
        )
        self.status_file.write_bytes(O.S.wire(record))
        result = self.run_review(terminal_sha=O.S.sha(self.source / "FAILED.json"))
        self.assertEqual(
            result["status"], "FAILED_RUN_RECORDED_NO_NUMERIC_QUALIFICATION"
        )
        self.assertNotIn("comparisons", result)


if __name__ == "__main__":
    unittest.main()
