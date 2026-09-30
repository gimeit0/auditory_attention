"""Offline entry ordering tests; temporary mocks, no actual SSH or model calls."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / (
    "docs/superpowers/evidence/2026-09-12-archive-cpu-connect-run.sh"
)


@unittest.skipUnless(sys.platform == "darwin", "entry is Mac-only")
class ArchiveCpuEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="archive-entry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        evidence = self.root / "docs/superpowers/evidence"
        evidence.mkdir(parents=True)
        self.calls = self.root / "calls"
        self.connect = evidence / "2026-09-10-hakusan-connect.sh"
        self.driver = evidence / "2026-09-11-archive-cpu-check.py"
        self.connect.write_text(
            'printf "connect\\n" >> "$ENTRY_CALLS"\nexit "${ENTRY_CONNECT_RC:-0}"\n'
        )
        self.driver.write_text("# mocked source, never imported\n")
        python = self.root / "fake-python"
        python.write_text(
            '#!/bin/bash\nif [ "${4:-}" = --run ]; then\n'
            'printf "run\\n" >> "$ENTRY_CALLS"\nexit "${ENTRY_RUN_RC:-0}"\n'
            'fi\nprintf "validate\\n" >> "$ENTRY_CALLS"\n'
            'exit "${ENTRY_VALIDATE_RC:-0}"\n'
        )
        ssh = self.root / "fake-ssh"
        ssh.write_text(
            '#!/bin/bash\ntest "$3" = -O && test "$4" = check || exit 99\n'
            'printf "socket-check\\n" >> "$ENTRY_CALLS"\nexit "${ENTRY_SSH_RC:-0}"\n'
        )
        for path in (python, ssh):
            path.chmod(0o700)
        text = SOURCE.read_text()
        replacements = {
            'BASE="/Users/gigi/发表/超算"': f'BASE="{self.root}"',
            'PYTHON="/opt/anaconda3/envs/audattn/bin/python"': f'PYTHON="{python}"',
            "/usr/bin/ssh": str(ssh),
            "601ca2e23d7d4907b39a3b72d601decb012d5eacfa5fecdb6833d1bc291f347a":
                hashlib.sha256(self.connect.read_bytes()).hexdigest(),
            "93eb072c954031db11f9788b2cfc4cfe82f6de86f6598bd6d55e0bffb1a8d2a8":
                hashlib.sha256(self.driver.read_bytes()).hexdigest(),
        }
        for old, new in replacements.items():
            self.assertEqual(text.count(old), 1)
            text = text.replace(old, new)
        self.entry = self.root / "entry.sh"
        self.entry.write_text(text)

    def run_entry(self, args=(), **settings):
        env = {key: value for key, value in os.environ.items() if not key.startswith("ENTRY_")}
        return subprocess.run(
            ["/bin/bash", str(self.entry), *args],
            env={**env, "ENTRY_CALLS": str(self.calls), **settings},
            capture_output=True, text=True, timeout=10,
        )

    def stages(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_default_and_explicit_check_do_not_connect(self):
        for args in ((), ("--check-only",)):
            with self.subTest(args=args):
                before = self.stages()
                result = self.run_entry(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.stages(), before + ["validate"])

    def test_run_connects_then_probes_once(self):
        result = self.run_entry(("--run",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stages(), ["validate", "connect", "socket-check", "run"])
        self.assertIn("ARCHIVE_CPU_PIPELINE_RC=0", result.stdout)

    def test_connection_failure_never_runs_probe(self):
        result = self.run_entry(("--run",), ENTRY_CONNECT_RC="255")
        self.assertEqual(result.returncode, 255)
        self.assertEqual(self.stages(), ["validate", "connect"])

    def test_socket_failure_never_runs_probe(self):
        result = self.run_entry(("--run",), ENTRY_SSH_RC="255")
        self.assertEqual(result.returncode, 255)
        self.assertEqual(self.stages(), ["validate", "connect", "socket-check"])

    def test_probe_failure_preserved_without_retry(self):
        result = self.run_entry(("--run",), ENTRY_RUN_RC="2")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.stages(), ["validate", "connect", "socket-check", "run"])
        self.assertIn("ARCHIVE_CPU_PIPELINE_RC=2", result.stdout)

    def test_bad_payload_never_connects(self):
        result = self.run_entry(("--run",), ENTRY_VALIDATE_RC="2")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.stages(), ["validate"])

    def test_bad_source_hash_never_connects(self):
        self.driver.write_text("# altered\n")
        self.assertNotEqual(self.run_entry(("--run",)).returncode, 0)
        self.assertEqual(self.stages(), [])

    def test_source_symlink_rejected(self):
        target = self.root / "original.py"
        self.driver.rename(target)
        self.driver.symlink_to(target)
        self.assertNotEqual(self.run_entry(("--run",)).returncode, 0)
        self.assertEqual(self.stages(), [])
        self.assertTrue(self.driver.is_symlink())

    def test_unrecognized_or_extra_arguments_never_connect(self):
        for args in (("submit",), ("--run", "--run")):
            with self.subTest(args=args):
                self.assertEqual(self.run_entry(args).returncode, 2)
                self.assertEqual(self.stages(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
