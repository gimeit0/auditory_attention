# G2 production cell lifetime — unreleased integration candidate

This library connects the fixed input binding, HOME-preserving scratch binding,
original real-model preparation and two-pass bridge. It is not a runnable job,
release approval, archive implementation or proof of production execution.

## Contract

`ProductionCell(bridge, diag, job=..., freeze_sha=..., production_bytes=..., parent_path=...)`
is constructed in one cold isolated process, using the new profile root and
freeze. `run(consume)` is single-use, including after failure.

Execution order:

1. Recheck sources; acquire the original v4 lock exclusively without altering its bytes.
2. Enter new per-profile scratch before numeric imports, retaining real HOME.
3. Original production process claim and input reconstruction; native/runtime checks.
4. Preload R/C compiler dependencies before preparation; enter frozen scene scope.
5. Original strict-load once, profile adaptation, actual A100 check, original guarded 16→1 passes.
6. Revalidate inputs, save arrays through the caller's bounded `consume` writer while mmap/scene remain live.
7. Recheck pass commitments, summary, RNG/model/runtime, scratch spills, inputs, lock and sources.
8. Revoke model/compiler authorities and close scopes. No successful result is returned if cleanup fails.

The writer returns a bounded JSON receipt with status `G2_PASS_ARTIFACTS_WRITTEN`,
job/PID/profile/input SHA, two original pass commitments and archive manifest SHA.
This validates identity/coverage, **not the archive's content**. Independent
array verification must be implemented by the owning package; the candidate's
`independent_results_verified` and `production_ready` remain false.

The launcher still owns reviewed source release and budget authorization,
per-profile input freezing, Slurm checks, a cold bounded process supervisor,
approved scratch-parent selection, terminal evidence and independent verification.
It must set `CUBLAS_WORKSPACE_CONFIG=:4096:8` before CUDA and the private-cache
environment from `Binding.environment`, without assigning HOME. It must not hold
an incompatible exclusive v4 lock in a separate parent descriptor while this
child acquires its own lock. Partial files are retained for the supervisor.
No reference/observed production parity is claimed by this library.

## Tests and limits

19 tests: explicit control-flow doubles and actual local OS locks. They cover
ordering, provenance rejection, single-use operation, numeric-difference versus
execution-failure, changed output/summary/RNG, receipt identity, failed preparation
with partial authorities, body/cleanup errors, final source drift and lock release.
Fake capability/device/receipts are test-only; they do not pass a production loader.

Separate cold D/E local synthetic checks exercise the actual pinned bridge with
the actual private scratch/spill/mmap implementation, 32 samples and 34 forwards
each, four feature-file mappings, preserved commitments and JSON handoff. An E
second-pass failure leaves only first-pass spills, revokes authority and rejects
retry. These use the original explicit hermetic fixture and a **local mount stub**.
They do not run `ProductionCell.run` with a real checkpoint or validate Linux/A100.

Final evidence: [g2-lifetime-local-20260917T032221Z-2bz9y1zy](../../evidence/g2-lifetime-local-20260917T032221Z-2bz9y1zy/).
Four fresh child processes complete in 30.208s; each has a 45s limit and the local
run has a 120s limit. Sources/logs/snapshots are bound and read-only recheck passes.
The initial 31.904s run is retained; the final run additionally checks actual
summary serialization and original authority revocation.

Read-only recheck from the workspace:

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_lifetime_20260917/validate_local.py verify \
  docs/superpowers/evidence/g2-lifetime-local-20260917T032221Z-2bz9y1zy
```

No remote code/freeze/job is created by these checks. Existing models, v4/v19,
profile sources and Job721086 release are unchanged. Only test-owned temporary
files are automatically removed; durable evidence is retained.
