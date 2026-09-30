"""Unit tests for the one-off finalizer-only recovery tool."""

from __future__ import annotations

import copy
import contextlib
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest import mock

import recover_full_completion_2026_08_28 as recovery


def valid_payload() -> dict:
    return {
        "pytorch-lightning_version": "2.1.1",
        "epoch": 40,
        "global_step": 69440,
        "loops": {
            "fit_loop": {
                "epoch_progress": {
                    "total": {
                        "ready": 40,
                        "started": 40,
                        "processed": 40,
                        "completed": 38,
                    },
                    "current": {
                        "ready": 40,
                        "started": 40,
                        "processed": 40,
                        "completed": 40,
                    },
                }
            }
        },
        "audattn_amp_state_v1": {
            "total_optimizer_attempts": 69440,
            "successful_optimizer_steps": 69414,
            "total_overflows": 26,
        },
        "audattn_run_metadata_v1": {
            "run_id": recovery.EXPECTED_RUN_ID,
            "source_semantic_sha256": "a" * 64,
            "config_sha256": "b" * 64,
        },
    }


def valid_audit_result() -> dict:
    payload = valid_payload()
    progress = payload["loops"]["fit_loop"]["epoch_progress"]
    return {
        "status": "CHECK_PASS",
        "run_id": recovery.EXPECTED_RUN_ID,
        "job_id": recovery.EXPECTED_FINAL_JOB_ID,
        "inputs": {
            "project_root": "/project",
            "run_root": f"/project/selftrain/experiments/runs/{recovery.EXPECTED_RUN_ID}",
            "log_dir": "/project/selftrain/hakusan/logs",
            "job_id": recovery.EXPECTED_FINAL_JOB_ID,
        },
        "checkpoint": {
            "lightning_version": "2.1.1",
            "epoch": 40,
            "global_step": 69440,
            "path": "/run/full/checkpoints/formal-final.ckpt",
            "basename": "formal-final.ckpt",
            "size": 753926144,
            "sha256": "c" * 64,
            "epoch_progress": copy.deepcopy(progress),
            "amp": {
                "attempts": 69440,
                "successful": 69414,
                "overflows": 26,
            },
            "run_metadata": copy.deepcopy(
                payload["audattn_run_metadata_v1"]
            ),
        },
        "schedule": copy.deepcopy(recovery.EXPECTED_SCHEDULE),
        "frozen_validators": {
            "run_integrity": {"status": "PASS"},
            "numerics_pass": {"status": "PASS"},
        },
        "sacct": {
            "job_id": recovery.EXPECTED_FINAL_JOB_ID,
            "state": "FAILED",
            "exit_code": "1:0",
        },
        "snapshot": {"manifest_sha256": "d" * 64},
        "state_evidence": {"PILOT4_GO.json": {"sha256": "e" * 64}},
        "lineage": {
            "last_checkpoint_resume_count": 2,
            "logical_completed_epochs": 40,
            "raw_total_completed": 38,
            "summary_evidence": {"count": 40, "epochs": [0, 39]},
            "jobs": {
                "628071": {"log": {"sha256": "f" * 64}}
            },
        },
    }


class PayloadTests(unittest.TestCase):
    def validate(self, payload: dict) -> dict:
        return recovery.validate_checkpoint_payload(
            payload,
            recovery.EXPECTED_RUN_ID,
            "a" * 64,
            "b" * 64,
        )

    def test_exact_known_signature_is_accepted(self) -> None:
        result = self.validate(valid_payload())
        self.assertEqual(result["epoch_progress"]["total"]["completed"], 38)
        self.assertEqual(result["epoch_progress"]["current"]["completed"], 40)

    def test_current_processed_shortfall_is_rejected(self) -> None:
        payload = valid_payload()
        payload["loops"]["fit_loop"]["epoch_progress"]["current"]["processed"] = 39
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)

    def test_current_completed_shortfall_is_rejected(self) -> None:
        payload = valid_payload()
        payload["loops"]["fit_loop"]["epoch_progress"]["current"]["completed"] = 39
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)

    def test_total_processed_shortfall_is_rejected(self) -> None:
        payload = valid_payload()
        payload["loops"]["fit_loop"]["epoch_progress"]["total"]["processed"] = 39
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)

    def test_different_total_completed_is_rejected(self) -> None:
        payload = valid_payload()
        payload["loops"]["fit_loop"]["epoch_progress"]["total"]["completed"] = 39
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)

    def test_amp_mismatch_is_rejected(self) -> None:
        payload = valid_payload()
        payload["audattn_amp_state_v1"]["successful_optimizer_steps"] = 69413
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)

    def test_metadata_mismatch_is_rejected(self) -> None:
        payload = valid_payload()
        payload["audattn_run_metadata_v1"]["run_id"] = "wrong"
        with self.assertRaises(recovery.RecoveryError):
            self.validate(payload)


