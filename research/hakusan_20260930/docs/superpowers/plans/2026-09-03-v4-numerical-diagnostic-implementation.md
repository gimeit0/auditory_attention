# V4 Job 646900 formal40 Numerical Diagnostic Implementation Plan

2026-09-10续作说明：下文为v1历史任务与当时固定SHA，保留不改写历史。
经过用户批准的逐版本修复，当前候选为独立v12，恢复原v4三个固定环境值并
补充有限异常链。当前执行以v12-runtime-repair和v12-remote-deployment证据
文档中的新SHA、真实输出和审批为准，不重跑v1或旧失败版本。本地612回归及
真实CPU准备已通过；实际GPU诊断和最终三模型比较仍必须验收，未完成。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, verify, deploy, and run one independent A100 numerical-diagnostic job that explains where Job 646900's `formal40_nll` batch-size difference first appears, without changing or publishing anything in frozen v4.

**Architecture:** A reviewed seven-file local package provides pure numeric primitives, a SHA-bound diagnostic CLI, a durable exactly-once submitter, and a thin Slurm runner. One Python coordinator owns the shared v4 lock and terminal state, launches `REFERENCE_COLD → A2 → equivalence → A1 → B1 → B2` as fresh child processes, validates all artifacts and bound inputs before and after execution, and treats finite `DIFF` as a successful observation rather than a job failure.

**Tech Stack:** Python 3.11, `unittest`, NumPy, pandas, PyTorch/torchaudio, JSON/CSV/NPY, `fcntl`, Bash, Slurm (`sbatch`, `squeue`, `sacct`), SHA-256.

**Spec:** [2026-09-03-v4-numerical-diagnostic-design.md](/Users/gigi/发表/超算/docs/superpowers/specs/2026-09-03-v4-numerical-diagnostic-design.md)

## Global Constraints

- The approved spec SHA-256 is `9508225bc6f1aa463423f3c50528c888a7b2450dde2f0997e6edaea8acf3ec15`. Verify it before implementation and stop if it differs.
- Work only in `/Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1` until the reviewed remote-deployment task.
- The current staging workspace is not a Git repository. Do not run `git init`. The repository at `/Users/gigi/projects/auditory_attention` is dirty and out of the writable staging scope; do not edit, clean, reset, or commit there. This plan therefore uses RED/GREEN transcripts and SHA-256 checkpoints in place of commit checkpoints.
- Frozen v4 is read-only: `/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4`.
- The diagnostic root is new and write-only for this protocol: `/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1`.
- Only `formal40` and the same 32 frozen smoke trials are in scope. Do not load `valbest33` or `author_external`; do not run control-cue branches or the 10k audit.
- Never call frozen v4 `run_evaluation()`, attempt/publication helpers, or its runner. Do not write `SMOKE_PASS.json`, `SAME_BANK_AUDIT_PUBLISHED.json`, or `COMPLETE.json` anywhere.
- All production Python invocations use absolute Python paths with `-I -B`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, and `PYTHONHASHSEED=0`.
- Under `python -I`, the script directory is not a trusted import path. Read every sibling production module once through `O_RDONLY|O_NOFOLLOW`, verify its canonical path, regular-file type, stable descriptor identity, size, and SHA-256, then `compile()` and `exec()` those exact verified source bytes in a controlled module object. Do not verify one path read and execute a second path read, and do not consume `.pyc` for frozen project/snapshot code.
- Every state/result publication is create-once, no-symlink, no-overwrite, same-directory atomic publication followed by directory `fsync`. Diagnostic artifacts must have link count one, except for the explicitly reviewed staging-to-tools publication hard links before staging names are unlinked.
- A finite numerical `DIFF` must not abort the matrix. Identity, alignment, shape, dtype, nonfinite values, trace inequivalence, mutated inputs/model state, missing artifacts, or integrity errors are `INVALID` and fail closed.
- No failed, ambiguous, or incomplete remote root/job is automatically retried. Preserve it and design a new version/root after review.
- The exact execution evidence record is `/Users/gigi/发表/超算/docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md`. Record every RED/GREEN command, reviewed release SHA, remote freeze approval, submission receipt, Slurm result, and final verifier result there; never treat terminal scrollback as the authoritative record.
- After Task 1 creates the package directory, use this preamble before every local command in Tasks 1–9 so each task is executable from a fresh shell:

```bash
set -eu
cd /Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1
P=/opt/anaconda3/envs/audattn/bin/python
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0
```

---

## Fixed Production Contract

```text
DIAGNOSTIC_PROTOCOL=formal40_batch_invariance_diag_20260903_v1
V4_PROTOCOL=fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1
EVALUATION_ROLE=REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST
V4_EVALUATOR_SHA256=31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4
V4_RUNNER_SHA256=b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495
V4_MANIFEST_SHA256=1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5
V4_LOCK_SHA256=63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710
FORMAL40_SHA256=2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff
HISTORICAL_NLL_MAX_ABS=0.0077362060546875
CANARY_REFERENCE_THRESHOLD=1e-6
WORST_CASE_BUDGET_BYTES=1073741824
```

## File Structure and Responsibilities

| File | Single responsibility |
|---|---|
| `numeric_trace.py` | Read-only tensor/file records, numerical comparison, model/RNG snapshots, runtime records, and artifact-inventory verification; no CLI, evaluator import, locks, or writes. |
| `diagnose_batch_invariance.py` | Frozen-v4 audit/freeze/check, SHA-bound module loading, formal40 reference/trace workers, cell artifacts, coordinator, aggregation, terminal markers, and read-only result verification. |
| `submit_numeric_diag.py` | Fixed-contract preflight, durable intent/raw response/receipt, one shell-free `sbatch`, and read-only status; no model import. |
| `run_numeric_diag.sbatch` | Fixed Slurm resources, clean bootstrap, spool/environment binding, then `exec` of the single Python coordinator. |
| `test_numeric_diag.py` | RED/GREEN coverage for primitives, frozen inputs, traced inference, cells, coordinator, artifacts, signals, and result verification. |
| `test_submit_numeric_diag.py` | RED/GREEN coverage for runner syntax/contract, scheduler gateway, exactly-once journal, ambiguity, and status. |
| `README.md` | Reviewed operator procedure, evidence semantics, immutable identities, release hashes, and recovery/stop rules. |

The seven files above are the deployable package. The external execution record at `docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md` is audit documentation, not an eighth package input.

---

### Task 1: Create the Package Skeleton and Read-Only File Primitives

**Files**

- Create: `/Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1/numeric_trace.py`
- Create: `/Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`
- Create: `/Users/gigi/发表/超算/docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md`

**Interfaces**

- **Consumes:** approved fixed constants and Python/NumPy/Torch objects supplied by tests.
- **Produces:** the exception, constants, and exact read-only functions listed below for Tasks 2–6.

- Constants: `TRACE_SCHEMA_VERSION = 1`, `RELATIVE_DENOMINATOR_FLOOR = 1e-12`, and `CANARY_REFERENCE_ABS = 0.0077362060546875`.
- Exception: `TraceContractError(ValueError)`.
- Pure/guarded functions: `canonical_json_bytes(value: object) -> bytes`, `read_stable_bytes(path: pathlib.Path, *, allowed_root: pathlib.Path) -> tuple[bytes, dict[str, object]]`, `stable_file_record(path: pathlib.Path, *, allowed_root: pathlib.Path) -> dict[str, object]`, `verify_file_record(record: Mapping[str, object], *, allowed_root: pathlib.Path) -> dict[str, object]`, and `fingerprint_tree(root: pathlib.Path) -> dict[str, object]`.

`fingerprint_tree()` does not follow or reject a tree symlink: it records each entry as `(relative_path, type, mode, size, st_mtime_ns, st_dev, st_ino, symlink_target)` using length-prefixed UTF-8 fields sorted by relative-path bytes, while the content aggregate hashes `(relative_path, size, sha256)` for sorted ordinary files. By contrast, `stable_file_record()` rejects a symlink when a pinned regular file is required.

- [ ] Create the package directory, these first two package files, and the external execution record with `apply_patch`; later tasks create the other five reviewed package files. Do not use shell redirection to write them.

- [ ] From the first RED run, make `test_numeric_diag.py` load the local SUT by an absolute test-only `importlib.util.spec_from_file_location()` helper; this avoids accidental dependence on the script directory under `-I`. Task 3 separately implements the stronger exact-source-bytes production loader.

```python
def load_test_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path.resolve(strict=True))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
```

- [ ] Write RED tests for canonical JSON, stable `lstat/open/fstat` reads, canonical-root enforcement, pinned-file symlink/hard-link rejection, replacement races, and NUL-safe tree/content fingerprints. Assert every required identity field, nanosecond mtime, sorted encoding, ordinary-file content aggregation, and non-followed symlink-target recording. `numeric_trace.py` has no CLI, evaluator import, file write, or lock acquisition.

```python
def test_tree_fingerprint_changes_on_identity_or_content(self):
    before = fingerprint_tree(self.root)
    (self.root / "input.bin").write_bytes(b"changed")
    after = fingerprint_tree(self.root)
    self.assertNotEqual(before["content_sha256"], after["content_sha256"])
```

- [ ] Run the isolated RED target and preserve its failure output in the implementation transcript.

```bash
cd /Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1
P=/opt/anaconda3/envs/audattn/bin/python
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" FilePrimitiveTests
```

Expected RED result: nonzero exit because `numeric_trace.py` does not yet expose the required primitives.

- [ ] Implement only the tested file primitives. Use descriptor-based reads with `O_RDONLY|O_NOFOLLOW`, require regular files and `st_nlink == 1`, compare pre-open path `lstat`, opened `fstat`, and post-read `fstat`, and hash bytes read from the descriptor.

```python
def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
```

- [ ] Rerun the target class and then the whole current test file.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" FilePrimitiveTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
```

- [ ] Record a checkpoint rather than a Git commit.

```bash
/usr/bin/shasum -a 256 numeric_trace.py test_numeric_diag.py
```

### Task 2: Implement Tensor, Difference, Model-State, RNG, and Artifact Contracts

**Files**

- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/numeric_trace.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`

**Interfaces**

- **Consumes:** Task 1 `TraceContractError`, `stable_file_record()`, `verify_file_record()`, and `canonical_json_bytes()`.
- **Produces:** exact tensor/state/RNG/runtime/inventory functions consumed by Tasks 4–6.

