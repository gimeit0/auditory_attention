"""One bounded, read-only formal40 CPU preparation through authenticated SSH.

Default: validate local payload only. --run: read the frozen checkpoint remotely,
inspect real bindings, test empty hook admission/removal. Never run inference or
submit Slurm. Temporary source/cache files only, no original input writes.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


PINS = {
    'targeted_trace_20260911/trace_observer.py':
        'dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328',
    'targeted_trace_20260911/FORMAL40_PLAN_CANDIDATE.json':
        '727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8',
    'targeted_stream_20260911/stream_capture.py':
        'e0a0282a80b4e68aa0c0d250a0d1383238bfc948b871b9ab05baa585d386c01e',
    'targeted_stream_20260911/stream_observer.py':
        'd939436a0cc84c84c9e56a9c927719df677008405d1545acd537bb8f9bc79474',
    'targeted_binding_20260911/probe_cpu.py':
        '1e7e0e0a2668eda482026ea3002c9c249ffc8cc0f84bdb23940b800ce00e5d6f',
}

EXPECTED_SUMMARY = {
    'binding_kind': 'REAL_FORMAL40_CPU_BINDING_PASS', 'parent_job_id': '685198',
    'plan_sha256': '727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8',
    'input_freeze_sha256': 'bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178',
    'checkpoint_sha256': '2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff',
    'diagnostic_sha256': '7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b',
    'parent_state_sha256': '018ff20279396599cef17f54550bc758d1a75a9726d35f74319573ea098c292c',
    'stages': 42, 'unique_modules': 27, 'registered_state_entries': 60,
    'parent_state_bytes_equal': True, 'hook_admission_and_cleanup': True,
    'state_unchanged': True, 'rng_unchanged': True, 'production_model_loaded': True,
    'scientific_forward_executed': False, 'cuda_initialized': False,
    'production_execution_authority_verified': False, 'intermediate_equivalence_proven': False,
    'jobs_submitted': 0, 'ready_for_gpu': False,
}


def bootstrap(sources):
    spec = {'sources': sources, 'pins': PINS}
    return ('SPEC = ' + repr(spec) + '\n' + '''
import hashlib, json, os, pathlib, subprocess, sys, tempfile
os.umask(0o077)
code, summary = 2, None
print("PROBE_SCOPE=FROZEN_FORMAL40_CPU_BINDING_NO_FORWARD", flush=True)
with tempfile.TemporaryDirectory(prefix="audattn-real-binding-", dir="/tmp") as temporary:
    root = pathlib.Path(temporary)
    for relative, sha in SPEC["pins"].items():
        data = SPEC["sources"][relative].encode("utf-8")
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError("source payload digest differs")
        path = root / relative
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
    environment = dict(os.environ)
    for key in ("MPLCONFIGDIR", "XDG_CACHE_HOME", "TORCHINDUCTOR_CACHE_DIR",
                "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "NUMBA_CACHE_DIR", "TORCH_HOME"):
        cache = root / key.lower()
        cache.mkdir(mode=0o700)
        environment[key] = str(cache)
    environment.update({"TMPDIR": str(root), "CUDA_VISIBLE_DEVICES": "",
        "OMP_NUM_THREADS": "8", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8", "TOKENIZERS_PARALLELISM": "false",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0",
        "PATH": "/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"})
    command = [sys.executable, "-u", "-I", "-B", str(root / "targeted_binding_20260911/probe_cpu.py")]
    try:
        result = subprocess.run(command, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=240, check=False)
        raw, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as error:
        raw, code = error.stdout or b"", 124
    print(raw.decode("utf-8", errors="replace"), end="", flush=True)
    for relative, sha in SPEC["pins"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != sha:
            raise RuntimeError("temporary source changed")
    records = [json.loads(line) for line in raw.decode("utf-8", errors="replace").splitlines()
               if line.startswith('{"binding_kind":')]
    if code == 0:
        if len(records) != 1 or records[0]["binding_kind"] != "REAL_FORMAL40_CPU_BINDING_PASS":
            raise RuntimeError("successful child summary missing")
        summary = records[0]
if root.exists():
    raise RuntimeError("temporary directory cleanup failed")
print(json.dumps({"probe_kind": "REAL_BINDING_CPU_PROBE", "rc": code, "summary": summary,
    "temporary_directory_removed": True, "source_sha256": SPEC["pins"],
    "production_files_published": False, "jobs_submitted": 0}), flush=True)
raise SystemExit(code)
''').encode('utf-8')


def verified_result(code, records):
    if code != 0 or len(records) != 1:
        return False
    record = records[0]
    if not (type(record) is dict and record.get('rc') == 0 and record.get('source_sha256') == PINS
            and record.get('temporary_directory_removed') is True
            and record.get('production_files_published') is False
            and record.get('jobs_submitted') == 0):
        return False
    summary = record.get('summary')
    return (type(summary) is dict
            and all(type(summary.get(k)) is type(v) and summary[k] == v
                    for k, v in EXPECTED_SUMMARY.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    workspace = here.parents[3]
    sources = {}
    for relative, sha in PINS.items():
        path = here.parent / relative
        if not stat.S_ISREG(path.lstat().st_mode):
            raise RuntimeError('source is not a regular file')
        raw = path.read_bytes()
        if len(raw) > 128 * 1024 or hashlib.sha256(raw).hexdigest() != sha:
            raise RuntimeError('source digest differs: ' + relative)
        sources[relative] = raw.decode('utf-8')
    payload = bootstrap(sources)
    compile(payload, '<real-binding-bootstrap>', 'exec')
    print('LOCAL_REAL_BINDING_PAYLOAD_VALID=PASS', flush=True)
    if not args.run:
        print('Validation only: no SSH, model load, inference or submission.')
        return 0
    control = workspace / '.hakusan-control/master.sock'
    info = control.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('owned authenticated SSH socket required')
    command = ['/usr/bin/ssh', '-S', str(control), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
               '-o', 'ConnectionAttempts=1', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
               's2510040@hakusan1', '/home/s2510040/miniconda3/envs/attn/bin/python -u -I -B -']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = Path(tempfile.mkdtemp(prefix='real-binding-cpu-' + stamp + '-',
                              dir=workspace / 'docs/superpowers/evidence'))
    print('REAL_BINDING_EVIDENCE=' + str(run), flush=True)
    code, error = 2, None
    with (run / 'bootstrap.py').open('xb') as output:
        output.write(payload)
    with (run / 'output.log').open('xb') as output:
        try:
            result = subprocess.run(command, input=payload, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=270, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code, error = 124, '270-second local deadline; do not automatically retry'
        except OSError as failure:
            error = str(failure)
    raw = (run / 'output.log').read_bytes()
    records = [json.loads(line) for line in raw.decode('utf-8', errors='replace').splitlines()
               if line.startswith('{"probe_kind":')]
    verified = verified_result(code, records)
    receipt = {'status': 'REAL_BINDING_CPU_VERIFIED' if verified else 'REAL_BINDING_NOT_VERIFIED',
               'returncode': code, 'error': error,
               'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'source_sha256': PINS, 'bootstrap_sha256': hashlib.sha256(payload).hexdigest(),
               'output_sha256': hashlib.sha256(raw).hexdigest(),
               'probe_record': records[0] if len(records) == 1 else None,
               'jobs_submitted': 0, 'ready_for_gpu': False}
    with (run / 'receipt.json').open('x') as output:
        json.dump(receipt, output, indent=2)
        output.write('\n')
    print(raw.decode('utf-8', errors='replace'), end='', flush=True)
    print('REAL_BINDING_VERIFIED=' + str(int(verified)), flush=True)
    return 0 if verified else (code or 2)


if __name__ == '__main__':
    raise SystemExit(main())
