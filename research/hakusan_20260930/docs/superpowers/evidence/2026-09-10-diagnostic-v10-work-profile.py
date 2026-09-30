"""Observe existing budget charges without removing checks or changing limits."""

import hashlib
import importlib.util
from pathlib import Path


BASE = Path(__file__).with_name("2026-09-10-diagnostic-v10-remote-cpu-probe.py")
BASE_SHA = "2da1094f6c31634a2d0d641c11a059911b28de430df2869502f9ae733ae9d144"


def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: v10 probe differs")
    spec = importlib.util.spec_from_file_location("profile_probe_base", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Intercept only the launcher's preparation, before it calls the shared base.
    # The remote production files remain exactly the same SHA-bound bytes.
    original_factory = importlib.util.module_from_spec

    def factory(spec):
        result = original_factory(spec)
        if spec.name != "v10_probe_base":
            return result
        original_exec = spec.loader.exec_module

        def execute(target):
            original_exec(target)
            source = target.REMOTE
            anchor = "                budget = diag._SealBudget()"
            # v10 inserts this anchor later, so instrument at its existing callsite.
            insertion = '                stage = "model_execution_fingerprint"'
            extra = r"""
                charge_totals = {}
                original_visit = diag._SealBudget.visit
                def observed_visit(budget, *args, **kwargs):
                    frame = sys._getframe(1)
                    name = frame.f_code.co_name
                    if name == "bounded":
                        checked = frame.f_locals.get("function")
                        name = "entry:" + checked.__name__
                        arguments = frame.f_locals.get("args", ())
                        if checked.__name__ == "_container_execution_identity" and arguments and arguments[0] is None:
                            name += ":None"
                    elif name == "_seal_visit":
                        name = "visit:" + frame.f_back.f_code.co_name
                    charge_totals[name] = charge_totals.get(name, 0) + kwargs.get("cost", 1)
                    return original_visit(budget, *args, **kwargs)
                diag._SealBudget.visit = observed_visit
""".rstrip()
            if source.count(insertion) != 1 or anchor in source:
                raise SystemExit("STOP: profile injection stage differs")
            source = source.replace(insertion, insertion + "\n" + extra)
            source = source.replace(
                "    except Exception as error:\n        event(stage,",
                '    except Exception as error:\n        if "charge_totals" in locals():\n            event("work_profile", totals=charge_totals)\n        event(stage,',
            )
            target.REMOTE = source

        spec.loader.exec_module = execute
        return result

    try:
        importlib.util.module_from_spec = factory
        return module.main()
    finally:
        importlib.util.module_from_spec = original_factory


if __name__ == "__main__":
    raise SystemExit(main())
