"""Local checks of the evidence wrapper; no real remote calls or result claims."""

import json
from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-failure-evidence.sh")
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
freeze = "1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c"
protocol = "formal40_batch_invariance_diag_20260903_v8"
job = "680910"
assert f"\nJ={job}\n" in remote and f"\nF={freeze}\n" in remote
assert (
    "\nH=6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182\n" in remote
)
assert remote.count('"$P" -I -B "$D" "${ARGS[@]}"') == 1
assert "freeze-inputs" not in remote and "--confirm-action" not in remote
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("SHELL_SYNTAX_AND_FIXED_IDENTITIES=PASS")

query = remote.split('--arg protocol "$PROTO" \'\n', 1)[1].split('\n  \' "$T"', 1)[0]
value = {
    "job_id": job,
    "input_freeze_sha256": freeze,
    "diagnostic_protocol": protocol,
    "status": "DIAGNOSTIC_FAILED",
    "primary_error": {"message": "synthetic test error"},
    "post_errors": [],
    "matrix": None,
    "artifact_inventory": {"files": [{"relative_path": "PRECHECK.json"}]},
}
for change in (None, "job_id", "input_freeze_sha256", "diagnostic_protocol", "status"):
    payload = dict(value)
    if change:
        payload[change] = "WRONG"
    result = subprocess.run(
        [
            "/usr/bin/jq",
            "-e",
            "--arg",
            "job",
            job,
            "--arg",
            "freeze",
            freeze,
            "--arg",
            "protocol",
            protocol,
            query,
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
    )
    assert (result.returncode == 0) is (change is None), result
    if change is None:
        summary = json.loads(result.stdout)
        assert summary["primary_error"] == value["primary_error"]
        assert summary["artifact_files"] == ["PRECHECK.json"]
print("MARKER_SUMMARY_AND_FOUR_IDENTITY_REJECTIONS=PASS")

section = (
    "ARGS=(verify-results"
    + remote.split("ARGS=(verify-results", 1)[1].split("# Continue collecting", 1)[0]
)
mock = (
    f"set -euo pipefail\nF={freeze}\nJ={job}\nP=mock_verify\nD=/mock/diagnostic.py\n"
    + 'mock_verify() { printf "ARG=%s\\n" "$@"; return 2; }\n'
)
result = subprocess.run(
    ["/bin/bash", "-c", mock + section],
    text=True,
    capture_output=True,
)
assert result.returncode == 0 and "VERIFY_RC=2" in result.stdout, result
assert "VERIFY_RESULTS_END" in result.stdout, result
actual = [line[4:] for line in result.stdout.splitlines() if line.startswith("ARG=")]
assert actual == [
    "-I",
    "-B",
    "/mock/diagnostic.py",
    "verify-results",
    "--expected-input-freeze-sha256",
    freeze,
    "--job-id",
    job,
], actual
print("VERIFY_FAILURE_PRESERVED_AND_CONTEXT_CONTINUES=PASS")

awk = remote.split('tail -n 120 "$L" | awk \'\n', 1)[1].split("\n  ' || READ_RC", 1)[0]
result = subprocess.run(
    ["/bin/bash", "-c", "set -o pipefail; tail -n 120 | awk " + shlex.quote(awk)],
    input="omitted\n" + "short\n" * 119 + "x" * 3000 + "\n",
    text=True,
    capture_output=True,
)
assert result.returncode == 0 and len(result.stdout.splitlines()) == 120, result
assert "omitted" not in result.stdout and "[DISPLAY_TRUNCATED]" in result.stdout, result
assert result.stdout.splitlines()[-1].startswith("x" * 2400 + " ..."), result
print("BOUNDED_LOG_DISPLAY=PASS")

footer = (
    'if [ "$VERIFY_RC" -ne 0 ]; then'
    + remote.rsplit('if [ "$VERIFY_RC" -ne 0 ]; then', 1)[1]
)
for verify_rc, read_rc in ((2, 0), (2, 1), (0, 1), (0, 0)):
    result = subprocess.run(
        ["/bin/bash", "-c", f"VERIFY_RC={verify_rc}; READ_RC={read_rc}; " + footer],
        text=True,
        capture_output=True,
    )
    assert result.returncode == (verify_rc or read_rc), result
print("FOUR_EXIT_CODE_COMBINATIONS=PASS")
setup = "uname() { printf 'Darwin\\n'; }; ssh() { return 255; }; export -f uname ssh; "
result = subprocess.run(
    ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
    text=True,
    capture_output=True,
)
assert result.returncode == 255 and "EVIDENCE_RC=255" in result.stdout, result
print("MOCK_SSH_FAILURE_PROPAGATION=PASS")
print(
    "LIMIT=Local mocks only; no SSH, real evidence/result verification, edits to remote files or submission"
)
