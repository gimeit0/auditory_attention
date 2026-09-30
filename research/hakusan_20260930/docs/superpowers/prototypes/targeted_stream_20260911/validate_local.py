"""Save local-only synthetic validation logs in a fresh private evidence folder."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parent
    workspace = here.parents[3]
    evidence = workspace / "docs/superpowers/evidence"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(tempfile.mkdtemp(prefix=f"stream-local-{stamp}-", dir=evidence))
    print(f"LOCAL_STREAM_EVIDENCE={out}", flush=True)
    source_before = {p.name: sha(p) for p in sorted(here.glob("*.py"))}
    records = []
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    for script, name in (("run_checks.py", "tests.log"), ("check_formal_plan.py", "static-plan.json")):
        with (out / name).open("xb") as stream:
            result = subprocess.run([sys.executable, "-I", "-B", str(here / script)],
                                    stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=120)
        records.append({"script": script, "returncode": result.returncode,
                        "output": name, "output_sha256": sha(out / name)})
    source_after = {p.name: sha(p) for p in sorted(here.glob("*.py"))}
    tests = [json.loads(line) for line in (out / "tests.log").read_text().splitlines()
             if line.startswith('{"status":')]
    ok = (all(r["returncode"] == 0 for r in records) and source_before == source_after
          and len(tests) == 1 and tests[0]["status"] == "STREAM_SYNTHETIC_CPU_PASS"
          and tests[0]["tests"] == 66 and tests[0]["cuda_initialized"] is False)
    receipt = {"status": "LOCAL_STREAM_VALIDATION_PASS" if ok else "LOCAL_VALIDATION_FAILED",
               "source_sha256": source_before, "source_unchanged": source_before == source_after,
               "records": records, "tests": tests, "remote_execution": False,
               "production_model_loaded": False, "jobs_submitted": 0, "ready_for_gpu": False}
    with (out / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
