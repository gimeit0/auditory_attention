"""Shell syntax/control flow only; real ssh/scp programs are never called."""

from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-create-upload.sh")
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("LOCAL_AND_REMOTE_SHELL_SYNTAX=PASS")

preflight = SCRIPT.with_name("2026-09-09-diagnostic-v8-remote-preflight.sh").read_text()
expected = preflight.split("HASHES=(\n", 1)[1].split("\n)", 1)[0]
observed = remote.split("HASHES=(\n", 1)[1].split("\n)", 1)[0]
assert expected == observed, "old evidence pins differ from reviewed preflight"
print("OLD_EVIDENCE_PINS_MATCH_PREFLIGHT=PASS")

for label, operating_system, ssh_rc, scp_rc, expected_rc, calls in (
    ("wrong_local_os", "Linux", 0, 0, 1, (False, False)),
    ("create_failure", "Darwin", 2, 0, 2, (True, False)),
    ("scp_failure", "Darwin", 0, 64, 64, (True, True)),
    ("staging_success", "Darwin", 0, 0, 0, (True, True)),
):
    setup = (
        f"uname() {{ printf '{operating_system}\\n'; }}; "
        f"ssh() {{ printf 'MOCK_SSH_ONLY\\n'; return {ssh_rc}; }}; "
        "scp() { printf 'MOCK_SCP_ONLY\\n'; "
        "printf 'MOCK_SCP_ARG=%s\\n' \"$@\"; "
        f"return {scp_rc}; }}; "
        "export -f uname ssh scp; "
    )
    result = subprocess.run(
        ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc, (label, result)
    assert f"UPLOAD_RC={expected_rc}" in result.stdout, (label, result)
    assert ("MOCK_SSH_ONLY" in result.stdout) is calls[0], (label, result)
    assert ("MOCK_SCP_ONLY" in result.stdout) is calls[1], (label, result)
    assert ("DIAG_V8_UPLOAD_TO_STAGING=PASS" in result.stdout) is (expected_rc == 0)
    if calls[1]:
        arguments = [
            line.removeprefix("MOCK_SCP_ARG=")
            for line in result.stdout.splitlines()
            if line.startswith("MOCK_SCP_ARG=")
        ]
        assert arguments == [
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "diagnose_batch_invariance.py",
            "numeric_trace.py",
            "submit_numeric_diag.py",
            "run_numeric_diag.sbatch",
            "s2510040@hakusan1:audattn_external_eval_diag/"
            "same_bank_v4_job646900_2026-09-03_v8/.upload-staging/",
        ], arguments
    print(f"LOCAL_MOCK_CONTROL_FLOW={label}:PASS")

print("LIMIT=No real SSH/SCP, directory creation, upload, publication, or submission")
