"""Local stdlib unit tests; no network, scheduler, torch or real worker."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import coordinator
import remote_ops


class JobToolTests(unittest.TestCase):
    def environment(self):
        return {"SLURM_JOB_ID": "123", "SLURM_CPUS_PER_TASK": "1", "SLURM_NTASKS": "1",
                "SLURM_NNODES": "1", "SLURM_JOB_PARTITION": "TINY", "SLURM_MEM_PER_NODE": "4096",
                "CUDA_VISIBLE_DEVICES": ""}

    def allocation(self):
        return ("JobId=123 Partition=TINY NumCPUs=1 NumNodes=1 NumTasks=1 CPUs/Task=1 "
                "TimeLimit=00:30:00 MinMemoryNode=4G ReqTRES=cpu=1,mem=4G,node=1,billing=1")

    def test_authorized_environment(self):
        coordinator.validate_environment(self.environment())

    def test_no_job_rejected(self):
        env = self.environment()
        del env["SLURM_JOB_ID"]
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_extra_cpu_rejected(self):
        env = self.environment()
        env["SLURM_CPUS_PER_TASK"] = "2"
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_extra_memory_rejected(self):
        env = self.environment()
        env["SLURM_MEM_PER_NODE"] = "8192"
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_gpu_zero_index_still_rejected(self):
        env = self.environment()
        env["SLURM_JOB_GPUS"] = "0"
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_visible_cuda_rejected(self):
        env = self.environment()
        env["CUDA_VISIBLE_DEVICES"] = "0"
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_wrong_partition_rejected(self):
        env = self.environment()
        env["SLURM_JOB_PARTITION"] = "GPU-1A"
        with self.assertRaises(RuntimeError):
            coordinator.validate_environment(env)

    def test_scheduler_allocation_accepted(self):
        self.assertTrue(remote_ops.approved_job(self.allocation()))

    def test_pending_single_node_range_accepted(self):
        self.assertTrue(remote_ops.approved_job(self.allocation().replace("NumNodes=1", "NumNodes=1-1")))

    def test_multiple_nodes_range_rejected(self):
        self.assertFalse(remote_ops.approved_job(self.allocation().replace("NumNodes=1", "NumNodes=1-2")))

    def test_actual_cancelled_job_request_was_within_limits(self):
        import json
        root = Path(__file__).resolve().parents[4]
        path = root / "docs/superpowers/evidence/compiled-cpu-job-20260913-v1/fetch-20260913T044031Z-_lytjl8g/SCHEDULER_ALLOCATION.json"
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "caf190d2cda051e6a5bfb65533273f77d0c1e167e735eab175c12d479f97dfbc")
        self.assertTrue(remote_ops.approved_job(json.loads(raw)["stdout"]))

    def test_scheduler_larger_time_rejected(self):
        self.assertFalse(remote_ops.approved_job(self.allocation().replace("00:30:00", "01:00:00")))

    def test_scheduler_gpu_rejected(self):
        self.assertFalse(remote_ops.approved_job(self.allocation() + ",gres/gpu=1"))

    def test_scheduler_larger_memory_rejected(self):
        self.assertFalse(remote_ops.approved_job(self.allocation().replace("MinMemoryNode=4G", "MinMemoryNode=8G")))

    def test_test_only_is_not_submit(self):
        args = remote_ops.submission_command(Path("/tmp/example"), "a" * 64, "b" * 32, True)
        self.assertIn("--test-only", args)
        self.assertEqual(args.count("sbatch"), 1)
        self.assertEqual(args[-2:], ["a" * 64, "b" * 32])
        self.assertNotIn("--test-only", remote_ops.submission_command(Path("/tmp/example"), "a" * 64, "b" * 32))

    def test_intent_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "intent.json"
            remote_ops.write_new(path, b"original")
            with self.assertRaises(FileExistsError):
                remote_ops.write_new(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"original")

    def test_symlink_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data"
            remote_ops.write_new(path, b"source")
            link = Path(folder) / "link"
            link.symlink_to(path)
            with self.assertRaises(RuntimeError):
                coordinator.checked_read(link, hashlib.sha256(b"source").hexdigest())

    def test_changed_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data"
            remote_ops.write_new(path, b"different")
            with self.assertRaises(RuntimeError):
                coordinator.checked_read(path, hashlib.sha256(b"source").hexdigest())

    def test_runner_limits_and_no_home_override(self):
        raw = (Path(__file__).parent / "run_cpu.sbatch").read_text()
        for flag in ("--partition=TINY", "--cpus-per-task=1", "--ntasks=1", "--mem=4096M", "--time=00:30:00", "--no-requeue"):
            self.assertIn("#SBATCH " + flag, raw)
        self.assertNotIn("#SBATCH --gpus", raw)
        self.assertNotIn("HOME=", raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