- Tensor recorders: `canonical_tensor_bytes(tensor: Any) -> bytes`, `tensor_record(tensor: Any, *, boundary: str) -> dict[str, Any]`, and `per_trial_tensor_records(tensor: Any, *, trial_ids: Sequence[int], boundary: str, batch_axis: int = 0) -> list[dict[str, Any]]`.
- Comparator: `compare_aligned_tensor(left: Any, right: Any, *, trial_ids: Sequence[int], boundary: str, class_axis: int | None = None, relative_floor: float = 1e-12) -> dict[str, Any]` returns the complete schema/finite/bitwise/difference/quantile/worst-location record.
- State functions: `snapshot_model_state(model)`, `compare_model_snapshots(before, between, after)`, `snapshot_rng_state()`, and `compare_rng_snapshots(before, between, after)`.
- Runtime function: `runtime_record(*, device: Any, autocast_enabled: bool, pass_batch_sizes: tuple[int, int], cache_dirs: Mapping[str, str]) -> dict[str, Any]`.
- Inventory function: `verify_artifact_inventory(root: pathlib.Path, *, expected: Sequence[Mapping[str, Any]], allowed_total_bytes: int = 1 << 30) -> dict[str, Any]`.

- [ ] Add RED tests for contiguous and noncontiguous tensors, bfloat16 raw bytes, tuple/list rejection when no batch axis is declared, duplicate trial IDs, shape/dtype/alignment mismatch, NaN/Inf patterns, and exact worst-index reporting.

- [ ] Add the historical canary fixture and require both flat-element and per-trial-max quantiles with NumPy `method="linear"`.

```python
def test_original_canary_delta_is_preserved_as_finite_diff(self):
    left = np.zeros((32,), dtype=np.float32)
    right = left.copy()
    right[17] = np.float32(0.0077362060546875)
    got = compare_aligned_tensor(left, right, trial_ids=tuple(range(32)), boundary="nll")
    self.assertTrue(got["schema_valid"])
    self.assertFalse(got["bitwise_equal"])
    self.assertGreater(got["max_abs"], 1e-6)
    self.assertEqual(got["worst"]["trial_id"], 17)
    self.assertEqual(got["quantile_method"], "linear")
```

- [ ] Add RED tests proving model snapshots contain every parameter and buffer, sorted by `(kind, name)`, with object identity, `_version`, shape, dtype, device, and content SHA; mutation at either checkpoint must be detected.

- [ ] Add RED tests for Python, NumPy, Torch CPU, and every available CUDA RNG state encoding/digest. RNG differences are reported but do not alone invalidate a cell.

- [ ] Add artifact-inventory RED tests for path escape, symlink, non-regular file, `nlink != 1`, duplicate/missing/extra paths, changed size/SHA, and total worst-case payload over `1,073,741,824` bytes.

- [ ] Run RED.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" NumericTraceTests StateAndInventoryTests
```

Expected RED result: missing comparison/state functions or assertion failures for the unimplemented contract.

- [ ] Implement the minimum contract. Tensor bytes must be detached, moved to CPU, made contiguous, and viewed as `uint8` so bfloat16 is preserved; bind digest separately to dtype and shape. Reject nonfinite values as schema-invalid, never as ordinary `DIFF`.

```python
abs_diff = np.abs(left64 - right64)
denominator = np.maximum(np.maximum(np.abs(left64), np.abs(right64)), relative_floor)
rel_diff = abs_diff / denominator
element_quantiles = {
    name: float(np.quantile(abs_diff.reshape(-1), q, method="linear"))
    for name, q in (("p50", 0.50), ("p95", 0.95), ("p99", 0.99))
}
trial_max = abs_diff.reshape(len(trial_ids), -1).max(axis=1)
```

- [ ] Run GREEN, then all tests and record hashes.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" NumericTraceTests StateAndInventoryTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
/usr/bin/shasum -a 256 numeric_trace.py test_numeric_diag.py
```

### Task 3: Encode the Frozen v4 Contract and Build the Immutable Diagnostic Freeze

**Files**

- Create: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/diagnose_batch_invariance.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`

**Interfaces**

- **Consumes:** Tasks 1–2 read-only records/inventory functions plus the reviewed local v4 evaluator bytes.
- **Produces:** `FrozenContract`, `TrialSpec`, SHA-bound loaders, the immutable diagnostic freeze, and three public validation subcommands for Tasks 4–12.

```python
@dataclasses.dataclass(frozen=True)
class FrozenContract:
    v4_root: pathlib.Path
    v4_protocol: str
    evaluation_role: str
    evaluator_sha256: str
    runner_sha256: str
    manifest_sha256: str
    lock_sha256: str
    formal40_sha256: str

@dataclasses.dataclass(frozen=True)
class TrialSpec:
    ordinal: int
    trial_id: int
    bank_row_index: int
    identity: Mapping[str, Any]

@dataclasses.dataclass(frozen=True)
class FrozenSceneAPI:
    waveform_cache_class: type
    raw_scene_batch: Callable[..., Any]
    correct_cue_batch: Callable[..., Any]
    imported_source_records: tuple[Mapping[str, Any], ...]

