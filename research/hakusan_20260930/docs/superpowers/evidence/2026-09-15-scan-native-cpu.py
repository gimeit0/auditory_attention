"""Existing SSH master only: <=60s native CPU scanner checks, no remote files/jobs."""
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CANDIDATE = ROOT / "docs/superpowers/prototypes/guard_scan_20260915"
CONTROL = ROOT / "docs/superpowers/prototypes/targeted_gpu_control_20260914_v4"
LOCAL_RESULT = HERE / "guard-scan-candidate-20260914T164836Z-e0wtqyns/receipt.json"

REMOTE = r'''
import ast, contextlib, hashlib, importlib.metadata, importlib.util, io
import json, os, pathlib, signal, statistics, sys, time, types, unittest

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def expired(*_):
    raise TimeoutError("native scanner probe 60-second deadline")

signal.signal(signal.SIGALRM, expired)
signal.alarm(60)
os.environ["CUDA_VISIBLE_DEVICES"] = ""
require(sys.version.split()[0] == "3.11.5" and os.getuid() != 0, "native interpreter/account differs")
require(pathlib.Path(sys.executable).resolve() == pathlib.Path("/home/s2510040/miniconda3/envs/attn/bin/python").resolve(), "wrong interpreter")
path = pathlib.Path("/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18/tools/diagnose_batch_invariance.py")
raw = path.read_bytes()
require(hashlib.sha256(raw).hexdigest() == SPEC["parent_sha256"], "deployed v18 source differs")
for name, source in SPEC["sources"].items():
    require(hashlib.sha256(source.encode()).hexdigest() == SPEC["source_sha256"][name], "payload source differs")
original_tree = ast.parse(raw)
target = next(n for n in original_tree.body if isinstance(n, ast.FunctionDef) and n.name == "_live_protected_module_bindings")
replacement = next(n for n in ast.parse(SPEC["sources"]["scanner.py"]).body if isinstance(n, ast.FunctionDef))
lines = raw.decode().splitlines(keepends=True)
assembled = "".join(lines[:target.lineno-1]) + ast.get_source_segment(SPEC["sources"]["scanner.py"], replacement) + "\n" + "".join(lines[target.end_lineno:])
def stripped(tree):
    return [ast.dump(n, include_attributes=False) for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == target.name)]
require(stripped(original_tree) == stripped(ast.parse(assembled)), "more than scanner changed")
require(hashlib.sha256(assembled.encode()).hexdigest() == SPEC["assembled_sha256"], "assembled candidate differs")
module = types.ModuleType("native_scan_candidate_only")
module.__file__ = str(path)
sys.modules[module.__name__] = module
exec(compile(assembled, "<native-cpu-scanner-candidate>", "exec", dont_inherit=True), vars(module))
namespace = dict(vars(module))
exec(compile(ast.Module(body=[target], type_ignores=[]), "<original-native-scan>", "exec"), namespace)
original_scan = namespace[target.name]
suite = unittest.TestSuite()
for name in ("test_binding_scan.py", "test_module_name_classification.py"):
    test = types.ModuleType("native_scan_" + name[:-3])
    test.__file__ = str(path.with_name(name))
    sys.modules[test.__name__] = test
    exec(compile(SPEC["sources"][name], test.__file__, "exec", dont_inherit=True), vars(test))
    test.diag = module
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(test))
outcome = unittest.TextTestRunner(verbosity=2).run(suite)
require(outcome.wasSuccessful() and outcome.testsRun == 18 and not outcome.skipped, "candidate rejection tests failed")
timings = []
for count in (2048, 8192):
    registry = {"src.x": object(), **{"unprotected_" + str(i): object() for i in range(count-1)}}
    values = {"original": [], "candidate": []}
    # Scanner globals only see a synthetic registry; do not replace process sys.modules.
    def bind(function):
        env = dict(function.__globals__)
        env["sys"] = types.SimpleNamespace(modules=registry)
        return types.FunctionType(function.__code__, env)
    functions = {"original": bind(original_scan), "candidate": bind(module._live_protected_module_bindings)}
    for repeat in range(6):
        order = ("original", "candidate") if repeat % 2 == 0 else ("candidate", "original")
        for variant in order:
            token = module._ACTIVE_SEAL_BUDGET.set(module._SealBudget())
            try:
                function = functions[variant]
                require(set(function({"src"})) == {"src.x"}, "warm scan differs")
                start = time.perf_counter()
                for _ in range(800):
                    result = function({"src"})
                elapsed = time.perf_counter() - start
                require(len(result) == 1 and result["src.x"] is registry["src.x"], "live value differs")
                values[variant].append(elapsed)
            finally:
                module._ACTIVE_SEAL_BUDGET.reset(token)
    medians = {k: statistics.median(v) for k,v in values.items()}
    timings.append({"registry_keys":count,"scans_per_repeat":800,"repeats":6,"timings_seconds":values,
                    "medians_seconds":medians,"speedup":medians["original"]/medians["candidate"]})
require(path.read_bytes() == raw, "deployed v18 source changed during probe")
torch_api = sys.modules.get("torch")
# Original v18 _default_anchor_identity -> _container_execution_identity
# imports torch/numpy for tuple defaults. Importing them is not GPU inference.
cuda_initialized = bool(torch_api is not None and torch_api.cuda.is_initialized())
require(not cuda_initialized, "unexpected CUDA initialization")
value = {"status":"NATIVE_CPU_SCANNER_CANDIDATE_PASS","request_id":SPEC["request_id"],
         "python":sys.version.split()[0],"installed_torch":importlib.metadata.version("torch"),
         "tests":18,"skipped":0,"timings":timings,"assembled_sha256":SPEC["assembled_sha256"],
         "source_sha256":SPEC["source_sha256"],"original_source_unchanged":True,
         "torch_imported":torch_api is not None,"cuda_initialized":cuda_initialized,
         "production_model_loaded":False,"production_snapshot_loaded":False,
         "remote_files_written":False,"jobs_submitted":0,"ready_for_gpu":False,
         "scope":"native Python scanner tests/microbenchmark only; no full trace or GPU validation"}
print("NATIVE_SCAN_RESULT=" + json.dumps(value,sort_keys=True),flush=True)
signal.alarm(0)
'''


