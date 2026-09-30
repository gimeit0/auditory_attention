# Namespace scan performance candidate — local tests only

This directory is **not a release, deployment package, or GPU authorization**.
The fixed v19 runtime and integration manifests remain untouched.

`candidate.py` checks the SHA of the v19 core and derives an in-memory copy by
lowering exactly two `any(type(key) is not str for key in dict.keys(namespace))`
checks inside `_safe_instance_dict` into ordinary short-circuit loops. The
iterator, exact `type(...) is str` policy, exception and descriptor access are
unchanged. Every call reads the live dictionary again. There is no successful
mutable-state cache, skipped check, new import, or changed model/tolerance.
An AST gate rejects any difference outside that one function.

Both A/B variants use an explicit, unissued test module identity in cold
processes. Only the hermetic fixture points at that module. The pinned bridge
must reject it; it may not impersonate the production v19 load.

`study.py baseline` runs unchanged-core synthetic expected-contract generation
once unprofiled and once under cProfile. `study.py candidate` runs the candidate
regressions, then A/B/B/A unprofiled trials and separate A/B profiles. It compares
all compact output bytes and coarse/derived boundary records across A2/B2 and
batch sizes 16/1. The reference fixture itself asserts 34 model calls per cell.
Profile results contain function metadata/counts only, not environment values.
The selected test modules retain their original assertions but point explicitly
to the candidate; source-reading tests are not a production integration claim.

Limits: local only, one sequential subprocess at a time, OMP/MKL threads=1,
CUDA visibility empty, child <=180 seconds, total <=600 seconds, bounded logs,
no retries. cProfile timings include instrumentation overhead and must not be
used as unprofiled speedups. Comparisons are synthetic CPU-only on the local
Python/torch version; they do not prove HAKUSAN compatibility, A100 performance,
hook transparency, or formal40-versus-author model quality.

Evidence is written once into new timestamped folders under `evidence/` with
process records, source hashes and artifact inventories. Never rerun a study
merely to reinterpret a failed result as passed. A new measured attempt must be
separately recorded, including the reason for a test/harness correction.
