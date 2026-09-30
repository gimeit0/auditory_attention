"""Locate a real CPU seal-budget rejection without increasing any limit.

Reuses the verified temporary probe. Adds only external budget/frame reporting;
the candidate sources, models, scientific settings and 200,000-work cap remain
unchanged. No worker attestation, forward, deployment or job submission.
"""

import hashlib
import importlib.util
from pathlib import Path


PATH = Path(__file__).with_name("2026-09-10-diagnostic-v9-remote-cpu-probe.py")
EXPECTED_SHA = "c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec"
ORIGINAL = "                fingerprint = diag._model_execution_fingerprint(model)"
REPLACEMENT = r"""
                budget = diag._SealBudget()
                budget_token = diag._ACTIVE_SEAL_BUDGET.set(budget)
                try:
                    fingerprint = diag._model_execution_fingerprint(model)
                except Exception as failure:
                    frames = []
                    tb = failure.__traceback__
                    while tb is not None:
                        frame = tb.tb_frame
                        name = frame.f_code.co_name
                        if name in ("_model_execution_fingerprint", "_callable_graph_fingerprint_impl", "_referenced_attribute_values"):
                            record = {"routine": name, "line": tb.tb_lineno}
                            if name == "_model_execution_fingerprint":
                                module_path = frame.f_locals.get("name")
                                if type(module_path) is str:
                                    record["module_path"] = module_path[:300]
                            code = frame.f_locals.get("code")
                            if type(code) is type(main.__code__):
                                record["inspected_code_name"] = code.co_name
                                record["inspected_code_file"] = code.co_filename
                            frames.append(record)
                        tb = tb.tb_next
                    event("seal_budget_failure", work=budget.work, unique_callable_nodes=len(budget.nodes), frames=frames)
                    raise
                finally:
                    diag._ACTIVE_SEAL_BUDGET.reset(budget_token)
""".rstrip()


def main():
    if hashlib.sha256(PATH.read_bytes()).hexdigest() != EXPECTED_SHA:
        raise SystemExit("STOP: original CPU probe differs")
    spec = importlib.util.spec_from_file_location("cpu_probe_launcher", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.REMOTE.count(ORIGINAL) != 1:
        raise SystemExit("STOP: instrumented callsite is not unique")
    module.REMOTE = module.REMOTE.replace(ORIGINAL, REPLACEMENT)
    compile(module.REMOTE, "remote_budget_probe", "exec")
    return module.main()


if __name__ == "__main__":
    raise SystemExit(main())
