"""G2 in-process two-pass candidate; no CLI, freeze, scheduler or authority issuer.

Keeps the preparation candidate and v19 inference/validation functions intact.
The caller still owns cold process, frozen input reconstruction, scratch budget,
artifact persistence, independent verification and submission authorization.
"""
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import uuid

HERE = Path(__file__).resolve().parent
CORE_SHAS = {
    'R': 'd77b316ca1d3dfdc0954100c73dd51783a074974a5ebb1d69c655a11a6ecdebd',
    'C': '32b79a3264ff3f1da3b43cdfed8d509c8aaa40df8da20ee9b8fd15b97da1b189',
    'D': '92fbad73ee2efa665d529fc69267d9b9397941e571b43cbb5bf35fa54920167b',
    'E': '4302bb1d2fc21897ced6618006587d3776c1c7c5339c5906fbf46d99babfd864',
}
TRACE_SHA = 'fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b'
BACKEND_SHA = '018089bf401af07a076818f2e7d7b9347aff60572bd57951b6b3207f504179a4'
PROFILES_SHA = 'd5d83e810fef28c15835c28a583f1a5c4a4401adcf558e164ef3e5f46ea91227'
OLD_FREEZE_SHA = 'bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178'
_LOADED = {}
_PRELOADED_BACKEND = None


