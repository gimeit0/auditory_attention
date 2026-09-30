"""Local syntax/API/exit-code checks only; never invoke the real ssh program."""

import ast
from collections import deque
import contextlib
import io
import json
from pathlib import Path
import shlex
import subprocess

import torch


SCRIPT = Path(__file__).with_name("2026-09-09-diagnostic-v8-remote-preflight.sh")
source = SCRIPT.read_text()
remote = source.split("<<'REMOTE'\n", 1)[1].rsplit("\nREMOTE\n", 1)[0]
probe = remote.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]
subprocess.run(["/bin/bash", "-n", str(SCRIPT)], check=True)
subprocess.run(["/bin/bash", "-n"], input=remote, text=True, check=True)
tree = ast.parse(probe)
compile(tree, "<remote-probe-syntax>", "exec")
functions = ast.Module(
    body=[node for node in tree.body if isinstance(node, ast.FunctionDef)],
    type_ignores=[],
)
scope = {"deque": deque, "torch": torch}
exec(compile(functions, "<local-api-only>", "exec"), scope)
values = scope["probe_collections"]()
assert values["shape_dimensions"] == (1, 2, 3)
print("LOCAL_BASH_AND_PYTHON_SYNTAX=PASS")
print("LOCAL_API_PRIMITIVES=" + json.dumps(values))
print("LOCAL_TORCH_VERSION=" + torch.__version__)

# Only execute through the version guard, never set numerical flags locally.
version_guard = ast.Module(body=[], type_ignores=[])
for node in tree.body:
    version_guard.body.append(node)
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "require"
    ):
        break
else:
    raise AssertionError("required version guard missing")
with contextlib.redirect_stdout(io.StringIO()):
    try:
        exec(compile(version_guard, "<version-guard-only>", "exec"), {})
    except SystemExit as error:
        assert torch.__version__ != "2.1.1+cu118"
        assert str(error) == "STOP: attn torch version is unexpected"
    else:
        assert torch.__version__ == "2.1.1+cu118"
print("VERSION_GATE=PASS")

for name, setup, expected_rc, expect_ssh in (
    (
        "transport_failure",
        "uname() { printf 'Darwin\\n'; }; "
        "ssh() { printf 'MOCK_SSH_ONLY\\n'; return 63; }; "
        "export -f uname ssh; ",
        63,
        True,
    ),
    (
        "wrong_local_os",
        "uname() { printf 'Linux\\n'; }; "
        "ssh() { printf 'MOCK_SSH_ONLY\\n'; return 99; }; "
        "export -f uname ssh; ",
        1,
        False,
    ),
):
    result = subprocess.run(
        ["/bin/bash", "-c", setup + "/bin/bash " + shlex.quote(str(SCRIPT))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc, (name, result)
    assert f"PREFLIGHT_RC={expected_rc}" in result.stdout, (name, result)
    assert ("MOCK_SSH_ONLY" in result.stdout) is expect_ssh, (name, result)
    assert "REMOTE_DIAG_V8_PREFLIGHT=PASS" not in result.stdout
    print(f"LOCAL_SHELL_CONTROL_FLOW={name}:PASS")

print("LIMIT=No actual SSH, production torch, model, GPU, or remote preflight tested")
