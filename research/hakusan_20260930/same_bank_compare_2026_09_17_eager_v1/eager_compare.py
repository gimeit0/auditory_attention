#!/usr/bin/env python3
"""Small, eager three-checkpoint qualification candidate. No submission code.

The pinned v4 module supplies scientific I/O, strict loading, native waveform
processing and result validation. This module owns the NEW execution protocol.
It neither calls v4.run_evaluation nor modifies that module's globals.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import sys
import tempfile
import time
import traceback

PROTOCOL = "same_bank_eager_fp32_small_20260917_v1"
ROLE = "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST"
V4_ROOT = Path("/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4")
V4_SHA = "31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4"
MANIFEST_SHA = "1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5"
MODEL_ORDER = ("formal40", "author_external", "valbest33")
CONDITIONS = ("correct", "shuffled", "silent", "distractor")
SEED = 20260829
# Original 32 diagnostic trials: do NOT replace with a fresh convenient sample.
TRIAL_IDS = (
    9000,
    0,
    1,
    158,
    317,
    476,
    634,
    793,
    952,
    1111,
    1269,
    1428,
    1587,
    1745,
    1904,
    2063,
    2222,
    2380,
    2539,
    2698,
    2856,
    3015,
    3174,
    3333,
    3491,
    3650,
    3809,
    3967,
    4126,
    4285,
    4444,
    4602,
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_bytes(path, payload):
    """Exclusive writes; a crash leaves an incomplete attempt, never success."""
    with Path(path).open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def create_json(path, value):
    create_bytes(
        path,
        (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
    )


def load_v4(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), "Invalid v4 source")
    require(sha256(path) == V4_SHA, "Pinned v4 source SHA mismatch")
    spec = importlib.util.spec_from_file_location("pinned_v4_scientific_core", path)
    module = importlib.util.module_from_spec(spec)
    # v4's functions retain their actual __file__, including in manifest checks.
    spec.loader.exec_module(module)
    require(sha256(path) == V4_SHA, "v4 source changed during import")
    return module


@contextlib.contextmanager
def stage(name):
    started = time.monotonic()
    print(f"STAGE_BEGIN={name}", flush=True)
    try:
        yield
    except BaseException:
        print(f"STAGE_FAILED={name}", flush=True)
        raise
    finally:
        print(f"STAGE_SECONDS={name}:{time.monotonic() - started:.3f}", flush=True)


def runtime_values():
    import torch

    return {
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "cudnn_deterministic": torch.backends.cudnn.deterministic,
        "cudnn_benchmark": torch.backends.cudnn.benchmark,
        "matmul_precision": torch.get_float32_matmul_precision(),
        "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_tf32": torch.backends.cudnn.allow_tf32,
    }


def configure_runtime():
    import numpy as np
    import torch

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    values = runtime_values()
    require(
        values
        == {
            "deterministic_algorithms": True,
            "cudnn_deterministic": True,
            "cudnn_benchmark": False,
            "matmul_precision": "highest",
            "matmul_tf32": False,
            "cudnn_tf32": False,
        },
        "FP32 runtime settings did not take effect",
    )
    return values


def unwrap_eager(model):
    """Unwrap ONLY the known model.model wrapper after strict checkpoint load.

    No replacing torch.compile, no recursive callable/closure/environment scan.
    All parameter/buffer bindings must remain the same objects and names apart
    from the one documented OptimizedModule prefix.
    """
    from torch._dynamo.eval_frame import OptimizedModule

    before = dict(model.named_parameters()) | dict(model.named_buffers())
    wrapped = type(model.model) is OptimizedModule
    if wrapped:
        original = model.model._orig_mod
        model.model = original
    expected = {}
    for name, tensor in before.items():
        if wrapped and name.startswith("model._orig_mod."):
            name = "model." + name[len("model._orig_mod.") :]
        require(name not in expected, "Unwrap name collision")
        expected[name] = tensor
    after = dict(model.named_parameters()) | dict(model.named_buffers())
    require(expected.keys() == after.keys(), "Unwrap changed state names")
    require(
        all(after[k] is v for k, v in expected.items()), "Unwrap changed state objects"
    )
    require(
        not any(isinstance(m, OptimizedModule) for m in model.modules()),
        "Unsupported additional compiled wrapper",
    )
    check_model(model)
    return {"known_wrapper_removed": wrapped, "state_bindings_preserved": len(after)}


def check_model(model):
    import torch

    for name, module in model.named_modules():
        require(not module.training, f"Training-mode module: {name}")
        require(
            not getattr(module, "_compiled_call_impl", None), f"Compiled call: {name}"
        )
        require(
            not module._forward_hooks and not module._forward_pre_hooks,
            f"Forward hooks are outside this uninstrumented protocol: {name}",
        )
        if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
            require(module.track_running_stats, f"Batch-dependent BatchNorm: {name}")
    for name, tensor in list(model.named_parameters()) + list(model.named_buffers()):
        require(not tensor.requires_grad, f"Trainable state: {name}")
        if tensor.is_floating_point():
            require(tensor.dtype == torch.float32, f"Non-FP32 state: {name}")
        require(bool(torch.isfinite(tensor).all()), f"Nonfinite state: {name}")


def state_digest(model):
    """Content, binding and version checks at PASS boundaries, not every op."""
    check_model(model)
    records = []
    for kind, entries in (
        ("parameter", model.named_parameters()),
        ("buffer", model.named_buffers()),
    ):
        for name, tensor in entries:
            raw = tensor.detach().cpu().contiguous().numpy().tobytes()
            records.append(
                (
                    kind,
                    name,
                    id(tensor),
                    tensor._version,
                    str(tensor.dtype),
                    tuple(tensor.shape),
                    hashlib.sha256(raw).hexdigest(),
                )
            )
    return records


def rng_digest():
    import numpy as np
    import torch

    # Only explicit RNG generators; never traverse Python runtime object graphs.
    numpy_state = np.random.get_state()
    digest = hashlib.sha256(
        repr((random.getstate(), numpy_state[0], numpy_state[2:])).encode()
    )
    digest.update(numpy_state[1].tobytes())
    digest.update(torch.get_rng_state().numpy().tobytes())
    if torch.cuda.is_initialized():
        for state in torch.cuda.get_rng_state_all():
            digest.update(state.cpu().numpy().tobytes())
    return digest.hexdigest()


def predict(base, model, scene, cue, labels, probes, device):
    import torch

    require(scene.dtype == cue.dtype == torch.float32, "Raw tensors must be FP32")
    before = (base._tensor_hashes(scene), base._tensor_hashes(cue))
    with torch.inference_mode(), torch.autocast(device_type=device.type, enabled=False):
        normalized_scene = base.singleton_native_preprocess(model, scene)
        normalized_cue = base.singleton_native_preprocess(model, cue)
        scene_features, _ = model.coch_gram.full_rep(normalized_scene.to(device), None)
        cue_features, _ = model.coch_gram.full_rep(normalized_cue.to(device), None)
        for value in (normalized_scene, normalized_cue, scene_features, cue_features):
            require(
                value.dtype == torch.float32 and bool(torch.isfinite(value).all()),
                "Preprocessing/features are not finite FP32",
            )
        logits = model(cue_features, scene_features, None)
        require(
            tuple(logits.shape) == (len(labels), 800), "Expected [batch,800] logits"
        )
        require(
            logits.dtype == torch.float32 and bool(torch.isfinite(logits).all()),
            "Logits are not finite FP32",
        )
        logp = logits.log_softmax(-1)
        p = logp.exp()
        predicted = p.argmax(-1)
        require(
            torch.equal(predicted, logits.argmax(-1)),
            "Probability rounding changed argmax relative to logits",
        )
        targets = labels.to(device)[:, None]
        probe_ids = probes.to(device)[:, None]
        values = {
            "pred_label": predicted,
            "nll": -logp.gather(1, targets).squeeze(1),
            "p_target": p.gather(1, targets).squeeze(1),
            "p_probe_distractor": p.gather(1, probe_ids).squeeze(1),
        }
    require(
        before == (base._tensor_hashes(scene), base._tensor_hashes(cue)),
        "Native preprocessing/model mutated shared raw input",
    )
    return {k: v.cpu().numpy() for k, v in values.items()}, logits.cpu().numpy()


def evaluate_pass(
    base,
    bank,
    historical_hashes,
    models,
    device,
    clips_dir,
    cache_class,
    raw_scene_batch,
    correct_cue_batch,
    role_batch,
    batch_size,
):
    """Shared scene/cue tensors for ALL three models, including all controls."""
    import numpy as np
    import torch

    require(
        set(models) == set(MODEL_ORDER), "Exactly the three fixed models are required"
    )
    require(batch_size in (1, 16), "Only predeclared small-run batch sizes 1/16")
    versions = {m: state_digest(models[m]) for m in MODEL_ORDER}
    runtime = runtime_values()
    rng_before = rng_digest()
    bank_before = bank.to_csv(index=False)
    results = base._prepare_result_frame(bank)
    cache = cache_class(max_items=128)
    logits = {f"{m}__{c}": [] for m in MODEL_ORDER for c in CONDITIONS}
    cue_hashes = {c: [] for c in CONDITIONS}
    snr_errors = []
    for start in range(0, len(bank), batch_size):
        frame = bank.iloc[start : start + batch_size]
        pos = np.arange(start, start + len(frame))
        scene = raw_scene_batch(frame, cache, clips_dir, snr_errors=snr_errors)
        correct = correct_cue_batch(frame, cache, clips_dir)
        hashes = base._tensor_hashes(scene)
        require(
            hashes == [historical_hashes[int(i)] for i in frame.trial_id],
            "Regenerated scene differs from frozen Job584990",
        )
        results.loc[pos, "scene_sha256"] = hashes
        results.loc[pos, "correct_cue_sha256"] = base._tensor_hashes(correct)
        labels = torch.tensor(frame.target_label.to_numpy(dtype=np.int64))
        probes = torch.tensor(
            np.where(frame.scene_kind == "mixed", frame.distractor_1_label, 0).astype(
                np.int64
            )
        )
        selected = np.flatnonzero(frame.control_subset.to_numpy(dtype=int) == 1)
        payloads = {"correct": (pos, scene, correct, labels, probes)}
        if len(selected):
            control = frame.iloc[selected]
            cues = {
                "shuffled": role_batch(control, "shuffled_cue", cache, clips_dir),
                "silent": torch.zeros_like(correct[selected]),
                "distractor": role_batch(
                    control, "probe_distractor_cue", cache, clips_dir
                ),
            }
            payloads.update(
                {
                    c: (
                        pos[selected],
                        scene[selected],
                        value,
                        labels[selected],
                        probes[selected],
                    )
                    for c, value in cues.items()
                }
            )
        for condition, (indices, raw, cue, target, probe) in payloads.items():
            cue_hashes[condition].extend(base._tensor_hashes(cue))
            for model_id in MODEL_ORDER:
                with stage(f"forward/{start}/{condition}/{model_id}"):
                    values, output = predict(
                        base, models[model_id], raw, cue, target, probe, device
                    )
                prefix = (
                    model_id if condition == "correct" else f"{model_id}_{condition}"
                )
                for metric, value in values.items():
                    results.loc[indices, f"{prefix}_{metric}"] = value
                results.loc[indices, f"{prefix}_correct"] = (
                    values["pred_label"] == target.numpy()
                ).astype(int)
                if condition != "correct":
                    results.loc[indices, f"{prefix}_probe_intrusion"] = (
                        values["pred_label"] == probe.numpy()
                    ).astype(int)
                logits[f"{model_id}__{condition}"].append(output)
    require(runtime_values() == runtime, "Runtime settings changed during pass")
    require(rng_digest() == rng_before, "Inference consumed or changed RNG state")
    require(
        bank.to_csv(index=False) == bank_before,
        "Scene callbacks mutated frozen bank rows",
    )
    for model_id in MODEL_ORDER:
        require(
            state_digest(models[model_id]) == versions[model_id],
            f"Model state changed: {model_id}",
        )
    base.validate_results(results, full_run=False)
    base.validate_result_identity(results, bank)
    require(all(np.isfinite(snr_errors)), "Nonfinite SNR reconstruction errors")
    arrays = {
        k: np.concatenate(v) if v else np.empty((0, 800), dtype=np.float32)
        for k, v in logits.items()
    }
    return (
        results,
        arrays,
        {
            "cue_hashes": cue_hashes,
            "snr_errors": snr_errors,
            "runtime": runtime,
            "batch_size": batch_size,
            "model_state_unchanged": True,
            "rng_state_unchanged": True,
            "bank_rows_unchanged": True,
        },
    )


def save_pass(output, bank, results, arrays, details):
    import numpy as np

    create_bytes(output / "bank.csv", bank.to_csv(index=False).encode())
    create_bytes(output / "results.csv", results.to_csv(index=False).encode())
    with (output / "logits.npz").open("xb") as handle:
        np.savez(handle, **arrays)
        handle.flush()
        os.fsync(handle.fileno())
    create_json(output / "pass.json", details)


def verify_pass(base, output):
    """Read disk artifacts afresh; recompute metrics from archived logits in NumPy."""
    import numpy as np
    import pandas as pd

    bank = pd.read_csv(
        output / "bank.csv", keep_default_na=False, dtype={"target_speaker": str}
    )
    results = pd.read_csv(
        output / "results.csv", keep_default_na=False, dtype={"target_speaker": str}
    )
    # Keep text such as literal words 'nan'/'null' intact; convert numeric columns explicitly.
    bank["target_speaker"] = bank.target_speaker.astype(str)
    bank["snr_db"] = pd.to_numeric(bank.snr_db.replace("", np.nan), errors="raise")
    identity = base._prepare_result_frame(bank)
    for column in results:
        if column == "snr_db" or column.startswith(tuple(m + "_" for m in MODEL_ORDER)):
            results[column] = pd.to_numeric(
                results[column].replace("", np.nan), errors="raise"
            )
    for frame in (bank, results):
        for column in frame:
            if column in (
                "trial_id",
                "target_label",
                "control_subset",
                "distractor_1_label",
                "probe_distractor_label",
            ) or column.endswith(("_pred_label", "_correct", "_probe_intrusion")):
                values = (
                    pd.to_numeric(frame[column], errors="raise")
                    .dropna()
                    .to_numpy(dtype=float)
                )
                require(
                    bool(np.isfinite(values).all())
                    and bool((values == np.floor(values)).all()),
                    f"Non-integer identity/prediction: {column}",
                )
    base.validate_results(results, full_run=False)
    base.validate_result_identity(results, bank, expected_generated=results)
    controls = bank.control_subset.to_numpy(dtype=int) == 1
    details = json.loads((output / "pass.json").read_text())
    require(
        len(details["cue_hashes"]["correct"]) == len(bank), "Missing correct-cue hashes"
    )
    require(
        details["cue_hashes"]["correct"] == results.correct_cue_sha256.tolist(),
        "Cue identity mismatch",
    )
    with np.load(output / "logits.npz", allow_pickle=False) as archive:
        require(
            set(archive.files)
            == {f"{m}__{c}" for m in MODEL_ORDER for c in CONDITIONS},
            "Wrong logits inventory",
        )
        for model_id in MODEL_ORDER:
            for condition in CONDITIONS:
                mask = (
                    np.ones(len(bank), dtype=bool)
                    if condition == "correct"
                    else controls
                )
                x = archive[f"{model_id}__{condition}"]
                require(
                    x.dtype == np.float32 and x.shape == (int(mask.sum()), 800),
                    "Wrong logits shape/dtype",
                )
                require(bool(np.isfinite(x).all()), "Nonfinite archived logits")
                require(
                    len(details["cue_hashes"][condition]) == int(mask.sum()),
                    "Missing control cue identity",
                )
                if not len(x):
                    continue
                targets = bank.target_label.to_numpy(dtype=int)[mask]
                probes = identity.probe_distractor_label.to_numpy(dtype=int)[mask]
                shifted = x.astype(np.float64) - x.max(axis=1, keepdims=True)
                logp = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
                rows = np.arange(len(x))
                prefix = (
                    model_id if condition == "correct" else f"{model_id}_{condition}"
                )
                require(
                    np.array_equal(
                        x.argmax(1), results.loc[mask, f"{prefix}_pred_label"]
                    ),
                    "Prediction not derived from logits",
                )
                for metric, expected in {
                    "nll": -logp[rows, targets],
                    "p_target": np.exp(logp[rows, targets]),
                    "p_probe_distractor": np.exp(logp[rows, probes]),
                }.items():
                    # CPU float64 vs original FP32 reduction/exp verification only.
                    # This is NOT a new tolerance for batch-size invariance.
                    require(
                        np.allclose(
                            expected,
                            results.loc[mask, f"{prefix}_{metric}"],
                            rtol=1e-6,
                            atol=2e-6,
                        ),
                        f"Metric does not match archived logits: {prefix}/{metric}",
                    )
    return {
        "status": "ARTIFACTS_RECOMPUTED",
        "trials": len(bank),
        "model_condition_predictions": 3 * (len(bank) + 3 * int(controls.sum())),
        "numeric_qualification": "NOT_ESTABLISHED",
        "full_comparison_complete": False,
    }


def verify_receipt(base, output, expected_sha):
    import pandas as pd

    output = base.safe_directory(output, "Attempt")
    receipt_path = base.safe_file(output / "RECEIPT.json", "Receipt")
    require(sha256(receipt_path) == expected_sha, "Receipt SHA mismatch")
    receipt = json.loads(receipt_path.read_text())
    require(
        receipt["protocol"] == PROTOCOL
        and receipt["status"] == "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
        "Wrong receipt",
    )
    expected_files = {
        "RUN.json",
        "LOAD_REPORTS.json",
        "bank.csv",
        "results.csv",
        "logits.npz",
        "pass.json",
    }
    require(set(receipt["files"]) == expected_files, "Incomplete artifact inventory")
    require(
        {p.name for p in output.iterdir()} == expected_files | {"RECEIPT.json"},
        "Unexpected files or failure marker in successful attempt",
    )
    for name, digest in receipt["files"].items():
        base.safe_file(output / name, "Artifact")
        require(sha256(output / name) == digest, f"Artifact changed: {name}")
    run = json.loads((output / "RUN.json").read_text())
    require(
        run["protocol"] == PROTOCOL and run["role"] == ROLE,
        "Wrong scientific role/protocol",
    )
    require(
        run["v4_source_sha256"] == V4_SHA and run["v4_manifest_sha256"] == MANIFEST_SHA,
        "Wrong source inputs",
    )
    require(set(run["models"]) == set(MODEL_ORDER), "Wrong model set")
    for model_id in MODEL_ORDER:
        require(
            run["models"][model_id]["sha256"] == base.EXPECTED_HASHES[model_id],
            "Wrong checkpoint SHA",
        )
    bank = pd.read_csv(output / "bank.csv", keep_default_na=False)
    require(
        tuple(bank.trial_id) == tuple(run["trial_ids"]) == TRIAL_IDS,
        "Wrong fixed small-run trial identities",
    )
    require(
        set(run["historical_scene_hashes"]) == {str(i) for i in TRIAL_IDS},
        "Historical scene binding lacks trial identities",
    )
    result_frame = pd.read_csv(output / "results.csv", keep_default_na=False)
    require(
        result_frame.scene_sha256.tolist()
        == [run["historical_scene_hashes"][str(i)] for i in TRIAL_IDS],
        "Saved scene hashes differ from historical bindings",
    )
    return verify_pass(base, output)


def select_trials(bank):
    require(bank.trial_id.is_unique, "Duplicate bank trial identity")
    selected = (
        bank.set_index("trial_id", drop=False)
        .loc[list(TRIAL_IDS)]
        .reset_index(drop=True)
    )
    require(tuple(selected.trial_id) == TRIAL_IDS, "Wrong diagnostic trial identities")
    return selected


def run_small(args):
    # Check launch context BEFORE numeric imports/any persistent attempt creation.
    require(sys.platform == "linux", "Production candidate requires HAKUSAN Linux")
    require(
        args.confirm == PROTOCOL, "Explicit small-run protocol confirmation required"
    )
    require(
        os.environ.get("SLURM_JOB_ID", "").isdigit(),
        "Run only in an allocated Slurm job",
    )
    require(
        sha256(__file__) == args.expected_candidate_sha256,
        "Candidate source SHA mismatch",
    )
    require(
        os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8",
        "Set CUBLAS_WORKSPACE_CONFIG before Python starts",
    )
    require(sys.flags.isolated and sys.dont_write_bytecode, "Launch with python -I -B")
    base = load_v4(args.v4_core)
    manifest, _ = base._validate_manifest_hash(
        V4_ROOT / "input_freeze.json", MANIFEST_SHA
    )
    output = Path(args.output).absolute()
    base.safe_directory(output.parent, "New candidate output parent")
    for root in list(manifest["roots"].values()) + [str(V4_ROOT)]:
        require(
            not output.is_relative_to(Path(root)),
            "Output must be outside all frozen input roots",
        )
    require(
        not output.exists() and not output.is_symlink(),
        "Attempt output already exists; never overwrite/retry in place",
    )
    scratch_parent = base.safe_directory(args.scratch_parent, "Scratch parent")
    require(
        scratch_parent.is_relative_to(Path("/tmp")),
        "Use an allocated /tmp scratch parent",
    )
    with tempfile.TemporaryDirectory(
        prefix="eager-small-", dir=scratch_parent
    ) as scratch:
        # Task-specific caches only. Never repurpose HOME.
        for key in (
            "TMPDIR",
            "MPLCONFIGDIR",
            "TORCH_HOME",
            "XDG_CACHE_HOME",
            "TORCHINDUCTOR_CACHE_DIR",
        ):
            directory = Path(scratch) / key.lower()
            directory.mkdir(mode=0o700)
            os.environ[key] = str(directory)
        output.mkdir(mode=0o700)
        try:
            with stage("runtime"):
                import torch

                require(
                    not torch.cuda.is_initialized(),
                    "CUDA initialized before initial runtime configuration",
                )
                require(
                    platform.python_version() == "3.11.5"
                    and torch.__version__ == "2.1.1+cu118",
                    "Native environment differs; review before deployment",
                )
                runtime = configure_runtime()
                require(torch.cuda.is_available(), "No CUDA allocation")
                require(
                    "A100" in torch.cuda.get_device_name(0),
                    "This candidate is declared for A100",
                )
                device = torch.device("cuda:0")
            with base.evaluation_lock(V4_ROOT):
                with stage("verify_frozen_inputs"):
                    base.validate_frozen_layout(V4_ROOT, manifest)
                    base.verify_frozen_manifest(manifest, V4_ROOT)
                    bank, _ = base.read_csv_pinned(
                        Path(manifest["inputs"]["bank"]["path"]),
                        "bank",
                        manifest["inputs"]["bank"]["sha256"],
                        sep="\t",
                        dtype={f"{r}_speaker": str for r in base.ROLE_NAMES},
                    )
                    historical, _ = base.read_csv_pinned(
                        Path(
                            manifest["historical_evidence"]["job584990_results"]["path"]
                        ),
                        "historical",
                        manifest["historical_evidence"]["job584990_results"]["sha256"],
                        dtype={"target_speaker": str},
                    )
                    base.validate_historical_scene_binding(bank, historical)
                    selected = select_trials(bank)
                    hashes = dict(
                        zip(
                            historical.trial_id.astype(int),
                            historical.scene_sha256.astype(str),
                        )
                    )
                create_json(
                    output / "RUN.json",
                    {
                        "protocol": PROTOCOL,
                        "role": ROLE,
                        "status": "RUNNING",
                        "job_id": os.environ["SLURM_JOB_ID"],
                        "pid": os.getpid(),
                        "candidate_sha256": args.expected_candidate_sha256,
                        "v4_source_sha256": V4_SHA,
                        "v4_manifest_sha256": MANIFEST_SHA,
                        "model_order": MODEL_ORDER,
                        "models": manifest["models"],
                        "trial_ids": TRIAL_IDS,
                        "historical_scene_hashes": {
                            str(i): hashes[i] for i in TRIAL_IDS
                        },
                        "runtime": runtime,
                        "amp": False,
                        "compiled_forward": False,
                        "batch_size": args.batch_size,
                        "tail_policy": "unmodified smaller final batch",
                        "environment": {
                            "python": platform.python_version(),
                            "torch": torch.__version__,
                            "cuda": torch.version.cuda,
                            "cudnn": torch.backends.cudnn.version(),
                            "device": torch.cuda.get_device_name(0),
                            "hostname": platform.node(),
                        },
                        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    },
                )
                with base._frozen_import_context(
                    Path(manifest["roots"]["snapshot_files"])
                ):
                    import selftrain.data.diotic_attention as data_module
                    import selftrain.scripts.eval_full_pilot as scene_module

                    for module in (data_module, scene_module):
                        source = base.safe_file(
                            base.inspect.getfile(module), "Scene module"
                        )
                        require(
                            source.is_relative_to(
                                Path(manifest["roots"]["snapshot_files"])
                            ),
                            "Scene import escaped the frozen snapshot",
                        )
                    models, reports = {}, {}
                    for model_id in MODEL_ORDER:
                        with stage(f"strict_load/{model_id}"):
                            model, report = base.strict_load_model(
                                manifest, model_id, device=torch.device("cpu")
                            )
                            report["eager_unwrap"] = unwrap_eager(model)
                            model.to(device)
                            models[model_id], reports[model_id] = model, report
                    # Checkpoint construction consumes RNG; the inference pass
                    # starts from an explicit seed, with flags checked beforehand.
                    require(
                        runtime_values() == runtime,
                        "Model loading changed runtime settings",
                    )
                    configure_runtime()
                    create_json(output / "LOAD_REPORTS.json", reports)
                    require(
                        runtime_values() == runtime,
                        "Model loading changed runtime settings",
                    )
                    with stage("shared_scene_and_prediction"):
                        results, arrays, details = evaluate_pass(
                            base,
                            selected,
                            hashes,
                            models,
                            device,
                            Path(manifest["roots"]["clips_dir"]),
                            data_module.WaveformCache,
                            scene_module._raw_scene_batch,
                            scene_module._correct_cue_batch,
                            scene_module._role_batch,
                            args.batch_size,
                        )
                    with stage("save_and_independent_reload"):
                        save_pass(output, selected, results, arrays, details)
                        verification = verify_pass(base, output)
                with stage("postcheck_frozen_inputs"):
                    base.verify_frozen_manifest(manifest, V4_ROOT)
                    require(
                        sha256(__file__) == args.expected_candidate_sha256,
                        "Candidate changed during run",
                    )
            receipt = {
                "protocol": PROTOCOL,
                "status": "SMALL_RUN_COMPLETE_NOT_QUALIFIED",
                "verification": verification,
                "files": {p.name: sha256(p) for p in output.iterdir() if p.is_file()},
            }
            create_json(output / "RECEIPT.json", receipt)
            print(
                json.dumps(
                    {
                        "status": receipt["status"],
                        "receipt_sha256": sha256(output / "RECEIPT.json"),
                        "output": str(output),
                    }
                ),
                flush=True,
            )
        except BaseException as error:
            create_bytes(output / "FAILURE.txt", traceback.format_exc().encode())
            create_json(
                output / "FAILED.json",
                {
                    "protocol": PROTOCOL,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "status": "FAILED",
                },
            )
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v4-core", type=Path, default=V4_ROOT / "tools/locked_same_bank_eval.py"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run-small", help="Allocated-node candidate only; 32 trials, no full run"
    )
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--scratch-parent", type=Path, required=True)
    run.add_argument("--expected-candidate-sha256", required=True)
    run.add_argument("--confirm", required=True)
    run.add_argument("--batch-size", type=int, choices=(1, 16), required=True)
    verify = commands.add_parser(
        "verify-small", help="Read-only, independent artifact verification"
    )
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "run-small":
        run_small(args)
    else:
        base = load_v4(args.v4_core)
        print(
            json.dumps(verify_receipt(base, args.output, args.receipt_sha256)),
            flush=True,
        )


if __name__ == "__main__":
    main()
