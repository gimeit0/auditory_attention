"""Offline Mac integration tests; all SSH calls use a temporary fake executable."""

import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
)

FAKE_SSH = r"""
import json
import os
from pathlib import Path
import socket
import sys

args = sys.argv[1:]
with open(os.environ["TEST_SSH_CALLS"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
if "-E" in args:
    path = args[args.index("-E") + 1]
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(descriptor, b"debug1: offline mock, not a real SSH connection\n")
    os.close(descriptor)
if "-M" in args:
    rc = int(os.environ.get("TEST_START_RC", "0"))
    if not rc:
        path = args[args.index("-S") + 1]
        connection = socket.socket(socket.AF_UNIX)
        connection.bind(path)
        connection.close()
    raise SystemExit(rc)
if "-O" in args:
    assert args[args.index("-O") + 1] == "check", "must not close the master"
    rc = int(os.environ.get("TEST_CHECK_RC", "0"))
    if not rc:
        print("Master running (pid=12345)", file=sys.stderr)
    raise SystemExit(rc)
assert args[-1] == (
    'set -eu; test "$(id -un)" = s2510040; hostname; '
    'echo HAKUSAN_AUTHENTICATED=PASS'
), "only the read-only identity command is permitted"
rc = int(os.environ.get("TEST_PROBE_RC", "0"))
if not rc:
    print("hakusan1\nHAKUSAN_AUTHENTICATED=PASS")
raise SystemExit(rc)
"""


