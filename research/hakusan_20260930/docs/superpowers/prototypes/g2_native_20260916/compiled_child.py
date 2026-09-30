"""One native CPU toy Inductor check, not a production model or acceptance test."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import faulthandler

started = time.monotonic()


def phase(name):
    print('G2_PHASE=' + json.dumps(dict(phase=name, elapsed_seconds=time.monotonic() - started)), flush=True)


faulthandler.enable()
faulthandler.dump_traceback_later(30, repeat=False)
phase('IMPORT_TORCH_BEGIN')
import torch
import backend_evidence
phase('IMPORT_TORCH_END')

torch.set_num_threads(1)
assert str(torch.__version__) == '2.1.1+cu118'
assert sys.version.split()[0] == '3.11.5'
assert not torch.cuda.is_initialized()
assert len(os.sched_getaffinity(0)) == 1
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


model = Toy().eval().requires_grad_(False)
inputs = (torch.arange(64, dtype=torch.float32).reshape(16, 4) / 100,
          torch.arange(4, dtype=torch.float32).reshape(1, 4) / 100)
with torch.inference_mode():
    eager = [model(x) for x in inputs]
    compiled = torch.compile(model, mode='default')
    phase('OBSERVER_PREPARE_BEGIN')
    observer = backend_evidence.BackendEvidence(compiled, Path(os.environ['TORCHINDUCTOR_CACHE_DIR']))
    phase('OBSERVER_PREPARE_END')
    with observer:
        outputs = []
        for index, x in enumerate(inputs):
            phase('FORWARD_' + str(index) + '_BEGIN')
            outputs.append(compiled(x))
            phase('FORWARD_' + str(index) + '_END')
    difference = [float((x - y).abs().max()) for x, y in zip(eager, outputs)]
    assert all(bool(torch.isfinite(x).all()) for x in outputs)
    assert max(difference) <= 1e-6
assert sys.getprofile() is None
assert not torch.cuda.is_initialized()
faulthandler.cancel_dump_traceback_later()
record = observer.result
for artifact in record['artifacts']:
    raw = Path(artifact['path']).read_bytes()
    artifact['source'] = base64.b64encode(raw).decode()
record.update(status='NATIVE_TOY_INDUCTOR_EXECUTION_PASS', python=sys.version.split()[0], torch=str(torch.__version__),
              cpu_affinity=sorted(os.sched_getaffinity(0)), cuda_initialized=False, production_model_loaded=False,
              production_ready=False, jobs_submitted=0, batch_sizes=[16, 1], eager_max_abs=difference,
              profiler_removed=True, real_g2_profiles_validated=False, interference_validated=False)
print('G2_COMPILED_CHILD=' + json.dumps(record, sort_keys=True), flush=True)