class BridgeError(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise BridgeError('G2 cell bridge: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected):
    path = Path(path).absolute()
    require(path.is_file() and path.stat().st_size <= 2 * 1024**2
            and not any(p.is_symlink() for p in (path, *path.parents)), 'bounded nonsymlink source required')
    raw = path.read_bytes()
    require(sha(raw) == expected, 'pinned bytes differ: ' + str(path))
    return raw


def _load(path, expected):
    path = Path(path).absolute()
    raw = read(path, expected)
    name = 'g2_cell_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True), vars(module))
    anchors = []
    for key, value in vars(module).items():
        if type(value) is types.FunctionType and value.__module__ == name:
            anchors.append((module, key, value, value.__code__))
        elif type(value) is type and value.__module__ == name:
            anchors.append((module, key, value, None))
            for attr, method in vars(value).items():
                if type(method) is types.FunctionType:
                    anchors.append((value, attr, method, method.__code__))
    _LOADED[id(module)] = (module, path, expected, tuple(anchors))
    return module


def _check_module(module):
    issued = _LOADED.get(id(module))
    require(issued is not None and issued[0] is module, 'source module not issued by pinned loader')
    read(issued[1], issued[2])
    for owner, name, value, code in issued[3]:
        require(getattr(owner, name) is value and (code is None or value.__code__ is code),
                'source callable changed: ' + name)


profiles = _load(HERE.parent / 'g2_profiles_20260916/profiles.py', PROFILES_SHA)


def load_candidate(path, profile):
    profiles.profile(profile)
    read(Path(path).with_name('numeric_trace.py'), TRACE_SHA)
    diag = _load(path, CORE_SHAS[profile])
    require(diag._G2_PROFILE == profile, 'derived profile differs')
    return diag


def preload_compiled_backend():
    """Call BEFORE preparing/sealing a real compiled worker; never issue authority."""
    global _PRELOADED_BACKEND
    import torch
    require(str(torch.__version__) == '2.1.1+cu118' and not torch.cuda.is_initialized(),
            'backend preload requires reviewed cold Torch')
    require(_PRELOADED_BACKEND is None, 'backend preload is single use')
    backend = _load(HERE.parent / 'g2_native_20260916/backend_evidence.py', BACKEND_SHA)
    # Avoid importing additional compiler modules after the old guard seals
    # the model's execution graph. BackendEvidence also checks live code later.
    for name, expected in backend.PINS.items():
        module = importlib.import_module(name)
        read(Path(module.__file__), expected)
    _PRELOADED_BACKEND = backend
    return dict(status='BACKEND_SOURCES_PRELOADED', production_ready=False)


def _cold_marker(*, hermetic_test):
    import torch
    import torch._dynamo.eval_frame as ef
    if str(torch.__version__) == '2.1.1+cu118':
        require('most_recent_backend' in vars(ef) and ef.most_recent_backend is None,
                'cold target compiler required')
        return True
    require(hermetic_test and str(torch.__version__) == '2.12.1', 'unreviewed native compiler state')
    # Local eager-only fixture coverage is NOT the 2.1.1 native cold-state check.
    return False


def _wire(diag, value):
    return diag._get_trace().canonical_json_bytes(value)


def _commitment(diag, result):
    require(type(result) is diag.PassResult, 'original PassResult required')
    digest = sha(_wire(diag, diag._pass_commitment_payload(result)))
    require(result.boundary_records.get('pass_commitment', {}).get('binding_sha256') == digest,
            'original pass commitment differs')
    return digest


def official_summary(left, right):
    """Finite-only numeric decision, NOT provenance or production acceptance."""
    import numpy as np
    names = ('pred_label', 'nll', 'p_target', 'p_probe_distractor')
    require(set(left) == set(right) == set(names), 'official output inventory differs')
    result = {}
    for name in names:
        a, b = left[name], right[name]
        require(type(a) is type(b) is np.ndarray and a.shape == b.shape == (32,)
                and a.dtype == b.dtype and a.dtype.kind in ('i' if name == 'pred_label' else 'f')
                and np.isfinite(a).all() and np.isfinite(b).all(), 'invalid official array: ' + name)
        if name == 'pred_label':
            require(((a >= 0) & (a < 800) & (b >= 0) & (b < 800)).all(), 'label out of range')
            result[name] = dict(flips=int(np.count_nonzero(a != b)), exact=bool(np.array_equal(a, b)))
        else:
            delta = np.abs(a.astype(np.float64) - b.astype(np.float64))
            result[name] = dict(max_abs=float(delta.max()), median_abs=float(np.median(delta)),
                                p95_abs=float(np.quantile(delta, .95)), p99_abs=float(np.quantile(delta, .99)),
                                above_atol=int(np.count_nonzero(delta > profiles.ATOL)))
    accepted = result['pred_label']['exact'] and all(result[n]['above_atol'] == 0 for n in names[1:])
    return dict(status='NUMERIC_ACCEPT' if accepted else 'NUMERIC_DIFF', atol=profiles.ATOL,
                comparisons=result, scientific_acceptance=False)


class CellBridge:
    """One prepared model, original guarded trace passes 16 then 1, AMP off.

    No reload/reseed/warmup/extra forward, no old CELL_SPECS mutation. Production
    run additionally requires coordinator-owned scratch. This component alone
    cannot certify worker process/input/artifact provenance or observer parity.
    """
    def __init__(self, diag, context, trials, expected_trials, *, hermetic_test=False, old_freeze=None):
        _check_module(diag)
        _check_module(profiles)
        require(type(hermetic_test) is bool, 'exact test-domain flag required')
        self.diag, self.context, self.trials = diag, dict(context), tuple(trials)
        self.profile = profiles.profile(diag._G2_PROFILE)
        self.hermetic_test, self.used = hermetic_test, False
        diag._validate_trial_documents(expected_trials)
        self.expected_wire = _wire(diag, expected_trials)
        if not hermetic_test:
            require(old_freeze is not None, 'pinned parent trial freeze required')
            original = json.loads(read(old_freeze, OLD_FREEZE_SHA))
            require(_wire(diag, original['trials']) == self.expected_wire
                    and tuple(t.trial_id for t in trials) == profiles.TRIALS, 'production trial identities differ')
        self.model = self.context.get('model')
        self.attestation = self.context.get('_formal40_worker_attestation')
        require(type(self.attestation) is diag._Formal40WorkerAttestation, 'issued preparation attestation required')
        require(self.context.get('cell_id') == self.profile.name, 'context profile differs')
        self.spec = diag.CellSpec(self.profile.name, False, (16, 1))
        with self._scope():
            self._live('g2_bridge_initial')

    def _scope(self):
        return self.diag._prediction_evaluator_context(self.context['evaluator'], model=self.model,
                                                     attestation=self.attestation)

    def _live(self, boundary):
        import torch
        diag = self.diag
        _check_module(diag)
        _check_module(profiles)
        read(Path(diag.__file__).with_name('numeric_trace.py'), TRACE_SHA)
        require(_wire(diag, diag._trial_documents(self.trials)) == self.expected_wire, 'complete trial records changed')
        frame = diag._pass_frame(self.context, self.trials)
        for trial, (_, row) in zip(self.trials, frame.iterrows()):
            identity = {key: diag._json_value(
                (int(row['distractor_1_label']) if str(row['scene_kind']) == 'mixed' else 0)
                if key == 'probe_distractor_label' else row[key]) for key in diag.TRIAL_IDENTITY_COLUMNS}
            require(_wire(diag, identity) == _wire(diag, dict(trial.identity)), 'bank full identity changed')
        actual = diag._live_inference_attestation(self.model, boundary)
        require(actual is self.attestation and actual.worker_pid == os.getpid(), 'worker identity differs')
        require(actual.frozen_capability.trust_domain == ('hermetic-test' if self.hermetic_test else 'production'),
                'worker trust domain differs')
        require(self.hermetic_test or self.context['device'].type == 'cuda', 'production requires CUDA')
        diag._require_active_inference_attestation(self.model, boundary + '_full')
        diag._validate_issued_model_state(actual)
        runtime = diag._read_frozen_numeric_runtime(torch)
        require(_wire(diag, runtime) == _wire(diag, self.context['runtime']) == _wire(diag, self.profile.runtime()),
                'runtime differs from profile')
        require(not torch.is_autocast_enabled() and not torch.is_autocast_cpu_enabled(), 'ambient AMP is enabled')
        return runtime

    def _backend_scope(self, cache_root):
        import torch
        import torch._dynamo.eval_frame as ef
        wrappers = [m for _, m, _, _ in self.diag._direct_model_module_inventory(self.model)
                    if type(m) is ef.OptimizedModule]
        if self.profile.compiled:
            require(str(torch.__version__) == '2.1.1+cu118', 'compiled bridge requires reviewed Torch 2.1.1')
        self._cold_marker_verified = _cold_marker(hermetic_test=self.hermetic_test)
        if not self.profile.compiled:
            require(not wrappers, 'eager profile retains a compiled wrapper')
            return contextlib.nullcontext(), None
        require(len(wrappers) == 1 and wrappers[0] is self.model.model, 'compiled target differs')
        root = Path(cache_root).absolute() if cache_root is not None else None
        require(root is not None and root.is_dir() and not root.is_symlink()
                and not any(p.is_symlink() for p in root.parents)
                and not any(root.iterdir()) and os.environ.get('TORCHINDUCTOR_CACHE_DIR') == str(root),
                'bound empty Inductor cache required')
        backend = _PRELOADED_BACKEND
        require(backend is not None, 'compiler dependencies must be preloaded before preparation')
        _check_module(backend)
        observer = backend.BackendEvidence(wrappers[0], root)
        if not self.hermetic_test:
            lifecycle = self.diag._ISSUED_COMPILER_LIFECYCLES.get(id(self.model))
            require(lifecycle is not None and len(lifecycle.contexts) == 1, 'original compiler lifecycle required')
            lifecycle.verify()
            target, ctx, enter, compiler, _ = lifecycle.contexts[0]
            require(target is observer.wrapper and ctx is observer.context and enter is observer.enter
                    and compiler is observer.compiler, 'observer and original guard targets differ')
        self._backend_module = backend
        return observer, observer

    def _consume(self, result, index):
        diag = self.diag
        diag._validate_cell_pass(result, self.spec, index)
        require(result.trial_ids == tuple(t.trial_id for t in self.trials), 'returned trial order differs')
        digest = _commitment(diag, result)
        metadata = result.boundary_records['metadata']
        require(metadata['attestation'] == self.attestation.public_record()
                and metadata['worker_pid'] == os.getpid()
                and metadata['worker_nonce'] == self.attestation.worker_nonce
                and metadata['model_nonce'] == self.attestation.model_nonce
                and metadata['load_report_sha256'] == self.attestation.load_report_sha256,
                'pass provenance differs')
        require(metadata['trial_bank_rows'] == [dict(trial_id=t.trial_id, bank_row_index=t.bank_row_index)
                                               for t in self.trials], 'pass bank rows differ')
        self._live('g2_bridge_consume')
        return digest

    def run(self, *, scratch=None, cache_root=None):
        require(not self.used, 'bridge is single use, including after failure')
        self.used = True
        diag = self.diag
        passes, commitments = [], []
        try:
            if not self.hermetic_test:
                require(type(scratch) is diag._WorkerScratch and scratch.anchors,
                        'production requires coordinator-owned pinned scratch')
                scratch.check()
                require(str(scratch.root) == self.context.get('scratch_root')
                        and scratch.cache_roots == self.context.get('cache_roots'),
                        'context scratch/cache binding differs')
                if self.profile.compiled:
                    require(str(cache_root) == scratch.cache_roots['torchinductor'],
                            'compiler cache not bound to worker scratch')
            with self._scope():
                self._live('g2_bridge_pre_run')
                scope, observer = self._backend_scope(cache_root)
                with scope:
                    for index, size in enumerate((16, 1)):
                        self._live('g2_bridge_pre_pass')
                        if scratch is not None:
                            scratch.check()
                        result = diag.run_trace_pass(self.context, self.trials, 'pass' + str(index + 1),
                                                     size, False, Path(self.context['scratch_root']))
                        if scratch is not None:
                            scratch.spill(result)
                        passes.append(result)
                        commitments.append(self._consume(result, index))
                if observer is not None:
                    _check_module(self._backend_module)
                    backend_record = observer.result
                else:
                    require(_cold_marker(hermetic_test=self.hermetic_test) == self._cold_marker_verified,
                            'unexpected compiler in eager cell')
                    backend_record = dict(compiled=False, observer_installed=False,
                                          native_cold_state_verified=self._cold_marker_verified)
                if scratch is not None:
                    scratch.verify_spills()
                self._live('g2_bridge_finished')
                timepoints = diag._cell_timepoints(*passes)
                require(not timepoints['rng']['rng_changed'], 'RNG moved during deterministic cell')
                compared = {}
                for name in diag._TRACE_BOUNDARIES:
                    compared[name] = diag._bounded_boundary_comparison(
                        passes[0].boundary_records[name]['tensor'], passes[1].boundary_records[name]['tensor'],
                        ids=passes[0].trial_ids, name=name)
                    require(compared[name]['schema_valid'] and compared[name]['finite_valid'], 'invalid boundary: ' + name)
                require(all(compared[n]['bitwise_equal'] for n in ('raw_scene', 'raw_cue')),
                        'raw input differs; not a numeric difference')
                summary = official_summary(*(p.outputs for p in passes))
                require([_commitment(diag, p) for p in passes] == commitments, 'pass evidence changed during comparison')
            return dict(status='HERMETIC_G2_CELL_COMPLETE' if self.hermetic_test else 'G2_CELL_CANDIDATE_COMPLETE',
                        profile=self.profile.name, trial_identity_sha256=sha(self.expected_wire),
                        pass_commitments=commitments, numeric=summary, boundaries=compared,
                        state=timepoints, backend=backend_record, passes=tuple(passes),
                        trust_domain=self.attestation.frozen_capability.trust_domain,
                        production_ready=False, production_interference_validated=False,
                        independent_results_verified=False, ready_for_gpu=False, jobs_submitted=0)
        except BaseException:
            diag._revoke_attestation(self.attestation)
            raise
