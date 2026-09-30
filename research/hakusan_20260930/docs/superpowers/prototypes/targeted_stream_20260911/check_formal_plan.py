"""Read-only static shape/storage estimate. No torch/model imports or execution."""

import hashlib
import json
import math
from pathlib import Path
import stat

import yaml


def pinned(path, sha):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError("nonregular pinned input")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise RuntimeError(f"changed pinned input: {path.name}")
    return raw


def build_report():
    root = Path(__file__).resolve().parents[4]
    proto = root / "docs/superpowers/prototypes/targeted_trace_20260911"
    archive = root / "docs/superpowers/evidence/job-685198-v18"
    plan_sha = "727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8"
    config_sha = "3efe0f455d7c902c772f5d1a6fb30cf0a4f13e46f0b72024ff5bfa7b9f3229b4"
    plan = json.loads(pinned(proto / "FORMAL40_PLAN_CANDIDATE.json", plan_sha))
    config = yaml.safe_load(pinned(archive / "frozen-model-source/full.yaml", config_sha))
    sources = {
        archive / "frozen-model-source/spatial_attn_architecture.py":
            "84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed",
        archive / "frozen-model-source/custom_modules.py":
            "98f0d393ee7a1a5fe1a8a8bd1302b0d6b574a4ef846946e30cf176adf860adad",
        Path("/Users/gigi/projects/auditory_attention/src/spatial_attn_lightning.py"):
            "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9",
        Path("/Users/gigi/projects/auditory_attention/src/layers/conv2d_same.py"):
            "826e2882b489157c578af68241303526079a529cd6d1dc04c1961b5a7e9cab1f",
        Path("/Users/gigi/projects/auditory_attention/src/layers/padding.py"):
            "4fbca19c54a30696c4dc8b27314e58ca2cc3c451ab8a9192dadea4eb07302213",
    }
    for path, sha in sources.items():
        pinned(path, sha)
    model = config["model"]
    if not (config["compile_model"] is True and model["norm_first"] is True
            and model["padding"] == ["valid_time"] * 7 and model["stride"] == [[1, 1]] * 7
            and model["attn"] == [1] * 7 and model["v08"] is True
            and plan["pass_batch_sizes"] == [16, 1] and len(plan["trials"]) == 32):
        raise RuntimeError("unexpected frozen shape contract")
    stages, shape = [], [2, 40, 20000]

    def add(module, branch, size):
        stages.append({"module": module, "branch": branch, "per_trial_shape": list(size),
                       "float32_bytes": math.prod(size) * 4})

    for branch in ("cue", "mixture"):
        add("model_dict.norm_coch_rep", branch, shape)
    for i in range(7):
        add(f"model_dict.attn{i}", "mixture", shape)
        kh, kw = model["kernel"][i]
        # Frozen padding helper: height=(kh-1)//2, time=0, dilation=1.
        shape = [model["out_channels"][i], shape[1] + 2 * ((kh - 1) // 2) - kh + 1,
                 shape[2] - kw + 1]
        for branch in ("cue", "mixture"):
            add(f"model_dict.conv_block_{i}", branch, shape)
        stride, kernel, padding = (model[name][i] for name in
                                   ("pool_stride", "pool_size", "pool_padding"))
        shape = [shape[0], *((shape[j + 1] - kernel[j] + 2 * padding[j]) // stride[j] + 1
                             for j in range(2))]
        for branch in ("cue", "mixture"):
            add(f"model_dict.hann_pool_{i}", branch, shape)
    add("model_dict.attnfc", "mixture", shape)
    for name in ("fullyconnected", "relufc", "dropout", "classification"):
        add(name, "logits" if name == "classification" else "mixture",
            [model["num_classes"]["num_words"] if name == "classification" else model["fc_size"]])
    if [{"module": s["module"], "branch": s["branch"]} for s in stages] != plan["post_hook_stages"]:
        raise RuntimeError("static stage order differs from pinned plan")
    if any(min(s["per_trial_shape"]) <= 0 for s in stages):
        raise RuntimeError("invalid derived shape")
    for cell, ids in (("A2", [9000, 4126]), ("B2", [1428, 2698])):
        if [x["trial"]["trial_id"] for x in plan["targets"][cell]] != ids:
            raise RuntimeError("target binding changed")
    per_cell = sum(s["float32_bytes"] for s in stages) * 2 * 2
    largest = max(s["float32_bytes"] for s in stages)
    return {"status": "STATIC_CAPTURE_ESTIMATE_NOT_RUNTIME_VALIDATION",
            "plan_sha256": plan_sha, "config_sha256": config_sha,
            "source_basis": "frozen architecture and padding inspected; formula only",
            "source_sha256": {str(p): sha for p, sha in sources.items()},
            "outer_path_prefix_candidate": "model._orig_mod.",
            "post_hook_stages": stages, "stage_count": len(stages),
            "trials": 32, "pass_batch_sizes": [16, 1], "targets_per_cell": 2,
            "float32_capture_bytes_per_cell": per_cell,
            "float32_capture_MiB_per_cell": per_cell / 1024**2,
            "largest_float32_capture_bytes": largest,
            "fits_2GiB_per_cell_capture_store": per_cell <= 2 * 1024**3,
            "fits_128MiB_per_tensor_limit": largest <= 128 * 1024**2,
            "A2_dtype_assumption": "float32 at every stage is a storage bound, not observed AMP dtypes",
            "excluded": ["model/input/state copies", "allocator and compiler workspaces",
                         "logits and metadata", "filesystem overhead", "extra boundaries"],
            "actual_live_module_binding_verified": False, "ready_for_gpu": False}


if __name__ == "__main__":
    print(json.dumps(build_report(), indent=2))
