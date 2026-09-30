"""Transport tests with fake SSH responses and temporary approvals only."""

import copy
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p05b_ship_tests", HERE / "ship.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)


class ShipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / "frozen"
        self.auth = dict(
            status="USER_APPROVED_P05B",
            limits=T.M.S.LIMITS,
            stages=list(T.M.S.STAGES),
            authorization=dict(
                single_held_submission=True,
                conditional_release=True,
                resource_repair=False,
                automatic_retry=False,
                user_approval_record="SYNTHETIC TEST ONLY",
            ),
        )
        self.auth_path = self.root / "approval.json"
        self.auth_path.write_bytes(T.M.S.wire(self.auth))
        self.auth_sha = T.M.S.sha(self.auth_path)
        self.sha = T.freeze(self.folder, self.auth_path, self.auth_sha)[
            "release_sha256"
        ]
        self.calls = []

    def fake(self, argv, **kwargs):
        self.calls.append(argv)
        if "-O" in argv:
            return SimpleNamespace(returncode=0)
        kwargs["stdout"].write(
            b'P05B_RESULT={"ok":true,"result":{"status":"SYNTHETIC"}}\n'
        )
        return SimpleNamespace(returncode=0)

    def socket(self):
        original = Path.lstat

        def fake(path, *args, **kwargs):
            if path == T.ROOT / ".hakusan-control/master.sock":
                return SimpleNamespace(
                    st_mode=stat.S_IFSOCK | 0o600, st_uid=T.os.getuid()
                )
            return original(path, *args, **kwargs)

        return patch.object(Path, "lstat", fake)

    def test_local_freeze_no_remote_and_exact_sources(self):
        raw, files = T.package(self.folder, self.sha)
        self.assertEqual(set(files), T.M.FILES)
        self.assertEqual(T.M.digest(raw), self.sha)
        self.assertFalse(self.calls)
        with self.assertRaises(FileExistsError):
            T.freeze(self.folder, self.auth_path, self.auth_sha)

    def test_approval_hash_and_scope_fail_closed(self):
        with self.assertRaises(ValueError):
            T.freeze(self.root / "bad", self.auth_path, "a" * 64)
        wrong = copy.deepcopy(self.auth)
        wrong["status"] = "CONTINUE"
        self.auth_path.write_bytes(T.M.S.wire(wrong))
        with self.assertRaises(ValueError):
            T.freeze(self.root / "bad", self.auth_path, T.M.S.sha(self.auth_path))

    def test_package_changed_rejected(self):
        (self.folder / "package" / T.M.PREFIX / "control.py").write_text("tampered")
        with self.assertRaises(ValueError):
            T.package(self.folder, self.sha)

    def test_request_bound_and_compiles(self):
        raw, files = T.package(self.folder, self.sha)
        payload = T.request("status", raw, files, self.sha)
        compile(payload, "<bootstrap>", "exec")
        self.assertIn(b"status", payload)
        with self.assertRaises(ValueError):
            T.request("retry", raw, files, self.sha)

    def test_status_repeat_allowed_without_mutation_intent(self):
        with self.socket():
            for _ in range(2):
                self.assertEqual(
                    T.act(self.folder, "status", self.sha, execute=self.fake)["result"][
                        "status"
                    ],
                    "SYNTHETIC",
                )
        self.assertFalse(list(self.folder.glob("LOCAL_*_INTENT.json")))
        self.assertEqual(len(self.calls), 4)
        self.assertIn("ProxyCommand=false", self.calls[-1])

    def test_submit_transport_never_repeated(self):
        with self.socket():
            T.act(self.folder, "submit", self.sha, execute=self.fake)
            with self.assertRaises(FileExistsError):
                T.act(self.folder, "submit", self.sha, execute=self.fake)
        self.assertEqual(sum("-O" not in a for a in self.calls), 1)

    def test_timeout_keeps_intent_and_evidence(self):
        def timeout(argv, **kwargs):
            if "-O" in argv:
                return self.fake(argv, **kwargs)
            self.calls.append(argv)
            raise subprocess.TimeoutExpired(argv, 240)

        with self.socket():
            with self.assertRaises(ValueError):
                T.act(self.folder, "release", self.sha, execute=timeout)
            with self.assertRaises(FileExistsError):
                T.act(self.folder, "release", self.sha, execute=self.fake)
        result = json.loads(next(self.folder.glob("release-*/RESULT.json")).read_text())
        self.assertEqual(result["rc"], 124)
        self.assertEqual(sum("-O" not in a for a in self.calls), 1)

    def test_missing_duplicate_response_rejected(self):
        for stdout in (b"", b"P05B_RESULT={}\nP05B_RESULT={}\n"):
            with self.assertRaises(ValueError):
                T.result_from(stdout)

    def test_lost_submission_status_is_readonly(self):
        # Use an actual published synthetic tree, but never a real scheduler.
        remote = self.root / "remote"
        raw, files = T.package(self.folder, self.sha)
        with patch.object(T.M, "ROOT", remote):
            T.M.publish(
                raw,
                self.sha,
                {n: T.base64.b64encode(b).decode() for n, b in files.items()},
            )
            T.M.record(remote / "state/SUBMIT_INTENT.json", {"unknown": True})
            before = T.M.S.inventory(remote)

            def query(argv):
                self.calls.append(argv)
                return dict(argv=argv, rc=0, stdout="", stderr="")

            result = T.M.status(self.sha, query)
            self.assertEqual(result["status"], "SUBMISSION_UNKNOWN_QUERY_ONLY")
            self.assertEqual(T.M.S.inventory(remote), before)
            self.assertTrue(
                all(Path(a[0]).name in ("squeue", "sacct") for a in self.calls)
            )


if __name__ == "__main__":
    unittest.main()
