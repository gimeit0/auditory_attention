# GPU deployment / single-submission controller

This controller wraps the unchanged GPU job candidate SHA
`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`.
It is not an authorization or a completed GPU/scientific result. Prior source
manifests, original v18, freezes, models and old evidence remain unchanged.

## Actions

| Action | Remote effects |
|---|---|
| `check-only` | None: verify local hashes and show proposed resources |
| `preflight` | Read original pins, queue, partition and filesystem free space; no remote files/job |
| `deploy` | Create only the fixed new root, verify every byte in staging, publish package; no authorization/job |
| `test-only` | Run scheduler validation; save a uniquely named result; no job |
| `submit` | Requires explicit new resource confirmation and reviewed test receipt; one held job, resource check, then one release |
| `status` | Read journals and scheduler state; never submit, release, retry or cancel |

Use the fixed local entry, from the project directory:

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_control_20260913/control.py check-only
```

Replacing `check-only` with `preflight` performs only the read-only remote checks.
It requires an already-authenticated private SSH master. The controller never
requests a password or reconnects automatically: a failed/missing master stops
the operation. `ProxyCommand=/usr/bin/false` blocks a new TCP fallback if the
master disappears. Passwords belong only at the separate SSH terminal prompt,
never in scripts, arguments or chat. Local logs/request payloads are private.

Do not run `submit` yet. Its exact confirmation option is displayed by `--help`,
and `--test-receipt` must identify the local receipt from a successful matching
`test-only` operation. A displayed confirmation token is not approval; the
human must separately authorize the proposed new job and resources.

## Resource and interruption policy

Proposed: one GPU-1A job, one A100, 8 CPUs, 64 GiB, two hours total. Child 50-minute
and pair 110-minute caps stay as in the unchanged job candidate. No reuse of
Job685198's already-consumed authorization.

The local submit intent is written exclusively before the single SSH attempt.
Remote authorization and submit intent are exclusive/fsynced before one
`sbatch --hold`. The returned numeric job ID, held state, owner, comment,
runner/workdir, CPU/node/task/GPU/memory/time and no-requeue settings must match.
Sources and original pins are rechecked before one `scontrol release` for that
exact job ID. A mismatch leaves the job held, without cancellation or retry.
Unknown/missing scheduler fields fail closed; actual site output still needs
remote validation. A release-response timeout might mean the same job was
released; inspect its journals/status instead of submitting another job.

Slurm documents [`--test-only` as not submitting a job and `--hold` as creating
a held job](https://slurm.schedmd.com/sbatch.html); [`scontrol release`
releases an existing held job](https://slurm.schedmd.com/scontrol.html).
These upstream semantics are not evidence that HAKUSAN's current configuration
has accepted this particular request.

Interrupted uploads leave the partial new root intact. No overwrite, deletion,
automatic cleanup or retry. `status` can inspect partial publication. Different
test-only attempts have separate records; submission binds one exact receipt
SHA no older than 24 hours. Failed checks cannot authorize submission.

## Validation scope and remaining gates

34 local tests use a fake scheduler/SSH and private local directories. They
exercise a roundtrip of the actual pinned source bytes (not the real remote
filesystem), exclusive journals, partial uploads, bad resource fields,
stale/changed receipts, timeout/uncertain responses and read-only status.
Small real local subprocesses test transport stdin/timeout handling. No
production model, CUDA, GPU allocation or real SSH occurs in this test suite.

Run `validate_local.py` with the same local Python for a source-bound durable
test receipt; check that receipt before treating the current package as tested.
The previous candidate's 42+38 tests are prior evidence, not new controller cases.

No deployment, scheduler test, or submission is implied by local test success.
Read-only preflight reports filesystem availability, **not account quota or
compute-node scratch capacity**. Actual scheduler/spool/cache assumptions and
fresh resource authorization remain required. The compute candidate checks its
allocated environment and original local-mount policy at runtime. Full GPU
artifact download/reverification is a separate post-run gate, not performed by
`status`. Three-model smoke and final 10k/control comparison are not complete.
