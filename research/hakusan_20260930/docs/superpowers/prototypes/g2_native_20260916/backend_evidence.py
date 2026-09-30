"""Target-bound PyTorch 2.1.1 compile/artifact call observer candidate.

No model hook, compiler callback replacement, or tensor copying. Profiling can
still affect compilation/overhead: production interference validation required.
"""
import hashlib
import importlib
from pathlib import Path
import sys
import threading
import types

PINS = {
    'torch': '7261130fcc9dae49bb38843604ae2d0cab8d6b7277eb57b5dbc1559e35e34be1',
    'torch._dynamo.eval_frame': 'a98df135208704b66f681646a3d9649b75cbe5a3093fc59e4650b44460c1921b',
    'torch._inductor.compile_fx': 'f59ef50fc045e4d3d6a38f1576bd4fd4f9287128cbf4b6ff5534e0d7b3fe635d',
    'torch._inductor.codecache': '6d21a794502ced94ae5bb21a82968442cb049707c5c358161cb7a37b5c98295d',
}


def require(ok, message):
    if not ok:
        raise RuntimeError('G2 backend evidence: ' + message)


def function_codes(function):
    seen, codes = set(), []
    while type(function) is types.FunctionType:
        require(id(function) not in seen and len(seen) < 32, 'wrapper cycle/budget')
        seen.add(id(function))
        codes.append(function.__code__)
        function = vars(function).get('__wrapped__')
    return codes


def source_codes(raw, filename):
    pending, result = [compile(raw, filename, 'exec', dont_inherit=True)], []
    while pending:
        code = pending.pop()
        result.append(code)
        require(len(result) < 10000, 'source code budget')
        pending.extend(v for v in code.co_consts if type(v) is types.CodeType)
    return result


class CallLedger:
    """In-process event matcher, not a trusted verifier of caller-created events."""
    def __init__(self, compiler, compiler_code, graph_code, graph_type, cache_root):
        self.compiler, self.compiler_code = compiler, compiler_code
        self.graph_code, self.graph_type = graph_code, graph_type
        self.cache_root = Path(cache_root).resolve()
        self.active_compilers, self.artifact_frames = {}, {}
        self.graphs, self.compiler_calls, self.compiler_returns = {}, 0, 0
        self.failed, self.thread = False, threading.get_ident()

    def observe(self, frame, event, arg):
        if event not in ('call', 'return'):
            return
        require(threading.get_ident() == self.thread, 'unexpected thread')
        code = frame.f_code
        if code is self.compiler_code:
            require(frame.f_locals.get('self') is self.compiler, 'other compiler in target interval')
            if event == 'call':
                self.compiler_calls += 1
                self.active_compilers[id(frame)] = frame
            else:
                require(id(frame) in self.active_compilers and callable(arg), 'compiler failed or unpaired return')
                del self.active_compilers[id(frame)]
                self.compiler_returns += 1
        elif code is self.graph_code and event == 'return':
            ancestor, owned = frame.f_back, False
            for _ in range(1024):
                if ancestor is None:
                    break
                if id(ancestor) in self.active_compilers:
                    owned = True
                    break
                ancestor = ancestor.f_back
            require(owned and type(arg) is self.graph_type, 'generated graph not owned by target compiler')
            fn = arg.compiled_artifact
            path = Path(arg.artifact_path)
            require(type(fn) is types.FunctionType and fn.__closure__ is None, 'unsupported compiled artifact callable')
            require(path.is_absolute() and path.resolve().is_relative_to(self.cache_root)
                    and not path.is_symlink() and path.is_file() and path.stat().st_size <= 4 * 1024**2,
                    'artifact outside fresh bounded cache')
            require(fn.__code__.co_filename == str(path) and fn.__globals__.get('call') is fn,
                    'generated callable identity differs')
            raw = path.read_bytes()
            require(fn.__code__ in source_codes(raw, str(path)), 'live artifact code differs from source')
            self.graphs[id(arg)] = dict(graph=arg, function=fn, code=fn.__code__, globals=fn.__globals__,
                                       path=str(path), key=arg.cache_key, sha256=hashlib.sha256(raw).hexdigest(),
                                       calls=0, returns=0)
        else:
            for row in self.graphs.values():
                if code is row['code']:
                    require(frame.f_globals is row['globals'], 'artifact globals differ')
                    if event == 'call':
                        require(not self.active_compilers, 'artifact called inside compilation, not inference')
                        self.artifact_frames[id(frame)] = (frame, row)
                        row['calls'] += 1
                    else:
                        require(id(frame) in self.artifact_frames and arg is not None, 'artifact failed/unpaired return')
                        self.artifact_frames.pop(id(frame))
                        row['returns'] += 1
                    break

    def callback(self, frame, event, arg):
        try:
            self.observe(frame, event, arg)
        except BaseException:
            self.failed = True
            raise

    def finish(self):
        require(not self.failed and not self.active_compilers and not self.artifact_frames, 'incomplete event sequence')
        require(self.compiler_calls == self.compiler_returns > 0 and self.graphs, 'no target-generated graph')
        artifacts = []
        for row in self.graphs.values():
            require(row['function'].__code__ is row['code'] and row['function'].__globals__ is row['globals']
                    and row['graph'].compiled_artifact is row['function'], 'artifact binding changed')
            require(row['calls'] == row['returns'] > 0, 'generated artifact not successfully executed')
            require(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() == row['sha256'], 'artifact source changed')
            artifacts.append({k: row[k] for k in ('path', 'key', 'sha256', 'calls', 'returns')})
        return dict(compiler_calls=self.compiler_calls, compiler_returns=self.compiler_returns,
                    artifacts=artifacts, target_generated_artifacts_executed=True,
                    production_ready=False, interference_validated=False)


