"""One explicitly selected Mac operation, with new private unmodified output log.

Never retries, never loops submissions, never supplies or records an SSH password.
All SSH calls in the selected reviewed scripts use the existing master/BatchMode.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OPERATIONS = (
    "create-upload", "publish", "audit-freeze", "check-only", "submit-once",
    "status", "verify-results", "failure-evidence", "resource-probe",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    args = parser.parse_args()
    script = HERE / f"2026-09-11-diagnostic-v18-{args.operation}.sh"
    if script.is_symlink() or not script.is_file():
        raise SystemExit("STOP: operation script absent or symlink")
    source = script.read_bytes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = HERE / f"v18-operation-{args.operation}-{stamp}"
    root.mkdir(mode=0o700)
    print("OPERATION_LOG_ROOT=" + str(root), flush=True)
    # A timeout is uncertain state; this tool does NOT retry it.
    with (root / "output.log").open("xb") as stream:
        process = subprocess.Popen(
            ["/bin/bash", str(script)], cwd=HERE,
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
        )
        try:
            rc = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            rc = 124
    output = (root / "output.log").read_bytes()
    record = dict(operation=args.operation, returncode=rc,
                  script_sha256=hashlib.sha256(source).hexdigest(),
                  output_sha256=hashlib.sha256(output).hexdigest(),
                  script_unchanged=source == script.read_bytes(),
                  retry_performed=False)
    with (root / "receipt.json").open("x") as stream:
        json.dump(record, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(output.decode("utf-8", errors="replace"), end="", flush=True)
    print("OPERATION_RECEIPT=" + json.dumps(record, sort_keys=True), flush=True)
    if not record["script_unchanged"]:
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