```

- `_read_stable_source_bytes(path: pathlib.Path, *, allowed_root: pathlib.Path) -> tuple[bytes, dict[str, object]]` is a private, stdlib-only bootstrap in `diagnose_batch_invariance.py`. It performs canonical-root containment, `lstat → open(O_RDONLY|O_NOFOLLOW) → fstat → descriptor read → fstat → lstat`, requires an ordinary single-link file, rejects identity/size changes, and computes SHA-256 over the descriptor bytes. It exists only to load `numeric_trace.py` before that module is trusted; it must not import or call `numeric_trace`.
- `load_verified_source_module(path: pathlib.Path, *, expected_size: int, expected_sha256: str, module_name: str) -> types.ModuleType` is the first-load path for `numeric_trace.py`: it calls the private bootstrap and compiles/executes exactly those verified source bytes. The production diagnoser contains the actual reviewed `NUMERIC_TRACE_SIZE` and `NUMERIC_TRACE_SHA256` literals finalized in Task 9; `audit-inputs`/`freeze-inputs` never accept these identities from an environment variable or caller flag. After `numeric_trace` is loaded, a separate `load_verified_v4_evaluator(trace, path, expected_size, expected_sha256)` and the snapshot loader reuse its independently tested `read_stable_bytes()` implementation.
- `frozen_scene_context(snapshot_files: pathlib.Path, source_records: Mapping[str, Mapping[str, Any]]) -> contextlib.AbstractContextManager[FrozenSceneAPI]` installs a manifest-backed source-bytes finder for every importable `.py` path in the frozen snapshot (including `src` and `selftrain`) and yields `WaveformCache`, `_raw_scene_batch`, and `_correct_cue_batch`; the worker keeps this context open through formal40 loading and both passes.
- `read_frozen_context()` returns the validated v4 manifest, roots, evaluator, bank, and historical scene binding.
- `select_trials(evaluator: types.ModuleType, bank: Any, *, count: int = 32) -> tuple[TrialSpec, ...]` returns trials in frozen order.
- `collect_snapshot_records(source_manifest: Mapping[str, Any], used_paths: Collection[pathlib.Path]) -> list[dict[str, Any]]` and `collect_clip_records(bank: Any, *, clips_dir: pathlib.Path) -> list[dict[str, Any]]` close the actual-input inventory.
- `audit_inputs() -> dict[str, Any]`, `freeze_inputs(*, confirm_protocol: str) -> dict[str, Any]`, and `check_only(*, expected_input_freeze_sha256: str) -> dict[str, Any]` return canonical JSON-compatible reports.
- `atomic_create_bytes(path, payload)`, `atomic_create_json(path, value)`, and `shared_v4_lock(path)` are private diagnoser helpers; they do not belong to `numeric_trace.py`.

For hermetic tests, internal functions take an explicit `FrozenContract` and injected process runner. Production `main(argv: Sequence[str] | None = None) -> int` always constructs the compiled-in production contract and exposes no environment/config override for roots, hashes, Python, or scheduler paths.

- [ ] Add RED tests for every fixed path/hash/protocol/role, all 24 v4 pinned records, source-manifest schema 2 (`semantic_files` and `provenance_files`), and the exact formal40 checkpoint.

- [ ] Add RED tests requiring every public CLI to emit exactly one canonical JSON document on stdout. Redirect import-time informational prints and warnings from the frozen audio stack to stderr so operator parsing never needs to strip lines before the first `{`.

- [ ] Add RED trial-selection tests that call the verified evaluator's `_select_smoke_bank(bank, 32)`, record original bank row indices before reset, require unique ordered `trial_id` values, and include the exact identity columns used by the frozen bank.

- [ ] Add RED clip enumeration tests. For each selected row, include every role whose `{role}_index >= 0` from frozen `ROLE_NAMES`; canonicalize under `cv_train/clips`, deduplicate, and bind type/size/SHA. Reject missing roles, escaping paths, symlinks, or duplicate identity rows.

- [ ] Add RED tests for the delayed frozen scene-generation import chain. Keep `_frozen_import_context(snapshot_files)` active through model loading and both passes; import `selftrain.data.diotic_attention.WaveformCache` plus `selftrain.scripts.eval_full_pilot._raw_scene_batch` and `_correct_cue_batch`, verify both module files stay under the frozen snapshot, and never retain callbacks after leaving that context.

- [ ] Add RED tests for a diagnostic `input_freeze.json` that binds the four production files, the frozen identities, the 32 trials, all selected clips, all source-manifest files actually imported/executed, package schema, and diagnostic protocol. A second freeze must refuse overwrite.

  Freeze every regular file listed by the snapshot source manifest, not merely the modules observed during a login-node dry run. Each worker must additionally report the subset of snapshot module files actually imported; the coordinator verifies that subset against the conservatively frozen superset before and after execution.

- [ ] Add exact-layout RED tests for production `tools`, `logs`, `state`, `attempts`, and `submitted_runners` directories: correct root, owner, mode `0700`, real-directory type, no unexpected entries, and no symlinks. `check-only` refuses a missing `logs/` directory before any scheduler call.

- [ ] Add RED tests for create-once JSON/bytes publication and nonblocking shared-lock behavior. The private diagnoser writer uses a same-directory temp opened with `O_CREAT|O_EXCL|O_NOFOLLOW` and mode `0600`, then `write → fsync(temp fd) → os.link(temp, final) → unlink(temp) → fsync(parent)`; it refuses an existing final path and never overwrites immutable evidence.

- [ ] Add the real isolated-import regression. The child must prove its `sys.path` lacks the package directory, yet the diagnoser can verify and execute the exact `numeric_trace.py` bytes by absolute path and SHA.

```python
def test_sha_bound_numeric_trace_loads_under_isolated_python(self):
    outcome = subprocess.run(
        [PYTHON, "-I", "-B", str(DIAGNOSER), "_self-test-isolated-loader"],
        text=True, capture_output=True, check=False,
        env=isolated_env(),
    )
    self.assertEqual(outcome.returncode, 0, outcome.stderr)
    self.assertEqual(json.loads(outcome.stdout)["status"], "ISOLATED_IMPORT_PASS")
```

- [ ] Add RED replacement/bytecode attacks before running any Task 3 implementation. Start with `numeric_trace` absent from `sys.modules`; replace the source pathname after the private bootstrap has opened its stable descriptor and place a valid-looking stale/malicious `.pyc` beside it. The loaded module must execute the originally verified descriptor bytes. Also require frozen snapshot imports to be served by a source-manifest-backed `MetaPathFinder/Loader` and recorded as actually imported.

- [ ] Run the complete focused RED target and preserve the failure output. Confirm the failure is missing Task 3 behavior—not a malformed fixture or accidental normal import.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" FrozenContractTests IsolatedImportTests
```

- [ ] Implement every Task 3 interface exercised by the RED suite: the private stdlib bootstrap reader; SHA-bound `numeric_trace` and v4 evaluator loaders; manifest-backed snapshot import context; frozen-context reading; exact trial/clip/source collection; create-once writers/shared lock; strict `audit-inputs`; create-once `freeze-inputs`; and zero-write `check-only`. `load_verified_source_module()` creates a `types.ModuleType`, assigns controlled `__file__`, `__loader__`, `__spec__`, and `__package__`, registers it in `sys.modules` for the duration of `exec(compile(verified_bytes, canonical_path, "exec", dont_inherit=True, optimize=0), module.__dict__)`, and removes it on failure.

```python
source, record = _read_stable_source_bytes(path, allowed_root=path.parent)
if record["size"] != expected_size or record["sha256"] != expected_sha256:
    raise DiagnosticError(f"verified source identity mismatch: {path}")
if module_name in sys.modules:
    raise DiagnosticError(f"module name already loaded: {module_name}")
module = types.ModuleType(module_name)
module.__file__ = str(record["path"])
module.__package__ = module_name.rpartition(".")[0]
module.__loader__ = None
module.__spec__ = importlib.util.spec_from_loader(module_name, loader=None,
                                                   origin=module.__file__)
sys.modules[module_name] = module
try:
    code = compile(source, module.__file__, "exec", dont_inherit=True, optimize=0)
    exec(code, module.__dict__)
except BaseException:
    sys.modules.pop(module_name, None)
    raise
```

The first successful call above produces the trusted `trace` module using the compiled-in reviewed size/SHA. Every subsequent source load calls `trace.read_stable_bytes()` on its own allowed root; no production code uses the test-only `spec_from_file_location()` helper, and no `.pyc` is consulted.

Loading the verified v4 evaluator is allowed only for this whitelist:

```text
_frozen_import_context
strict_load_model
singleton_native_preprocess
predict_batch
_select_smoke_bank
_configure_runtime
_tensor_hashes
```

Explicitly reject or never expose `run_evaluation`, `_create_attempt_directory`, publication functions, and v4 terminal-marker functions.

- [ ] The snapshot source loader maps every frozen manifest `.py` record to its package/module name, handles package `__init__.py`, refuses modules absent from the manifest, and records exact executed-source SHA values. Set `sys.dont_write_bytecode=True` and a distinct empty scratch `sys.pycache_prefix` as defense in depth, while still proving the custom loader—not bytecode-cache behavior—determines executed project bytes.

- [ ] Define the production CLI with fixed roots in constants; do not accept caller-supplied production root, runner, Python, or v4 paths.

```text
diagnose_batch_invariance.py audit-inputs
diagnose_batch_invariance.py freeze-inputs --confirm-protocol formal40_batch_invariance_diag_20260903_v1
diagnose_batch_invariance.py check-only --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA"
```

- [ ] Run GREEN only after the implementation is present, and prove `check-only` changes neither a fixture tree fingerprint nor file-content fingerprint.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" FrozenContractTests IsolatedImportTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
/usr/bin/shasum -a 256 diagnose_batch_invariance.py numeric_trace.py test_numeric_diag.py
```

### Task 4: Reproduce the Frozen Prediction Path and Prove Trace Equivalence

**Files**

- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/diagnose_batch_invariance.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`

**Interfaces**

- **Consumes:** Task 3 `FrozenContract`, `TrialSpec`, verified evaluator whitelist, and immutable trial/input records; Task 2 trace/state functions.
- **Produces:** `CellSpec`, `TraceBatch`, `PassResult`, frozen-reference and traced-pass functions, and the equivalence record used by Tasks 5–6.

```python
@dataclasses.dataclass(frozen=True)
class CellSpec:
    cell_id: Literal["A1", "A2", "B1", "B2"]
    autocast_enabled: bool
    pass_batch_sizes: tuple[int, int]

CELL_SPECS = {
    "A1": CellSpec("A1", True, (16, 16)),
    "A2": CellSpec("A2", True, (16, 1)),
    "B1": CellSpec("B1", False, (16, 16)),
    "B2": CellSpec("B2", False, (16, 1)),
}
EXECUTION_ORDER = ("REFERENCE_COLD", "A2", "EQUIVALENCE", "A1", "B1", "B2")

@dataclasses.dataclass
class TraceBatch:
    trial_ids: tuple[int, ...]
    raw_scene: Any
    raw_cue: Any
    normalized_scene: Any
    normalized_cue: Any
    scene_features: Any
    cue_features: Any
    native_logits: Any
    log_probabilities: Any
    outputs: Mapping[str, Any]

@dataclasses.dataclass
class PassResult:
    pass_id: Literal["pass1", "pass2"]
    batch_size: int
    trial_ids: tuple[int, ...]
    outputs: Mapping[str, Any]
    boundary_records: Mapping[str, Any]
    model_snapshots: Mapping[str, Sequence[Mapping[str, Any]]]
    rng_snapshots: Mapping[str, Mapping[str, Any]]
```

- `TraceBatch` holds aligned trial IDs and post-output captures for raw, normalized, cochleagram, logits, log-probabilities, and scalar/discrete outputs.
- `PassResult` holds pass identity, batch size, outputs, boundary records, and before/between/after state/RNG evidence.
- `trace_predict_batch(model: Any, raw_scene: Any, raw_cue: Any, labels: Any, probes: Any, device: Any, *, autocast_enabled: bool, trial_ids: Sequence[int]) -> TraceBatch` is the instrumented path.
- `run_reference_pass(context, trials, pass_id, batch_size) -> PassResult` directly calls frozen `predict_batch()`.
- `run_trace_pass(context, trials, pass_id, batch_size, autocast_enabled, scratch_root) -> PassResult` uses the traced path.
- `compare_reference_equivalence(reference, a2)` returns a bitwise evidence record and raises on any schema or identity violation.
- `build_raw_batch(scene_api: FrozenSceneAPI, frame: Any, *, clips_dir: pathlib.Path, historical_scene_hashes: Mapping[int, str], cache: Any) -> tuple[Any, Any]` calls the frozen raw-scene/correct-cue functions, validates every regenerated scene digest against Job584990, and returns no control-cue tensors.

- [ ] Write RED CPU toy-model tests with a call recorder for the exact frozen operation order and for cochleagram functions returning a tuple/list. Reject outputs without a declared batch axis or logits not shaped `[batch, 800]`.

- [ ] Write RED scene-construction tests. Each pass constructs a fresh `WaveformCache` with the frozen cache-size setting, calls `raw_scene_batch(frame, cache, clips_dir, snr_errors=...)` and `correct_cue_batch(frame, cache, clips_dir)`, checks trial-wise scene hashes before inference, and leaves `frozen_scene_context()` only after formal40's second pass and final state/RNG snapshot. Assert a wrong Job584990 hash or an early context exit fails before any interpretable comparison.

- [ ] Require the trace path to match this operation sequence. Do not insert `.cpu()`, `.numpy()`, digest, or synchronization between operators; copy/capture boundaries only after all official outputs for the batch exist.

```python
normalized_scene = evaluator.singleton_native_preprocess(model, raw_scene)
normalized_cue = evaluator.singleton_native_preprocess(model, raw_cue)
labels_device = labels.to(device, non_blocking=True)
probes_device = probes.to(device, non_blocking=True)
with torch.inference_mode():
    with torch.autocast(device_type=device.type,
                        dtype=torch.float16 if device.type == "cuda" else torch.bfloat16,
                        enabled=autocast_enabled and device.type == "cuda"):
        scene_features, _ = model.coch_gram.full_rep(normalized_scene.to(device, non_blocking=True), None)
        cue_features, _ = model.coch_gram.full_rep(normalized_cue.to(device, non_blocking=True), None)
        logits = model(cue_features, scene_features, None)
        log_probabilities = logits.float().log_softmax(dim=-1)
        probabilities = log_probabilities.exp()
        predicted = probabilities.argmax(dim=-1)
        nll = -log_probabilities.gather(1, labels_device[:, None]).squeeze(1)
        p_target = probabilities.gather(1, labels_device[:, None]).squeeze(1)
        p_probe = probabilities.gather(1, probes_device[:, None]).squeeze(1)
# Only now copy raw/normalized/coch/logits/log_prob/target-logit/logsumexp/results.
```

- [ ] Add RED mutation-guard tests for raw scene/cue, normalized scene/cue, and scene/cue cochleagram tensors. Immediately before each tensor is consumed, record object identity, `_version`, shape, dtype, and device without copying or synchronizing; after all official outputs for that batch exist, require the same object identity/shape/dtype/device and unchanged `_version`. A toy preprocess, cochleagram, or model that performs an in-place mutation must make the pass `INVALID`, even if all five fresh processes would deterministically repeat that mutation. Content digests remain post-output captures and must agree with the corresponding guard record.

- [ ] Add RED tests that `REFERENCE_COLD` calls the frozen `predict_batch()` directly for `16→1`, while A2 calls `trace_predict_batch()` in a distinct process/model/cache with the same seed/runtime.

- [ ] Assert each child calls frozen `strict_load_model(manifest, "formal40", device=device)` exactly once and never requests `valbest33` or `author_external`. Capture the resulting load report in the child inventory.

- [ ] Assert the frozen runtime settings in every fresh process: deterministic algorithms on, cuDNN deterministic on, cuDNN benchmark off, float32 matmul precision `medium`, CUDA matmul TF32 on, and cuDNN TF32 on. The four-cell matrix changes only autocast and batch shape; B1/B2 are `autocast OFF`, not strict IEEE FP32.

- [ ] Require per-pass bitwise equivalence after `trial_id` alignment for raw scene/cue identity, shapes, dtypes, `pred_label`, `nll`, `p_target`, and `p_probe_distractor`, plus unchanged model state on both sides.

- [ ] Run the complete focused RED target before implementing Task 4. Preserve failures showing the missing operation recorder, frozen-reference equivalence, and mutation guards.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" PredictionPathTests ReferenceEquivalenceTests
```

- [ ] Implement only the Task 4 reference/trace functions and mutation guards.

- [ ] Run the focused GREEN target, then the full regression and hash checkpoint.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" PredictionPathTests ReferenceEquivalenceTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
/usr/bin/shasum -a 256 diagnose_batch_invariance.py test_numeric_diag.py
```

### Task 5: Implement Cell Execution, Boundary Comparisons, and Bounded Artifacts

**Files**

- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/diagnose_batch_invariance.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/numeric_trace.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`

**Interfaces**

- **Consumes:** Task 4 reference/trace pass results and Task 2 comparison/inventory functions.
- **Produces:** immutable reference/cell artifacts, cell status/comparison, A2 replay classification, first-divergence record, and `CELL_COMPLETE.json` inventories for Task 6.

- `run_reference_cold(args)` and `run_cell(spec, args)` return complete child result manifests.
- `compare_passes(first: PassResult, second: PassResult, *, spec: CellSpec) -> dict[str, Any]` returns the cell comparison without treating finite differences as exceptions.
- `classify_a2(comparison)` returns exactly `REPRODUCED`, `NOT_REPRODUCED`, or `DIFFERENT_NUMERIC_BEHAVIOR`.
- `first_divergence(comparisons)` returns the first ordered boundary or `None`.
- `write_npy_create_once(path, array)` and `write_cell_artifacts(cell_root, result)` publish only verified immutable files.

Use this canonical attempt layout and reject all alternate/output-argument paths:

```text
attempts/slurm-${SLURM_JOB_ID}/
├── ENVIRONMENT.json
├── RUNNING.json
├── reference_cold/
│   ├── REFERENCE_INPUTS.json
│   ├── RUNTIME.json
│   ├── TRIAL_OUTPUTS.csv
│   ├── STATE_BEFORE.jsonl
│   ├── STATE_BETWEEN.jsonl
│   ├── STATE_AFTER.jsonl
│   ├── RNG_BEFORE.json
│   ├── RNG_BETWEEN.json
│   ├── RNG_AFTER.json
│   └── REFERENCE_COMPLETE.json
├── cells/{A1,A2,B1,B2}/
│   ├── CELL_INPUTS.json
│   ├── RUNTIME.json
│   ├── STATE_{BEFORE,BETWEEN,AFTER}.jsonl
│   ├── RNG_{BEFORE,BETWEEN,AFTER}.json
│   ├── TRIAL_OUTPUTS.csv
│   ├── BOUNDARY_DIGESTS.jsonl
│   ├── LOGITS_PASS1.npy
│   ├── LOGITS_PASS2.npy
│   ├── WORST_CASES/
│   ├── COMPARISON.json
│   └── CELL_COMPLETE.json
├── REFERENCE_EQUIVALENCE.json
├── MATRIX_SUMMARY.json
├── INVALID_TRACE_PATH.json       # only when reference equivalence fails
└── TARGETED_TRACE_REQUIRED.json  # only when the defined boundary rule requires it
```

- [ ] Write RED tests for the exact matrix, distinct child PID/model/cache per cell, no seed reset between a cell's two passes, seed reset at cell start, and per-trial alignment independent of batch-call order.

- [ ] Test every required boundary in the fixed order:

```text
raw scene/cue
normalized scene/cue
scene/cue cochleagram
native logits
float log_softmax
target logit and float logsumexp
NLL, target/probe probability, predicted label, correct
```

- [ ] Test `PASS`, finite `DIFF`, and `INVALID` separately. A1/A2/B1/B2 must finish after ordinary finite differences; nonfinite/schema/state violations must fail. Test the historical `0.0077362060546875` value without requiring the live run to reproduce it exactly.

- [ ] Require every pass to compare each regenerated raw-scene digest with the corresponding Job584990 frozen `scene_sha256`. At aggregation, require `trial_id`, original bank row, raw-scene digest, and correct-cue digest to match across `REFERENCE_COLD` and all four cells before any numerical interpretation.

- [ ] Encode the v4-compatible cell status exactly: after schema/identity/finite checks, `canary_status="PASS"` only when predicted-label/correct fields are exact and every official floating output (`nll`, `p_target`, `p_probe_distractor`) has `max_abs <= 1e-6`; otherwise the valid finite cell is `canary_status="DIFF"`. Boundary-level nonzero differences below threshold remain in the comparison record.

- [ ] Test A2 classification exactly:

```python
if identity_exact and pred_exact and nll_max_abs > 1e-6:
    return "REPRODUCED"
if identity_exact and pred_exact and nll_max_abs <= 1e-6:
    return "NOT_REPRODUCED"
return "DIFFERENT_NUMERIC_BEHAVIOR"
```

Invoke this classifier only after exact trial/raw identity, alignment, shape, dtype, and finite checks pass. Identity failure is `INVALID`, never `DIFFERENT_NUMERIC_BEHAVIOR`.

- [ ] Test first divergence ordering `raw → normalized waveform → cochleagram → logits → log_softmax/NLL`. When cochleagram matches but logits differ, require `TARGETED_TRACE_REQUIRED.json`; never install broad hooks automatically.

- [ ] Test the full per-cell inventory: inputs, runtime, three model snapshots, three RNG snapshots, CSV outputs, boundary JSONL, both `[32,800]` logits NPY files, comparison, bounded worst cases, and `CELL_COMPLETE.json`.

- [ ] Independently test the `reference_cold/` inventory: both-pass input digests and frozen `predict_batch()` final outputs, runtime, three model snapshots, three RNG snapshots, imported-source records, and `REFERENCE_COMPLETE.json` containing exact relative path/size/SHA records. The result verifier must reject one missing, extra, replaced, linked, or corrupt reference file just as it rejects a bad cell.

- [ ] Add a cell-level RED test proving any changed Task 4 tensor mutation guard makes that cell `INVALID` before A2 classification or first-divergence interpretation; identical downstream outputs must not mask the mutation.

- [ ] Run the complete Task 5 focused RED target before implementing cell/artifact behavior. Preserve failures for the missing matrix, comparison, inventory, bounded publication, and mutation-invalid semantics.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" CellSemanticsTests ArtifactContractTests
```

- [ ] Implement every Task 5 interface exercised by the RED suite: `run_reference_cold`, `run_cell`, aligned pass comparison, A2 classification, first-divergence reporting, exact inventories, and create-once cell/reference artifacts. Implement streaming NPY publication through a private same-directory temp file. Use verified node-local scratch for full cochleagram intermediates. Persist at most one worst trial per boundary and calculate projected bytes before any worst-case write; fail instead of truncating when the global cap would exceed 1 GiB.

- [ ] Run the focused GREEN target, then the full numeric suite and hash checkpoint.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" CellSemanticsTests ArtifactContractTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
/usr/bin/shasum -a 256 diagnose_batch_invariance.py numeric_trace.py test_numeric_diag.py
```

### Task 6: Implement the Single-Owner Coordinator and Terminal-State Semantics

**Files**

- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/diagnose_batch_invariance.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_numeric_diag.py`

**Interfaces**

- **Consumes:** Tasks 3–5 frozen contract, worker entry points, immutable child artifacts, and Task 1 fingerprints.
- **Produces:** fixed child argv, matrix aggregate, archived spool record, unique terminal marker, and read-only `verify-results` report used by Tasks 7 and 12.

- `child_command(mode, job_id, input_freeze_sha256, cell, scratch_root)` returns an absolute, shell-free child argv.
- `aggregate_matrix(cells, equivalence)` returns the four-cell interpretation and first-divergence summary.
- `archive_spool_runner(spool_path, job_id, expected_sha256)` returns the immutable archived file record.
- `run_coordinator(args)` is the sole execution/terminal-marker owner.
- `verify_results(expected_input_freeze_sha256, job_id)` is read-only and recomputes all evidence.

The production/internal CLI is fixed and derives every output directory from `job_id`; it accepts no arbitrary output root:

```text
diagnose_batch_invariance.py run-coordinator \
  --job-id "$SLURM_JOB_ID" \
  --intent-nonce "$INTENT_NONCE" \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA" \
  --spool-runner "$0"
diagnose_batch_invariance.py _child-reference \
  --job-id "$SLURM_JOB_ID" \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA"
diagnose_batch_invariance.py _child-cell \
  --job-id "$SLURM_JOB_ID" \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA" \
  --cell A2
diagnose_batch_invariance.py verify-results \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA" \
  --job-id "$SLURM_JOB_ID"
```

- [ ] Build an injected fake-process/event-recorder harness and write RED lifecycle tests. Assert this exact coordinator order:

```text
bounded wait for matching receipt, then validate receipt/spool/package
open v4 evaluation.lock O_RDONLY|O_NOFOLLOW
acquire LOCK_SH|LOCK_NB
revalidate lock bytes/identity while locked
v4 tree/content PRE
all bound inputs PRE
REFERENCE_COLD child
A2 child
REFERENCE_EQUIVALENCE
A1 child
B1 child
B2 child
verify every child inventory
write MATRIX_SUMMARY
all bound inputs POST
v4 tree/content POST
create exactly one terminal marker
release shared flock
```

- [ ] Add RED cases for equivalence failure (write `INVALID_TRACE_PATH.json`, preserve reference/A2, skip A1/B1/B2), child crash, timeout, corrupt child inventory, pre/post mutation, lock contention, and simultaneous primary plus post-verification failures.

- [ ] Add the fast-start race test: the Slurm job may begin before the submitter has fsynced `SUBMISSION_RECEIPT.json`. The coordinator waits up to 120 seconds for a stable create-once receipt matching `intent_nonce`, `SLURM_JOB_ID`, input-freeze SHA, and runner SHA; a missing or mismatched receipt fails closed before the shared v4 lock or PRE fingerprint.

- [ ] Add signal tests for `SIGINT`, `SIGTERM`, and `SIGHUP`: terminate the active child process group, perform best-effort post-verification, and write one `DIAGNOSTIC_FAILED.json`. Define a read-only status classifier that returns `INCOMPLETE_UNTRAPPED_TERMINATION` when Slurm has ended but neither terminal marker exists; never retry it.

- [ ] Test the shared-lock limitation explicitly: an official v4 job found by pre-submit `squeue` blocks submission; any official-runner write that races after the check changes the post fingerprint and yields `INVALID_FROZEN_ROOT_CHANGED`.

- [ ] Test every non-v4 bound input pre/post record explicitly. Any changed diagnostic source/runner/spool, v4 pinned record, executed snapshot source, selected clip, bank/checkpoint, or diagnostic freeze yields `INVALID_BOUND_INPUT_CHANGED`; this terminal invalidity overrides otherwise complete finite matrix observations.

- [ ] Test worker environment allowlisting and fresh caches. Preserve required `SLURM_*` and `CUDA_VISIBLE_DEVICES`; set distinct empty `TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, and `CUDA_CACHE_PATH` under the runner-verified `DIAG_SCRATCH_ROOT`. Invoke `subprocess.Popen(child_argv, env=child_env, shell=False, start_new_session=True, pass_fds=())`.

- [ ] Keep the `diagnose_batch_invariance.py` coordinator/bootstrap path and all of `submit_numeric_diag.py` stdlib-only before worker dispatch: do not import Torch, torchaudio, pandas, NumPy, `numeric_trace`, or the frozen evaluator at module import time. Each child loads the SHA-verified numerical modules only after its exclusive cache environment is present; cover this with a subprocess test that checks `sys.modules` before dispatch.

- [ ] Add RED result-verifier assertions for `FORBIDDEN_SCIENCE_MARKERS = ("SMOKE_PASS.json", "SAME_BANK_AUDIT_PUBLISHED.json", "COMPLETE.json")`. Verification must use no-following `lstat` checks to prove these names are absent from the diagnostic root and that frozen v4's complete tree/content fingerprint is unchanged; the diagnoser must contain no code path that creates them.

- [ ] Run the complete Task 6 focused RED target before implementing the coordinator. Preserve failures for missing lifecycle ordering, receipt race handling, signal/failure aggregation, terminal ownership, and read-only verification.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" CoordinatorLifecycleTests ResultVerifierTests
```

- [ ] Implement every Task 6 interface exercised by the RED suite: shell-free child commands, matrix aggregation, spool archival, the coordinator, and the read-only result verifier/status classifier. The coordinator alone creates `RUNNING.json`, `MATRIX_SUMMARY.json`, `DIAGNOSTIC_COMPLETE.json`, or `DIAGNOSTIC_FAILED.json`. It holds the same shared-lock file descriptor through terminal-marker link and parent-directory `fsync`; children neither inherit nor reacquire it.

- [ ] Ensure `DIAGNOSTIC_COMPLETE.json` means evidence integrity only. A matrix containing finite `DIFF` exits zero and remains explicitly labeled `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`.

- [ ] Run the focused GREEN target, then full regression and hash checkpoint.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py" CoordinatorLifecycleTests ResultVerifierTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_numeric_diag.py"
/usr/bin/shasum -a 256 diagnose_batch_invariance.py test_numeric_diag.py
```

### Task 7: Build and Test the Thin Slurm Runner

**Files**

- Create: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/run_numeric_diag.sbatch`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_submit_numeric_diag.py`

**Interfaces**

- **Consumes:** Task 6 coordinator CLI, Task 3 immutable input freeze, exactly two submitter-provided positional arguments, and Slurm's `$0`/`SLURM_JOB_ID`.
- **Produces:** fixed A100 resource request, verified environment/spool bootstrap, and one `exec` call into the coordinator.

**Runner contract**

```bash
#!/bin/bash
#SBATCH --job-name=audattn_v4_numdiag
#SBATCH --partition=GPU-1A
#SBATCH --nodes=1
#SBATCH --gpus=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=01:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
#SBATCH --output=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/logs/audattn_v4_numdiag_%j.log
#SBATCH --error=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/logs/audattn_v4_numdiag_%j.log
```

- [ ] Create `test_submit_numeric_diag.py` using an absolute `spec_from_file_location` test loader, then write RED static runner tests for every directive, exactly two positional arguments (`input-freeze SHA`, `intent nonce`), numeric `SLURM_JOB_ID`, `umask 077`, absolute paths, clean environment, `-I -B`, and a final `exec` into the coordinator.

- [ ] Add RED static/embedded-bootstrap tests for spool/live/frozen SHA mismatch and an existing submitted-runner archive. The test extracts the stdlib bootstrap body between fixed sentinel comments and executes its pure validation functions against temporary fixture paths; it must not add a production environment-variable root override. The full fake-Slurm integration exercises the real submit/coordinator argv boundary, while the immutable production shell itself is additionally gated by `bash -n`, exact-text assertions, hashes, and remote preflight.

- [ ] Run the complete Task 7 focused RED target before creating the runner implementation. Preserve the expected missing/invalid-runner failures.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py" RunnerContractTests
```

- [ ] Implement the runner as a thin bootstrap. Unset Python, Conda, virtualenv, preload, and dynamic-loader injection variables; keep only the fixed allowlist. A stdlib-only bootstrap must verify freeze SHA, live production hashes, `$0` spool bytes, intent nonce, and environment fingerprint before `exec`. Receipt/job binding is deliberately checked by the coordinator's bounded wait because Slurm can start before the submitter publishes its receipt.

- [ ] Resolve scratch as `${SLURM_TMPDIR}/audattn_v4_numdiag_${SLURM_JOB_ID}` when Slurm provides a real user-owned node-local directory. Otherwise allow only the literal `/tmp` when it is root-owned, sticky, mode `01777`, on a different device/mount from both NFS roots, and not an NFS/network filesystem; atomically create `/tmp/audattn_v4_numdiag_${SLURM_JOB_ID}` with owner equal to the job UID and mode `0700`. Reject every other fallback. Pass only the verified `DIAG_SCRATCH_ROOT` to the coordinator; each cold worker creates its own exclusive subtree.

- [ ] For coordinator and every child, redirect all general and framework write locations into exclusive scratch: `HOME`, `XDG_CACHE_HOME`, `TORCH_HOME`, `TMPDIR`, `TMP`, `TEMP`, `MPLCONFIGDIR`, `NUMBA_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`, `TRITON_CACHE_DIR`, and `CUDA_CACHE_PATH`. Record the resolved paths and assert none is inside the account home, frozen v4, or diagnostic NFS root. Add a filesystem write-audit test that fails on any unexpected file outside scratch/artifact output.

```bash
/usr/bin/mkdir -m 0700 \
  "$SCRATCH_ROOT/coordinator-home" \
  "$SCRATCH_ROOT/coordinator-cache" \
  "$SCRATCH_ROOT/coordinator-torch" \
  "$SCRATCH_ROOT/coordinator-tmp" \
  "$SCRATCH_ROOT/coordinator-mpl" \
  "$SCRATCH_ROOT/coordinator-numba"
exec /usr/bin/env -i \
  HOME="$SCRATCH_ROOT/coordinator-home" \
  PATH=/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  XDG_CACHE_HOME="$SCRATCH_ROOT/coordinator-cache" \
  TORCH_HOME="$SCRATCH_ROOT/coordinator-torch" \
  TMPDIR="$SCRATCH_ROOT/coordinator-tmp" TMP="$SCRATCH_ROOT/coordinator-tmp" \
  TEMP="$SCRATCH_ROOT/coordinator-tmp" MPLCONFIGDIR="$SCRATCH_ROOT/coordinator-mpl" \
  NUMBA_CACHE_DIR="$SCRATCH_ROOT/coordinator-numba" \
  SLURM_JOB_ID="$SLURM_JOB_ID" DIAG_SCRATCH_ROOT="$SCRATCH_ROOT" \
  CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES" \
  /home/s2510040/miniconda3/envs/attn/bin/python -I -B \
  /home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/tools/diagnose_batch_invariance.py \
  run-coordinator --job-id "$SLURM_JOB_ID" \
  --intent-nonce "$INTENT_NONCE" \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA" \
  --spool-runner "$0"
```

- [ ] The coordinator, immediately after bootstrap, create-once archives exact `$0` bytes as `submitted_runners/${SLURM_JOB_ID}.sbatch` and verifies its SHA against the reviewed runner in `input_freeze.json`. The shell must not write terminal markers.

- [ ] Run Bash syntax plus the focused GREEN target only after the runner implementation exists.

```bash
/bin/bash -n "$PWD/run_numeric_diag.sbatch"
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py" RunnerContractTests
```

Expected GREEN: Bash syntax exit 0 and all runner contract tests pass.

- [ ] Record a checkpoint.

```bash
/usr/bin/shasum -a 256 run_numeric_diag.sbatch test_submit_numeric_diag.py
```

### Task 8: Implement Durable Exactly-Once Submission and Read-Only Status

**Files**

- Create: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/submit_numeric_diag.py`
- Modify: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/test_submit_numeric_diag.py`

**Interfaces**

- **Consumes:** Task 7 runner path/argument contract and Task 3 immutable freeze; shell-free injected scheduler commands in tests.
- **Produces:** durable intent/raw response/receipt, exactly-once submission result, and read-only status for Tasks 10–12.

- `CommandOutcome` is a frozen dataclass containing `argv: tuple[str, ...]`, `returncode: int`, and raw `stdout`/`stderr: bytes`.
- `SubmissionError` and `AmbiguousSubmissionError` separate definite refusal from uncertain external submission state.
- `SubmissionJournal` owns lock/intent/raw-response/receipt persistence; `SchedulerGateway` owns shell-free `squeue`, `sacct`, and `sbatch` calls.
- `SubmissionContract` is a frozen dataclass containing all fixed production paths, job names, confirmation strings, and hashes.
- `submit(confirm_action: str, confirm_v4_job_id: str, expected_input_freeze_sha256: str, *, contract: SubmissionContract, gateway: SchedulerGateway) -> dict[str, Any]` returns the canonical submission report.
- `status(*, contract: SubmissionContract, gateway: SchedulerGateway) -> dict[str, Any]` returns a canonical read-only state report.
- `run_cli(argv: Sequence[str], *, contract: SubmissionContract, gateway: SchedulerGateway) -> int` is the hermetic library seam. Production `main(argv: Sequence[str] | None = None) -> int` constructs `PRODUCTION_CONTRACT` and a real `SchedulerGateway`; only tests call `run_cli()` with a temporary contract/fake gateway. No production CLI flag or environment variable replaces fixed paths.
- `SUBMISSION_RECEIPT.json` contains at minimum string fields `job_id`, `intent_nonce`, `input_freeze_sha256`, and `runner_sha256`, plus the bound response-record SHA. Its schema and types are validated before either coordinator execution or monitoring trusts the Job ID.

- [ ] Write RED tests for a nonblocking exclusive `state/submission.lock`, active `audattn_samebank_v4` or `audattn_v4_numdiag` jobs, malformed/failed/timed-out `squeue`, and any pre-existing attempt/spool/terminal evidence.

- [ ] Write RED tests proving `INTENT.json` is durable before `sbatch`, that `subprocess.run(argv, shell=False)` invokes `sbatch` exactly once, and that the exact canonical argv is constructed as follows:

```python
argv = [
    "/usr/bin/sbatch",
    "--parsable",
    "--export=NONE",
    f"--comment=audattn-v4-numdiag-{intent_nonce[:12]}",
    "/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/tools/run_numeric_diag.sbatch",
    expected_input_freeze_sha256,
    intent_nonce,
]
```

- [ ] Test nonzero exit, timeout, signal, stderr, empty output, `123;cluster`, whitespace-surrounded text other than a pure numeric ID, and receipt write failure. Persist `SBATCH_RESPONSE.json` with return code and base64 raw stdout/stderr. Any ambiguity leaves an unresolved intent and permanently blocks automatic resubmission.

- [ ] Test idempotency: a matching valid intent+receipt returns `ALREADY_SUBMITTED` without `sbatch`; intent without receipt, mismatched receipt, or existing attempt evidence returns `STOP_AMBIGUOUS` without `sbatch`.

- [ ] Test the submitter's small stdlib-only create-once writer against the same no-symlink/no-overwrite/fsync contract as the diagnoser. Keep it local to `submit_numeric_diag.py`; do not make the isolated submitter import the GPU diagnoser merely to share persistence code.

- [ ] Test `status` as strictly read-only. It distinguishes `PENDING/RUNNING`, `DIAGNOSTIC_COMPLETE`, `DIAGNOSTIC_FAILED`, and `INCOMPLETE_UNTRAPPED_TERMINATION` using receipt, markers, `squeue`, and `sacct`; it never submits or mutates.

- [ ] Run RED.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py" SubmissionJournalTests StatusTests
```

- [ ] Implement fixed production constants and only these public CLI forms:

```text
submit_numeric_diag.py submit \
  --confirm-action SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC \
  --confirm-v4-job-id 646900 \
  --expected-input-freeze-sha256 "$INPUT_FREEZE_SHA"
submit_numeric_diag.py status
```

Do not expose mutable production root, runner, Python, partition, or resource flags.

- [ ] Run GREEN and full submission tests.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py" SubmissionJournalTests StatusTests
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py"
/usr/bin/shasum -a 256 submit_numeric_diag.py test_submit_numeric_diag.py
```

### Task 9: Complete Operator Documentation and the Local Release Gate

**Files**

- Create: `same_bank_eval_2026_09_03_v4_numeric_diag_v1/README.md`
- Modify as needed after review: all six code/test files in the package
- Modify: `docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md`

**Interfaces**

- **Consumes:** all code/test/runner contracts and their final local test/hash evidence from Tasks 1–8.
- **Produces:** a reviewed seven-file local release and copy-safe operator procedure consumed by Tasks 10–12.

- [ ] Write README sections for scope, Job 646900 facts, non-conclusions, all frozen identities, package hashes, seven-file inventory, local tests, new-root/no-overwrite deployment, freeze/check commands, exactly-once submission, execution order, artifact schema, 1 GiB cap, `DIFF` versus `INVALID`, status/results audit, terminal-state semantics, and the no-auto-retry rule. README must state that loading only formal40 changes resident-model allocation context relative to Job646900, and that A2 non-reproduction therefore cannot rule out multi-model residency or original compiler-cache context. README may embed the six non-README file hashes; record the README's own final hash only in the external release transcript/master record to avoid an impossible self-hash cycle.

- [ ] Include complete copy-safe command blocks rather than prose pasted into shells. State clearly that `sbatch` survives SSH/tmux disconnection and that tmux is optional observation only.

- [ ] Add an AST/call-recorder security test and a positive whitelist test. The release must fail if production code invokes v4 `run_evaluation`, attempt/publication helpers, or any write helper with a path under the v4 root. Literal forbidden-marker names are allowed only in the read-only result verifier that proves their absence.

```bash
if rg --pcre2 -n '\.run_evaluation\(|\._create_attempt_directory\(|\.publish_(smoke|audit)' \
  diagnose_batch_invariance.py numeric_trace.py submit_numeric_diag.py run_numeric_diag.sbatch; then
  echo 'STOP: forbidden v4 callable surface found' >&2
  exit 2
fi
```

- [ ] Run the full local release gate with the environment that has NumPy/pandas/Torch; do not use the system Python lacking those dependencies.

```bash
cd /Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1
P=/opt/anaconda3/envs/audattn/bin/python
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0

"$P" -I -B "$PWD/test_numeric_diag.py"
"$P" -I -B "$PWD/test_submit_numeric_diag.py"
/bin/bash -n "$PWD/run_numeric_diag.sbatch"
"$P" -I -B -c 'import ast,pathlib,sys; [ast.parse(pathlib.Path(p).read_text()) for p in sys.argv[1:]]' \
  "$PWD/numeric_trace.py" "$PWD/diagnose_batch_invariance.py" \
  "$PWD/submit_numeric_diag.py" "$PWD/test_numeric_diag.py" \
  "$PWD/test_submit_numeric_diag.py"
/opt/anaconda3/bin/ruff check --no-cache \
  numeric_trace.py diagnose_batch_invariance.py submit_numeric_diag.py \
  test_numeric_diag.py test_submit_numeric_diag.py
/opt/anaconda3/bin/ruff format --check --no-cache \
  numeric_trace.py diagnose_batch_invariance.py submit_numeric_diag.py \
  test_numeric_diag.py test_submit_numeric_diag.py
```

- [ ] Run a fake-Slurm end-to-end integration through `run_cli(test_argv, gateway=fake_gateway, contract=fixture_contract)` at the Python entry seam, the parsed immutable runner argument contract, coordinator, five children, inventories, and result verifier. The test must not require `/usr/bin/sbatch` or `/home/...` on the Mac; a separate assertion proves production `main()` uses only `PRODUCTION_CONTRACT`. Require exactly one fake scheduler call, zero frozen-v4 writes, and a valid complete marker even when a cell is finite `DIFF`.

```bash
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$P" -I -B "$PWD/test_submit_numeric_diag.py" HermeticFakeSlurmIntegrationTests
```

- [ ] Finalize hashes in dependency order without placeholders: freeze `numeric_trace.py` first; compute its exact byte size and SHA-256; insert those actual literals as `NUMERIC_TRACE_SIZE`/`NUMERIC_TRACE_SHA256` in `diagnose_batch_invariance.py`; rerun isolated-loader and full numeric tests; then freeze/hash the diagnoser, submitter, runner, and tests. If `numeric_trace.py` changes afterward, repeat this sequence before any remote upload. Assert the production constants equal the local file record.

- [ ] Compute the six non-README hashes and paste those actual values into a machine-readable README block delimited by exact lines `<!-- RELEASE_SHA256_BEGIN -->` and `<!-- RELEASE_SHA256_END -->`, with one standard `64hex␠␠relative-name` checksum line for each non-README file. Rerun all tests after that edit, then compute all seven final hashes and save the authoritative output in the implementation transcript and later master record. Task 10 must consume these reviewed README literals with `shasum -c`; it must not regenerate expected values from the files being checked.

```bash
/usr/bin/shasum -a 256 \
  diagnose_batch_invariance.py numeric_trace.py submit_numeric_diag.py \
  run_numeric_diag.sbatch test_numeric_diag.py test_submit_numeric_diag.py README.md
```

- [ ] Have a fresh reviewer inspect spec compliance, security boundaries, numerical semantics, and operator commands. Address findings through new RED tests; rerun the full release gate. No remote work begins until review says ready.

### Task 10: Publish Once to a Fresh Remote Root and Freeze Inputs

**Files**

- Remote create: `/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/tools/{diagnose_batch_invariance.py,numeric_trace.py,submit_numeric_diag.py,run_numeric_diag.sbatch}`
- Remote create: `/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/input_freeze.json`
- Modify: `/Users/gigi/发表/超算/docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md`
- Never modify: `/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/**`

**Interfaces**

- **Consumes:** Task 9 reviewed local hashes/package and the fixed v4 identity contract.
- **Produces:** create-once remote production tools, reviewed `input_freeze.json` SHA, and zero-write preflight evidence for Task 11.

- [ ] On the Mac, verify the approved spec and all final local hashes again. Extract the four production expected hashes from the reviewed machine-readable block in README; never derive an expected value by hashing the same file immediately before checking it.

```bash
set -eu
cd /Users/gigi/发表/超算/same_bank_eval_2026_09_03_v4_numeric_diag_v1
test "$(/usr/bin/shasum -a 256 ../docs/superpowers/specs/2026-09-03-v4-numerical-diagnostic-design.md | awk '{print $1}')" = \
  9508225bc6f1aa463423f3c50528c888a7b2450dde2f0997e6edaea8acf3ec15
printf 'Paste REVIEWED_README_SHA from the closed Task 9 release record: ' >&2
IFS= read -r REVIEWED_README_SHA
case "$REVIEWED_README_SHA" in
  ''|*[!0-9a-f]*) echo 'STOP: invalid reviewed README SHA' >&2; exit 2 ;;
esac
test "${#REVIEWED_README_SHA}" -eq 64
printf '%s  %s\n' "$REVIEWED_README_SHA" README.md |
  /usr/bin/shasum -a 256 -c -
RELEASE_LINES=$(
  /usr/bin/sed -n \
    '/^<!-- RELEASE_SHA256_BEGIN -->$/,/^<!-- RELEASE_SHA256_END -->$/p' \
    README.md |
  /usr/bin/awk '/^[0-9a-f]{64}  [A-Za-z0-9_.-]+$/ { print }'
)
test "$(printf '%s\n' "$RELEASE_LINES" | /usr/bin/wc -l | tr -d ' ')" = 6
printf '%s\n' "$RELEASE_LINES" | /usr/bin/shasum -a 256 -c -
D_SHA=$(printf '%s\n' "$RELEASE_LINES" | /usr/bin/awk '$2 == "diagnose_batch_invariance.py" {print $1}')
N_SHA=$(printf '%s\n' "$RELEASE_LINES" | /usr/bin/awk '$2 == "numeric_trace.py" {print $1}')
S_SHA=$(printf '%s\n' "$RELEASE_LINES" | /usr/bin/awk '$2 == "submit_numeric_diag.py" {print $1}')
R_SHA=$(printf '%s\n' "$RELEASE_LINES" | /usr/bin/awk '$2 == "run_numeric_diag.sbatch" {print $1}')
for H in "$D_SHA" "$N_SHA" "$S_SHA" "$R_SHA"; do
  test "${#H}" = 64
done
printf 'REVIEWED_PRODUCTION_SHA=%s\n' "$D_SHA" "$N_SHA" "$S_SHA" "$R_SHA"
```

- [ ] Run a read-only remote preflight: the base must be a real directory (create only if absent), the exact v1 root must be unused and not a symlink, and both official/diagnostic job-name queries must be empty. Stop on any existing v1 path; never reuse it.

```bash
ssh s2510040@hakusan1 '
  set -eu
  BASE=/home/s2510040/audattn_external_eval_diag
  ROOT=$BASE/same_bank_v4_job646900_2026-09-03_v1
  test ! -L "$BASE"
  if test -e "$BASE"; then test -d "$BASE"; fi
  test ! -e "$ROOT"
  test ! -L "$ROOT"
  set +e
  OFFICIAL_OUT=$(squeue -h -u "$USER" -n audattn_samebank_v4 -o "%A|%T|%j" 2>&1)
  OFFICIAL_RC=$?
  DIAG_OUT=$(squeue -h -u "$USER" -n audattn_v4_numdiag -o "%A|%T|%j" 2>&1)
  DIAG_RC=$?
  set -e
  if ! { test "$OFFICIAL_RC" -eq 0 && test "$DIAG_RC" -eq 0 &&
         test -z "$OFFICIAL_OUT" && test -z "$DIAG_OUT"; }; then
    printf "OFFICIAL_RC=%s OUTPUT=%s\n" "$OFFICIAL_RC" "$OFFICIAL_OUT" >&2
    printf "DIAG_RC=%s OUTPUT=%s\n" "$DIAG_RC" "$DIAG_OUT" >&2
    exit 2
  fi
  echo REMOTE_DIAGNOSTIC_ROOT_PREFLIGHT=PASS
'
```

- [ ] Create the fresh root and fixed directories `tools`, `.upload-staging`, `logs`, `state`, `attempts`, and `submitted_runners`, all with `umask 077`, exact owner, mode `0700`, real-directory type, and no symlinks; `fsync` the base/root directories with a short stdlib Python check. Upload the four production files into staging and verify every remote staging SHA against the four locally captured values. The fixture/fake-Slurm test must prove that a missing `logs/` directory blocks submission before `sbatch`.

```bash
ssh s2510040@hakusan1 '
  set -eu
  umask 077
  BASE=/home/s2510040/audattn_external_eval_diag
  ROOT=$BASE/same_bank_v4_job646900_2026-09-03_v1
  test ! -L "$BASE"
  if ! test -e "$BASE"; then /usr/bin/mkdir -m 0700 "$BASE"; fi
  test -d "$BASE"
  test ! -e "$ROOT"
  test ! -L "$ROOT"
  /usr/bin/mkdir -m 0700 "$ROOT"
  /usr/bin/mkdir -m 0700 \
    "$ROOT/tools" "$ROOT/.upload-staging" "$ROOT/logs" \
    "$ROOT/state" "$ROOT/attempts" "$ROOT/submitted_runners"
  for P in "$ROOT" "$ROOT/tools" "$ROOT/.upload-staging" \
           "$ROOT/logs" "$ROOT/state" "$ROOT/attempts" \
           "$ROOT/submitted_runners"; do
    test -d "$P"
    test ! -L "$P"
    test "$(/usr/bin/stat -c %U "$P")" = "$USER"
    test "$(/usr/bin/stat -c %a "$P")" = 700
  done
  /home/s2510040/miniconda3/envs/attn/bin/python -I -B -c \
    "import os,sys; f=[os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW) for p in sys.argv[1:]]; [os.fsync(x) for x in f]; [os.close(x) for x in f]" \
    "$BASE" "$ROOT"
  echo REMOTE_DIAGNOSTIC_ROOT_CREATED=PASS
'
```

```bash
scp diagnose_batch_invariance.py numeric_trace.py submit_numeric_diag.py run_numeric_diag.sbatch \
  s2510040@hakusan1:audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/.upload-staging/
```

- [ ] Publish each file with a no-overwrite hard link from staging to `tools`, verify its SHA, unlink only the staging name, and remove the empty staging directory. If any step fails, preserve the entire root for audit and stop; do not repair or republish in place.

```bash
for H in "$D_SHA" "$N_SHA" "$S_SHA" "$R_SHA"; do test "${#H}" = 64; done
ssh s2510040@hakusan1 /bin/bash -s -- \
  "$D_SHA" "$N_SHA" "$S_SHA" "$R_SHA" <<'REMOTE'
set -eu
test "$#" -eq 4
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
STAGE=$ROOT/.upload-staging
TOOLS=$ROOT/tools
FILES=(diagnose_batch_invariance.py numeric_trace.py submit_numeric_diag.py run_numeric_diag.sbatch)
HASHES=("$1" "$2" "$3" "$4")

for I in 0 1 2 3; do
  SRC=$STAGE/${FILES[$I]}
  DST=$TOOLS/${FILES[$I]}
  SHA=${HASHES[$I]}
  test -f "$SRC" && test ! -L "$SRC"
  test "$(/usr/bin/stat -c %h "$SRC")" = 1
  test ! -e "$DST" && test ! -L "$DST"
  printf '%s  %s\n' "$SHA" "$SRC" | /usr/bin/sha256sum -c -
  /usr/bin/ln "$SRC" "$DST"
  printf '%s  %s\n' "$SHA" "$DST" | /usr/bin/sha256sum -c -
  /usr/bin/unlink "$SRC"
  test -f "$DST" && test ! -L "$DST"
  test "$(/usr/bin/stat -c %h "$DST")" = 1
done

/usr/bin/rmdir "$STAGE"
/home/s2510040/miniconda3/envs/attn/bin/python -I -B -c \
  'import os,sys; f=[os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW) for p in sys.argv[1:]]; [os.fsync(x) for x in f]; [os.close(x) for x in f]' \
  "$ROOT" "$TOOLS"
for I in 0 1 2 3; do
  printf '%s  %s\n' "${HASHES[$I]}" "$TOOLS/${FILES[$I]}" |
    /usr/bin/sha256sum -c -
done
echo REMOTE_PRODUCTION_TOOLS_PUBLISHED=PASS
REMOTE
```

- [ ] Run production `audit-inputs`, then the one allowed create-once freeze command.

```bash
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
DIAG="$ROOT/tools/diagnose_batch_invariance.py"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0

"$PYTHON" -I -B "$DIAG" audit-inputs
"$PYTHON" -I -B "$DIAG" freeze-inputs \
  --confirm-protocol formal40_batch_invariance_diag_20260903_v1
/usr/bin/sha256sum "$ROOT/input_freeze.json"
```

- [ ] Human-review `input_freeze.json`: exact fixed hashes, 32 trial identities and bank rows, all referenced clips, imported snapshot records, four production hashes, protocol/role, and empty attempt/state except freeze layout. After review, copy its observed 64-hex SHA as a literal into the create-once Task 10 approval section of the implementation transcript and label it `REVIEWED_INPUT_FREEZE_SHA`. Do not approve a shell assignment that recomputes this expected value from the current remote file. In this and every later task, paste only that reviewed literal when prompted, validate its syntax, and use `sha256sum -c` before trusting the file.

- [ ] Before `sbatch`, require real non-symlink directories `logs`, `state`, `attempts`, and `submitted_runners` to have been created by the reviewed root bootstrap and revalidated by `freeze-inputs/check-only`; require `state/` to contain only immutable freeze-related files and require the other output directories to be empty. The coordinator later creates exactly `attempts/slurm-${SLURM_JOB_ID}`. This pre-created `logs/` directory is mandatory because Slurm must open the absolute `#SBATCH --output` path before the runner starts.

```bash
set -eu
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
DIAG="$ROOT/tools/diagnose_batch_invariance.py"
printf 'Paste REVIEWED_INPUT_FREEZE_SHA from the approved Task 10 transcript: ' >&2
IFS= read -r REVIEWED_INPUT_FREEZE_SHA
case "$REVIEWED_INPUT_FREEZE_SHA" in
  ''|*[!0-9a-f]*) echo 'STOP: invalid reviewed freeze SHA' >&2; exit 2 ;;
esac
test "${#REVIEWED_INPUT_FREEZE_SHA}" -eq 64
printf '%s  %s\n' "$REVIEWED_INPUT_FREEZE_SHA" "$ROOT/input_freeze.json" |
  /usr/bin/sha256sum -c -

tree_fp() {
  (set -o pipefail; cd "$ROOT" && /usr/bin/find . -xdev \
    -printf '%P\t%y\t%m\t%s\t%T@\t%D\t%i\t%l\0' |
    LC_ALL=C /usr/bin/sort -z | /usr/bin/sha256sum | /usr/bin/awk '{print $1}')
}
content_fp() {
  (set -o pipefail; cd "$ROOT" && /usr/bin/find . -xdev -type f -print0 |
    LC_ALL=C /usr/bin/sort -z | /usr/bin/xargs -0 -r /usr/bin/sha256sum |
    /usr/bin/sha256sum | /usr/bin/awk '{print $1}')
}
TREE_BEFORE=$(tree_fp)
CONTENT_BEFORE=$(content_fp)
set +e
"$PYTHON" -I -B "$DIAG" check-only \
  --expected-input-freeze-sha256 "$REVIEWED_INPUT_FREEZE_SHA"
CHECK_RC=$?
set -e
TREE_AFTER=$(tree_fp)
CONTENT_AFTER=$(content_fp)
test "$CHECK_RC" -eq 0
test "$TREE_BEFORE" = "$TREE_AFTER"
test "$CONTENT_BEFORE" = "$CONTENT_AFTER"
printf 'CHECK_ONLY_ZERO_WRITE=PASS TREE=%s CONTENT=%s\n' \
  "$TREE_AFTER" "$CONTENT_AFTER"
```

- [ ] Record remote production hashes, the literal `REVIEWED_INPUT_FREEZE_SHA`, tree/content fingerprints, and the zero-write proof in the implementation transcript. Close that approval section create-once and do not submit in the same unchecked shell block.

### Task 11: Submit Exactly One A100 Diagnostic and Monitor It Without Resubmission

**Files**

- Remote create-once: `state/INTENT.json`
- Remote create-once: `state/SBATCH_RESPONSE.json`
- Remote create-once: `state/SUBMISSION_RECEIPT.json`
- Remote create-once during job: `submitted_runners/JOB_ID.sbatch`, `attempts/slurm-JOB_ID/**`, one terminal marker

**Interfaces**

- **Consumes:** Task 10 reviewed remote freeze SHA and Task 8 submit/status CLI.
- **Produces:** one durable receipt/Job ID and one completed, failed, or incomplete evidence chain for Task 12.

- [ ] In a fresh shell, paste the exact `REVIEWED_INPUT_FREEZE_SHA` literal from the closed Task 10 approval record; do not recompute it. Verify it with `sha256sum -c`, re-run `check-only`, separately require successful/empty `squeue` queries for both job names, then invoke the submitter once.

```bash
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
DIAG="$ROOT/tools/diagnose_batch_invariance.py"
SUBMIT="$ROOT/tools/submit_numeric_diag.py"
set -eu
printf 'Paste REVIEWED_INPUT_FREEZE_SHA from the approved Task 10 transcript: ' >&2
IFS= read -r REVIEWED_INPUT_FREEZE_SHA
case "$REVIEWED_INPUT_FREEZE_SHA" in
  ''|*[!0-9a-f]*) echo 'STOP: invalid reviewed freeze SHA' >&2; exit 2 ;;
esac
test "${#REVIEWED_INPUT_FREEZE_SHA}" -eq 64
printf '%s  %s\n' "$REVIEWED_INPUT_FREEZE_SHA" "$ROOT/input_freeze.json" |
  /usr/bin/sha256sum -c -
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$PYTHON" -I -B "$DIAG" check-only \
    --expected-input-freeze-sha256 "$REVIEWED_INPUT_FREEZE_SHA"

set +e
OFFICIAL_OUT=$(squeue -h -u "$USER" -n audattn_samebank_v4 -o '%A|%T|%j' 2>&1)
OFFICIAL_RC=$?
DIAG_OUT=$(squeue -h -u "$USER" -n audattn_v4_numdiag -o '%A|%T|%j' 2>&1)
DIAG_RC=$?
set -e
if ! { test "$OFFICIAL_RC" -eq 0 && test "$DIAG_RC" -eq 0 &&
       test -z "$OFFICIAL_OUT" && test -z "$DIAG_OUT"; }; then
  printf 'OFFICIAL_RC=%s OUTPUT=%s\n' "$OFFICIAL_RC" "$OFFICIAL_OUT" >&2
  printf 'DIAG_RC=%s OUTPUT=%s\n' "$DIAG_RC" "$DIAG_OUT" >&2
  exit 2
fi

PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$PYTHON" -I -B "$SUBMIT" submit \
    --confirm-action SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC \
    --confirm-v4-job-id 646900 \
    --expected-input-freeze-sha256 "$REVIEWED_INPUT_FREEZE_SHA"
```

- [ ] Parse the numeric Job ID only from the durable receipt; do not scrape a partially displayed shell variable.

```bash
JOB_ID=$(/usr/bin/jq -er '.job_id | select(type == "string" and test("^[0-9]+$"))' \
  "$ROOT/state/SUBMISSION_RECEIPT.json")
/usr/bin/jq -e --arg sha "$REVIEWED_INPUT_FREEZE_SHA" \
  '.input_freeze_sha256 == $sha and (.intent_nonce | type == "string")' \
  "$ROOT/state/SUBMISSION_RECEIPT.json" >/dev/null
printf 'JOB_ID=%s\n' "$JOB_ID"
set +e
SQUEUE_OUTPUT=$(squeue -j "$JOB_ID" -o '%.18i %.32j %.10T %.12M %.24R' 2>&1)
SQUEUE_RC=$?
set -e
printf '%s\n' "$SQUEUE_OUTPUT"
printf 'SQUEUE_RC=%s (nonzero may mean the job already left the live queue)\n' "$SQUEUE_RC"
sacct -j "$JOB_ID" -X \
  --format=JobIDRaw,JobName,State,ExitCode,Submit,Start,End,Elapsed,NodeList,Comment
```

- [ ] Once the receipt exists, never call submit again. SSH and tmux may disconnect safely. Monitor with `squeue` while active and `sacct` after it leaves the queue; read the log, not terminal scrollback.

- [ ] If SSH disconnects during the single submit attempt, run only the read-only recovery block below. A receipt authorizes monitoring; an intent without a verified receipt is `STOP_AMBIGUOUS`, so query the nonce/comment with both scheduler views and stop without submitting again. Only absence of both intent and receipt proves that no durable submit attempt began.

```bash
set -eu
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
SUBMIT="$ROOT/tools/submit_numeric_diag.py"
set +e
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$PYTHON" -I -B "$SUBMIT" status
STATUS_RC=$?
set -e
printf 'READ_ONLY_STATUS_RC=%s\n' "$STATUS_RC"
if test -f "$ROOT/state/SUBMISSION_RECEIPT.json" &&
   test ! -L "$ROOT/state/SUBMISSION_RECEIPT.json"; then
  echo RECEIPT_PRESENT_MONITOR_ONLY=PASS
elif test -f "$ROOT/state/INTENT.json" && test ! -L "$ROOT/state/INTENT.json"; then
  INTENT_NONCE=$(/usr/bin/jq -er '.intent_nonce | select(type == "string")' \
    "$ROOT/state/INTENT.json")
  printf 'UNRESOLVED_INTENT_NONCE=%s\n' "$INTENT_NONCE"
  squeue -h -u "$USER" -n audattn_v4_numdiag -o '%A|%T|%j|%k'
  sacct -S 2026-09-03 -X \
    --name=audattn_v4_numdiag \
    --format=JobIDRaw,JobName,State,ExitCode,Submit,Start,End,Comment
  echo STOP_AMBIGUOUS_DO_NOT_SUBMIT >&2
  exit 2
else
  echo NO_DURABLE_SUBMIT_ATTEMPT_FOUND
fi
```

- [ ] If the job ends without either terminal marker, classify it as `INCOMPLETE_UNTRAPPED_TERMINATION`, preserve all evidence, and stop. If it writes `DIAGNOSTIC_FAILED.json`, preserve evidence and stop. Neither state authorizes a retry.

### Task 12: Verify Results, Interpret Only the Allowed Evidence, and Synchronize Documentation

**Files**

- Remote verify: `/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1/**`
- Modify: `/Users/gigi/发表/超算/docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md`
- Modify after a verified terminal result: `/Users/gigi/发表/超算/2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md`
- Stage and sync after review: `/Users/gigi/projects/auditory_attention/全量任务/full训练40轮完成、恢复发布与same-bank评估准备记录_2026-08-30.md`
- Stage and sync after review: `/Users/gigi/projects/auditory_attention/docs/项目进程总结_2026-08-31.md`

**Interfaces**

- **Consumes:** Task 11 receipt/Slurm terminal state and Task 6 read-only result verifier.
- **Produces:** verified interpretation, synchronized master/project records, and exactly one reviewed follow-up decision.

- [ ] Run the read-only result verifier after Slurm termination. It must recompute the submitted-runner SHA, every reference/cell inventory, exact reference equivalence, all four comparisons, before/after frozen-v4 and bound-input fingerprints, summary, terminal marker, and forbidden-marker absence.

```bash
set -eu
ROOT=/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v1
PYTHON=/home/s2510040/miniconda3/envs/attn/bin/python
DIAG="$ROOT/tools/diagnose_batch_invariance.py"
printf 'Paste REVIEWED_INPUT_FREEZE_SHA from the approved Task 10 transcript: ' >&2
IFS= read -r REVIEWED_INPUT_FREEZE_SHA
case "$REVIEWED_INPUT_FREEZE_SHA" in
  ''|*[!0-9a-f]*) echo 'STOP: invalid reviewed freeze SHA' >&2; exit 2 ;;
esac
test "${#REVIEWED_INPUT_FREEZE_SHA}" -eq 64
printf '%s  %s\n' "$REVIEWED_INPUT_FREEZE_SHA" "$ROOT/input_freeze.json" |
  /usr/bin/sha256sum -c -
JOB_ID=$(/usr/bin/jq -er '.job_id | select(type == "string" and test("^[0-9]+$"))' \
  "$ROOT/state/SUBMISSION_RECEIPT.json")
/usr/bin/jq -e --arg sha "$REVIEWED_INPUT_FREEZE_SHA" --arg job "$JOB_ID" \
  '.input_freeze_sha256 == $sha and .job_id == $job' \
  "$ROOT/state/SUBMISSION_RECEIPT.json" >/dev/null

sacct -j "$JOB_ID" -X \
  --format=JobIDRaw,JobName,State,ExitCode,Submit,Start,End,Elapsed,NodeList,Comment
if test -f "$ROOT/logs/audattn_v4_numdiag_${JOB_ID}.log" &&
   test ! -L "$ROOT/logs/audattn_v4_numdiag_${JOB_ID}.log"; then
  tail -n 240 "$ROOT/logs/audattn_v4_numdiag_${JOB_ID}.log"
else
  echo 'LOG_ABSENT_OR_INVALID: continue with terminal/incomplete verifier' >&2
fi
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  "$PYTHON" -I -B "$DIAG" verify-results \
    --expected-input-freeze-sha256 "$REVIEWED_INPUT_FREEZE_SHA" \
    --job-id "$JOB_ID"
```

- [ ] Require either a verified `DIAGNOSTIC_COMPLETE.json` or a verified failure/incomplete audit. For a complete result, extract A1/A2/B1/B2 `canary_status`, first divergence, tensor/trial max differences, worst trial, model-state stability, RNG observations, and A2 replay classification. A Slurm `COMPLETED 0:0` may validly contain `DIFF`.

- [ ] State only conclusions allowed by the approved matrix. Do not infer model quality, independent-test performance, a new tolerance, or a specific CUDA kernel cause. If logits are the first divergence after matching cochleagrams, record only that targeted model-forward tracing is required.

- [ ] Append `### 17.12 Job646900 formal40独立四格数值诊断与证据边界` to the staging master record. Include spec/package/freeze/submitted-runner hashes, intent/receipt/job/Slurm identity, environment/log/terminal hashes, all input fingerprint checks, reference equivalence, four-cell results, A2 classification, permitted/non-permitted conclusions, and exactly one next decision gate.

- [ ] Correct the stale claims in project `docs/项目进程总结_2026-08-31.md` §4.5 and §5 that say v4 was not uploaded/frozen/smoked. Update its title or explicit coverage date to 2026-09-03; do not merely append a contradictory note.

- [ ] Because both project targets are outside this staging root and the project worktree is dirty, build reviewed copies in `/private/tmp`, diff them against the current files, then copy only those exact two files with explicit approval. Do not modify any other project file.

- [ ] Verify the two full-training records are byte-identical and hash all three final documents.

```bash
cmp -s \
  '/Users/gigi/发表/超算/2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md' \
  '/Users/gigi/projects/auditory_attention/全量任务/full训练40轮完成、恢复发布与same-bank评估准备记录_2026-08-30.md'
/usr/bin/shasum -a 256 \
  '/Users/gigi/发表/超算/2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md' \
  '/Users/gigi/projects/auditory_attention/全量任务/full训练40轮完成、恢复发布与same-bank评估准备记录_2026-08-30.md' \
  '/Users/gigi/projects/auditory_attention/docs/项目进程总结_2026-08-31.md'
```

- [ ] End with a result-review checkpoint. Select exactly one later action from the approved decision gate—v5 autocast/batch contract, TF32/compiled separation, targeted forward trace, or environment-difference analysis—and write a new design before executing it.

## Final Acceptance Checklist

- [ ] Every local RED test was observed failing for the intended reason before its GREEN implementation.
- [ ] Both complete local test files, AST parse, Ruff, Bash syntax, isolated-import, fake-Slurm, and denylist gates pass.
- [ ] The seven final local files have reviewed SHA-256 values and README contains no hash placeholders.
- [ ] Remote v1 began unused, was published create-once, and its immutable freeze passed audit/check-only.
- [ ] Exactly one `sbatch` call is proven by intent, raw response, receipt, Job ID, comment, and archived spool bytes.
- [ ] One allocation ran five fresh processes in the fixed order and held the shared v4 lock across all PRE/POST checks and terminal publication.
- [ ] Reference/A2 trace equivalence passed before A1/B1/B2 were interpreted.
- [ ] All four cell inventories and the matrix summary verify; finite `DIFF` was preserved as evidence rather than converted into failure.
- [ ] Frozen v4 and every bound input have matching pre/post records; no scientific publication marker exists.
- [ ] Documentation reports evidence boundaries and was synchronized without disturbing unrelated dirty-worktree changes.
