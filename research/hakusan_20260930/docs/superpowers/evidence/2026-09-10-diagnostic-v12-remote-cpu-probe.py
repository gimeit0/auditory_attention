"""Pinned real formal40 CPU state/RNG/graph checks, never GPU attestation."""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "b5cf658961739a9f9b1ae3532554ce35f28dd43d927af43534dea70928c213a4"
MANIFEST_SHA = "afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b"


def replace_once(module, old, new):
    if module.REMOTE.count(old) != 1:
        raise SystemExit("STOP: base probe insertion differs")
    module.REMOTE = module.REMOTE.replace(old, new)


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v12_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v12"
    module.MANIFEST = module.MANIFEST.with_name("v12-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v12")
    replace_once(
        module,
        "            import torch",
        """            # Approved original-runner environment before numerical import.
            fixed = {"CUBLAS_WORKSPACE_CONFIG": ":4096:8", "OMP_NUM_THREADS": "8", "TOKENIZERS_PARALLELISM": "false"}
            require("torch" not in sys.modules, "numeric import occurred before fixed environment")
            os.environ.update(fixed)
            require({key: os.environ.get(key) for key in fixed} == fixed, "fixed launch environment differs")
            event("fixed_launch_environment", status="PASS", values=fixed)
            import torch""",
    )
    replace_once(
        module,
        '                require(not any(diag._direct_module_training_state(item[1]) for item in inventory), "non-eval module")',
        "                diag._require_registered_modules_eval(model)",
    )
    replace_once(
        module,
        '            with diag.frozen_scene_context(context["snapshot_files"], records):',
        '            with diag.frozen_scene_context(context["snapshot_files"], records) as scene_api:',
    )
    anchor = '                stage = "materialize_model_callable_graphs"'
    before_graphs = """
                registry_types = {}
                for _, child, _, _ in inventory:
                    for registry_name in ("_parameters", "_buffers", "_modules"):
                        value = vars(child)[registry_name]
                        label = type(value).__module__ + "." + type(value).__qualname__
                        registry_types[label] = registry_types.get(label, 0) + 1
                event("actual_formal40_registry_types", counts=registry_types)
                trace = diag._get_trace()
                rng_before = trace.snapshot_rng_state()
                stage = "snapshot_frozen_formal40_state"
                entries = diag._snapshot_model_entries(model)
                required = {id(value) for value in model.parameters()} | {id(value) for value in model.buffers()}
                require(required <= {entry["identity"] for entry in entries}, "registered state coverage missing")
                event(stage, status="PASS", entries=len(entries), registered_unique_tensors=len(required))
                stage = "materialize_scene_callable_graphs"
                scene_values = {name: getattr(scene_api, name) for name in ("waveform_cache_class", "raw_scene_batch", "correct_cue_batch")}
                scene_graphs = diag._callable_graphs(scene_values, materialize_module_attributes=True)
                event(stage, status="PASS", callable_count=len(scene_values))
""".rstrip()
    replace_once(module, anchor, before_graphs + "\n" + anchor)
    replace_once(
        module,
        "                fingerprint = diag._model_execution_fingerprint(model)",
        """
                budget = diag._SealBudget()
                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)
                try:
                    fingerprint = diag._materialized_model_execution_fingerprint(model, inventory)
                finally:
                    event("fingerprint_budget", work=budget.work, unique_callable_nodes=len(budget.nodes), cached_code_objects=len(budget.instructions), cached_literal_defaults=len(budget.literal_defaults))
                    diag._ACTIVE_SEAL_BUDGET.reset(budget_token)
""".rstrip(),
    )
    anchor = '            stage = "post_source_check"'
    after_graphs = """
                stage = "repeat_state_rng_and_scene"
                after_entries = diag._snapshot_model_entries(model)
                require(entries == after_entries, "unchanged model state snapshot differs")
                transition = diag._model_transition({"before": entries, "after": after_entries})
                rng_after = trace.snapshot_rng_state()
                require(rng_before == rng_after, "CPU preparation changed RNG after initial load")
                diag._rng_transition({"before": rng_before, "after": rng_after})
                require(scene_graphs == diag._callable_graphs(scene_values, materialize_module_attributes=False), "unchanged scene graph differs")
                diag._validate_model_module_inventory(model, inventory)
                diag._require_registered_modules_eval(model)
                diag._require_frozen_direct_parameters(inventory)
                diag._read_frozen_numeric_runtime(torch)
                require(transition["state_unchanged"] is True, "state comparator rejected unchanged snapshot")
                event(stage, status="PASS", entries=len(entries), state_unchanged=True, rng_unchanged=True)
""".rstrip()
    # This must execute before leaving the frozen scene context.
    replace_once(module, anchor, after_graphs + "\n" + anchor)
    cause_anchor = "        traceback.print_exc(limit=8)"
    cause_step = """
        if "diag" in locals():
            event("exception_chain", diagnostic=diag._bounded_exception_diagnostic(error))
""".rstrip()
    replace_once(module, cause_anchor, cause_step)
    module.REMOTE = module.REMOTE.replace(
        "FORMAL40_CPU_SEAL_PROBE_PASS", "FORMAL40_CPU_STATE_SEAL_PROBE_PASS"
    )
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
