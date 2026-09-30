"""Candidate compute child. Fixed real B2; never a login-node probe or submitter.

Refuses absent new authorization. The original v18 inference APIs stay intact;
startup and HOME-preserving scratch are explicitly NEW candidate policies.
"""
import ast
import fcntl
import hashlib
import os
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
from dataclasses import asdict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job_contract as contract  # noqa: E402
import process_runner as process  # noqa: E402
import scratch_adapter  # noqa: E402


def lifetime(cuda, archive_adapter, archive, scratch_type, gate, scratch, writer, lease):
    contract.require(type(gate) is cuda.bridge.BaselineBridge and not gate.hermetic_test and gate.cell == "B2"
                     and gate.context["device"].type == "cuda"
                     and gate.attestation.frozen_capability.trust_domain == "production", "original production gate required")
    contract.require(type(scratch) is scratch_type and scratch.anchors and str(scratch.root) == gate.context["scratch_root"],
                     "exact private candidate scratch required")
    contract.require(type(writer) is archive.PassArchive and writer.binding["pid"] == os.getpid()
                     and writer.binding["role"] == ("reference" if lease is None else "observed"), "archive identity differs")
    authority = gate.diag._ISSUED_COMPILER_LIFECYCLES.get(id(gate.model))
    contract.require(type(authority) is gate.diag._CompilerLifecycle and not authority.entered, "cold original compiler required")
    authority.verify()
    if lease is None:
        contract.require(all(not m._forward_hooks and not m._forward_pre_hooks for m in gate.model.modules()), "reference contains hooks")
        tree, audit = scratch_adapter.reference_loop(archive_adapter, scratch_type)
        namespace = dict(vars(cuda.bridge))
        namespace["_private_scratch_type"] = scratch_type
    else:
        contract.require(type(lease) is cuda.CudaCompiledLease, "exact candidate lease required")
        tree, audit = archive_adapter.derive("observed")
        namespace = dict(vars(cuda))
    collector = archive_adapter.PassCollector(gate, scratch, writer, spill=lease is not None)
    collector.names = (cuda.bridge.replay.BOUNDARIES, cuda.bridge.replay.COARSE)
    exec(compile(ast.fix_missing_locations(tree), "<gpu-pair-archived-lifetime>", "exec"), namespace)
    if lease is None:
        summary = namespace["archived_reference"](gate, scratch=scratch, _archiver=collector)
        authority.verify()
    else:
        summary = namespace["archived_observed"](gate, lease, _archiver=collector)
        contract.require(lease.closed and authority.revoked, "observer cleanup missing")
    contract.require(bool(authority.entered), "actual compiler backend not entered")
    return {"summary": summary, "loop_audit": audit, "archive": writer.finish()}


import contextlib as _startup_contextlib
sys.path.insert(0, str(HERE.parent / "targeted_gpu_startup_20260914"))
import startup as _startup

