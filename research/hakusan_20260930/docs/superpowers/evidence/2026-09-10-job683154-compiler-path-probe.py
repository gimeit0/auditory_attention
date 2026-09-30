"""Read-only installed Triton path probe: no model, GPU inference or submission.

Stream into the reviewed HAKUSAN Python with -I -B. Cache locations are temporary;
HOME, installed files, published tools and frozen inputs are never modified.
Only ldconfig's read-only -p operation is allowed, never a cache update.
"""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


PYTHON = Path("/home/s2510040/miniconda3/envs/attn/bin/python")
BUILD = PYTHON.parent.parent / "lib/python3.11/site-packages/triton/common/build.py"
BUILD_SHA = "3503228fd15303fce0ce19a7b2258d9bde34a92bdbb0168480dd25b296725810"
FIXED_PATH = str(PYTHON.parent) + ":/usr/local/bin:/usr/bin:/bin"


def main():
    assert Path(sys.executable).resolve() == PYTHON.resolve()
    assert sys.version_info[:3] == (3, 11, 5)
    assert sys.flags.isolated and sys.dont_write_bytecode
    assert hashlib.sha256(BUILD.read_bytes()).hexdigest() == BUILD_SHA
    signal.alarm(40)
    with tempfile.TemporaryDirectory(prefix="job683154-path-probe-") as temporary:
        os.chmod(temporary, 0o700)
        for name, relative in (
            ("TRITON_CACHE_DIR", "triton"),
            ("TORCHINDUCTOR_CACHE_DIR", "inductor"),
            ("CUDA_CACHE_PATH", "cuda"),
            ("XDG_CACHE_HOME", "cache"),
        ):
            os.environ[name] = str(Path(temporary) / relative)
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        os.environ["PATH"] = FIXED_PATH
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["PYTHONNOUSERSITE"] = "1"

        from triton.common import build

        assert Path(build.__file__).resolve() == BUILD.resolve()
        assert build.libcuda_dirs.cache_info().currsize == 0
        result = {
            "scope": "INSTALLED_TRITON_PATH_ONLY_NO_MODEL_NO_GPU_NO_SUBMISSION",
            "torch_distribution_version": importlib.metadata.version("torch"),
            "triton_distribution_version": importlib.metadata.version("triton"),
            "build_sha256": BUILD_SHA,
            "fixed_path_ldconfig": shutil.which("ldconfig"),
        }
        try:
            build.libcuda_dirs()
        except FileNotFoundError as error:
            result["fixed_path_call"] = {
                "type": type(error).__name__,
                "errno": error.errno,
                "filename": error.filename,
            }
        except Exception as error:
            result["fixed_path_call"] = {"type": type(error).__name__}
        else:
            result["fixed_path_call"] = {"type": "NO_EXCEPTION"}

        # Isolate a read-only executable-availability check from GPU library checks.
        absolute = Path("/usr/sbin/ldconfig")
        absolute_result = {"present": absolute.is_file()}
        if absolute.is_file():
            absolute_result["sha256"] = hashlib.sha256(
                absolute.read_bytes()
            ).hexdigest()
            assert absolute_result["sha256"] == (
                "bfd5df90c7f070feab584435f106f254ffffaa268a04de5b5c3bd61d59c092f3"
            )
            completed = subprocess.run(
                [str(absolute), "-p"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=8,
                check=False,
            )
            absolute_result.update(
                {
                    "returncode": completed.returncode,
                    "stdout_bytes": len(completed.stdout),
                    "stderr_bytes": len(completed.stderr),
                    "mentions_libcuda": b"libcuda.so" in completed.stdout,
                }
            )
        result["absolute_read_only_ldconfig"] = absolute_result
        assert hashlib.sha256(BUILD.read_bytes()).hexdigest() == BUILD_SHA
        print(json.dumps(result, sort_keys=True), flush=True)
    signal.alarm(0)


if __name__ == "__main__":
    main()
