"""Local/same-environment G2 API check using the existing SSH master only."""
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ADAPTER = HERE.parent / 'g2_profiles_20260916/adapter.py'
PREVIOUS = ROOT / 'docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu/RECEIPT.json'
PREVIOUS_SHA = 'fe1f4d7484bcf34651d30a81bc9ecf6da3da8cd5ad9f96d235d26bab75f80395'
PREFIX = 'G2_CPU_API_RESULT='


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024**2, 'bounded source/log required')
    return path.read_bytes()


def write(path, raw):
    with path.open('xb') as out:
        out.write(raw)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def validate(result, spec):
    require(result['status'] == 'G2_CPU_API_PASS' and result['request_id'] == spec['request_id']
            and result['mode'] == spec['mode'] and result['adapter_sha256'] == spec['adapter_sha256'], 'result identity differs')
    require([x['profile'] for x in result['profiles']] == ['R', 'C', 'D', 'E'], 'profile inventory differs')
    for row in result['profiles']:
        tf32 = row['profile'] in ('R', 'D')
        require(row['runtime'] == dict(deterministic_algorithms=True, cudnn_deterministic=True,
                    cudnn_benchmark=False, float32_matmul_precision='high' if tf32 else 'highest',
                    cuda_matmul_allow_tf32=tf32, cudnn_allow_tf32=tf32), 'runtime differs')
        item = row['adaptation']
        require(item['status'] == 'PRE_ATTESTATION_ADAPTED' and item['profile'] == row['profile']
                and item['trust_domain'] == 'hermetic-test' and item['compiled_wrapper_retained'] == (row['profile'] in ('R', 'C'))
                and item['state_object_identity_preserved'] is True and item['rng_unchanged'] is True
                and item['runtime_unchanged'] is True and item['production_ready'] is False, 'adaptation differs')
    require(result['cuda_initialized'] is False and result['production_model_loaded'] is False
            and result['compiled_forward_called'] is False and result['production_ready'] is False
            and result['jobs_submitted'] == 0 and result['home_unchanged'] is True
            and result['threads'] == 1 and 0 <= result['elapsed_seconds'] < 50, 'scope/budget differs')
    if spec['mode'] == 'NATIVE_CPU':
        require(result['torch'] == '2.1.1+cu118' and result['python'] == '3.11.5'
                and len(result['cpu_affinity']) == 1
                and result['native_binding'] == dict(type_module='torch', type_name='_TorchCompileInductorWrapper',
                                                     compiler_entered=False, compiled_forward_called=False), 'native environment differs')
    require(set(result['compiler_sources']) == {'torch', 'torch._dynamo.eval_frame', 'torch._dynamo.convert_frame',
                'torch._dynamo.utils', 'torch._dynamo.backends.inductor', 'torch._inductor.compile_fx', 'torch._inductor.codecache'}, 'source set differs')
    for item in result['compiler_sources'].values():
        raw = base64.b64decode(item['source'], validate=True)
        require(len(raw) == item['size'] < 1024**2 and sha(raw) == item['sha256'], 'source hash differs')


def run(mode):
    old_raw = read(PREVIOUS)
    require(sha(old_raw) == PREVIOUS_SHA, 'previous local receipt differs')
    old = json.loads(old_raw)
    adapter = read(ADAPTER)
    require(next(x for x in old['sources_before'] if x['path'] == str(ADAPTER))['sha256'] == sha(adapter), 'untested adapter')
    socket = ROOT / '.hakusan-control/master.sock'
    spec = dict(mode=mode, request_id=uuid.uuid4().hex, adapter=base64.b64encode(adapter).decode(), adapter_sha256=sha(adapter))
    body = read(HERE / 'probe.py')
    payload = ('SPEC=' + repr(spec) + '\n').encode() + body
    if mode == 'NATIVE_CPU':
        require(socket.is_socket(), 'existing authenticated SSH master required')
        command = ['/usr/bin/ssh', '-S', str(socket), '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
                   '-o', 'ProxyCommand=/usr/bin/false', '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=12',
                   '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
                   's2510040@hakusan1', '/home/s2510040/miniconda3/envs/attn/bin/python -I -B -']
    else:
        command = [sys.executable, '-I', '-B', '-']
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
    folder = Path(tempfile.mkdtemp(prefix='g2-api-' + mode.lower() + '-' + stamp, dir=ROOT / 'docs/superpowers/evidence'))
    write(folder / 'request.py', payload)
    print('EVIDENCE=' + str(folder), flush=True)
    receipt = dict(status='FAILED', mode=mode, jobs_submitted=0, production_ready=False, request_sha256=sha(payload),
                   driver_sha256=sha(read(Path(__file__))), probe_sha256=sha(body), error=None)
    with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
        try:
            result = subprocess.run(command, input=payload, stdout=out, stderr=err, timeout=65)
            receipt['returncode'] = result.returncode
            require(result.returncode == 0, 'CPU transport/probe failed; no retry')
            lines = [json.loads(line[len(PREFIX):]) for line in read(folder / 'stdout.log').decode().splitlines() if line.startswith(PREFIX)]
            require(len(lines) == 1, 'missing/duplicate result')
            validate(lines[0], spec)
            require(read(ADAPTER) == adapter and read(HERE / 'probe.py') == body, 'local sources changed')
            write(folder / 'result.json', wire(lines[0]))
            for name, item in lines[0]['compiler_sources'].items():
                write(folder / (name + '.source.py'), base64.b64decode(item['source'], validate=True))
            receipt['status'] = 'VERIFIED'
        except Exception as exc:
            receipt['error'] = dict(type=type(exc).__name__, message=str(exc))
    receipt['artifacts'] = {p.name: sha(read(p)) for p in sorted(folder.iterdir()) if p.is_file()}
    write(folder / 'receipt.json', wire(receipt))
    print(json.dumps(receipt, sort_keys=True), flush=True)
    require(receipt['status'] == 'VERIFIED', 'probe failed; preserve evidence, do not retry automatically')


if __name__ == '__main__':
    os.umask(0o077)
    require(len(sys.argv) == 2 and sys.argv[1] in ('local', 'native'), 'usage: run.py local|native')
    run('NATIVE_CPU' if sys.argv[1] == 'native' else 'LOCAL_CPU')
