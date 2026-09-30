"""Release integration tests with real temp files and simulated scheduler only."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("repair_fixture", "test_repair_724808.py")
u = load("release_under_test", "release_724808.py")
r = fixture.r


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.RepairTests(
            methodName="test_archive_replace_verify_end_to_end"
        )
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.install()
        r.update_gpu(self.f.c, self.f.spec, self.f.release, self.f.execute)
        self.c = self.f.c
        self.c.V4 = self.f.root / "science"
        self.c.V4.mkdir()
        self.c.write(self.c.V4 / "input.json", b"synthetic pinned input\n")
        self.c.FIXED_INPUTS = {"input.json": self.c.sha(b"synthetic pinned input\n")}
        amendment = self.c.sha(self.c.read(self.f.root / "state/CONTROL_REPAIR.json"))
        self.p = patch.object(u, "AMENDMENT_SHA", amendment)
        self.p.start()
        self.addCleanup(self.p.stop)
        self.f.calls.clear()

    def execute(self, argv):
        if argv == u.RELEASE_ARGV:
            self.f.calls.append(argv)
            self.f.raw = self.f.raw.replace(
                "Reason=JobHeldUser", "Reason=Priority"
            ).replace("Priority=0", "Priority=10")
            return {"argv": argv, "rc": 0, "stdout": "", "stderr": ""}
        return self.f.execute(argv)

    def release(self, execute=None):
        return u.remote(
            self.c,
            r,
            "release-once",
            self.c.sha((HERE / "release_724808.py").read_bytes()),
            execute or self.execute,
        )

    def count(self):
        return sum(a == u.RELEASE_ARGV for a in self.f.calls)

    def test_release_exactly_once_and_preserves_package(self):
        before = {
            p.name: self.c.sha(self.c.read(p))
            for p in (self.f.root / "tools").iterdir()
        }
        result = self.release()
        self.assertEqual(result["status"], "RELEASED_ONCE")
        self.assertEqual(self.count(), 1)
        self.assertEqual(
            before,
            {
                p.name: self.c.sha(self.c.read(p))
                for p in (self.f.root / "tools").iterdir()
            },
        )
        self.assertFalse(
            any(a == r.UPDATE or a[0].endswith("sbatch") for a in self.f.calls)
        )
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.release()
        self.assertEqual(self.count(), 1)

    def test_timeout_keeps_exclusive_intent_and_no_retry(self):
        def timeout(argv):
            if argv == u.RELEASE_ARGV:
                self.f.calls.append(argv)
                return {"argv": argv, "rc": 124, "stdout": "", "stderr": "timeout"}
            return self.execute(argv)

        with self.assertRaisesRegex(RuntimeError, "Command failed"):
            self.release(timeout)
        with self.assertRaisesRegex(RuntimeError, "already attempted"):
            self.release()
        self.assertEqual(self.count(), 1)
        self.assertTrue((self.f.root / "state/RELEASE_RESPONSE.json").is_file())

    def test_wrong_current_gpu_blocks_release(self):
        self.f.raw = self.f.raw.replace("gres/gpu:nvidia_a100=1", "gres/gpu:h100-20c=1")
        with self.assertRaises(RuntimeError):
            self.release()
        self.assertEqual(self.count(), 0)

    def test_amendment_change_blocks_release(self):
        (self.f.root / "state/CONTROL_REPAIR.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "amendment differs"):
            self.release()
        self.assertEqual(self.count(), 0)

    def test_science_input_change_blocks_release(self):
        (self.c.V4 / "input.json").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "science evidence changed"):
            self.release()
        self.assertEqual(self.count(), 0)

    def test_spool_script_change_blocks_release(self):
        self.f.batch += "# changed\n"
        with self.assertRaisesRegex(RuntimeError, "batch script differs"):
            self.release()
        self.assertEqual(self.count(), 0)

    def test_status_after_release_is_read_only(self):
        self.release()
        self.f.calls.clear()
        result = u.remote(self.c, r, "status", "unused-readonly", self.execute)
        self.assertEqual(result["status"], "READ_ONLY")
        self.assertIn("RELEASE_INTENT.json", result)
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