class BackendEvidence:
    def __init__(self, wrapper, cache_root):
        modules = {name: importlib.import_module(name) for name in PINS}
        checked_codes = {}
        for name, module in modules.items():
            path = Path(module.__file__)
            require(path.is_file() and path.stat().st_size < 1024**2
                    and hashlib.sha256(path.read_bytes()).hexdigest() == PINS[name], 'compiler source differs: ' + name)
            checked_codes[name] = source_codes(path.read_bytes(), str(path))
        torch, ef = modules['torch'], modules['torch._dynamo.eval_frame']
        require(str(torch.__version__) == '2.1.1+cu118' and type(wrapper) is ef.OptimizedModule,
                'exact reviewed wrapper/runtime required')
        context = vars(wrapper)['dynamo_ctx']
        require(type(context) is ef.OptimizeContext, 'exact optimization context required')
        enter = vars(context)['on_enter']
        require(type(enter) is types.FunctionType and enter.__globals__ is vars(ef)
                and enter.__code__ in checked_codes['torch._dynamo.eval_frame'], 'live context source differs')
        cells = dict(zip(enter.__code__.co_freevars, enter.__closure__))
        require(set(cells) == {'compiler_fn'}, 'compiler closure differs')
        compiler = cells['compiler_fn'].cell_contents
        require(type(compiler) is torch._TorchCompileInductorWrapper and vars(compiler) == dict(config={}, dynamic=None),
                'exact default Inductor target required')
        require(ef.most_recent_backend is None and not sys.getprofile() and not threading.getprofile(),
                'cold unprofiled process required')
        fx = modules['torch._inductor.compile_fx']
        codes = function_codes(fx.fx_codegen_and_compile)
        target = [c for c in codes if c.co_name == 'fx_codegen_and_compile']
        require(len(target) == 1, 'codegen function identity differs')
        require(target[0] in checked_codes['torch._inductor.compile_fx']
                and type(compiler).__call__.__globals__ is vars(torch)
                and type(compiler).__call__.__code__ in checked_codes['torch'], 'live compiler source differs')
        self.wrapper, self.context, self.enter, self.compiler = wrapper, context, enter, compiler
        self.modules = modules
        self.ledger = CallLedger(compiler, type(compiler).__call__.__code__, target[0],
                                 modules['torch._inductor.codecache'].CompiledFxGraph, cache_root)
        self.profile = self.ledger.callback
        self.used = False

    def __enter__(self):
        require(not self.used and sys.getprofile() is None, 'single unprofiled interval required')
        self.used = True
        sys.setprofile(self.profile)
        return self

    def __exit__(self, kind, value, traceback):
        current = sys.getprofile()
        sys.setprofile(None)
        require(current is self.profile and kind is None, 'profile changed or target operation failed')
        require(vars(self.wrapper)['dynamo_ctx'] is self.context and vars(self.context)['on_enter'] is self.enter,
                'target compiler binding changed')
        self.result = self.ledger.finish()
        self.result['compiler_sources'] = dict(PINS)
