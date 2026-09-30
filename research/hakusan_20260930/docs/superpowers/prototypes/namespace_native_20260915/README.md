# HAKUSAN namespace candidate CPU subset

This is a temporary test-only extension of the reviewed v19 CPU supervisor,
not a new deployed v19 release or GPU controller.

Scope: unchanged 15 namespace candidate tests plus 5 binding and 13 name
classification tests; then the same synthetic dictionary microbenchmark as the
local candidate study (8/256/3000 keys, 6 repeats × 2000 calls). All selected
test bodies and assertions are unchanged. The remaining 106 tests from the
local 139-test suite and the full expected-contract/scratch lifecycle are
explicitly **not** certified by this subset. Counts from different candidates
and overlapping subsets must not be added together.

`run_native.py` verifies the original 162-source runtime manifest and previous
candidate evidence first. It derives the existing temporary CPU supervisor with
exact substitutions for a single test group, response labels, and three extra
SHA-bound candidate files. The original manifest is unchanged: 163 parent
package members (162 + manifest) plus 3 test-only files = 166 temporary members.
The separate child script is also SHA-bound. No frozen or deployed code is edited.

The child uses an in-memory, explicitly unissued candidate core. Original loader
rejection remains one of the tests. Synthetic model setup occurs for rejection
tests, but no production model/snapshot or full trace is loaded/executed. CUDA
must remain uninitialized.

Limits remain: one login-node CPU affinity, child <=50 seconds, supervisor <=90
seconds, transport <=110 seconds, bounded source/log sizes. Account HOME stays
unchanged; caches and test source files live in a new private temporary directory
and are removed at completion. No scheduler command, freeze, permanent upload,
password capture, reconnection or automatic retry occurs. Existing authenticated
SSH master only. Local same-payload success is required before native execution.

Evidence:

- `namespace-local_harness-20260915T060552Z-qyhduscx`: 33 passed, 6.277 seconds.
- `namespace-native_cpu-20260915T060811Z-ulq1vgqg`: 33 passed, 39.054 seconds,
  Python 3.11.5 / torch 2.1.1+cu118, CPU affinity `[0]`, cleanup complete.
- Native scanner-only median speedups: 1.581 / 1.647 / 1.547. These are not
  end-to-end inference speedups and do not resolve the original timeout gate.

Both operations have already run once. To inspect them without another remote
execution, run the fixed read-only reviewer from the workspace root:

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-15-namespace-native-review.py
```

The 12 offline harness tests are in `test_native.py`. The previous immutable
runtime/candidate evidence checks remain prerequisites and are not replaced by
the subset PASS result.
