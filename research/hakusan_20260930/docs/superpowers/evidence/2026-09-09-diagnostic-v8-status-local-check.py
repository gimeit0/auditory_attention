"""Local validation of the read-only status wrapper; no real SSH or scheduler."""

import json
from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-status.sh")
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
freeze = "1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c"
job = "680910"
assert f"\nJ={job}\n" in remote and f"\nF={freeze}\n" in remote
assert remote.count('"$P" -I -B "$S" status') == 1
assert remote.count('/usr/bin/sacct -j "$J"') == 1
assert "freeze-inputs" not in remote and "--confirm-action" not in remote
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("SHELL_SYNTAX_AND_FIXED_JOB_FREEZE=PASS")
function = (
    "validate_identity ()\n"
    + remote.split("validate_identity ()\n", 1)[1].split(
        "\nprintf 'EXPECTED_DIAG_JOB", 1
    )[0]
)
prefix = f"set -euo pipefail\nJ={job}\nF={freeze}\n" + function
base = {"job_id": job, "input_freeze_sha256": freeze, "results_verified": False}
for state in ("PENDING", "RUNNING", "DIAGNOSTIC_COMPLETE", "DIAGNOSTIC_FAILED"):
    value = dict(base, status=state)
    result = subprocess.run(
        ["/bin/bash", "-c", prefix + "\nvalidate_identity"],
        input=json.dumps(value),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result
    print(f"IDENTITY_ACCEPTS_{state}=PASS")
bad_values = [
    dict(base, job_id="680519"),
    dict(base, input_freeze_sha256="0" * 64),
    dict(base, results_verified=True),
    None,
]
payloads = [json.dumps(value) for value in bad_values]
payloads += [
    "",
    json.dumps(base) + "\n" + json.dumps(base),
    "noise\n" + json.dumps(base),
]
for number, payload in enumerate(payloads):
    result = subprocess.run(
        ["/bin/bash", "-c", prefix + "\nvalidate_identity"],
        input=payload,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0, (number, result)
print("IDENTITY_REJECTS_SEVEN_INVALID_PAYLOADS=PASS")

# Exercise the actual query section, replacing the two read-only external calls.
query = "printf 'EXPECTED_DIAG_JOB" + remote.split("printf 'EXPECTED_DIAG_JOB", 1)[1]
query = query.replace("/usr/bin/sacct", "mock_sacct")
for status_rc, accounting_rc in ((0, 0), (3, 0), (0, 1), (3, 1)):
    mocks = (
        "\nP=mock_status\nS=/mock/submit_numeric_diag.py\n"
        + "mock_status() { printf '%s\\n' "
        + shlex.quote(json.dumps(base))
        + f"; return {status_rc}; }}\n"
        + f"mock_sacct() {{ printf 'MOCK_ACCOUNTING\\n'; return {accounting_rc}; }}\n"
    )
    result = subprocess.run(
        ["/bin/bash", "-c", prefix + mocks + query],
        text=True,
        capture_output=True,
    )
    assert result.returncode == (status_rc or accounting_rc), result
    assert f"STATUS_RC={status_rc}" in result.stdout, result
    assert f"ACCOUNTING_RC={accounting_rc}" in result.stdout, result
print("QUERY_ERROR_PROPAGATION_FOUR_CASES=PASS")

setup = "uname() { printf 'Darwin\\n'; }; ssh() { return 255; }; export -f uname ssh; "
result = subprocess.run(
    ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
    text=True,
    capture_output=True,
)
assert result.returncode == 255 and "QUERY_RC=255" in result.stdout, result
print("MOCK_SSH_FAILURE_PROPAGATION=PASS")
print(
    "LIMIT=Local mocks only; no SSH, live status, submission or GPU/result verification"
)
