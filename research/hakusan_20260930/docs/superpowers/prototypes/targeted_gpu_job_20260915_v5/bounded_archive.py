"""Candidate disk-file bound derived from immutable real B2 array metadata.

The previous 128 MiB FILE cap cannot hold a 204,800,000-byte feature array.
Only that file bound changes in a private module copy. 1 MiB transfer chunks,
2 GiB total per child, all hash/type/finite checks and old files stay unchanged.
This does NOT increase the separate 128 MiB intermediate tensor-capture limit.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import types

import job_contract as contract

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "targeted_gpu_pair_20260915_scan/pass_archive.py"
SOURCE_SHA = "48fe6e50b54a1b5a2ab88057dcbc2be5bd073f00fae9c06eaf7273a61026dfbd"
PARENT_SHA = "95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34"


def build():
    raw = contract.pinned_read(SOURCE, SOURCE_SHA)
    parent = json.loads(contract.pinned_read(contract.WORKSPACE / contract.PARENT, PARENT_SHA))
    parts = list(parent["cells"]["B2"]["passes"].values())
    sizes = [b["aggregate"]["nbytes"] for p in parts for b in p["boundaries"].values()]
    largest = max(sizes)
    total = sum(sizes) + sum(p["boundaries"][n]["aggregate"]["nbytes"]
                             for p in parts for n in ("nll", "p_target", "p_probe_distractor", "pred_label"))
    contract.require(largest == 204800000 and 0 < total <= 2 * 1024**3, "frozen B2 archive budget differs")
    tree = ast.parse(raw)
    original = copy.deepcopy(tree)
    matches = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "MAX_ARRAY"]
    contract.require(len(matches) == 1 and ast.unparse(matches[0].value) == "128 * CHUNK", "old file budget assignment differs")
    prior = copy.deepcopy(matches[0].value)
    matches[0].value = ast.Constant(value=largest)
    compiled = compile(ast.fix_missing_locations(tree), str(HERE / "<real-size-pass-archive>"), "exec")
    matches[0].value = prior
    contract.require(ast.dump(tree) == ast.dump(original), "archive adaptation changed other logic")
    module = types.ModuleType("real_size_candidate_pass_archive")
    module.__file__ = str(__file__)
    exec(compiled, module.__dict__)
    contract.require(module.CHUNK == 1024**2 and module.MAX_TOTAL == 2 * 1024**3,
                     "transfer/total budgets changed")
    report = {"source_sha256": hashlib.sha256(raw).hexdigest(), "parent_sha256": PARENT_SHA,
              "file_cap_bytes": largest, "expected_array_bytes_per_child": total,
              "transfer_chunk_bytes": module.CHUNK, "total_cap_bytes_per_child": module.MAX_TOTAL,
              "only_file_cap_assignment_changed": True, "gpu_executed": False}
    return module, report


archive, BUDGET = build()