def run(role, package_sha, nonce):
    contract.child_cold_gate(os.environ)
    contract.require(role in ('reference', 'observed'), 'fixed pair role required')
    contract.check_sources(package_sha)
    contract.check_authorization(contract.REMOTE, package_sha, nonce)
    job = os.environ['SLURM_JOB_ID']
    output = contract.REMOTE / 'artifacts' / role
    output.mkdir(mode=448, exist_ok=False)
    result = {'status': 'GPU_CHILD_FAILED', 'role': role, 'job_id': job, 'worker_pid': os.getpid(), 'package_sha256': package_sha, 'pair_nonce': nonce, 'input_sha256': contract.FREEZE_SHA, 'ready_for_gpu': False, 'jobs_submitted': 0}
    process.write_once(output / 'STARTED.json', result)
    request = lease = writer = store = prepared = diag = None
    lock = None
    error = None
    startup_stack = _startup_contextlib.ExitStack()
    try:
        startup_lease = startup_stack.enter_context(_startup.open_scratch(contract, role))
        sys.path.insert(0, str(HERE.parent / 'targeted_production_preparation_20260913'))
        sys.path.insert(0, str(HERE.parent / 'targeted_gpu_pair_20260913'))
        import cuda_registration as cuda
        import archive_adapter
        from bounded_archive import archive
        contract.require(str(cuda.torch.__version__) == '2.1.1+cu118' and cuda.torch.cuda.is_available(), 'actual reviewed CUDA torch required')
        contract.require(cuda.torch.cuda.device_count() == 1 and 'A100' in cuda.torch.cuda.get_device_name(0), 'one actual A100 required')
        lock = os.open(contract.V4 / 'state/evaluation.lock', os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contract.pinned_read(contract.V4 / 'state/evaluation.lock', contract.LOCK_SHA)
        diag = cuda.bridge.load_v18(contract.V18 / 'tools/diagnose_batch_invariance.py')
        scratch_type, scope, _ = _startup.bind_scope(startup_lease, diag, cuda.bridge)
        args = SimpleNamespace(job_id=job, expected_input_freeze_sha256=contract.FREEZE_SHA)
        scratch_role = 'reference_cold' if role == 'reference' else 'B2'
        with scope(args, scratch_role) as scratch:
            bundle = diag._load_worker_inputs(contract.FREEZE_SHA)
            context = bundle['context']
            context['cell_id'] = 'B2'
            process.write_once(output / 'PRECHECK.json', diag._portable_worker_audit(bundle['audit']))
            sources = {r['relative_path']: r for r in bundle['audit']['snapshot_files']}
            with diag.frozen_scene_context(context['snapshot_files'], sources) as scene:
                context['scene_api'] = scene
                if role == 'reference':
                    prepared = diag.prepare_formal40_worker(context, allow_cpu=False)
                else:
                    store = cuda.life.capture.CaptureStore(output / 'captures', max_records=168)
                    request = cuda.ProductionRequest(diag, context, store, 'B2', contract.pinned_read(contract.WORKSPACE / contract.PLAN), contract.pinned_read(contract.V18 / 'input_freeze.json', contract.FREEZE_SHA))
                    prepared, lease, preparation = cuda.prepare_production(request)
                    process.write_once(output / 'PREPARATION.json', preparation)
                software = diag._worker_software_record(prepared['device'])
                process.write_once(output / 'ENVIRONMENT.json', software)
                run_context = {**context, **prepared, 'scratch_root': str(scratch.root), 'cache_roots': scratch.cache_roots, 'worker_environment': {**scratch.record, 'software': software}}
                gate = cuda.bridge.BaselineBridge(diag, run_context, bundle['trials'], contract.pinned_read(contract.WORKSPACE / contract.PARENT, cuda.bridge.PARENT_SHA), cuda.bridge.PARENT_SHA, 'B2')
                binding = {'pair_nonce': nonce, 'role': role, 'pid': os.getpid(), 'cell': 'B2', 'input_sha256': contract.FREEZE_SHA, 'package_sha256': package_sha}
                writer = archive.PassArchive(output / 'arrays', binding)
                result['lifetime'] = lifetime(cuda, archive_adapter, archive, scratch_type, gate, scratch, writer, lease)
                if lease is not None:
                    contract.require(len(store.refs) == 168 and len(lease.records) == 34, 'complete capture schedule required')
                    contract.require(cuda.life._wire(lease.records) == lease.record_seal, 'closed observer ledger changed')
                    process.write_once(output / 'OBSERVER.json', {'plan': asdict(lease.plan), 'records': lease.records, 'refs': [asdict(r) for r in store.refs], 'ledger_sha256': hashlib.sha256(lease.record_seal).hexdigest()})
                diag._revalidate_worker_inputs(bundle)
                process.write_once(output / 'POSTCHECK.json', diag._portable_worker_audit(diag.audit_inputs(context=context, diagnostic_root=diag.DIAGNOSTIC_ROOT)))
                contract.require(contract.pinned_read(output / 'PRECHECK.json') == contract.pinned_read(output / 'POSTCHECK.json'), 'bound inputs changed')
                result.update(status='GPU_CHILD_CANDIDATE_COMPLETE', cell='B2', production_model_loaded=True, cuda_initialized=cuda.torch.cuda.is_initialized(), input_checks_unchanged=True)
    except BaseException as exc:
        traceback.print_exc()
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        cleanup_errors = []
        if error is not None and store is not None:
            try:
                process.write_once(output / 'OBSERVER_PARTIAL.json', {'complete': False, 'refs': [asdict(r) for r in store.refs], 'records': lease.records if lease is not None else [], 'current': {k: lease.current[k] for k in ('pass_id', 'batch_index', 'trials', 'index', 'captures')} if lease is not None and lease.current is not None else None, 'scope': 'partial failure evidence only; not verified numerical results'})
            except BaseException as exc:
                cleanup_errors.append({'type': type(exc).__name__, 'message': str(exc)})
        for item in (request, lease, writer, store, startup_stack):
            if item is not None:
                try:
                    item.close()
                except BaseException as exc:
                    cleanup_errors.append({'type': type(exc).__name__, 'message': str(exc)})
        if prepared is not None:
            try:
                diag._revoke_attestation(prepared['_formal40_worker_attestation'])
                authority = diag._ISSUED_COMPILER_LIFECYCLES.get(id(prepared['model']))
                if authority is not None:
                    authority.revoked = True
                result['hooks_removed'] = all((not m._forward_hooks and (not m._forward_pre_hooks) for m in prepared['model'].modules()))
            except BaseException as exc:
                cleanup_errors.append({'type': type(exc).__name__, 'message': str(exc)})
        if lock is not None:
            os.close(lock)
        try:
            contract.check_sources(package_sha)
        except BaseException as exc:
            cleanup_errors.append({'type': type(exc).__name__, 'message': str(exc)})
        result.update(error=error, cleanup_errors=cleanup_errors)
        if error or cleanup_errors:
            result['status'] = 'GPU_CHILD_FAILED'
        process.write_once(output / 'CHILD.json', result)
    return 0 if result['status'] == 'GPU_CHILD_CANDIDATE_COMPLETE' else 2

if __name__ == "__main__":
    os.umask(0o077)
    contract.require(len(sys.argv) == 4, "expected role, package SHA, pair nonce")
    raise SystemExit(run(*sys.argv[1:]))
