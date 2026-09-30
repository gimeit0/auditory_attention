"""One same-version synthetic CPU archive test; no production/model/GPU job.

Validate locally by default. --run uses the existing authenticated SSH socket.
31 unit checks plus one cold dependent pair. Child/group deadlines, no retries.
Small synthetic archives are returned for a separate local full-byte recheck.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
PROTOTYPES = ROOT / 'docs/superpowers/prototypes'
PINS = {
    'targeted_trace_20260911/trace_observer.py': 'dcbe162257fc130450a2f2b4a2fd5680caded503d10c67b704c6a0331ec86328',
    'targeted_trace_20260911/test_trace_observer.py': '25c427438faedd30fde6770ff1f7f26598f809d6a949d3f6050200b0f0450b16',
    'targeted_stream_20260911/stream_capture.py': 'e0a0282a80b4e68aa0c0d250a0d1383238bfc948b871b9ab05baa585d386c01e',
    'targeted_stream_20260911/stream_observer.py': 'd939436a0cc84c84c9e56a9c927719df677008405d1545acd537bb8f9bc79474',
    'targeted_archive_20260911/trace_archive.py': '80fcf7bd77f7702547ec374d3f7362c77a8eec37d90ce82277f05fc93b4e6f81',
    'targeted_archive_20260911/cold_worker.py': 'c3e0c1714e1fad73b64f33bbcd96a0048a104a73d395e99101330400b50386f3',
    'targeted_archive_20260911/run_cold_pair.py': 'c584bafcef7e1b6704ca5419353d431b8aef540d110ce91555dd7b72ab811d55',
    'targeted_archive_20260911/test_trace_archive.py': '942304af12a0e18417fbec9282731ccd77e678f0718e4528cfc8fcbd12dfd7fa',
    'targeted_archive_20260911/run_checks.py': '644a46620f2998edd66195ec6fac5891b2d1a8027f6b1244da64d721a4720146',
    'targeted_archive_20260911/validate_local.py': '783a80770fdf8fb1a19350efdd3a77590020f8244f581fea1c3031059381ff68',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bootstrap(sources):
    return ('SPEC = ' + repr({'sources': sources, 'pins': PINS}) + '\n' + '''
import base64, hashlib, json, os, pathlib, pwd, signal, socket, stat, subprocess, sys, tempfile
os.umask(0o077)
if pwd.getpwuid(os.getuid()).pw_name != "s2510040" or socket.gethostname().split(".")[0] != "hakusan1":
    raise RuntimeError("wrong login-node CPU probe account/host")
if sys.version.split()[0] != "3.11.5":
    raise RuntimeError("Python version differs")
print("PROBE_SCOPE=ARCHIVE_SYNTHETIC_CPU_NO_MODEL_NO_GPU", flush=True)
code, units, pair, artifacts = 2, None, None, {}
with tempfile.TemporaryDirectory(prefix="audattn-archive-cpu-", dir="/tmp") as temporary:
    root = pathlib.Path(temporary)
    for relative, sha in SPEC["pins"].items():
        raw = SPEC["sources"][relative].encode()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise RuntimeError("payload digest differs")
        path = root / relative
        path.parent.mkdir(mode=0o700, exist_ok=True)
        with path.open("xb") as output:
            output.write(raw)
    env = dict(os.environ)
    env.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", TMPDIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    package = root / "targeted_archive_20260911"
    calls = [("units", [sys.executable, "-I", "-B", str(package / "run_checks.py")], 60),
             ("pair", [sys.executable, "-I", "-B", str(package / "run_cold_pair.py"),
                       "--root", str(root / "pair"), "--case", "dependent"], 150)]
    for label, command, timeout in calls:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   env=env, start_new_session=True)
        try:
            raw, _ = process.communicate(timeout=timeout)
            code = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            raw, _ = process.communicate()
            code = 124
        print(raw.decode("utf-8", errors="replace"), end="", flush=True)
        if code:
            for role in ("reference", "observed"):
                path = root / "pair" / (role + ".log")
                if path.is_file():
                    print(path.read_text()[-16000:], flush=True)
            break
        if label == "units":
            values = [json.loads(line) for line in raw.decode().splitlines() if line.startswith('{"status":')]
            if not (len(values) == 1 and values[0]["status"] == "ARCHIVE_UNIT_TESTS_PASS"
                    and values[0]["tests"] == 31 and values[0]["skipped"] == 0
                    and values[0]["torch"] == "2.1.1+cu118" and not values[0]["cuda_initialized"]):
                raise RuntimeError("same-version unit success missing")
            units = values[0]
        else:
            pair = json.loads((root / "pair/PAIR_RECEIPT.json").read_bytes())
            if pair["case_status"] != "SUPERVISED_SYNTHETIC_COLD_PAIR_PASS":
                raise RuntimeError("cold pair did not pass")
    for relative, sha in SPEC["pins"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != sha:
            raise RuntimeError("source changed during CPU probe")
    if code == 0:
        names = ["PAIR_RECEIPT.json", "reference.log", "observed.log", "reference/archive.json", "observed/archive.json"]
        names += [p.relative_to(root / "pair").as_posix() for p in sorted((root / "pair/observed/captures").iterdir())]
        total = 0
        for name in names:
            path = root / "pair" / name
            info = path.lstat()
            if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1):
                raise RuntimeError("unexpected returned synthetic artifact")
            if info.st_size > 2 * 1024**2:
                raise RuntimeError("synthetic artifact export limit exceeded")
            raw = path.read_bytes()
            total += len(raw)
            if total > 4 * 1024**2:
                raise RuntimeError("synthetic return byte budget exceeded")
            artifacts[name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                               "data": base64.b64encode(raw).decode("ascii")}
if root.exists():
    raise RuntimeError("temporary cleanup failed")
print(json.dumps({"probe_kind": "ARCHIVE_REMOTE_CPU_PROBE", "rc": code, "unit_tests": units,
    "pair": pair, "artifact_bundle": artifacts, "source_sha256": SPEC["pins"],
    "temporary_directory_removed": True, "production_model_loaded": False, "jobs_submitted": 0}), flush=True)
raise SystemExit(code)
''').encode()


def restore_and_recheck(run, record):
    artifacts = record['artifact_bundle']
    fixed = {'PAIR_RECEIPT.json', 'reference.log', 'observed.log',
             'reference/archive.json', 'observed/archive.json'}
    if not fixed <= set(artifacts) or not all(name in fixed or re.fullmatch(
            r'observed/captures/[0-9]{8}\.bin', name) for name in artifacts):
        raise RuntimeError('returned artifact paths differ')
    if len(artifacts) != 21 or sum(item['size'] for item in artifacts.values()) > 4 * 1024**2:
        raise RuntimeError('returned synthetic inventory/size differs')
    out = run / 'remote-pair'
    out.mkdir(mode=0o700)
    for name, entry in artifacts.items():
        raw = base64.b64decode(entry['data'], validate=True)
        if len(raw) != entry['size'] or digest(raw) != entry['sha256']:
            raise RuntimeError('returned artifact digest differs')
        path = out / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
    pair = json.loads((out / 'PAIR_RECEIPT.json').read_bytes())
    if pair != record['pair'] or pair['binding']['torch'] != '2.1.1+cu118':
        raise RuntimeError('returned pair receipt differs')
    sys.path.insert(0, str(PROTOTYPES / 'targeted_archive_20260911'))
    import trace_archive as archive
    from cold_worker import plan
    readers = {}
    try:
        for role in ('reference', 'observed'):
            child = pair['children'][role]
            if digest((out / (role + '.log')).read_bytes()) != child['log_sha256']:
                raise RuntimeError('child log digest differs')
            readers[role] = archive.ArchiveReader(out / role, expected_sha256=child['manifest_sha256'],
                expected_binding=pair['binding'], expected_plan=plan(), expected_role=role)
            if readers[role].writer_pid != child['pid'] or readers[role].invocation_id != child['invocation_id']:
                raise RuntimeError('supervised writer identity differs')
        compared = archive.compare_archives(readers['reference'], readers['observed'])
        if compared != pair['comparison']:
            raise RuntimeError('local byte recheck differs from remote comparison')
    finally:
        for reader in readers.values():
            reader.close()
    return compared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    sources = {}
    for name, sha in PINS.items():
        path = PROTOTYPES / name
        raw = path.read_bytes()
        if path.is_symlink() or len(raw) > 128 * 1024 or digest(raw) != sha:
            raise RuntimeError('local source digest differs: ' + name)
        sources[name] = raw.decode()
    payload = bootstrap(sources)
    compile(payload, '<archive-cpu-bootstrap>', 'exec')
    print('ARCHIVE_CPU_PAYLOAD_VALID=PASS', flush=True)
    if not args.run:
        print('Validation only: no SSH, uploads, inference or jobs.')
        return 0
    control = ROOT / '.hakusan-control/master.sock'
    info = control.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError('owned authenticated socket required')
    command = ['/usr/bin/ssh', '-S', str(control), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12',
        '-o', 'ConnectionAttempts=1', '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=15',
        '-o', 'ServerAliveCountMax=2', 's2510040@hakusan1',
        '/home/s2510040/miniconda3/envs/attn/bin/python -u -I -B -']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = Path(tempfile.mkdtemp(prefix='archive-remote-cpu-' + stamp + '-', dir=Path(__file__).parent))
    print('ARCHIVE_REMOTE_EVIDENCE=' + str(run), flush=True)
    with (run / 'bootstrap.py').open('xb') as output:
        output.write(payload)
    code, failure, verified, comparison = 2, None, False, None
    with (run / 'output.log').open('xb') as output:
        try:
            result = subprocess.run(command, input=payload, stdout=output, stderr=subprocess.STDOUT,
                                    timeout=270, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code, failure = 124, 'local deadline; no automatic retry'
    raw = (run / 'output.log').read_bytes()
    values = [json.loads(line) for line in raw.decode(errors='replace').splitlines()
              if line.startswith('{"probe_kind":')]
    record = values[0] if len(values) == 1 else None
    if code == 0 and record and record['rc'] == 0 and record['source_sha256'] == PINS:
        try:
            if record['temporary_directory_removed'] is not True:
                raise RuntimeError('remote cleanup not verified')
            comparison = restore_and_recheck(run, record)
            verified = True
        except Exception as error:
            failure = type(error).__name__ + ': ' + str(error)
    if record:
        record['artifact_bundle'] = {k: {f: v for f, v in e.items() if f != 'data'}
                                     for k, e in record['artifact_bundle'].items()}
    receipt = {'status': 'REMOTE_ARCHIVE_CPU_AND_LOCAL_RECHECK_PASS' if verified else 'ARCHIVE_PROBE_NOT_VERIFIED',
        'returncode': code, 'error': failure, 'probe_record': record, 'local_comparison': comparison,
        'source_sha256': PINS, 'driver_sha256': digest(Path(__file__).read_bytes()),
        'bootstrap_sha256': digest(payload), 'output_sha256': digest(raw),
        'production_model_loaded': False, 'jobs_submitted': 0, 'ready_for_gpu': False}
    with (run / 'receipt.json').open('x') as output:
        json.dump(receipt, output, indent=2)
        output.write('\n')
    print('REMOTE_ARCHIVE_LOCAL_RECHECK=' + ('PASS' if verified else 'FAIL'), flush=True)
    if failure:
        print(failure, flush=True)
    return 0 if verified else (code or 2)


if __name__ == '__main__':
    raise SystemExit(main())
