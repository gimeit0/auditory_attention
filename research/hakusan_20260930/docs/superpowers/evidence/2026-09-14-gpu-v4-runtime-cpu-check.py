"""Bounded actual-environment CPU readback after deployment; no GPU submission."""
import base64
import os
from pathlib import Path
import sys
import uuid

W = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(W / 'docs/superpowers/prototypes/targeted_gpu_control_20260914_v4'))
import control

os.umask(0o077)
raw, release, files = control.package()
assert control.ops.sha(raw) == 'abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864'
control.master_check(control.SOCKET)
spec = {'action': 'runtime-cpu', 'request_id': uuid.uuid4().hex, 'release_sha256': control.ops.sha(raw)}
remote = r'''
import io, os, sys, tempfile, time
root = OPS.REMOTE
release = OPS.validate_release(OPS.read(root / 'CONTROL_RELEASE.json'), SPEC['release_sha256'])
OPS.Operations().sources(release)
OPS.Operations().protected_inputs()
OPS.Operations().clean_queue()
assert not (root / 'SUBMIT_INTENT.json').exists()
job_source = root / 'package' / OPS.PREFIX
sys.path.insert(0, str(job_source))
import coordinator
assert not any(n.partition('.')[0] in {'torch', 'numpy'} for n in sys.modules)
started = time.monotonic()
results = []
code = ('import io,json,os,sys;sys.path.insert(0,' + repr(str(job_source)) + ');'
        'import runtime_environment as r;r.check(os.environ);'
        'import torch;record=r.readback(torch);'
        'record.update(python=sys.version.split()[0],torch=str(torch.__version__),cuda_initialized=torch.cuda.is_initialized());'
        'assert record["python"]=="3.11.5" and record["torch"]=="2.1.1+cu118";'
        'assert record["cuda_initialized"] is False;'
        'print(json.dumps(record,sort_keys=True))')
with tempfile.TemporaryDirectory(prefix='audattn-v4-runtime-cpu-', dir='/tmp') as temporary:
    for role in ('reference', 'observed'):
        env = coordinator.child_environment(os.environ, Path(temporary), role)
        env['CUDA_VISIBLE_DEVICES'] = ''
        for key in coordinator.WRITE_PATHS:
            Path(env[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
        remaining = 90 - (time.monotonic() - started)
        assert remaining > 0
        p = OPS.subprocess.run([str(OPS.Path('/home/s2510040/miniconda3/envs/attn/bin/python')), '-I', '-B', '-c', code],
                               env=env, stdin=OPS.subprocess.DEVNULL, capture_output=True, timeout=min(45, remaining))
        assert p.returncode == 0, p.stderr[:4096].decode(errors='replace')
        assert len(p.stdout) + len(p.stderr) <= 16384
        record = json.loads(p.stdout)
        assert record['fixed_exports'] == dict(coordinator.runtime_environment.FIXED)
        assert record['torch_num_threads'] == 8 and record['cuda_initialized'] is False
        results.append({'role': role, 'readback': record, 'stderr': p.stderr.decode(errors='replace')})
assert time.monotonic() - started < 90
OPS.Operations().sources(release)
OPS.Operations().protected_inputs()
result = {'status': 'HAKUSAN_FIXED_STARTUP_CPU_PASS', 'roles': results, 'jobs_submitted': 0,
          'production_model_loaded': False, 'elapsed_seconds': round(time.monotonic()-started,3),
          'temporary_scratch_removed': True, 'published_sources_unchanged': 58,
          'scope': 'actual environment factory, fresh torch CPU readback only; not GPU inference or timeout causality'}
'''
code = 'import base64,json,types\nfrom pathlib import Path\nSPEC=' + repr(spec) + '\n'
code += "OPS=types.ModuleType('pinned_ops')\nexec(compile(base64.b64decode(" + repr(base64.b64encode(files[control.ops.OPS]).decode()) + "),'<pinned-ops>','exec'),OPS.__dict__)\n"
code += 'try:\n' + '\n'.join(' ' + line for line in remote.splitlines()) + '\n'
code += " response={'ok':True,'result':result}\nexcept BaseException as exc:\n response={'ok':False,'error':{'type':type(exc).__name__,'message':str(exc)}}\n"
code += "print('GPU_CONTROL='+json.dumps({**SPEC,**response}),flush=True)\nraise SystemExit(0 if response['ok'] else 2)\n"
control.payload = lambda _spec, _source: code.encode('ascii')
receipt = control.operate(spec, files)
raise SystemExit(receipt['returncode'])
