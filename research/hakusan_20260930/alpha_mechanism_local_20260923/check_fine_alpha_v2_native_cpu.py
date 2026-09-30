"""One explicitly invoked, <=90s native CPU type probe; no deployment or GPU job."""
import argparse
import datetime
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
from fine_alpha_entry import identity, verify_package
from publish_fine_alpha import SOCKET, SSH, REMOTE_PY

HERE = Path(__file__).absolute().parent
ROOT = HERE/'release_fine_alpha_20260928_candidate_v2'
BOOTSTRAP = r'''
import hashlib, json, os, subprocess, sys
packet = json.load(sys.stdin)
raw = packet['probe_source'].encode()
if dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) != packet['probe_identity']:
    raise ValueError('PROBE_DRIVER_SHA')
env = os.environ.copy()
env.update(CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
           OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
p = subprocess.run([sys.executable, '-I', '-B', '-c', packet['probe_source']],
                   input=json.dumps(packet).encode(), env=env, timeout=90)
sys.exit(p.returncode)
'''


def packet_for(package, digest):
    manifest = verify_package(package, digest)
    if manifest['scope'] != 'FINE_ALPHA_001_20260928_V2': raise ValueError('V2_REQUIRED')
    names = ('e0_layout_reference.py', 'e1_execution.py', 'e1_worker_archive.py')
    probe = HERE/'fine_alpha_provenance_cpu_probe.py'
    return dict(release_sha256=digest, probe_source=probe.read_text(), probe_identity=identity(probe),
                sources={n: dict(source=(package/n).read_text(), identity=manifest['files'][n]) for n in names})


def validate(result, packet):
    if (result.get('status') != 'FINE_ALPHA_PROVENANCE_CPU_TYPE_CHECK_PASS' or
        result.get('release_sha256') != packet['release_sha256'] or
        result.get('python') != '3.11.5' or result.get('torch') != '2.1.1+cu118' or
        result.get('source_identities') != {n: row['identity'] for n, row in packet['sources'].items()}):
        raise ValueError('NATIVE_CPU_PROBE_IDENTITY')
    for name in ('cuda_initialized', 'production_checkpoint_loaded', 'remote_source_files_written', 'production_validated'):
        if result.get(name) is not False: raise ValueError('CPU_SCOPE:'+name)
    if type(result.get('jobs_submitted')) is not int or result['jobs_submitted'] != 0: raise ValueError('CPU_SCOPE:jobs')
    for name in ('live_object_verified', 'json_roundtrip_verified', 'cpu_cannot_pass_production'):
        if result.get(name) is not True: raise ValueError('CPU_CHECK:'+name)
    if (result.get('recorded_version_type') != 'str' or result.get('invalid_versions_rejected') != 4 or
        result.get('raw_version_type') != 'torch.torch_version.TorchVersion'):
        raise ValueError('CPU_VERSION_RESULT')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-sha256', required=True)
    parser.add_argument('--execute-native-cpu-check', action='store_true', required=True)
    args = parser.parse_args(); package = ROOT/'package'
    packet = packet_for(package, args.release_sha256)
    if SOCKET.is_symlink() or not SOCKET.is_socket(): raise ValueError('USER_RECONNECT_REQUIRED')
    output = Path(tempfile.mkdtemp(prefix='native-cpu-', dir=ROOT))
    report = dict(status='NATIVE_CPU_CHECK_NOT_FINISHED', release_sha256=args.release_sha256,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source_identities={n: r['identity'] for n, r in packet['sources'].items()},
                  probe_identity=packet['probe_identity'], driver_identity=identity(Path(__file__)),
                  automatic_reconnect=False, automatic_retry=False, jobs_submitted=0)
    print('NATIVE_CPU_EVIDENCE='+str(output), flush=True)
    try:
        cmd = shlex.join([REMOTE_PY, '-I', '-B', '-c', BOOTSTRAP])
        with (output/'remote.json').open('xb') as stdout, (output/'remote.stderr').open('xb') as stderr:
            p = subprocess.run(SSH+[cmd], input=json.dumps(packet).encode(), stdout=stdout, stderr=stderr, timeout=105)
        if p.returncode: raise ValueError('NATIVE_CPU_RC='+str(p.returncode))
        result = json.loads((output/'remote.json').read_bytes()); validate(result, packet)
        verify_package(package, args.release_sha256)
        report.update(status='FINE_ALPHA_V2_NATIVE_CPU_TYPE_CHECK_PASS_NOT_GPU_VALIDATED', result=result)
        print(json.dumps(report), flush=True)
    except BaseException as exc:
        report.update(status='STOPPED_NO_RECONNECT_NO_RETRY', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with (output/'RESULT.json').open('x') as stream: json.dump(report, stream, indent=2)


if __name__ == '__main__': main()
