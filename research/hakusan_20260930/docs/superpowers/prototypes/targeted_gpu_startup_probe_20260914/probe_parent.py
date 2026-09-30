"""Payload entry: bounded ephemeral CPU package; no scheduler or model calls."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

JOB_PREFIX = "docs/superpowers/prototypes/targeted_gpu_job_20260914/"
PROBE_PREFIX = "docs/superpowers/prototypes/targeted_gpu_startup_probe_20260914/"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def install(spec, bundle):
    require(type(spec["local_test"]) is bool and len(spec["files"]) == 51, "exact CPU probe inventory required")
    total = 0
    for name, item in spec["files"].items():
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and str(path) == name
                and path.parts[0] in ("docs", "same_bank_eval_2026_09_03_v4_numeric_diag_v18")
                and path.suffix in (".py", ".md", ".json", ".sbatch"), "unsafe payload member")
        raw = base64.b64decode(item["base64"], validate=True)
        total += len(raw)
        require(len(raw) <= 1024**2 and total <= 8 * 1024**2
                and hashlib.sha256(raw).hexdigest() == item["sha256"], "payload bytes differ")
        target = bundle / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    raw = (bundle / JOB_PREFIX / "SOURCE_MANIFEST.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == spec["package_sha256"], "new GPU package SHA differs")
    manifest = json.loads(raw)
    require(len(manifest["files"]) == 49 and set(spec["files"]) ==
            set(manifest["files"]) | {JOB_PREFIX + "SOURCE_MANIFEST.json", PROBE_PREFIX + "probe_child.py"},
            "probe source coverage differs")
    require(all(spec["files"][n]["sha256"] == h for n, h in manifest["files"].items()), "source digest coverage differs")


def run(spec):
    os.umask(0o077)
    require(sys.flags.isolated and sys.dont_write_bytecode, "isolated bootstrap required")
    if not spec["local_test"]:
        import pwd
        require(sys.version.split()[0] == "3.11.5" and sys.platform.startswith("linux")
                and pwd.getpwuid(os.getuid()).pw_name == "s2510040", "unexpected remote CPU environment")
    require("torch" not in sys.modules and "numpy" not in sys.modules, "stdlib-only CPU bootstrap required")
    result = {"status": "STARTUP_CPU_PROBE_FAILED", "local_test": spec["local_test"], "jobs_submitted": 0,
              "production_model_loaded": False, "forward_calls": 0, "ready_for_gpu": False,
              "package_sha256": spec["package_sha256"], "automatic_retry": False, "cases": [], "error": None}
    try:
        with tempfile.TemporaryDirectory(prefix="audattn-startup-cpu-", dir="/tmp") as temp:
            base = Path(temp).resolve()
            bundle = base / "package"
            install(spec, bundle)
            sys.path.insert(0, str(bundle / JOB_PREFIX))
            import coordinator
            import job_contract as contract
            import process_runner as process
            contract.check_sources(spec["package_sha256"])
            if spec["local_test"]:
                fixture = bundle / "local_fixture_v18/tools"
                fixture.mkdir(mode=0o700, parents=True)
                source = bundle / "same_bank_eval_2026_09_03_v4_numeric_diag_v18/diagnose_batch_invariance.py"
                with (fixture / source.name).open("xb") as stream:
                    stream.write(source.read_bytes())
            started = time.monotonic()
            for mode, role in (("old", "reference"), ("new", "reference"), ("new", "observed")):
                label = mode + "-" + role
                trial = base / label
                trial.mkdir(mode=0o700)
                # Not a job ID obtained from Slurm. No worker/allocation gate is
                # bypassed: the child does not call gpu_child.run at all.
                synthetic_label = "777" + str(os.getpid())
                scratch = trial / ("audattn_v4_numdiag_" + synthetic_label)
                scratch.mkdir(mode=0o700)
                env = coordinator.child_environment({**os.environ, "SLURM_JOB_ID": synthetic_label,
                                                      "CUDA_VISIBLE_DEVICES": ""}, scratch, role)
                env.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
                argv = [sys.executable, "-I", "-B", str(bundle / PROBE_PREFIX / "probe_child.py"),
                        mode, role, spec["package_sha256"], str(trial / "result.json")]
                if spec["local_test"]:
                    argv += ["--local-test", "--local-python", sys.version.split()[0]]
                remaining = 85 - (time.monotonic() - started)
                require(remaining > 0, "85-second aggregate CPU budget exhausted")
                outcome = process.run_process(argv, env, trial / "output.log", seconds=min(45, remaining),
                                              max_log_bytes=256 * 1024)
                evidence = json.loads((trial / "result.json").read_bytes()) if (trial / "result.json").is_file() else None
                item = {"case": label, "process": outcome, "result": evidence,
                        "log_base64": base64.b64encode((trial / "output.log").read_bytes()).decode("ascii")}
                result["cases"].append(item)
                require(outcome["returncode"] == 0 and outcome["error"] is None and evidence is not None
                        and evidence["pid"] == outcome["pid"], "CPU child failed: " + label)
                require(not evidence["cuda_initialized"] and evidence["home_preserved"], "CPU child scope differs")
            contract.check_sources(spec["package_sha256"])
            for name, item in spec["files"].items():
                require(hashlib.sha256((bundle / name).read_bytes()).hexdigest() == item["sha256"], "post-source differs")
            result.update(status="LOCAL_STARTUP_PAYLOAD_PASS" if spec["local_test"] else "HAKUSAN_STARTUP_CPU_PASS",
                          source_files=len(spec["files"]), sources_unchanged=True)
        result["temporary_directory_removed"] = not base.exists()
    except BaseException as exc:
        traceback.print_exc()
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    print(json.dumps({"startup_cpu_result": result}, sort_keys=True), flush=True)
    return 0 if result["error"] is None else 2


if "SPEC" in globals():
    raise SystemExit(run(SPEC))
