"""Build a non-executable plan bound to reviewed evidence; no model/torch import."""

import hashlib
import json
from pathlib import Path
import stat


def pinned_bytes(path, expected):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError(f"Not a regular file: {path.name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f"Pinned evidence differs: {path.name}")
    return data


def pinned_json(path, expected):
    return json.loads(pinned_bytes(path, expected))


def main():
    root = Path(__file__).resolve().parents[4]
    evidence = root / "docs" / "superpowers" / "evidence"
    archive = evidence / "job-685198-v18"
    freeze_sha = "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178"
    analysis_sha = "14167f622198ce84a1ad02074c77e967c4b55a680ada9e732277230a9fc36f6f"
    marker_sha = "8c2a4289962308d059b1fc5ed2fa8e4715fdac12086804fe076a8f5e734b0938"
    freeze = pinned_json(evidence / "v18-deployment-artifacts" / "input_freeze.json", freeze_sha)
    analysis = pinned_json(archive / "OFFLINE_ANALYSIS.json", analysis_sha)
    marker = pinned_json(archive / "TARGETED_TRACE_REQUIRED.json", marker_sha)
    for name, digest in analysis["frozen_source_sha256"].items():
        if name not in ("spatial_attn_architecture.py", "custom_modules.py", "full.yaml"):
            raise RuntimeError("Unexpected frozen source name")
        pinned_bytes(archive / "frozen-model-source" / name, digest)
    trials = freeze["trials"]
    if len(trials) != 32 or [x["ordinal"] for x in trials] != list(range(32)):
        raise RuntimeError("Frozen trial order differs")
    cells = {c["cell"]: c for c in analysis["cells"]}
    stages = [{"module": "model_dict.norm_coch_rep", "branch": "cue"},
              {"module": "model_dict.norm_coch_rep", "branch": "mixture"}]
    for index in range(7):
        stages.append({"module": f"model_dict.attn{index}", "branch": "mixture"})
        for kind in ("conv_block", "hann_pool"):
            for branch in ("cue", "mixture"):
                stages.append({"module": f"model_dict.{kind}_{index}", "branch": branch})
    stages.append({"module": "model_dict.attnfc", "branch": "mixture"})
    for name in ("fullyconnected", "relufc", "dropout", "classification"):
        stages.append({"module": name, "branch": "logits" if name == "classification" else "mixture"})
    targets = {}
    for cell in ("A2", "B2"):
        if marker["worst_trials"][cell]["trial_id"] != cells[cell]["native_logits_worst_trial_id"]:
            raise RuntimeError("Worst-logit selection differs from original marker")
        chosen = [("native_logits", cells[cell]["native_logits_worst_trial_id"]),
                  ("nll", cells[cell]["nll_worst_trial_id"])]
        targets[cell] = [{"metric": metric, "trial": next(t for t in trials if t["trial_id"] == trial)}
                         for metric, trial in chosen]
    print(json.dumps({"status": "BOUND_TRACE_PLAN_CANDIDATE_NOT_EXECUTABLE",
                      "evaluation_role": "REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST",
                      "parent_job_id": "685198", "freeze_sha256": freeze_sha,
                      "offline_analysis_sha256": analysis_sha, "marker_sha256": marker_sha,
                      "trials": trials, "targets": targets, "post_hook_stages": stages,
                      "frozen_source_sha256": analysis["frozen_source_sha256"],
                      "autocast_enabled": {"A2": True, "B2": False},
                      "numerical_policy": "preserve original TF32, compile, preprocessing and canary threshold",
                      "pass_batch_sizes": [16, 1], "preserve_all_32_trials_and_call_order": True,
                      "post_hook_stage_count": len(stages), "ready_for_gpu": False,
                      "not_implemented": ["flatten/pre-hook boundary", "within-block operator trace",
                                          "real loader/source/capability integration",
                                          "independent cold-process scientific baseline replay",
                                          "real-model memory and time bounds"]}, indent=2))


if __name__ == "__main__":
    main()
