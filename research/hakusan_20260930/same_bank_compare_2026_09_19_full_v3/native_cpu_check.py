"""One-shot temporary native CPU regression; no deployment or Slurm submission."""

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "same_bank_compare_2026_09_19_full_v3"

REMOTE = r'''
import base64, hashlib, json, os, pathlib, pwd, signal, subprocess, sys, tempfile
assert sys.version_info[:2] == (3, 11)
if not SELF_TEST:
    assert sys.version.split()[0] == "3.11.5"
    assert pwd.getpwuid(os.getuid()).pw_name == "s2510040"
os.umask(0o077)
os.environ.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
                  OPENBLAS_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
with tempfile.TemporaryDirectory(prefix="p08full-synthetic-cpu-") as temporary:
    root = pathlib.Path(temporary)
    for name, record in FILES.items():
        relative = pathlib.PurePosixPath(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        data = base64.b64decode(record["data"], validate=True)
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    code = ''' + repr('''import json, sys, torch, unittest
from pathlib import Path
assert torch.__version__ == sys.argv[2], torch.__version__
torch.set_num_threads(1)
suite = unittest.TestSuite(unittest.TestLoader().discover(str(Path(sys.argv[1]) / "same_bank_compare_2026_09_19_full_v3" / group)) for group in ("tests", "controller_tests"))
assert suite.countTestCases() == 107, suite.countTestCases()
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert not torch.cuda.is_initialized()
print("NATIVE_CPU_RESULT=" + json.dumps(dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped), python=sys.version.split()[0], torch=torch.__version__, cuda_initialized=False, production_model_loaded=False, jobs_submitted=0)), flush=True)
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 2)
''') + r'''
    command = [sys.executable, "-I", "-B", "-c", code, str(root), TORCH_VERSION]
    child = subprocess.Popen(command, start_new_session=True)
    try:
        rc = child.wait(timeout=1500)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        rc = 124
    for name, record in FILES.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == record["sha256"]
print("CPU_CHECK_FINISHED=" + json.dumps(dict(rc=rc, temporary_directory_removed=not root.exists(), jobs_submitted=0)), flush=True)
raise SystemExit(rc)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("p08full_sequence", ROOT / PACKAGE / "sequence.py")
    sequence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sequence)
    names = set(sequence.PINNED) | sequence.OWN_FILES
    names.update(str(p.relative_to(ROOT)) for p in (ROOT / PACKAGE / "tests").glob("*.py"))
    names.update(str(p.relative_to(ROOT)) for p in (ROOT / PACKAGE / "controller_tests").glob("*.py"))
    names.update(PACKAGE + "/" + n for n in ("control.py", "launch_approved.py", "ship.py", "offline_review.py"))
    names.update({
        "checkpoint_compare_workflow_20260917/tests/test_review_runs.py",
        "same_bank_compare_2026_09_17_eager_v1/tests/test_eager_compare.py",
        "same_bank_compare_2026_09_17_eager_v1/tests/fixture_model.py",
        "same_bank_compare_2026_09_18_layout_v1/tests/test_eager_compare.py",
        "same_bank_compare_2026_09_18_layout_v1/tests/test_layouts.py",
        "same_bank_compare_2026_09_18_layout_v1/tests/fixture_model.py",
        "same_bank_compare_2026_09_18_layout_v1/eager_compare.py",
        "same_bank_compare_2026_09_18_layout_v1/review_layouts.py",
        "same_bank_compare_2026_09_19_confirm_v2/tests/test_eager_compare.py",
        "same_bank_compare_2026_09_19_confirm_v2/tests/test_layouts.py",
        "same_bank_compare_2026_09_19_confirm_v2/tests/fixture_model.py",
    })
    files = {}
    for name in sorted(names):
        path = sequence.safe(ROOT / name)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if name in sequence.PINNED:
            assert digest == sequence.PINNED[name], name
        files[name] = {"sha256": digest, "data": base64.b64encode(data).decode()}
    assert sum(len(x["data"]) for x in files.values()) < 4 * 1024 * 1024
    if args.self_test:
        import torch
        version = torch.__version__
        command = [sys.executable, "-I", "-B", "-"]
    else:
        version = "2.1.1+cu118"
        socket = ROOT / ".hakusan-control/master.sock"
        info = socket.lstat()
        assert stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
        subprocess.run(["ssh", "-S", str(socket), "-O", "check", "s2510040@hakusan1"], check=True, timeout=10)
        command = ["ssh", "-S", str(socket), "-o", "BatchMode=yes", "-o", "ProxyCommand=false",
                   "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1", "s2510040@hakusan1",
                   "/home/s2510040/miniconda3/envs/attn/bin/python", "-I", "-B", "-"]
    payload = (f"FILES={files!r}\nSELF_TEST={args.self_test!r}\nTORCH_VERSION={version!r}\n" + REMOTE).encode()
    evidence = Path(tempfile.mkdtemp(prefix="p08full-cpu-local-" if args.self_test else "p08full-cpu-native-",
                                    dir=ROOT / "docs/superpowers/evidence"))
    manifest = {n: r["sha256"] for n, r in files.items()}
    (evidence / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"EVIDENCE={evidence}", flush=True)
    with (evidence / "output.log").open("xb") as log:
        try:
            rc = subprocess.run(command, input=payload, stdout=log, stderr=subprocess.STDOUT, timeout=1800).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    output = (evidence / "output.log").read_bytes()
    print(output.decode(errors="replace"), end="")
    receipt = dict(rc=rc, self_test=args.self_test, jobs_submitted=0,
                   driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   payload_sha256=hashlib.sha256(payload).hexdigest(),
                   output_sha256=hashlib.sha256(output).hexdigest())
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