class AtomicCreateTests(unittest.TestCase):
    def test_atomic_create_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "COMPLETE"
            recovery.atomic_create(path, b"first\n")
            with self.assertRaises(FileExistsError):
                recovery.atomic_create(path, b"second\n")
            self.assertEqual(path.read_bytes(), b"first\n")


class ExistingRunLockTests(unittest.TestCase):
    def test_missing_lock_is_refused_without_creating_anything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / "state"
            state.mkdir()
            before = tuple(state.iterdir())
            with self.assertRaises(recovery.RecoveryError):
                recovery.open_existing_run_lock(
                    state / "run.lock", writable=False
                )
            self.assertEqual(tuple(state.iterdir()), before)

    def test_existing_lock_is_opened_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory) / "state"
            state.mkdir()
            lock = state / "run.lock"
            lock.write_bytes(b"existing-lock\n")
            before = lock.stat()
            before_listing = tuple(state.iterdir())
            with recovery.open_existing_run_lock(lock, writable=False) as handle:
                self.assertEqual(handle.read(), b"existing-lock\n")
            after = lock.stat()
            self.assertEqual(tuple(state.iterdir()), before_listing)
            self.assertEqual(lock.read_bytes(), b"existing-lock\n")
            self.assertEqual(before.st_ino, after.st_ino)
            self.assertEqual(before.st_size, after.st_size)
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
            self.assertEqual(before.st_ctime_ns, after.st_ctime_ns)

    def test_check_only_main_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state = root / "run" / "state"
            state.mkdir(parents=True)
            lock = state / "run.lock"
            lock.write_bytes(b"existing-lock\n")
            args = types.SimpleNamespace(
                run_root=root / "run",
                project_root=root / "project",
                log_dir=None,
                job_id=recovery.EXPECTED_FINAL_JOB_ID,
                check_only=True,
                publish=False,
                confirm_run_id=None,
            )
            audit = valid_audit_result()
            before = lock.stat()
            before_listing = tuple(state.iterdir())
            lock_calls = []
            real_flock = recovery.fcntl.flock

            def record_flock(fd, operation):
                lock_calls.append(operation)
                return real_flock(fd, operation)

            with mock.patch.object(recovery, "parse_args", return_value=args), mock.patch.object(
                recovery, "audit", return_value=audit
            ), mock.patch.object(
                recovery.fcntl, "flock", side_effect=record_flock
            ), contextlib.redirect_stdout(io.StringIO()):
                recovery.main()
            after = lock.stat()
            self.assertEqual(tuple(state.iterdir()), before_listing)
            self.assertEqual(lock.read_bytes(), b"existing-lock\n")
            self.assertEqual(before.st_ino, after.st_ino)
            self.assertEqual(before.st_size, after.st_size)
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
            self.assertEqual(before.st_ctime_ns, after.st_ctime_ns)
            self.assertEqual(
                lock_calls, [recovery.fcntl.LOCK_SH | recovery.fcntl.LOCK_NB]
            )

    def test_publish_main_uses_writable_fd_and_exclusive_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            state = root / "run" / "state"
            state.mkdir(parents=True)
            lock = state / "run.lock"
            lock.write_bytes(b"existing-lock\n")
            args = types.SimpleNamespace(
                run_root=root / "run",
                project_root=root / "project",
                log_dir=None,
                job_id=recovery.EXPECTED_FINAL_JOB_ID,
                check_only=False,
                publish=True,
                confirm_run_id=recovery.EXPECTED_RUN_ID,
            )
            audit = valid_audit_result()
            before = lock.stat()
            open_modes = []
            lock_calls = []
            real_open_lock = recovery.open_existing_run_lock
            real_flock = recovery.fcntl.flock

            def record_open(path, *, writable):
                open_modes.append(writable)
                return real_open_lock(path, writable=writable)

            def record_flock(fd, operation):
                lock_calls.append(operation)
                return real_flock(fd, operation)

            with mock.patch.object(recovery, "parse_args", return_value=args), mock.patch.object(
                recovery, "audit", return_value=audit
            ), mock.patch.object(
                recovery, "publish", return_value={"status": "MOCK_PUBLISHED"}
            ), mock.patch.object(
                recovery, "open_existing_run_lock", side_effect=record_open
            ), mock.patch.object(
                recovery.fcntl, "flock", side_effect=record_flock
            ), contextlib.redirect_stdout(io.StringIO()):
                recovery.main()
            after = lock.stat()
            self.assertEqual(open_modes, [True])
            self.assertEqual(
                lock_calls, [recovery.fcntl.LOCK_EX | recovery.fcntl.LOCK_NB]
            )
            self.assertEqual(lock.read_bytes(), b"existing-lock\n")
            self.assertEqual(before.st_ino, after.st_ino)
            self.assertEqual(before.st_size, after.st_size)
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
            self.assertEqual(before.st_ctime_ns, after.st_ctime_ns)


