"""External diagnostics around the unchanged real-registration candidate."""
import faulthandler
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("fixed registration worker; no arguments accepted")
    worker = Path(__file__).resolve().parent.parent / "targeted_real_registration_20260913/probe_cpu.py"
    print("CPU_CHILD_START=" + json.dumps({"mode": "registration", "pid": os.getpid(),
                                          "worker": str(worker)}), flush=True)
    faulthandler.enable()
    faulthandler.dump_traceback_later(120, repeat=True)
    try:
        sys.argv = [str(worker)]
        runpy.run_path(str(worker), run_name="__main__")
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
