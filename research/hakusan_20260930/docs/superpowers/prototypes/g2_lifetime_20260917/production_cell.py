"""Unreleased G2 production cell lifetime; no CLI or resource authorization.

The separately reviewed launcher still owns release/Slurm authorization, cold
process supervision, scratch-parent selection, archive writer and independent
verification. This component does not provide any of those approvals.
"""
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
PINS = {
    'g2_scratch_20260917/scratch_binding.py':
        'f0d16a11c712c9c1c96de6a5906efc4ac3978d012660eb33399672a681b2e271',
    'g2_inputs_20260917/input_binding.py':
        '6a99559df859bb88cdf730d7dcd1bf72caf2f2f04800ae69781da23e64103896',
}
LOCK_SHA = '63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710'


def require(ok, message):
    if not ok:
        raise RuntimeError('G2 lifetime: ' + message)


def load_component(relative):
    path = HERE.parent / relative
    require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)),
            'regular nonsymlink component required')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PINS[relative], 'component source changed')
    spec = importlib.util.spec_from_file_location('g2_lifetime_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), vars(module))
    return module


scratch_api = load_component('g2_scratch_20260917/scratch_binding.py')
input_api = load_component('g2_inputs_20260917/input_binding.py')


class CellFailure(RuntimeError):
    """Preserve both primary and cleanup failures; never return partial success."""
    def __init__(self, primary, cleanup):
        self.primary, self.cleanup = primary, tuple(cleanup)
        super().__init__('G2 cell failed: ' + repr(primary) + '; cleanup=' + repr(self.cleanup))


class ProductionCell:
    """One new profile identity, real strict-load and two original trace passes.

    Construct before numeric imports. The parent sets the isolated environment
    using the same Binding.environment policy; HOME must remain the real HOME.
    consume(result, metadata) persists all arrays while the scene, model and
    mmap scopes remain alive. Its bounded JSON receipt is NOT independent
    artifact verification. No result is returned until all scopes close.
    """
    def __init__(self, bridge, diag, *, job, freeze_sha, production_bytes, parent_path):
        scratch_api.cold()
        require(type(job) is str and job.isascii() and job.isdecimal()
                and not job.startswith('0') and len(job) <= 20
                and os.environ.get('SLURM_JOB_ID') == job, 'bound canonical Slurm job required')
        self.bridge, self.diag, self.job = bridge, diag, job
        self.freeze_sha = freeze_sha
        self.binding = scratch_api.Binding(bridge, diag)
        self.parent_path = Path(parent_path)
        parent = input_api.read_stable(self.parent_path, input_api.MAX_JSON)
        self.inputs = input_api.WorkerInputs(bridge, diag, freeze_sha, production_bytes, parent)
        self.pid, self.used = os.getpid(), False
        self.cleanup_errors = []

    def source_check(self):
        self.bridge._check_module(self.diag)
        self.bridge.read(self.bridge.__file__, input_api.BRIDGE_SHA)
        for relative, digest in PINS.items():
            require(hashlib.sha256(input_api.read_stable(HERE.parent / relative, 2 * 1024**2)).hexdigest()
                    == digest, 'lifetime component changed')
        require(input_api.read_stable(self.parent_path, input_api.MAX_JSON) == self.inputs.parent_raw,
                'historical data reference changed')

    @contextlib.contextmanager
    def exclusive_lock(self):
        """Keep old lock bytes intact; never steal or delete the lock file."""
        path = self.diag.V4_ROOT / 'state/evaluation.lock'
        raw = input_api.read_stable(path, 4096)
        require(hashlib.sha256(raw).hexdigest() == LOCK_SHA, 'v4 lock content differs')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            initial = os.fstat(fd)
            identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                                     info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)

            def check():
                require(identity(os.fstat(fd)) == identity(initial)
                        == identity(path.stat(follow_symlinks=False))
                        and os.pread(fd, 4097, 0) == raw
                        and input_api.read_stable(path, 4096) == raw, 'held v4 lock changed')
            check()
            try:
                yield check
            finally:
                check()
        finally:
            # Closing releases this descriptor's flock, including failed setup.
            os.close(fd)

    def runtime_check(self):
        import torch
        require(sys.platform == 'linux' and sys.version.split()[0] == '3.11.5'
                and str(torch.__version__) == '2.1.1+cu118', 'native runtime required')
        require(not torch.cuda.is_initialized(), 'CUDA initialized before configuration')
        require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8', 'pre-CUDA CUBLAS policy differs')
        if self.diag._G2_PROFILE in ('R', 'C'):
            self.bridge.preload_compiled_backend()

    def device_check(self, prepared):
        import torch
        require(prepared['device'].type == 'cuda' and torch.cuda.is_initialized()
                and torch.cuda.device_count() == 1
                and 'A100' in torch.cuda.get_device_name(0), 'one actual A100 required')

    def revoke(self):
        # Own cold process only. Include authorities issued by a preparation
        # that failed before returning, not merely the successfully returned one.
        for attestation in tuple(self.diag._ISSUED_FORMAL40_ATTESTATIONS.values()):
            try:
                self.diag._revoke_attestation(attestation)
            except BaseException as error:
                self.cleanup_errors.append(error)
        for lifecycle in tuple(self.diag._ISSUED_COMPILER_LIFECYCLES.values()):
            try:
                lifecycle.revoked = True
            except BaseException as error:
                self.cleanup_errors.append(error)

    def execute(self, scratch, check_lock, consume):
        diag, bridge = self.diag, self.bridge
        bundle = self.inputs.load()  # original claim BEFORE numeric import/load
        self.runtime_check()
        context = dict(bundle['context'], cell_id=diag._G2_PROFILE)
        require(context['_frozen_context_capability'].trust_domain == 'production',
                'hermetic context cannot run as production')
        require(not diag._ISSUED_FORMAL40_ATTESTATIONS and not diag._ISSUED_COMPILER_LIFECYCLES,
                'pre-existing model authority in cold worker')
        sources = {r['relative_path']: r for r in bundle['audit']['snapshot_files']}
        with diag.frozen_scene_context(context['snapshot_files'], sources) as scene:
            context['scene_api'] = scene
            try:
                prepared = diag.prepare_formal40_worker(context, allow_cpu=False)
                self.device_check(prepared)
                run = {**context, **prepared, 'scratch_root': str(scratch.root),
                       'cache_roots': scratch.cache_roots,
                       'worker_environment': {**scratch.record,
                           'software': diag._worker_software_record(prepared['device'])}}
                gate = self.binding.bridge_type(diag, run, bundle['trials'], bundle['freeze']['trials'],
                                                old_freeze=self.parent_path)
                result = gate.run(scratch=scratch, cache_root=scratch.cache_roots['torchinductor'])
                require(result['status'] == 'G2_CELL_CANDIDATE_COMPLETE'
                        and result['trust_domain'] == 'production', 'production cell result required')
                self.inputs.revalidate()
                check_lock()
                commitments = tuple(bridge._commitment(diag, p) for p in result['passes'])
                require(len(commitments) == 2 and list(commitments) == result['pass_commitments'],
                        'two complete committed passes required')
                summary = input_api.canonical({k: v for k, v in result.items() if k != 'passes'})
                metadata = dict(job_id=self.job, pid=self.pid, profile=diag._G2_PROFILE,
                                input_freeze_sha256=self.freeze_sha, input_relation=self.inputs.proof,
                                preparation=prepared['attestation'], scratch=dict(scratch.record))
                rng_before = diag._get_trace().snapshot_rng_state()
                receipt = consume(result, json.loads(input_api.canonical(metadata)))
                require(type(receipt) is dict and 0 < len(input_api.canonical(receipt)) <= 1024**2,
                        'bounded archive receipt required')
                require(receipt.get('status') == 'G2_PASS_ARTIFACTS_WRITTEN'
                        and all(receipt.get(k) == metadata[k]
                                for k in ('job_id', 'pid', 'profile', 'input_freeze_sha256'))
                        and receipt.get('pass_commitments') == list(commitments)
                        and type(receipt.get('archive_manifest_sha256')) is str
                        and re.fullmatch('[a-f0-9]{64}', receipt['archive_manifest_sha256']),
                        'archive receipt identity/coverage differs')
                require(tuple(bridge._commitment(diag, p) for p in result['passes']) == commitments,
                        'archive callback changed pass content')
                require(input_api.canonical({k: v for k, v in result.items() if k != 'passes'}) == summary,
                        'archive callback changed cell summary')
                with gate._scope():
                    gate._live('g2_after_archive')
                require(diag._get_trace().snapshot_rng_state() == rng_before,
                        'archive callback changed RNG')
                scratch.verify_spills()
                self.inputs.revalidate()
                check_lock()
                self.source_check()
                return dict(status='G2_PRODUCTION_CELL_STORED_CANDIDATE', profile=diag._G2_PROFILE,
                            numeric=result['numeric'], pass_commitments=list(commitments),
                            archive_receipt=json.loads(input_api.canonical(receipt)),
                            input_freeze_sha256=self.freeze_sha, job_id=self.job,
                            independent_results_verified=False, production_ready=False,
                            production_interference_validated=False, jobs_submitted=0)
            finally:
                self.revoke()  # before the frozen scene scope is exited

    def run(self, consume):
        require(not self.used and os.getpid() == self.pid, 'single-use owner process required')
        self.used = True  # neither startup errors nor numeric failures permit retry
        result, primary = None, None
        try:
            require(callable(consume), 'coordinator archive callback required')
            scratch_api.cold()
            self.source_check()
            with self.exclusive_lock() as check_lock:
                with self.binding.scope(self.job, self.freeze_sha, 'observed') as scratch:
                    result = self.execute(scratch, check_lock, consume)
        except BaseException as error:
            primary = error
        # Also covers failures during loader/runtime setup or scene entry/exit.
        self.revoke()
        try:
            self.source_check()
        except BaseException as error:
            self.cleanup_errors.append(error)
        if primary is not None or self.cleanup_errors:
            raise CellFailure(primary, self.cleanup_errors) from primary
        return result
