# GPU v2 deployment and one-shot controller candidate

This add-only candidate targets
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v2`.
It does not modify, release, retry, cancel, or resubmit Job705468 or the old v1
package. No new GPU resource authorization is implied by building or testing it.

The 49-file job package SHA is
`8ddf8cc8ece27a14c49336b60fd1a45ffa295f57fb45778a66c559514d6d04f5`.
CONTROL_RELEASE.json covers those 49 files, their manifest, and these five
controller files (including this README): 55 files total. Scientific code,
numeric tolerances, B2 conditions, 32 trials and 16-to-1 order are unchanged.

## Changes from the pinned v1 controller

- Independent v2 root, source inventory, local evidence directory and explicit
  confirmation token. Neither the old submission intent nor its approval is reused.
- Runner requests one `nvidia_a100` in both total-job and per-node fields.
- The held-job check requires exact typed A100, CPU8, memory64GiB, time2h,
  unstarted/unallocated state, owner, nonce, runner, working directory and logs.
  Aggregate `gres/gpu=1` is allowed only alongside the typed A100, not instead.
- `sacct` must report exactly one matching PENDING/unallocated/zero-runtime job
  with the same requested resources before the exclusive release intent is written.
  Missing or delayed accounting fails closed; it is not retried automatically.
- Both query records are preserved and available from read-only status.

Submission still journals authorization and intent before a single `sbatch --hold`.
After a lost response, mismatched resources, or failed release, inspect the same
job and journals: do not rerun submit. No automatic update/release/requeue recovery
is included. GPU device identity is also checked by the existing compute child;
the scheduler checks alone are not proof that A100 inference has succeeded.

## Local validation only

Run on the Mac, from the workspace:

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_control_20260914/validate_local.py
```

Expected suite: 45 tests, zero skips; scheduler and SSH are fake. This includes
actual file-backed local transport, timeout handling, package roundtrip, exclusive
intent, source corruption, typed GPU mismatch, accounting mismatch/missing data,
old-authorization rejection and read-only status. A durable receipt includes
source, child PID, log and result hashes. No model is loaded and no job submitted.

Local package check (no network):

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_control_20260914/control.py check-only
```

## External gates still required

First restore an authenticated shared SSH connection and complete the native
Linux/torch2.1.1 startup CPU probe in `targeted_gpu_startup_probe_20260914`.
Local self-tests are not a replacement for that probe or an A100 run.
Then review preflight, deploy this independent root, and review a fresh successful
scheduler test-only receipt. Deployment and test-only do not authorize a job.
Actual submit additionally requires a new explicit one-job authorization for
1 A100 / 8 CPUs / 64 GiB / 2 hours and the reviewed matching test-only receipt.
Do not infer that authorization from a printed confirmation token.

The controller only uses the existing private SSH master, with fallback disabled.
It does not collect passwords, reconnect, or retry. The CPU probe, GPU cold pair,
scientific smoke, full three-model comparison and research report are separate
acceptance steps. Results remain a reused-validation-bank audit, not an
independent test result.
