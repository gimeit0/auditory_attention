"""Check publish syntax, pinned targets and wrapper exits without real SSH."""

import hashlib
from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-publish.sh")
ROOT = SCRIPT.resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v8"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-candidate-manifest.sha256"
)
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("LOCAL_AND_REMOTE_SHELL_SYNTAX=PASS")

expected_files = (
    "diagnose_batch_invariance.py",
    "numeric_trace.py",
    "submit_numeric_diag.py",
    "run_numeric_diag.sbatch",
)
manifest = {
    name: digest
    for digest, name in (
        line.split(maxsplit=1) for line in MANIFEST.read_text().splitlines()
    )
}
hashes = remote.split("H=(\n", 1)[1].split("\n)", 1)[0].split()
assert hashes == [manifest[name] for name in expected_files]
for name in expected_files:
    assert hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() == manifest[name]
assert "F=(diagnose_batch_invariance.py numeric_trace.py)" in remote
assert "F+=(submit_numeric_diag.py run_numeric_diag.sbatch)" in remote
assert 'R="$B/same_bank_v4_job646900_2026-09-03_v8"' in remote
assert 'S="$R/.upload-staging"' in remote and 'T="$R/tools"' in remote
assert remote.index('echo "DIAG_V8_PUBLISH_PREFLIGHT=PASS"') < remote.index(
    "/usr/bin/ln -T --"
)
assert remote.index('test "$(stat -c %h "$P")" = 2') < remote.index("/usr/bin/unlink")
assert remote.index('rmdir "$S"') < remote.index(
    'echo "REMOTE_DIAG_V8_TOOLS_PUBLISHED=PASS"'
)
print("FOUR_PRODUCTION_PINS_AND_TARGETS=PASS")
print("PUBLICATION_AND_CLEANUP_SOURCE_ORDER=PASS")

for label, operating_system, ssh_rc, expected_rc, expect_ssh in (
    ("wrong_local_os", "Linux", 0, 1, False),
    ("remote_rejection", "Darwin", 2, 2, True),
    ("connection_failure", "Darwin", 255, 255, True),
    ("remote_exit_zero", "Darwin", 0, 0, True),
):
    setup = (
        f"uname() {{ printf '{operating_system}\\n'; }}; "
        f"ssh() {{ printf 'MOCK_SSH_ONLY\\n'; return {ssh_rc}; }}; "
        "export -f uname ssh; "
    )
    result = subprocess.run(
        ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc, (label, result)
    assert f"PUBLISH_RC={expected_rc}" in result.stdout, (label, result)
    assert ("MOCK_SSH_ONLY" in result.stdout) is expect_ssh
    # A mock SSH success is not a real remote publication success.
    assert "REMOTE_DIAG_V8_TOOLS_PUBLISHED=PASS" not in result.stdout
    print(f"LOCAL_MOCK_CONTROL_FLOW={label}:PASS")

print(
    "LIMIT=No SSH, remote filesystem/hash/link/permission test, cleanup or publication performed"
)
