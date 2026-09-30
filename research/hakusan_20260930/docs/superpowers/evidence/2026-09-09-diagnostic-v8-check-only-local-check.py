"""Local JSON/pipe/exit checks only; no real SSH or production check-only."""

import copy
import json
from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-check-only.sh")
ROOT = SCRIPT.resolve().parents[3]
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("LOCAL_AND_REMOTE_SHELL_SYNTAX=PASS")

freeze = "1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c"
protocol = "formal40_batch_invariance_diag_20260903_v8"
root = "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v8"
assert len(freeze) == 64 and int(freeze, 16) > 0
assert "\nF=" + freeze + "\n" in remote
assert 'ARGS=(check-only --expected-input-freeze-sha256 "$F")' in remote
assert "freeze-inputs" not in remote and "sbatch" not in remote
manifest_file = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-candidate-manifest.sha256"
)
manifest = {
    name: digest
    for digest, name in (
        line.split(maxsplit=1) for line in manifest_file.read_text().splitlines()
    )
}
assert "\nH=" + manifest["diagnose_batch_invariance.py"] + "\n" in remote
print("NEW_USER_FREEZE_AND_CANDIDATE_PIN=PASS")

function = (
    "validate_result ()\n"
    + remote.split("validate_result ()\n", 1)[1].split("\nARGS=(check-only", 1)[0]
)
prefix = (
    f"set -euo pipefail\nPROTO={shlex.quote(protocol)}\nR={shlex.quote(root)}\nF={freeze}\n"
    + function
)
value = {
    "schema_version": 1,
    "status": "CHECK_PASS",
    "diagnostic_protocol": protocol,
    "input_freeze_sha256": freeze,
    "layout": {
        "root": root,
        "directories": ["tools", "logs", "state", "attempts", "submitted_runners"],
    },
}


def check(label, payload, *, accepted=False, producer_failure=False):
    command = "validate_result"
    if producer_failure:
        command = "produce() { /bin/cat; return 2; }; produce | " + command
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            prefix + "\n" + command + "\necho VALIDATION_NEXT_REACHED\n",
        ],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, (label, result)
    assert ("VALIDATION_NEXT_REACHED" in result.stdout) is accepted, (label, result)
    if producer_failure:
        assert result.returncode == 2, result
    print(f"LOCAL_JSON_CASE={label}:PASS")


check("valid_check", json.dumps(value), accepted=True)
for key, replacement in (
    ("schema_version", 2),
    ("status", "INPUTS_FROZEN"),
    ("diagnostic_protocol", "formal40_batch_invariance_diag_20260903_v7"),
    (
        "input_freeze_sha256",
        "6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920",
    ),
    (
        "layout",
        {"root": root + "_wrong", "directories": value["layout"]["directories"]},
    ),
    ("layout", {"root": root, "directories": ["tools", "state"]}),
):
    invalid = copy.deepcopy(value)
    invalid[key] = replacement
    check("bad_" + key, json.dumps(invalid))
for label, payload in (
    ("empty", ""),
    ("double_json", json.dumps(value) + "\n" + json.dumps(value)),
    ("stdout_noise", "warning\n" + json.dumps(value)),
    ("null", "null"),
):
    check(label, payload)
check("producer_failure_with_valid_json", json.dumps(value), producer_failure=True)

setup = "uname() { printf 'Darwin\\n'; }; ssh() { printf 'MOCK_SSH_ONLY\\n'; return 255; }; export -f uname ssh; "
result = subprocess.run(
    ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
    text=True,
    capture_output=True,
    check=False,
)
assert result.returncode == 255 and "CHECK_ONLY_RC=255" in result.stdout, result
assert (
    "MOCK_SSH_ONLY" in result.stdout and "DIAG_V8_CHECK_ONLY=PASS" not in result.stdout
)
print("LOCAL_TRANSPORT_FAILURE_PROPAGATION=PASS")
print("LIMIT=No SSH, filesystem inspection, actual check-only, freeze or submission")
