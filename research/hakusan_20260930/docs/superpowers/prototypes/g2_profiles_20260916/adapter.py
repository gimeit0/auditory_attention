"""Functions embedded into a NEW diagnostic candidate before attestation issuance.

This is preparation only, not an authority to run a production matrix. Names are
prefixed to avoid changing the parent diagnostic namespace. No global patch of
torch.compile, loader, model forward, RNG reset, or old frozen runtime.
"""
import hashlib as _g2_hashlib
import json as _g2_json
import os as _g2_os
import random as _g2_random


def _g2_require(ok, message):
    if not ok:
        raise RuntimeError('G2 preparation: ' + message)


def _g2_wire(value):
    return (_g2_json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def _g2_expected(name):
    _g2_require(type(name) is str and name in ('R', 'C', 'D', 'E'), 'unknown profile')
    tf32 = name in ('R', 'D')
    return dict(deterministic_algorithms=True, cudnn_deterministic=True, cudnn_benchmark=False,
                float32_matmul_precision='high' if tf32 else 'highest',
                cuda_matmul_allow_tf32=tf32, cudnn_allow_tf32=tf32)


def _g2_read_runtime(torch_api):
    return dict(deterministic_algorithms=torch_api.are_deterministic_algorithms_enabled(),
                cudnn_deterministic=torch_api.backends.cudnn.deterministic,
                cudnn_benchmark=torch_api.backends.cudnn.benchmark,
                float32_matmul_precision=torch_api.get_float32_matmul_precision(),
                cuda_matmul_allow_tf32=torch_api.backends.cuda.matmul.allow_tf32,
                cudnn_allow_tf32=torch_api.backends.cudnn.allow_tf32)


def _g2_check_runtime(actual, name):
    expected = _g2_expected(name)
    _g2_require(type(actual) is dict and set(actual) == set(expected)
                and all(type(actual[k]) is type(v) and actual[k] == v for k, v in expected.items()),
                'runtime readback differs from profile ' + name)


def _g2_before_configuration(torch_api, trust_domain):
    _g2_require(trust_domain in ('production', 'hermetic-test'), 'unknown provenance domain')
    if trust_domain == 'production':
        _g2_require(str(torch_api.__version__) == '2.1.1+cu118', 'unreviewed production Torch')
        _g2_require(not torch_api.cuda.is_initialized(), 'CUDA already initialized before CUBLAS configuration check')
        _g2_require(_g2_os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8', 'missing pre-CUDA CUBLAS workspace config')


def _g2_apply_runtime(torch_api, name):
    # Frozen configure_runtime is called ONCE by the parent immediately before
    # this function. Only the two predeclared precision variables change here.
    _g2_check_runtime(_g2_read_runtime(torch_api), 'R')
    expected = _g2_expected(name)
    if name in ('C', 'E'):
        torch_api.set_float32_matmul_precision('highest')
        torch_api.backends.cuda.matmul.allow_tf32 = False
        torch_api.backends.cudnn.allow_tf32 = False
    _g2_check_runtime(_g2_read_runtime(torch_api), name)
    return expected


def _g2_rng(torch_api):
    import numpy as np
    numpy = np.random.get_state()
    payload = repr(_g2_random.getstate()).encode() + numpy[1].tobytes() + repr((numpy[0], *numpy[2:])).encode()
    payload += bytes(torch_api.get_rng_state().tolist())
    if torch_api.cuda.is_initialized():
        for state in torch_api.cuda.get_rng_state_all():
            payload += bytes(state.tolist())
    return _g2_hashlib.sha256(payload).hexdigest()


def _g2_path(name):
    if name == 'model._orig_mod':
        return 'model'
    return 'model.' + name[len('model._orig_mod.'):] if name.startswith('model._orig_mod.') else name


def _g2_state(model, torch_api, wrapper):
    modules = {}
    for name, module in model.named_modules(remove_duplicate=False):
        if module is wrapper:
            continue
        path = _g2_path(name)
        _g2_require(path not in modules, 'ambiguous canonical module path')
        _g2_require(module.training is False and not module._forward_hooks and not module._forward_pre_hooks,
                    'all modules must be eval and unobserved')
        modules[path] = (id(module), id(type(module)), bool(module.training))
    tensors, objects = {}, {}
    for kind, pairs in (('parameter', model.named_parameters(remove_duplicate=False)),
                        ('buffer', model.named_buffers(remove_duplicate=False))):
        for name, tensor in pairs:
            _g2_require(type(tensor) in (torch_api.Tensor, torch_api.nn.Parameter), 'tensor subclass rejected')
            _g2_require(not tensor.requires_grad and tensor.layout == torch_api.strided, 'unfrozen or unsupported state')
            key = kind + ':' + _g2_path(name)
            _g2_require(key not in tensors, 'ambiguous canonical state path')
            if tensor.is_floating_point() or tensor.is_complex():
                _g2_require(bool(torch_api.isfinite(tensor).all()), 'nonfinite model state')
            raw = tensor.detach().contiguous().reshape(-1).view(torch_api.uint8).cpu().numpy().tobytes()
            tensors[key] = dict(shape=list(tensor.shape), dtype=str(tensor.dtype), device=str(tensor.device),
                                sha256=_g2_hashlib.sha256(raw).hexdigest())
            objects[key] = (id(tensor), tensor.data_ptr(), tuple(tensor.stride()), tensor.storage_offset())
    return dict(modules=modules, objects=objects, tensors=tensors)


def _g2_adapt_loaded_model(model, report, name, trust_domain):
    import torch
    from torch._dynamo.eval_frame import OptimizedModule
    _g2_require(trust_domain in ('production', 'hermetic-test'), 'unknown provenance domain')
    _g2_check_runtime(_g2_read_runtime(torch), name)
    _g2_require(isinstance(model, torch.nn.Module) and 'model' in vars(model).get('_modules', {}), 'registered self.model required')
    wrapper = model._modules['model']
    _g2_require(type(wrapper) is OptimizedModule, 'exact native OptimizedModule required after strict load')
    _g2_require([path for path, item in model.named_modules(remove_duplicate=False) if type(item) is OptimizedModule] == ['model'],
                'one unique compiled wrapper at model required')
    _g2_require(set(wrapper._modules) == {'_orig_mod'} and not wrapper._parameters and not wrapper._buffers,
                'wrapper owns unexpected state/modules')
    _g2_require(wrapper.training is False and not wrapper._forward_hooks and not wrapper._forward_pre_hooks, 'wrapper mode/hooks differ')
    original = wrapper._modules['_orig_mod']
    if trust_domain == 'production':
        _g2_require(str(torch.__version__) == '2.1.1+cu118', 'unreviewed production Torch')
        _g2_require(report['model_module']['sha256'] == '6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9', 'frozen model source differs')
        _g2_require(type(model).__module__ == 'src.spatial_attn_lightning' and type(model).__name__ == 'BinauralAttentionModule', 'production root type differs')
        _g2_require(type(original).__module__ == 'src.spatial_attn_architecture'
                    and type(original).__name__ == 'BinauralAuditoryAttentionCNN', 'production inner type differs')
        from torch._dynamo import eval_frame
        _g2_require(vars(eval_frame).get('most_recent_backend', False) is None, 'backend is not cold')
    runtime_before, rng_before = _g2_read_runtime(torch), _g2_rng(torch)
    state_before = _g2_state(model, torch, wrapper)
    compiled = name in ('R', 'C')
    if not compiled:
        # Preserve strict checkpoint loading and exact Parameter/buffer objects.
        # Change just the registered dispatch edge, BEFORE any new attestation.
        torch.nn.Module.__setattr__(model, 'model', original)
    state_after = _g2_state(model, torch, wrapper)
    _g2_require(state_before == state_after, 'unwrapping changed model identity/state')
    _g2_require(model._modules['model'] is (wrapper if compiled else original), 'dispatch edge differs')
    _g2_require(runtime_before == _g2_read_runtime(torch) and rng_before == _g2_rng(torch), 'adaptation changed RNG/runtime')
    return dict(schema_version=1, profile=name, trust_domain=trust_domain, status='PRE_ATTESTATION_ADAPTED',
                strict_load_preserved=True, wrapper_path='model', original_path='model._orig_mod',
                active_path='model' if not compiled else 'model._orig_mod', compiled_wrapper_retained=compiled,
                state_mapping='model._orig_mod.* -> model.*' if not compiled else 'identity',
                canonical_state_sha256=_g2_hashlib.sha256(_g2_wire(state_after['tensors'])).hexdigest(),
                state_object_identity_preserved=True, rng_unchanged=True, runtime_unchanged=True,
                compiler_context_entered=False, compiled_execution_verified=False, production_ready=False)


def _g2_backend_gate(*, compiled, context_entered, target_backend, generated_graphs, compiled_execution_verified):
    # Explicitly DO NOT turn the old lifecycle.entered flag into an execution
    # certificate. The production collector of target-bound backend evidence is
    # still a separate integration gate; CPU backend='eager' cannot satisfy it.
    _g2_require(all(type(x) is bool for x in (compiled, context_entered, compiled_execution_verified)), 'backend flags must be bool')
    _g2_require(type(generated_graphs) is int and generated_graphs >= 0, 'graph count invalid')
    if compiled:
        _g2_require(context_entered and target_backend == 'inductor' and generated_graphs > 0 and compiled_execution_verified,
                    'compiled execution not verified')
    else:
        _g2_require(not context_entered and target_backend is None and generated_graphs == 0 and not compiled_execution_verified,
                    'unexpected compiler entry in eager profile')
    return 'BACKEND_EVIDENCE_CONDITIONS_MET_NOT_AN_AUTHORITY'