@unittest.skipUnless(sys.platform == "darwin", "script uses native macOS stat")
class ConnectionScriptTests(unittest.TestCase):
    def setUp(self):
        # Short /tmp path also fits the Unix-domain socket path-length limit.
        self.temp = tempfile.TemporaryDirectory(prefix="hc-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "project"
        self.base.mkdir(mode=0o700)
        self.control = self.base / ".hakusan-control"
        self.socket_path = self.control / "master.sock"
        self.calls_path = self.root / "calls.jsonl"
        fake = self.root / "fake-ssh"
        fake.write_text(f"#!{sys.executable} -I\n" + FAKE_SSH)
        fake.chmod(0o700)
        original = SOURCE.read_text()
        self.assertEqual(original.count('BASE="/Users/gigi/发表/超算"'), 1)
        script = original.replace(
            'BASE="/Users/gigi/发表/超算"', f'BASE="{self.base}"'
        ).replace("/usr/bin/ssh", str(fake))
        self.script = self.root / "connect.sh"
        self.script.write_text(script)
        self.env = os.environ.copy()
        self.env["TEST_SSH_CALLS"] = str(self.calls_path)
        for name in ("TEST_START_RC", "TEST_CHECK_RC", "TEST_PROBE_RC"):
            self.env.pop(name, None)

    def run_script(self, **settings):
        return subprocess.run(
            ["/bin/bash", str(self.script)],
            env={**self.env, **settings},
            capture_output=True,
            text=True,
            timeout=15,
        )

    def calls(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def make_socket(self):
        self.control.mkdir(mode=0o700)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(self.socket_path))
        sock.close()
        return self.socket_path.lstat().st_ino

    def log_dirs(self):
        return list((self.control / "logs").glob("connect-*"))

    def test_new_master_uses_twelve_hours_and_private_background_log(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HAKUSAN_SHARED_CONNECTION=PASS", result.stdout)
        self.assertIn("12 idle hours", result.stdout)
        starts = [call for call in self.calls() if "-M" in call]
        self.assertEqual(len(starts), 1)
        for option in (
            "ControlPersist=43200",
            "ServerAliveInterval=30",
            "ServerAliveCountMax=3",
            "LogLevel=DEBUG1",
        ):
            self.assertIn(option, starts[0])
        self.assertNotIn("ControlPersist=3600", starts[0])
        run_dir = self.log_dirs()[0]
        self.assertEqual(
            {p.name for p in run_dir.iterdir()},
            {"events.log", "master-ssh.log", "check-ssh.log"},
        )
        for directory in (self.control, self.control / "logs", run_dir):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for path in run_dir.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        events = (run_dir / "events.log").read_text()
        self.assertIn("NEW_MASTER_STARTED", events)
        self.assertIn("REMOTE_IDENTITY_PASS", events)
        self.assertIn("SCRIPT_EXIT rc=0", events)

    def test_reuse_preserves_master_and_does_not_claim_new_settings(self):
        inode = self.make_socket()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.socket_path.lstat().st_ino, inode)
        self.assertFalse(any("-M" in call for call in self.calls()))
        self.assertIn("original timeout/log settings still apply", result.stdout)
        self.assertIn("next NEW master", result.stdout)
        self.assertNotIn("MASTER_TRANSPORT_LOG=", result.stdout)
        self.assertFalse((self.log_dirs()[0] / "master-ssh.log").exists())

    def test_each_invocation_preserves_previous_logs(self):
        self.make_socket()
        self.assertEqual(self.run_script().returncode, 0)
        first = self.log_dirs()[0]
        before = {p: p.read_bytes() for p in first.iterdir()}
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(len(self.log_dirs()), 2)
        self.assertEqual(before, {p: p.read_bytes() for p in first.iterdir()})

    def test_stale_socket_stops_without_removal_or_reconnection(self):
        inode = self.make_socket()
        result = self.run_script(TEST_CHECK_RC="255")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.socket_path.lstat().st_ino, inode)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("CONNECTION_CHECK_FAILED_RC=2", result.stderr)
        events = (self.log_dirs()[0] / "events.log").read_text()
        self.assertIn("EXISTING_MASTER_UNAVAILABLE", events)
        self.assertIn("SCRIPT_EXIT rc=2", events)

    def test_auth_failure_preserves_exit_code_and_does_not_retry(self):
        result = self.run_script(TEST_START_RC="255")
        self.assertEqual(result.returncode, 255)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("CONNECTION_CHECK_FAILED_RC=255", result.stderr)
        self.assertNotIn("HAKUSAN_SHARED_CONNECTION=PASS", result.stdout)
        self.assertIn("CONNECTION_LOG_DIRECTORY=", result.stdout)

    def test_failed_remote_probe_does_not_close_existing_master(self):
        inode = self.make_socket()
        result = self.run_script(TEST_PROBE_RC="255")
        self.assertEqual(result.returncode, 255)
        self.assertEqual(self.socket_path.lstat().st_ino, inode)
        self.assertNotIn("HAKUSAN_SHARED_CONNECTION=PASS", result.stdout)
        self.assertFalse(any("-M" in call for call in self.calls()))

    def test_regular_file_at_socket_is_not_overwritten(self):
        self.control.mkdir(mode=0o700)
        self.socket_path.write_text("preserve me")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.socket_path.read_text(), "preserve me")
        self.assertEqual(self.calls(), [])

    def test_socket_symlink_is_not_followed(self):
        self.control.mkdir(mode=0o700)
        target = self.root / "target"
        target.write_text("preserve me")
        self.socket_path.symlink_to(target)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertTrue(self.socket_path.is_symlink())
        self.assertEqual(target.read_text(), "preserve me")
        self.assertEqual(self.calls(), [])

    def test_control_symlink_is_not_followed(self):
        target = self.root / "other"
        target.mkdir(mode=0o700)
        self.control.symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_logs_symlink_is_not_followed(self):
        self.control.mkdir(mode=0o700)
        target = self.root / "other"
        target.mkdir(mode=0o700)
        (self.control / "logs").symlink_to(target, target_is_directory=True)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_nonprivate_logs_directory_is_rejected(self):
        self.control.mkdir(mode=0o700)
        logs = self.control / "logs"
        logs.mkdir(mode=0o700)
        logs.chmod(0o755)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(list(logs.iterdir()), [])
        self.assertEqual(self.calls(), [])

    def test_nonprivate_control_directory_is_rejected(self):
        self.control.mkdir(mode=0o700)
        self.control.chmod(0o755)
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertEqual(list(self.control.iterdir()), [])
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