class SummaryTests(unittest.TestCase):
    @staticmethod
    def logs() -> dict[str, dict]:
        result = {}
        total_overflows = 0
        total_successful = 0
        overflow_epochs = {3, 18, 21, 22, 26, 28, 32, 33, 34, 35, 37}
        for segment in recovery.SEGMENTS:
            summaries = []
            for epoch in segment["epochs"]:
                epoch_overflows = 1 if epoch in overflow_epochs else 0
                total_overflows += epoch_overflows
                epoch_successful = 1736 - epoch_overflows
                total_successful += epoch_successful
                summaries.append(
                    {
                        "epoch": epoch,
                        "epoch_overflows": epoch_overflows,
                        "epoch_attempts": 1736,
                        "epoch_successful": epoch_successful,
                        "total_overflows": total_overflows,
                        "total_attempts": (epoch + 1) * 1736,
                        "total_successful": total_successful,
                    }
                )
            result[str(segment["job_id"])] = {"summaries": summaries}
        # Match this run's exact final total of 26 overflows while preserving
        # the per-epoch arithmetic.
        extra = 26 - total_overflows
        self_final = result["628071"]["summaries"][-1]
        self_final["epoch_overflows"] += extra
        self_final["epoch_successful"] -= extra
        self_final["total_overflows"] += extra
        self_final["total_successful"] -= extra
        return result

    def test_all_forty_epoch_summaries_are_accepted(self) -> None:
        evidence = recovery.validate_summaries(self.logs())
        self.assertEqual(evidence["count"], 40)

    def test_missing_epoch_summary_is_rejected(self) -> None:
        logs = self.logs()
        logs["628071"]["summaries"].pop(0)
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_summaries(logs)


class CompleteSchemaTests(unittest.TestCase):
    def test_complete_payload_preserves_original_field_set(self) -> None:
        audit = {
            "checkpoint": {
                "epoch": 40,
                "global_step": 69440,
                "path": "/run/full/checkpoints/formal-final.ckpt",
                "basename": "formal-final.ckpt",
                "sha256": "c" * 64,
                "amp": {"successful": 69414, "overflows": 26},
            },
            "schedule": recovery.EXPECTED_SCHEDULE,
        }
        payload = recovery.complete_payload(audit, "2026-08-28T00:00:00+00:00")
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "status",
                "run_id",
                "run_phase",
                "job_id",
                "completed_at",
                "checkpoint_epoch",
                "completed_epochs",
                "last_completed_epoch_index",
                "global_step",
                "successful_optimizer_steps",
                "amp_overflows",
                "checkpoint",
                "checkpoint_basename",
                "checkpoint_sha256",
                "schedule",
            },
        )


