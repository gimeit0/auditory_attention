"""Pure-stdlib, byte-exact verifier for synthetic B2 cold-process endpoints.

No imports of torch, networking, production data or mutation of input records.
Passing is NOT A100/Inductor or Job685198 replay validation.
"""
import base64
import hashlib
import math

COARSE = ("raw_scene", "raw_cue", "normalized_scene", "normalized_cue", "scene_features",
          "cue_features", "native_logits", "log_probabilities")
DERIVED = ("target_logit", "logsumexp", "target_log_probability", "nll", "p_target",
           "p_probe_distractor", "pred_label", "correct")
OFFICIAL = ("nll", "p_target", "p_probe_distractor", "pred_label")
WIDTHS = {"<f4": 4, "<f2": 2, "<f8": 8, "<i8": 8, "|b1": 1}
RUNTIME = {"deterministic_algorithms": True, "cudnn_deterministic": True,
           "cudnn_benchmark": False, "float32_matmul_precision": "high",
           "cuda_matmul_allow_tf32": True, "cudnn_allow_tf32": True}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def descriptor(raw, shape, dtype):
    return {"shape": shape, "dtype": dtype, "nbytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def array_bytes(record):
    require(type(record) is dict and record.get("dtype") in WIDTHS, "array type/dtype differs")
    shape = record.get("shape")
    require(type(shape) is list and shape and all(type(n) is int and n > 0 for n in shape), "array shape differs")
    size = math.prod(shape) * WIDTHS[record["dtype"]]
    require(size <= 256 * 1024 and record.get("nbytes") == size, "array byte budget/size differs")
    require(type(record.get("base64")) is str and len(record["base64"]) <= 350000, "array encoding exceeds budget")
    raw = base64.b64decode(record["base64"], validate=True)
    require(len(raw) == size and hashlib.sha256(raw).hexdigest() == record.get("sha256"), "array content digest differs")
    return raw


def verify_record(value, mode):
    require(type(value) is dict and value.get("status") == "HERMETIC_COMPILED_LIFETIME_PASS"
            and value.get("mode") == mode, "worker status/mode differs")
    require(type(value.get("pid")) is int and value["pid"] > 0, "invalid PID")
    require(value.get("python") == "3.11.5" and value.get("torch") == "2.1.1+cu118"
            and value.get("backend") == "eager" and value.get("cell") == "B2", "runtime/scope differs")
    require(value.get("load_calls") == 1 and value.get("forward_calls") == 34
            and value.get("complete_passes") == 2, "lifetime counts differ")
    require(value.get("stage_invocations") == (136 if mode == "observed" else 0), "stage count differs")
    for key in ("compiler_backend_entered", "original_guards_enabled", "original_compiler_authority",
                "hooks_removed", "attestation_revoked"):
        require(value.get(key) is True, "missing runtime/cleanup gate: " + key)
    for key in ("production_model_loaded", "cuda_initialized", "ready_for_gpu", "real_parent_replay_completed"):
        require(value.get(key) is False, "invalid scope claim: " + key)
    require(value.get("jobs_submitted") == 0 and value.get("runtime") == RUNTIME, "job/runtime differs")
    trials = value.get("trials")
    require(type(trials) is list and len(trials) == 32, "trial count differs")
    ids = [t["trial_id"] for t in trials]
    require(ids == list(range(100, 132)) and [t["ordinal"] for t in trials] == list(range(32)), "trial order differs")
    plan = value["relative_plan"]
    require(plan["trials"] == ids and plan["targets"] == [100, 128]
            and plan["batch_sizes"] == [16, 1], "observation plan differs")
    require(plan["stages"] == [{"module": a, "branch": b} for a, b in
                              (("stem", "cue"), ("stem", "scene"), ("mix", "scene"), ("head", "logits"))],
            "stage plan differs")
    require(len(value.get("passes", [])) == 2, "pass count differs")
    for index, result in enumerate(value["passes"]):
        size = (16, 1)[index]
        require(result["pass_id"] == "pass" + str(index + 1) and result["batch_size"] == size
                and result["trial_ids"] == ids and result["runtime"] == RUNTIME
                and result["autocast_enabled"] is False and result["state_rng_unchanged"] is True,
                "pass identity/runtime/state differs")
        require(set(result["boundaries"]) == set(COARSE + DERIVED), "boundary coverage differs")
        for name, record in result["boundaries"].items():
            raw = array_bytes(record)
            shape, dtype = record["shape"], record["dtype"]
            require(shape[0] == 32, "boundary trial axis differs")
            width = len(raw) // 32
            row_shape = shape[1:] or [1]
            rows = [{"trial_id": trial, **descriptor(raw[i * width:(i + 1) * width], row_shape, dtype)}
                    for i, trial in enumerate(ids)]
            require(record["rows"] == rows, "boundary row bytes/order differ")
            batches = [descriptor(raw[i * width:(i + size) * width], [size] + shape[1:], dtype)
                       for i in range(0, 32, size)] if name in COARSE else []
            require(record["batches"] == batches, "batch bytes/order differ")
        require(set(result["official_outputs"]) == set(OFFICIAL), "official output coverage differs")
        for record in result["official_outputs"].values():
            array_bytes(record)
            require(record["shape"] == [32], "official output shape differs")
    observations = value["observer_records"]
    if mode == "reference":
        require(not observations and not value["captures"], "reference has observation artifacts")
        return
    schedule = [("pass1", i // 16, ids[i:i + 16]) for i in range(0, 32, 16)]
    schedule += [("pass2", i, [trial]) for i, trial in enumerate(ids)]
    require(len(observations) == 34 and len(value["captures"]) == 16, "capture/lifetime coverage differs")
    refs = []
    for record, (pass_id, batch, group) in zip(observations, schedule):
        require(record["pass_id"] == pass_id and record["batch_index"] == batch
                and record["trials"] == group, "observed schedule differs")
        result = value["passes"][int(pass_id[-1]) - 1]
        require(record["logits"] == result["boundaries"]["native_logits"]["batches"][batch], "observer logits differ")
        require(record["inputs"] == [result["boundaries"][n]["batches"][batch]
                                      for n in ("cue_features", "scene_features")], "observer inputs differ")
        keys = [[pass_id, batch, stage, trial] for stage in range(4) for trial in group if trial in (100, 128)]
        require([r["key"] for r in record["captures"]] == keys, "capture event order differs")
        refs.extend(record["captures"])
    require(refs == [r["record"] for r in value["captures"]], "capture ledger differs")
    for index, entry in enumerate(value["captures"]):
        ref = entry["record"]
        require(ref["ordinal"] == index and ref["dtype"] == "torch.float32", "capture ordinal/dtype differs")
        data = {"shape": ref["shape"], "dtype": "<f4", "nbytes": ref["size"],
                "sha256": ref["sha256"], "base64": entry["base64"]}
        raw = array_bytes(data)
        p, batch, stage, trial = ref["key"]
        # The four synthetic Identity stages have a known, exact oracle.
        name = ("cue_features", "scene_features", "scene_features", "native_logits")[stage]
        bound = value["passes"][int(p[-1]) - 1]["boundaries"][name]
        expected = array_bytes(bound)
        width = len(expected) // 32
        row = ids.index(trial)
        require(ref["shape"] == bound["shape"][1:] and raw == expected[row * width:(row + 1) * width],
                "captured stage bytes differ from synthetic oracle")


def verify_pair(reference, observed):
    verify_record(reference, "reference")
    verify_record(observed, "observed")
    require(reference["pid"] != observed["pid"], "cold pair must use distinct processes")
    require(reference["trials"] == observed["trials"] and reference["relative_plan"] == observed["relative_plan"],
            "cold pair input identities differ")
    for one, two in zip(reference["passes"], observed["passes"]):
        for key in ("boundaries", "official_outputs", "runtime", "autocast_enabled", "trial_ids", "batch_size"):
            require(one[key] == two[key], "observation changed endpoints: " + key)
    return {"status": "SYNTHETIC_COMPILED_COLD_PAIR_PASS", "reference_pid": reference["pid"],
            "observed_pid": observed["pid"], "forwards_per_process": 34, "passes_per_process": 2,
            "boundaries_per_pass": 16, "observed_stage_invocations": 136, "capture_records": 16,
            "cell": "B2", "backend": "eager", "production_model_loaded": False,
            "ready_for_gpu": False, "jobs_submitted": 0, "real_parent_replay_completed": False}
