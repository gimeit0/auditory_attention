"""Local shell/JSON summary tests. No real SSH, audit or freeze invocation."""

import copy
import json
from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-audit-freeze.sh")
ROOT = SCRIPT.resolve().parents[3]
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("LOCAL_AND_REMOTE_SHELL_SYNTAX=PASS")

manifest_path = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-candidate-manifest.sha256"
)
manifest = {
    name: digest
    for digest, name in (
        line.split(maxsplit=1) for line in manifest_path.read_text().splitlines()
    )
}
names = (
    "diagnose_batch_invariance.py",
    "numeric_trace.py",
    "submit_numeric_diag.py",
    "run_numeric_diag.sbatch",
)
hashes = remote.split("HASHES=(\n", 1)[1].split("\n)", 1)[0].split()
assert hashes == [manifest[name] for name in names]
print("PRODUCTION_PINS=PASS")

protocol = "formal40_batch_invariance_diag_20260903_v8"
root = "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v8"
summary = (
    "summarize ()\n"
    + remote.split("summarize ()\n", 1)[1].split('\necho "DIAG_V8_AUDIT_BEGIN"', 1)[0]
)
prefix = (
    f"set -euo pipefail\nPROTO={shlex.quote(protocol)}\nR={shlex.quote(root)}\n"
    + summary
)
value = {
    "schema_version": 1,
    "status": "AUDIT_PASS",
    "diagnostic_protocol": protocol,
    "roots": {"diagnostic_root": root},
    "trials": list(range(32)),
    "v4": {"status": "V4_MANIFEST_PASS", "pinned_file_count": 24},
}


def check_summary(
    label, payload, status="AUDIT_PASS", *, accepted=False, producer_failure=False
):
    command = "summarize " + shlex.quote(status)
    if producer_failure:
        command = "produce() { /bin/cat; return 2; }; produce | " + command
    result = subprocess.run(
        ["/bin/bash", "-c", prefix + "\n" + command + "\necho SUMMARY_NEXT_REACHED\n"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, (label, result)
    assert ("SUMMARY_NEXT_REACHED" in result.stdout) is accepted, (label, result)
    if producer_failure:
        assert result.returncode == 2, result
    print(f"LOCAL_SUMMARY_CASE={label}:PASS")


check_summary("audit_valid", json.dumps(value), accepted=True)
frozen = copy.deepcopy(value)
frozen["status"] = "INPUTS_FROZEN"
check_summary("freeze_valid", json.dumps(frozen), "INPUTS_FROZEN", accepted=True)
for label, payload in (
    ("empty", ""),
    ("multiple_documents", json.dumps(value) + "\n" + json.dumps(value)),
    ("stdout_noise", "WARNING: stdout contaminated\n" + json.dumps(value)),
    ("null", "null"),
    ("array", "[]"),
):
    check_summary(label, payload)

for field, replacement in (
    ("schema_version", 2),
    ("status", "ERROR"),
    ("diagnostic_protocol", "formal40_batch_invariance_diag_20260903_v7"),
    ("roots", {"diagnostic_root": root + "_wrong"}),
    ("trials", list(range(31))),
    ("trials", "32"),
    ("v4", {"status": "V4_MANIFEST_PASS", "pinned_file_count": 25}),
    ("v4", {"status": "ERROR", "pinned_file_count": 24}),
):
    invalid = copy.deepcopy(value)
    invalid[field] = replacement
    check_summary("bad_" + field, json.dumps(invalid))
check_summary(
    "producer_failed_with_valid_json", json.dumps(value), producer_failure=True
)

setup = "uname() { printf 'Darwin\\n'; }; ssh() { printf 'MOCK_SSH_ONLY\\n'; return 255; }; export -f uname ssh; "
result = subprocess.run(
    ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
    text=True,
    capture_output=True,
    check=False,
)
assert result.returncode == 255 and "AUDIT_FREEZE_RC=255" in result.stdout, result
assert "MOCK_SSH_ONLY" in result.stdout
assert "DIAG_V8_FREEZE=PASS" not in result.stdout
print("LOCAL_TRANSPORT_FAILURE_PROPAGATION=PASS")
print(
    "LIMIT=No real SSH, production input audit, filesystem validation or freeze tested"
)
