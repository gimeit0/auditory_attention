"""Local shell mocks and pinned-argument checks; never contact HAKUSAN."""

from pathlib import Path
import shlex
import subprocess


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-submit-once.sh")
ROOT = SCRIPT.resolve().parents[3]
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
freeze = "1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c"
manifest = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-candidate-manifest.sha256"
)
pins = {
    name: digest
    for digest, name in (
        line.split(maxsplit=1) for line in manifest.read_text().splitlines()
    )
}
assert "\nF=" + freeze + "\n" in remote
assert "\nH=" + pins["submit_numeric_diag.py"] + "\n" in remote
assert 'R="$B/same_bank_v4_job646900_2026-09-03_v8"' in remote
assert remote.count('"$P" -I -B "$S" "${ARGS[@]}"') == 1
assert "freeze-inputs" not in remote
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
print("SHELL_SYNTAX_AND_REVIEWED_PINS=PASS")


def shell(code):
    return subprocess.run(
        ["/bin/bash", "-c", "set -euo pipefail\n" + code],
        text=True,
        capture_output=True,
        check=False,
    )


# Exercise the actual evidence guard without filesystem or scheduler access.
gate = remote.split("# Any prior attempt", 1)[1].split("\nexport PYTHONNOUSERSITE", 1)[
    0
]
gate = "# Any prior attempt" + gate
for evidence in ("", "state", "logs", "attempts", "submitted_runners"):
    setup = (
        'R="/mock-diag-v8"\n'
        + 'find() { if [ "$1" = "$R/'
        + evidence
        + '" ]; then printf "%s/EXISTING\\n" "$1"; fi; return 0; }\n'
    )
    result = shell(setup + gate + "\necho GATE_NEXT\n")
    assert result.returncode == (2 if evidence else 0), result
    assert ("GATE_NEXT" in result.stdout) is (not evidence), result
    print("MOCK_EVIDENCE_GATE=" + (evidence or "empty") + ":PASS")
result = shell(
    'R="/mock-diag-v8"\nfind() { return 1; }\n' + gate + "\necho GATE_NEXT\n"
)
assert result.returncode == 1 and "GATE_NEXT" not in result.stdout, result
print("MOCK_EVIDENCE_READ_FAILURE=PASS")

# Run the real export/argument/invocation section with a shell-function submitter.
invoke = "export PYTHONNOUSERSITE=1" + remote.split("export PYTHONNOUSERSITE=1", 1)[1]
expected_args = [
    "-I",
    "-B",
    "/mock-diag-v8/tools/submit_numeric_diag.py",
    "submit",
    "--confirm-action",
    "SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC",
    "--confirm-v4-job-id",
    "646900",
    "--expected-input-freeze-sha256",
    freeze,
]
for code in (0, 2, 3):
    setup = (
        f"F={freeze}\nP=mock_submitter\nS={shlex.quote(expected_args[2])}\n"
        + "mock_submitter() {\n"
        + 'test "$PYTHONNOUSERSITE/$PYTHONDONTWRITEBYTECODE/$PYTHONHASHSEED" = "1/1/0"\n'
        + 'printf "MOCK_INVOKED\\n"\nprintf "ARG=%s\\n" "$@"\n'
        + f"return {code}\n}}\n"
    )
    result = shell(setup + invoke + "\necho SUBMIT_NEXT\n")
    assert result.returncode == code, result
    assert result.stdout.count("MOCK_INVOKED") == 1, result
    args = [line[4:] for line in result.stdout.splitlines() if line.startswith("ARG=")]
    assert args == expected_args, args
    assert ("SUBMIT_NEXT" in result.stdout) is (code == 0), result
    print(f"MOCK_SINGLE_INVOCATION_RC_{code}=PASS")

# Verify the Mac wrapper propagates failure and never retries the SSH call.
for code in (2, 255):
    setup = (
        "uname() { printf 'Darwin\\n'; }; "
        + f"ssh() {{ printf 'MOCK_SSH_ONLY\\n'; return {code}; }}; "
        + "export -f uname ssh; "
    )
    result = subprocess.run(
        ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == code and f"SUBMIT_RC={code}" in result.stdout, result
    assert result.stdout.count("MOCK_SSH_ONLY") == 1, result
    assert "DIAG_V8_SUBMIT_BEGIN" not in result.stdout, result
    assert "Do not rerun this script." in result.stdout, result
    print(f"MOCK_TRANSPORT_RC_{code}=PASS")
print(
    "LIMIT=Local mocks only; no SSH, remote validation, freeze, sbatch or GPU execution"
)
