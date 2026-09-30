"""Pinned candidate in remote /tmp: two eight-element CPU forwards, no GPU/job."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v16"
TRACE_SHA = "fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b"
REMOTE = r"""
import base64, hashlib, importlib.util, json, os, pathlib, signal, socket, sys, tempfile
signal.alarm(150)
assert socket.gethostname().split('.')[0] == 'hakusan1'
assert sys.version_info[:3] == (3,11,5) and sys.flags.isolated and sys.dont_write_bytecode
packet=json.loads(sys.stdin.buffer.read(2000001))
assert set(packet)=={'files','backend','negative','expected'}
with tempfile.TemporaryDirectory(prefix='audattn-v16-toy-',dir='/tmp') as temporary:
    root=pathlib.Path(temporary)
    assert set(packet['files'])=={'diagnose_batch_invariance.py','numeric_trace.py'}
    for name, encoded in packet['files'].items():
        content=base64.b64decode(encoded,validate=True)
        assert hashlib.sha256(content).hexdigest()==packet['expected'][name]
        descriptor=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(descriptor,'wb') as stream: stream.write(content)
    for key in ('MPLCONFIGDIR','XDG_CACHE_HOME','TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH'):
        path=root/key.lower(); path.mkdir(mode=0o700); os.environ[key]=str(path)
    os.environ['OMP_NUM_THREADS']='1'
    os.environ['PATH']='/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    import torch
    assert str(torch.__version__)=='2.1.1+cu118' and not torch.cuda.is_available()
    torch.set_num_threads(1)
    torch._dynamo.reset()
    spec=importlib.util.spec_from_file_location('v16_lifecycle_probe',root/'diagnose_batch_invariance.py')
    diag=importlib.util.module_from_spec(spec); sys.modules[spec.name]=diag; spec.loader.exec_module(diag)
    class Toy(torch.nn.Module):
        def forward(self,x): return x.sin()+1
    model=torch.compile(Toy().eval(),backend=packet['backend'])
    inventory=diag._direct_model_module_inventory(model)
    stage='issue'
    try:
        authority=diag._issue_compiler_lifecycle(model,inventory)
        assert authority is not None
        stage='before_fingerprint'
        before=diag._materialized_model_execution_fingerprint(model,inventory)
        assert before==diag._model_execution_fingerprint(model,inventory)
        outputs=[]
        values=torch.arange(8,dtype=torch.float32)
        for ordinal in (1,2):
            stage='forward_'+str(ordinal)
            with torch.inference_mode(): output=model(values)
            assert torch.equal(output,values.sin()+1)
            current=diag._model_execution_fingerprint(model,inventory)
            if current!=before:
                raise diag._guard_mismatch_error('toy','model_execution',0,before,current)
            outputs.append({'ordinal':ordinal,'exact_output':True,'guard_unchanged':True})
        if packet['negative']:
            stage='negative_backend'
            from torch._dynamo import eval_frame
            eval_frame.most_recent_backend=lambda *args: None
            try: diag._model_execution_fingerprint(model,inventory)
            except diag.DiagnosticError: pass
            else: raise AssertionError('replacement backend accepted')
            assert authority.revoked
        print(json.dumps({'status':'CPU_COMPILER_LIFECYCLE_PROBE_PASS','backend':packet['backend'],'torch':str(torch.__version__),'scope':'8_ELEMENT_SYNTHETIC_CPU_ONLY','scientific_model_used':False,'source_sha256':packet['expected']['diagnose_batch_invariance.py'],'passes':outputs,'negative_backend_rejected':bool(packet['negative'])}),flush=True)
    except Exception as error:
        print(json.dumps({'status':'CPU_COMPILER_LIFECYCLE_PROBE_FAILED','stage':stage,'type':type(error).__name__,'diagnostic':diag._bounded_exception_diagnostic(error)}),flush=True)
        raise SystemExit(2)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-diag-sha", required=True)
    parser.add_argument("--backend", choices=("eager", "inductor"), default="eager")
    parser.add_argument("--negative", action="store_true")
    args = parser.parse_args()
    expected = {
        "diagnose_batch_invariance.py": args.expected_diag_sha,
        "numeric_trace.py": TRACE_SHA,
    }
    files = {}
    for name, sha in expected.items():
        source = (PACKAGE / name).read_bytes()
        if hashlib.sha256(source).hexdigest() != sha:
            raise SystemExit("STOP: local candidate SHA mismatch")
        files[name] = base64.b64encode(source).decode()
    result = subprocess.run(
        [
            "ssh",
            "-S",
            str(ROOT / ".hakusan-control/master.sock"),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=12",
            "s2510040@hakusan1",
            "/home/s2510040/miniconda3/envs/attn/bin/python -I -B -c "
            + shlex.quote(REMOTE),
        ],
        input=json.dumps(
            {
                "files": files,
                "backend": args.backend,
                "negative": args.negative,
                "expected": expected,
            }
        ).encode(),
        timeout=170,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
