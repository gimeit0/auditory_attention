"""Bounded synthetic CPU/API probe. No checkpoint, inference on GPU, or scheduler."""
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import time


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def probe(spec):
    started = time.monotonic()
    require(spec['mode'] in ('LOCAL_CPU', 'NATIVE_CPU'), 'unknown mode')
    adapter = base64.b64decode(spec['adapter'], validate=True)
    require(len(adapter) < 65536 and sha(adapter) == spec['adapter_sha256'], 'adapter differs')
    original_home = os.environ.get('HOME')
    os.environ.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    if hasattr(os, 'sched_getaffinity'):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    import torch
    require(not torch.cuda.is_initialized(), 'CUDA initialized')
    if spec['mode'] == 'NATIVE_CPU':
        require(sys.version.split()[0] == '3.11.5' and str(torch.__version__) == '2.1.1+cu118', 'unreviewed native runtime')
    torch.set_num_threads(1)
    namespace = {}
    exec(compile(adapter, '<sha-bound-g2-adapter>', 'exec'), namespace)

    class Toy(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = torch.compile(torch.nn.Linear(4, 8), backend='eager')
        def forward(self, x):
            return self.model(x)

    rows = []
    for name in ('R', 'C', 'D', 'E'):
        torch.use_deterministic_algorithms(True)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        # 2.1.1 original setup reads back high after allow_tf32=True. The newer
        # local Torch rejects some legacy medium/API combinations; local tests
        # start at that same high readback, not a claimed native configuration.
        torch.set_float32_matmul_precision('medium' if spec['mode'] == 'NATIVE_CPU' else 'high')
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        namespace['_g2_apply_runtime'](torch, name)
        model = Toy().eval().requires_grad_(False)
        wrapper, inner = model.model, model.model._orig_mod
        report = namespace['_g2_adapt_loaded_model'](model, {}, name, 'hermetic-test')
        require(model.model is (wrapper if name in ('R', 'C') else inner), 'wrong dispatch binding')
        rows.append(dict(profile=name, runtime=namespace['_g2_read_runtime'](torch), adaptation=report))
    # Inspect the real default compiler without calling the compiled function.
    wrapped = torch.compile(torch.nn.Linear(4, 8), mode='default')
    from torch._dynamo import eval_frame
    native_binding = None
    if spec['mode'] == 'NATIVE_CPU':
        context = vars(wrapped)['dynamo_ctx']
        enter = vars(context)['on_enter']
        closure = dict(zip(enter.__code__.co_freevars, enter.__closure__))
        compiler = closure['compiler_fn'].cell_contents
        require(type(compiler) is torch._TorchCompileInductorWrapper, 'default backend is not exact Inductor wrapper')
        require(vars(eval_frame)['most_recent_backend'] is None, 'probe unexpectedly entered compiler context')
        native_binding = dict(type_module=type(compiler).__module__, type_name=type(compiler).__name__,
                              compiler_entered=False, compiled_forward_called=False)
    modules = ['torch', 'torch._dynamo.eval_frame', 'torch._dynamo.convert_frame', 'torch._dynamo.utils',
               'torch._dynamo.backends.inductor', 'torch._inductor.compile_fx', 'torch._inductor.codecache']
    files = {}
    for name in modules:
        module = importlib.import_module(name)
        path = Path(module.__file__)
        require(path.suffix == '.py' and path.is_file() and not path.is_symlink()
                and path.stat().st_size < 1024**2, 'unsupported compiler source')
        raw = path.read_bytes()
        files[name] = dict(path=str(path), sha256=sha(raw), size=len(raw), source=base64.b64encode(raw).decode())
    require(not torch.cuda.is_initialized() and original_home == os.environ.get('HOME'), 'probe scope changed')
    return dict(status='G2_CPU_API_PASS', request_id=spec['request_id'], mode=spec['mode'],
                adapter_sha256=spec['adapter_sha256'], python=sys.version.split()[0], torch=str(torch.__version__),
                profiles=rows, native_binding=native_binding, compiler_sources=files,
                initial_precision_request='medium' if spec['mode'] == 'NATIVE_CPU' else 'high',
                cuda_initialized=False, production_model_loaded=False, compiled_forward_called=False,
                production_ready=False, jobs_submitted=0, home_unchanged=True,
                cpu_affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
                threads=torch.get_num_threads(), elapsed_seconds=time.monotonic() - started)


if __name__ == '__main__':
    # The transport places SPEC in globals; no remote source file is installed.
    def timeout(*_):
        raise TimeoutError('synthetic CPU probe reached 50 second limit')
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(50)
    try:
        result = probe(SPEC)
        print('G2_CPU_API_RESULT=' + json.dumps(result, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
