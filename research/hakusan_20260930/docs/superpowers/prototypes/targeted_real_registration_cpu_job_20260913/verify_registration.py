"""Independent stdlib admission-result verifier; not scientific inference."""
import json
import re

FIXED = {
    "status": "REAL_COMPILED_CALLBACK_REGISTRATION_CPU_PASS", "cell": "B2",
    "parent_job_id": "685198", "strict_load_calls": 1,
    "checkpoint_sha256": "2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff",
    "plan_sha256": "727dce6b20292d9eaf61807b80b79cf95080c182916b529d8684ef0598aa70e8",
    "freeze_sha256": "bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178",
    "compiled_adapter_sha256": "f0f820bebdcc35bd3892b5930abb144f9e942ea4800676040537c5891cebdcb2",
    "stages": 42, "unique_stage_modules": 27, "installed_hooks": 29,
    "callbacks": "unchanged_CompiledLease", "registered_state_entries": 60,
    "parent_state_bytes_equal": True, "state_rng_runtime_unchanged": True,
    "compiler_authority_issued": True, "compiler_backend_entered": False,
    "compiler_authority_revoked": True, "hooks_removed": True,
    "source_reexecuted_for_restoration": False, "production_model_loaded": True,
    "production_worker_issued": False, "production_preparation_validated": False,
    "forward_calls": 0, "captures": 0, "cuda_initialized": False,
    "ready_for_gpu": False, "jobs_submitted_by_probe": 0,
    "temporary_directory_removed": True, "python": "3.11.5", "torch": "2.1.1+cu118",
}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def verify_result(result, job, pid):
    require(type(result) is dict, "native result object required")
    require(type(job) is str and re.fullmatch(r"[1-9][0-9]*", job), "invalid job identity")
    require(type(pid) is int and pid > 0, "invalid process identity")
    require(result.get("job_id") == job and type(result.get("worker_pid")) is int
            and result["worker_pid"] == pid, "worker/job identity differs")
    for key, value in FIXED.items():
        require(type(result.get(key)) is type(value) and result[key] == value,
                "registration contract differs: " + key)
    restored = result.get("source_objects_restored")
    require(type(restored) is list and all(type(v) is str for v in restored)
            and len(restored) == len(set(restored)), "restoration record differs")
    report = result.get("strict_load_report")
    require(type(report) is dict, "strict load report absent")
    expected = {"key_count": 61, "missing_keys": [], "unexpected_keys": [],
                "shape_mismatches": {}, "dtype_mismatches": {},
                "loaded_trainable_numel": 62622520, "trainable_numel": 62622520,
                "native_preprocessing": "selftrain_singleton_per_example_leveling"}
    for key, value in expected.items():
        require(type(report.get(key)) is type(value) and report[key] == value,
                "strict load report differs: " + key)
    require(type(report.get("loaded_trainable_numel_ratio")) in (float, int)
            and report["loaded_trainable_numel_ratio"] == 1.0, "load ratio is not exact")
    require(report.get("prefix_rule") == "exact", "prefix rule differs")
    module = report.get("model_module")
    require(type(module) is dict and type(module.get("path")) is str
            and module["path"].endswith("/snapshot/files/src/spatial_attn_lightning.py")
            and module.get("sha256") == "6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9"
            and module.get("size") == 37409,
            "model module path differs")
    return dict(result)


def verify_output(raw, job, pid):
    lines = raw.decode().splitlines()
    def one(prefix):
        rows = [json.loads(s[len(prefix):]) for s in lines if s.startswith(prefix)]
        require(len(rows) == 1, "missing or duplicate " + prefix)
        return rows[0]
    entry = one("CPU_CHILD_START=")
    begin = one("REAL_REGISTRATION_BEGIN=")
    require(entry.get("pid") == pid and entry.get("mode") == "registration",
            "entry identity differs")
    require(begin.get("pid") == pid and begin.get("job_id") == job
            and begin.get("cell") == "B2", "begin identity differs")
    return verify_result(one("REAL_REGISTRATION_RESULT="), job, pid)
