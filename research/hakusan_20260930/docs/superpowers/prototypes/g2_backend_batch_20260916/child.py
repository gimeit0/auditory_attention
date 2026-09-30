"""Cold native synthetic CPU child. No checkpoint, model hooks or GPU inference."""
import base64
import contextlib
import faulthandler
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as c

started = time.monotonic()
def phase(name):
    print('G2_PHASE=' + json.dumps(dict(phase=name, elapsed=time.monotonic()-started)), flush=True)

role, raw_root, digest, nonce, job, raw_part = sys.argv[1:]
root, part = Path(raw_root), Path(raw_part)
c.require(role in ('reference', 'observed') and root == c.REMOTE, 'child scope differs')
c.require(part == root / 'attempts' / ('slurm-' + job) / role, 'child path differs')
c.require(os.environ.get('SLURM_JOB_ID') == job and len(os.sched_getaffinity(0)) == 1, 'allocation differs')
c.require(os.environ.get('CUDA_VISIBLE_DEVICES') == '' and sys.flags.isolated and sys.dont_write_bytecode,
          'isolated CPU required')
manifest = c.release(c.read(root / 'RELEASE.json'), digest)
c.source_check(root / 'package', manifest)
sys.path.insert(0, str(root / 'package'))
faulthandler.enable()
faulthandler.dump_traceback_later(60, repeat=True)
phase('IMPORT_TORCH_BEGIN')
import torch
phase('IMPORT_TORCH_END')
c.require(str(torch.__version__) == '2.1.1+cu118' and sys.version.split()[0] == '3.11.5', 'native version differs')
c.require(not torch.cuda.is_initialized(), 'CUDA initialized')
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(20260829)
torch.use_deterministic_algorithms(True)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False
torch.set_float32_matmul_precision('highest')
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False

class Toy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(4, 8)
    def forward(self, x):
        return self.linear(x).relu()

def tensor(value):
    value = value.detach().cpu().contiguous()
    c.require(value.dtype == torch.float32 and bool(torch.isfinite(value).all()), 'finite float32 required')
    raw = value.numpy().tobytes()
    return dict(dtype='float32', shape=list(value.shape), sha256=c.sha(raw), bytes_b64=base64.b64encode(raw).decode())

def runtime():
    return [torch.are_deterministic_algorithms_enabled(), torch.backends.cudnn.deterministic,
            torch.backends.cudnn.benchmark, torch.get_float32_matmul_precision(),
            torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32]

model = Toy().eval().requires_grad_(False)
inputs = [torch.arange(64, dtype=torch.float32).reshape(16, 4)/100,
          torch.arange(4, dtype=torch.float32).reshape(1, 4)/100]
def state():
    return dict(weights={n: tensor(t) for n, t in model.state_dict().items()}, inputs=[tensor(x) for x in inputs],
                rng_sha256=c.sha(torch.get_rng_state().numpy().tobytes()), runtime=runtime(),
                training=[m.training for m in model.modules()], requires_grad=[p.requires_grad for p in model.parameters()])

before = state()
with torch.inference_mode():
    eager = [model(x) for x in inputs]
    phase('WRAPPER_BEGIN')
    compiled = torch.compile(model, mode='default')
    phase('WRAPPER_END')
    observer = None
    if role == 'observed':
        phase('OBSERVER_PREPARE_BEGIN')
        import backend_evidence
        observer = backend_evidence.BackendEvidence(compiled, Path(os.environ['TORCHINDUCTOR_CACHE_DIR']))
        phase('OBSERVER_PREPARE_END')
    outputs = []
    with observer if observer is not None else contextlib.nullcontext():
        for index, x in enumerate(inputs):
            phase('FORWARD_' + str(index) + '_BEGIN')
            outputs.append(compiled(x))
            phase('FORWARD_' + str(index) + '_END')
    eager_record, output_record = [tensor(x) for x in eager], [tensor(x) for x in outputs]
after = state()
c.require(before == after, 'weights/inputs/RNG/runtime/training state changed')
c.require(sys.getprofile() is None and not torch.cuda.is_initialized(), 'profile/CUDA cleanup differs')
record = observer.result if observer is not None else None
if record:
    for artifact in record['artifacts']:
        artifact['source'] = base64.b64encode(c.read(Path(artifact['path']))).decode()
cache = Path(os.environ['TORCHINDUCTOR_CACHE_DIR'])
cache_files = list(cache.rglob('*'))
cache_bytes = sum(p.stat().st_size for p in cache_files if p.is_file())
c.require(cache_bytes <= 256 * 1024**2 and len(cache_files) <= 4096, 'cache evidence budget exceeded')
c.source_check(root / 'package', manifest)
c.write(part / 'result.json', c.wire(dict(status='NATIVE_CPU_CHILD_PASS', role=role, job_id=job,
    nonce=nonce, release_sha256=digest, pid=os.getpid(), python=sys.version.split()[0], torch=str(torch.__version__),
    affinity=sorted(os.sched_getaffinity(0)), threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
    before=before, after=after, eager=eager_record, outputs=output_record, backend=record,
    cache_root=str(cache), cache_bytes=cache_bytes, profiler_removed=True, source_postcheck=True,
    cuda_initialized=False, production_model_loaded=False, ready_for_gpu=False)))
faulthandler.cancel_dump_traceback_later()
phase('CHILD_PASS')
