"""Resolve the job-bound contract after a separately approved held release."""

import importlib.util
import os
from pathlib import Path
import sys


def main():
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "p05b_launch_control", here / "control.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.S.require(
        len(sys.argv) == 2 and sys.platform == "linux", "Native release digest required"
    )
    path, digest = module.launch_contract(
        sys.argv[1], os.environ.get("SLURM_JOB_ID", "")
    )
    os.execv(
        module.S.PYTHON,
        [
            module.S.PYTHON,
            "-I",
            "-B",
            "-u",
            str(here / "sequence.py"),
            "run",
            "--contract",
            str(path),
            "--contract-sha256",
            digest,
        ],
    )


if __name__ == "__main__":
    main()
