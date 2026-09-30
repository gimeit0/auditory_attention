# B2 GPU cold-pair job candidate — NOT submitted

Local implementation of the next compute-node package. This is not a released
GPU result, a new allocation authorization, or the final three-model comparison.
Original v18, model weights, freezes, prior source manifests and evidence are
unchanged. Scientific role remains
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`.

## What this candidate does

- Starts a new reference process, verifies its artifacts, then starts a separate
  observed process. B2 only, formal40, original 32 trials and 16→1 schedule.
- Uses original preparation/worker checks, original pass commitments and pinned
  parent-array matching. The previously tested CUDA adapter installs the actual
  42-stage candidate hooks; this runtime integration is not yet GPU-tested.
- Keeps real `HOME`. Ten cache variables and temporary files use private local
  directories. The candidate scratch class retains original spill/mmap methods;
  only the HOME/cache policy and its exact-type reference guard are adapted.
- Archives both complete passes, 80 arrays per pair, plus all 168 observed
  intermediate tensors and the 34-batch observation ledger. Original decoder,
  state/RNG continuity, actual child PID, environment, hashes and exact file
  coverage are required; process return code zero alone does not pass.
- Full-size input audit found that each feature array is **204,800,000 bytes**,
  larger than the old 128 MiB disk-file limit. `bounded_archive.py` derives a
  private copy with exactly this file bound. Original source unchanged; 1 MiB
  transfers and 2 GiB array-total cap per child unchanged. This is a disk-file
  sizing correction, not a changed numerical tolerance or intermediate tensor
  capture limit (still 128 MiB each / 2 GiB total).
- Deadlines, log caps, descendant-process termination, write-once start and
  terminal records. Failed and partial arrays/captures remain at the new remote
  artifact root; Python-handled observer failures also retain a partial ledger.
  SIGKILL/node loss may prevent a child terminal record; missing records fail
  verification. Temporary package/cache/mmap files are removed after supervisor
  exit; they are not the durable result archive.
- `submit_once` is a tested **journal helper**, not a scheduler CLI. Intent is
  fsynced before a single injected call. An uncertain response blocks retry.

## Local validation

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_job_20260913/validate_local.py
```

42 new tests: 24 process/control, 13 synthetic capture/inventory, 2 original
hermetic CPU scratch tests, 3 real-size synthetic file tests. The latter writes
and fully rehashes 204,800,000 synthetic bytes using at most 1 MiB transfer
chunks; this is not a total-RSS claim. Original reference lifetime has one toy
load, 34 forwards, four real mmap spill files and valid original commitments.
It does not test the Linux mount factory, production model, CUDA or Inductor.

The validator also reruns the prior 38 archive tests; these are regression tests,
not 38 additional newly designed cases. Its durable receipt is authoritative
for whether the current package actually passed. No network call or submission.

## Not yet authorized / not yet validated

Proposed one-job limits: GPU-1A, one A100, 8 CPUs, 64 GiB RAM, 2 hours total;
each child at most 50 minutes; pair plus verification at most 110 minutes.
These proposed limits require new user authorization and current scheduler
`--test-only` checks. Prior Job685198's authorization cannot be reused.

`run_gpu.sbatch` is syntax-checked candidate source, **not a command to run now**.
It requires a separately reviewed `AUTHORIZATION.json` and matching durable
`SUBMIT_INTENT.json` at the fixed new root; neither is created by this package.
No deployment controller or actual `sbatch` invocation is included yet. A
controller still must verify remote package publication, bind authorization,
perform the one scheduler call and archive/reconcile its receipt without retry.

Before submission: review this package and its limits, implement/review that
controller, validate scheduler/spool/environment assumptions read-only, then
obtain specific authorization. After a real run: retrieve and independently
rehash the full archive locally, verify the cold-pair endpoint gate and inspect
the intermediate differences. CPU tests cannot establish observation neutrality
under actual A100/Inductor. Three-model smoke and 10k/control evaluation remain
later scientific gates. Do not relax their tolerances to get PASS.