class SidecarTests(unittest.TestCase):
    def test_exact_sidecar_is_accepted(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        planned, encoded = recovery.validate_recovery_sidecar(
            sidecar, audit, tool
        )
        self.assertEqual(planned, sidecar["planned_complete_payload"])
        self.assertEqual(
            recovery.sha256_bytes(encoded), sidecar["planned_complete_sha256"]
        )

    def test_self_consistent_tampered_payload_is_rejected(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        sidecar["planned_complete_payload"]["status"] = "NOT_COMPLETE"
        sidecar["planned_complete_sha256"] = recovery.sha256_bytes(
            recovery.canonical_json(sidecar["planned_complete_payload"])
        )
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_recovery_sidecar(sidecar, audit, tool)

    def test_changed_audit_evidence_is_rejected(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        changed = copy.deepcopy(audit)
        changed["lineage"]["raw_total_completed"] = 39
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_recovery_sidecar(sidecar, changed, tool)

    def test_changed_frozen_validator_output_is_rejected(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        changed = copy.deepcopy(audit)
        changed["frozen_validators"]["run_integrity"]["extra"] = "changed"
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_recovery_sidecar(sidecar, changed, tool)

    def test_tampered_stored_audit_hash_is_rejected(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        sidecar["audit_sha256"] = "0" * 64
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_recovery_sidecar(sidecar, audit, tool)

    def test_self_consistent_changed_stored_audit_is_rejected(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        sidecar["audit"]["inputs"]["log_dir"] = "/forged/logs"
        sidecar["audit_sha256"] = recovery.sha256_bytes(
            recovery.canonical_json(sidecar["audit"])
        )
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_recovery_sidecar(sidecar, audit, tool)

    def test_sidecar_only_crash_retry_and_existing_complete_are_verified(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            run_root = pathlib.Path(directory)
            state = run_root / "state"
            state.mkdir()
            (state / "COMPLETE_RECOVERY.json").write_bytes(
                recovery.canonical_json(sidecar)
            )
            first = recovery.publish(run_root, audit)
            self.assertEqual(first["status"], "PUBLISHED_FROM_EXISTING_SIDECAR")
            self.assertEqual(
                json.loads((state / "COMPLETE").read_text()),
                sidecar["planned_complete_payload"],
            )
            second = recovery.publish(run_root, audit)
            self.assertEqual(second["status"], "ALREADY_PUBLISHED_AND_VERIFIED")

    def test_changed_audit_cannot_publish_from_existing_sidecar(self) -> None:
        audit = valid_audit_result()
        tool = pathlib.Path(recovery.__file__).resolve()
        sidecar = recovery.build_recovery_sidecar(
            audit, tool, "2026-08-28T12:00:00+00:00"
        )
        changed = copy.deepcopy(audit)
        changed["checkpoint"]["size"] = 123
        with tempfile.TemporaryDirectory() as directory:
            run_root = pathlib.Path(directory)
            state = run_root / "state"
            state.mkdir()
            (state / "COMPLETE_RECOVERY.json").write_bytes(
                recovery.canonical_json(sidecar)
            )
            with self.assertRaises(recovery.RecoveryError):
                recovery.publish(run_root, changed)
            self.assertFalse((state / "COMPLETE").exists())


class FinalLogTests(unittest.TestCase):
    @staticmethod
    def final_lines(checkpoint: pathlib.Path) -> list[str]:
        return [
            (
                "Epoch 39: 100% val_loss_epoch=2.990, val_acc=0.434 "
                "AMP epoch summary: epoch=39, epoch_overflows=0, "
                "epoch_attempts=1736, epoch_successful_steps=1736, "
                "total_overflows=26, total_attempts=69440, "
                "total_successful_steps=69414"
            ),
            recovery.FINAL_STOP_MARKER,
            (
                "Saved explicit final checkpoint: "
                f"{checkpoint.resolve()} "
                "(epoch=40, global_step=69440, fit_max_epochs=40)"
            ),
            recovery.FINAL_TRACEBACK_MARKER,
            recovery.FINAL_VALUE_ERROR_MARKER,
            recovery.FINAL_ERROR_MARKER,
        ]

    def test_exact_final_failure_signature_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            checkpoint = root / "formal-final.ckpt"
            log = root / "final.log"
            log.write_text("\n".join(self.final_lines(checkpoint)) + "\n")
            parsed = recovery.parse_log(
                log, final_job=True, expected_final_checkpoint=checkpoint
            )
            self.assertEqual(parsed["tracebacks"], 1)
            self.assertEqual(parsed["summaries"][0]["epoch"], 39)

    def test_wrong_saved_checkpoint_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            checkpoint = root / "formal-final.ckpt"
            lines = self.final_lines(checkpoint)
            lines[2] = lines[2].replace(str(checkpoint), str(root / "wrong.ckpt"))
            log = root / "final.log"
            log.write_text("\n".join(lines) + "\n")
            with self.assertRaises(recovery.RecoveryError):
                recovery.parse_log(
                    log, final_job=True, expected_final_checkpoint=checkpoint
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
