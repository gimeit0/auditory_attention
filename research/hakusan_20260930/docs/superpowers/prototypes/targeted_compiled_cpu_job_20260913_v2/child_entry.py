"""External stack diagnostics around the byte-identical synthetic worker."""
import faulthandler
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("reference", "observed"):
        raise RuntimeError("exact worker mode required")
    mode = sys.argv[1]
    worker = Path(__file__).resolve().parent.parent / "targeted_compiled_lifetime_20260913/worker.py"
    print("CPU_CHILD_START=" + json.dumps({"mode": mode, "pid": os.getpid(),
                                           "unix_time": time.time(), "worker": str(worker)}), flush=True)
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        sys.argv = [str(worker), mode]
        runpy.run_path(str(worker), run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