def main():
    os.umask(0o077)
    require = lambda ok, message: None if ok else (_ for _ in ()).throw(RuntimeError(message))
    result = json.loads(LOCAL_RESULT.read_bytes())
    require(result["status"] == "LOCAL_SCAN_CANDIDATE_VERIFIED", "local candidate must pass first")
    for relative, digest in result["new_sources"].items():
        require(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest, "candidate source changed")
    sys.path.insert(0, str(CANDIDATE))
    import candidate
    profile_source = HERE / "2026-09-15-guard-cpu-profile.py"
    require(hashlib.sha256(profile_source.read_bytes()).hexdigest() == "b34d51a3d5f48887341eb7625a42dfbfb9c3f23793cb36182192471f1cf60e8e", "source verifier changed")
    spec = importlib.util.spec_from_file_location("native_probe_profile_parent", profile_source)
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    before = profile.sources()
    sys.path.insert(0, str(CONTROL))
    import control
    control.master_check(control.SOCKET)
    sources = {p.name: p.read_text() for p in (CANDIDATE / "scanner.py",
               candidate.SOURCE.with_name("test_binding_scan.py"), candidate.SOURCE.with_name("test_module_name_classification.py"))}
    spec = {"request_id": uuid.uuid4().hex, "sources": sources,
            "source_sha256": {n: hashlib.sha256(s.encode()).hexdigest() for n,s in sources.items()},
            "parent_sha256": candidate.PARENT_SHA,
            "assembled_sha256": hashlib.sha256(candidate.assemble().encode()).hexdigest()}
    payload = ("SPEC=" + repr(spec) + "\n" + REMOTE).encode()
    folder = Path(tempfile.mkdtemp(prefix="scan-native-cpu-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-",dir=HERE))
    print("NATIVE_CPU_EVIDENCE=" + str(folder),flush=True)
    run = control.transport(control.ssh_command(control.SOCKET), payload, folder, timeout=75, log_cap=2*1024**2)
    log = (folder / "output.log").read_bytes()
    remote, error = None, None
    try:
        lines = [line.removeprefix("NATIVE_SCAN_RESULT=") for line in log.decode().splitlines() if line.startswith("NATIVE_SCAN_RESULT=")]
        require(len(lines) == 1 and run["returncode"] == 0 and run["error"] is None, "native probe failed")
        remote = json.loads(lines[0])
        require(remote["request_id"] == spec["request_id"] and remote["source_sha256"] == spec["source_sha256"]
                and remote["assembled_sha256"] == spec["assembled_sha256"] and remote["tests"] == 18
                and remote["status"] == "NATIVE_CPU_SCANNER_CANDIDATE_PASS", "response binding differs")
        require(before == profile.sources(), "frozen local sources changed")
    except Exception as exc:
        error = {"type":type(exc).__name__,"message":str(exc)}
    receipt = {"status":"NATIVE_CPU_RECHECK_PASS" if error is None else "NATIVE_CPU_RECHECK_FAILED",
               "error":error,"transport":run,"remote":remote,"spec":spec,
               "payload_sha256":hashlib.sha256(payload).hexdigest(),"output_sha256":hashlib.sha256(log).hexdigest(),
               "original_sources_unchanged":before==profile.sources(),"automatic_retry":False,"jobs_submitted":0}
    control.ops.write_new(folder / "receipt.json",control.ops.wire(receipt))
    print(json.dumps({"status":receipt["status"],"error":error,"remote":remote,"receipt":str(folder/"receipt.json")}),flush=True)
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
