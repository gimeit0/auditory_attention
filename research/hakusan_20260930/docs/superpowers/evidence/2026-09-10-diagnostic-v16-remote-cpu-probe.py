"""Pinned real formal40 CPU state/RNG/graph checks, never GPU attestation."""

import hashlib
import importlib.util
from pathlib import Path
import sys


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
BASE_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
DIAG_SHA = "e776d9917ecad3da529d311d536de89d90121d23bceb2cefe9fdadc7450609ec"
MANIFEST_SHA = "b8dd965e688ea8d2452a14cf831985e342969927e66363377eaaff1c6582bf15"


def replace_once(module, old, new):
    if module.REMOTE.count(old) != 1:
        raise SystemExit("STOP: base probe insertion differs")
    module.REMOTE = module.REMOTE.replace(old, new)


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: base probe differs")
    spec = importlib.util.spec_from_file_location("v16_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old_sha = module.SOURCES["diagnose_batch_invariance.py"]
    module.SOURCES["diagnose_batch_invariance.py"] = DIAG_SHA
    module.PACKAGE = module.ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v16"
    module.MANIFEST = module.MANIFEST.with_name("v16-candidate-manifest.sha256")
    module.MANIFEST_SHA = MANIFEST_SHA
    module.REMOTE = module.REMOTE.replace(old_sha, DIAG_SHA).replace("v9", "v16")
    replace_once(
        module,
        '            stage = "read_verified_frozen_context"',
        """            stage = "same_version_exception_metadata"
            from torch._dynamo.exc import BackendCompilerFailed
            inner = RuntimeError("ptxas SYNTHETIC_PRIVATE_ARGUMENT")
            wrapper = BackendCompilerFailed(lambda *args: None, inner)
            packet = diag._bounded_exception_diagnostic(wrapper)
            require([n["type"] for n in packet["chain"]] == ["BackendCompilerFailed", "RuntimeError"], "internal exception edge missing")
            require(packet["chain"][1]["relation"] == "inner_exception", "internal relation differs")
            require("PTXAS_MENTIONED" in packet["chain"][1]["reason_codes"], "fixed compiler label missing")
            require("SYNTHETIC_PRIVATE_ARGUMENT" not in json.dumps(packet), "raw argument leaked")
            first, second = object(), object()
            error = diag._frozen_module_binding_error({"src.toy": first}, {"src.toy": second})
            delta = diag._bounded_exception_diagnostic(error)["chain"][0]["binding_delta"]
            require(delta["replaced"] == {"count": 1, "names": ["src.toy"]}, "bounded binding delta differs")
            event(stage, status="PASS", synthetic_metadata_only=True)
            stage = 'read_verified_frozen_context'
""".rstrip(),
    )
    replace_once(
        module,
        "            import torch",
        """            # Approved original-runner environment before numerical import.
            fixed = {"CUBLAS_WORKSPACE_CONFIG": ":4096:8", "OMP_NUM_THREADS": "8", "TOKENIZERS_PARALLELISM": "false"}
            require("torch" not in sys.modules, "numeric import occurred before fixed environment")
            os.environ.update(fixed)
            require({key: os.environ.get(key) for key in fixed} == fixed, "fixed launch environment differs")
            event("fixed_launch_environment", status="PASS", values=fixed)
            os.environ["PATH"] = "/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            import shutil
            require(shutil.which("ldconfig") == "/usr/sbin/ldconfig", "fixed PATH did not resolve ldconfig")
            listing = subprocess.run(["ldconfig", "-p"], capture_output=True, check=True, timeout=15)
            event("compiler_path_resolution", status="PASS", ldconfig=shutil.which("ldconfig"), listing_bytes=len(listing.stdout), gpu_driver_verified=False)
            import torch""",
    )
    replace_once(
        module,
        "            stage = 'read_verified_frozen_context'",
        """            stage = "synthetic_cross_module_dynamo"
            toy_root = scratch / "synthetic"
            (toy_root / "src").mkdir(parents=True, mode=0o700)
            toy_sources = {
                "src/__init__.py": "",
                "src/audio_transforms.py": "def transform(x):\\n    return x.sin()\\n",
                "src/custom_modules.py": "from src.audio_transforms import transform\\ndef helper(x):\\n    return transform(x) + 1\\n",
                "src/toy.py": "import torch\\nfrom src.custom_modules import helper\\nclass Toy(torch.nn.Module):\\n    def forward(self, x):\\n        return helper(x)\\n",
            }
            toy_records = {}
            for name, source in toy_sources.items():
                data = source.encode()
                (toy_root / name).write_bytes(data)
                toy_records[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            finder = diag._SnapshotLoader(toy_root, toy_records, diag._get_trace())
            require(not any(key == "src" or key.startswith("src.") for key in sys.modules), "preexisting src in toy probe")
            sys.meta_path.insert(0, finder)
            token = diag._ACTIVE_SNAPSHOT_AUTHORITY.set(finder)
            try:
                toy_module = importlib.import_module("src.toy")
                toy = torch.compile(toy_module.Toy().eval(), backend=lambda graph, inputs: graph.forward)
                issued = {name: entries[0][0] for name, entries in finder.issued_modules.items()}
                for name in issued:
                    sys.modules.pop(name)
                restored = diag._restore_missing_snapshot_modules_before_seal(finder)
                require(set(restored) == set(issued), "toy restoration incomplete")
                finder.seal_runtime_bindings()
                values = torch.arange(8, dtype=torch.float32)
                require(torch.equal(toy(values), values.sin() + 1), "toy numerical output differs")
                finder.verify_runtime_bindings()
                require(all(sys.modules.get(name) is value for name, value in issued.items()), "toy module object changed")
                event(stage, status="PASS", restored=len(restored), backend="CPU_DYNAMO_GRAPH_FORWARD_ONLY", postseal_binding_delta=0, scientific_model_forward=False)
            finally:
                diag._ACTIVE_SNAPSHOT_AUTHORITY.reset(token)
                sys.meta_path.remove(finder)
                for name in tuple(sys.modules):
                    if name == "src" or name.startswith("src."):
                        sys.modules.pop(name)
                torch._dynamo.reset()
            stage = 'read_verified_frozen_context'""",
    )
    replace_once(
        module,
        "                diag._require_load_report(report)",
        """                authority = diag._ACTIVE_SNAPSHOT_AUTHORITY.get()
                existing = {name: value for name, value in sys.modules.items() if name.partition(".")[0] in authority.protected_tops}
                original_objects = {name: entries[0][0] for name, entries in authority.issued_modules.items() if name not in sys.modules and len(entries) == 1}
                restored = diag._restore_missing_snapshot_modules_before_seal(authority)
                expected_restored = {"src", "src.audio_attention_transforms", "src.audio_transforms", "src.custom_modules", "src.layers", "src.layers.conv2d_same", "src.layers.padding", "src.spatial_attn_architecture", "src.spatial_attn_lightning", "src.time_domain_cochleagram"}
                require(set(restored) == expected_restored, "actual restored set differs from reviewed inventory")
                require(all(sys.modules.get(name) is value for name, value in existing.items()), "existing scene binding was replaced")
                require(all(sys.modules.get(name) is original_objects[name] for name in restored), "restored object differs")
                event("restore_actual_formal40_modules", status="PASS", restored=list(restored), existing_bindings_unchanged=True, source_reexecuted=False)
                diag._require_load_report(report)""",
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
                stage = "issue_compiler_lifecycle"
                lifecycle = diag._issue_compiler_lifecycle(model, inventory)
                require(lifecycle is not None and len(lifecycle.contexts) == 1, "actual compiled context count differs")
                require(not lifecycle.entered, "actual CPU preparation must not enter compiler")
                event(stage, status="PASS", compiled_contexts=len(lifecycle.contexts), source_shas=dict(diag._COMPILER_SOURCE_SHAS), forward_executed=False)
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
        '                stage = "repeat_seal"',
        """                authority.seal_runtime_bindings()
                authority.verify_runtime_bindings()
                event("actual_snapshot_import_seal", status="PASS", bindings=len(authority.sealed_bindings))
                stage = 'repeat_seal'""",
    )
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
                authority.verify_runtime_bindings()
                lifecycle.verify()
                require(not lifecycle.entered, "CPU preparation unexpectedly compiled a forward")
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
    # Never execute the synthetic compiled toy before the real-model seal probe:
    # Dynamo's process-global caches are themselves part of execution state.
    start = module.REMOTE.index('            stage = "synthetic_cross_module_dynamo"')
    end = module.REMOTE.index("            stage = 'read_verified_frozen_context'")
    if "--synthetic-only" in sys.argv:
        sys.argv.remove("--synthetic-only")
        finish = module.REMOTE.index('        event("complete",')
        module.REMOTE = module.REMOTE[:end] + module.REMOTE[finish:]
        module.REMOTE = module.REMOTE.replace(
            "FORMAL40_CPU_STATE_SEAL_PROBE_PASS", "SYNTHETIC_IMPORT_CPU_PROBE_PASS"
        )
    else:
        module.REMOTE = module.REMOTE[:start] + module.REMOTE[end:]
    if "--profile-budget" in sys.argv:
        sys.argv.remove("--profile-budget")
        replace_once(
            module,
            "                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)",
            """                profile = {"validation_calls": 0, "validation_work": 0, "depth": 0, "start": 0, "anchor_calls": 0, "container_calls": 0}
                def count_seal_work(frame, kind, argument):
                    if frame.f_code.co_filename != str(scratch / "diagnose_batch_invariance.py"):
                        return
                    name = frame.f_code.co_name
                    if kind == "call" and name == "_callable_anchor":
                        profile["anchor_calls"] += 1
                    if kind == "call" and name == "_container_execution_identity":
                        profile["container_calls"] += 1
                    if name == "verify_runtime_bindings":
                        if kind == "call":
                            profile["validation_calls"] += 1
                            if profile["depth"] == 0:
                                profile["start"] = budget.work
                            profile["depth"] += 1
                        elif kind == "return":
                            profile["depth"] -= 1
                            if profile["depth"] == 0:
                                profile["validation_work"] += budget.work - profile["start"]
                require(sys.getprofile() is None, "existing profiler must not be replaced")
                sys.setprofile(count_seal_work)
                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)""",
        )
        replace_once(
            module,
            '                    event("fingerprint_budget",',
            '                    sys.setprofile(None)\n                    event("budget_profile", **profile)\n                    event("fingerprint_budget",',
        )
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
