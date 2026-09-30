"""Instantiate SHA-bound full architecture on CPU and test actual seal routines.

Random initialization only: no checkpoint, data, inference, GPU, SSH or submit.
Does not change the v9 candidate or production numerical settings.
"""

import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "same_bank_eval_2026_09_03_v4_numeric_diag_v9"
MANIFEST = (
    ROOT
    / ".superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v9-candidate-manifest.sha256"
)


def main():
    stage = "verify_local_candidate"
    with tempfile.TemporaryDirectory(prefix="v9-real-instance-") as temporary:
        # Per-process dependency caches only; never repurpose HOME.
        for key in (
            "MPLCONFIGDIR",
            "XDG_CACHE_HOME",
            "TORCHINDUCTOR_CACHE_DIR",
            "TRITON_CACHE_DIR",
        ):
            path = Path(temporary) / key.lower()
            path.mkdir(mode=0o700)
            os.environ[key] = str(path)
        try:
            manifest = MANIFEST.read_bytes()
            if (
                hashlib.sha256(manifest).hexdigest()
                != "a625c64179823d8e1b45b820d99ccf81f2fa463981cb4ed60e9cb65f49a446f7"
            ):
                raise ValueError("candidate manifest differs")
            for line in manifest.decode().splitlines():
                digest, name = line.split(maxsplit=1)
                if hashlib.sha256((PACKAGE / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("candidate file differs: " + name)
            spec = importlib.util.spec_from_file_location(
                "real_instance_fixtures", PACKAGE / "test_environment_mapping.py"
            )
            fixtures = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = fixtures
            spec.loader.exec_module(fixtures)
            import torch
            import yaml

            config_path = fixtures.PROJECT / "selftrain/configs/full.yaml"
            payload = config_path.read_bytes()
            if (
                hashlib.sha256(payload).hexdigest()
                != "3efe0f455d7c902c772f5d1a6fb30cf0a4f13e46f0b72024ff5bfa7b9f3229b4"
            ):
                raise ValueError("full config differs")
            config = yaml.safe_load(payload)
            print(
                json.dumps(
                    {
                        "scope": "REAL_ARCHITECTURE_RANDOM_CPU_NO_CHECKPOINT_NO_INFERENCE",
                        "torch": str(torch.__version__),
                        "python": sys.version.split()[0],
                        "config_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ),
                flush=True,
            )
            stage = "import_full_model_class"
            cls = fixtures.full_source_model_class()
            stage = "construct_full_model"
            model = cls(config=config)
            model.eval()
            for parameter in model.parameters():
                parameter.requires_grad_(False)
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "PASS",
                        "parameter_numel": sum(p.numel() for p in model.parameters()),
                        "state_keys": len(model.state_dict()),
                        "compiled_wrapper": hasattr(model.model, "_orig_mod"),
                    }
                ),
                flush=True,
            )
            stage = "materialize_model_callable_graphs"
            diag = fixtures.diag
            values = diag._model_callable_values(model)
            first_graphs = diag._callable_graphs(
                values, materialize_module_attributes=True
            )
            print(
                json.dumps(
                    {"stage": stage, "status": "PASS", "callable_count": len(values)}
                ),
                flush=True,
            )
            stage = "full_model_execution_fingerprint"
            inventory = diag._direct_model_module_inventory(model)
            for name, module, _, _ in inventory:
                namespace = diag._safe_instance_dict(module)
                if namespace is None or type(namespace.get("training")) is not bool:
                    module_type = type(module)
                    print(
                        json.dumps(
                            {
                                "stage": "training_state_inventory",
                                "module_path": name,
                                "module_type": module_type.__module__
                                + "."
                                + module_type.__qualname__,
                                "training_in_instance_dict": namespace is not None
                                and "training" in namespace,
                                "public_training_value": module.training,
                            }
                        ),
                        flush=True,
                    )
            first = diag._model_execution_fingerprint(model)
            print(
                json.dumps(
                    {"stage": stage, "status": "PASS", "module_records": len(first)}
                ),
                flush=True,
            )
            stage = "repeat_seal"
            if first != diag._model_execution_fingerprint(model):
                raise ValueError("unchanged model execution fingerprint differs")
            if first_graphs != diag._callable_graphs(
                values, materialize_module_attributes=False
            ):
                raise ValueError("unchanged model callable graph differs")
            print("REAL_INSTANCE_CPU_SEAL=PASS_NOT_GPU_OR_CHECKPOINT_PASS", flush=True)
            return 0
        except Exception as error:
            # No object repr, environment values or tensor payloads in evidence.
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "status": "PROBE_FAILED",
                        "error_type": type(error).__name__,
                        "message": str(error)[:1600],
                    }
                ),
                flush=True,
            )
            traceback.print_exc(limit=8)
            return 2
        finally:
            # Best effort for dependencies with exit hooks accessing temp caches.
            with contextlib.suppress(Exception):
                import matplotlib.pyplot as plt

                plt.close("all")


if __name__ == "__main__":
    raise SystemExit(main())
