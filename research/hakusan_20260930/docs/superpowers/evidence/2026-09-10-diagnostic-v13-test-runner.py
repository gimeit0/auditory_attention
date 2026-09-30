"""Independent subprocess entrypoints; no merged discovery or remote execution."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v13"


def run(path):
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(path)],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    return path.name, result.returncode, output


def main():
    tests = sorted(PACKAGE.glob("test_*.py"))
    failures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for name, rc, output in pool.map(run, tests):
            print(f"TEST_ENTRY={name} RC={rc}\n{output[-5000:]}", flush=True)
            if rc:
                failures.append(name)
    print(f"ENTRIES={len(tests)} FAILURES={failures}", flush=True)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
