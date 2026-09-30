# Synthetic two-pass bridge pair candidate

This package tests the pinned G2 CellBridge against the original guarded trace
path, in separate cold processes. It is not a checkpoint comparison.

Local mode runs D/E, each reference then observed: 32 synthetic records,
batch 16 then 1, AMP off, 34 model calls, one fixture strict load, fixture seed 0.
Eight coarse endpoints and four official outputs are preserved for both passes.
Reference/observed floating arrays must agree within the existing absolute 1e-6;
classes must match exactly. Bit equality is reported separately. Model state,
RNG, six runtime flags, full identities, source hashes and child PIDs are bound.
Returned RNG pickle bytes are hashed only, never deserialized.

The compiled child supports only native Python 3.11.5 / Torch 2.1.1+cu118 in a
single-CPU Slurm allocation. It preserves the original compiler lifecycle and
uses the pinned target-bound compiler/artifact observer for R/C. Its fixture
constructs the model before synthetic strict-load and issues original lifecycle
before sealing. This explicit test preinjection is NOT validation of production
checkpoint loading chronology. No real model, waveform corpus or GPU is loaded.
Native compilation has not been validated by local D/E success.

There is deliberately no SSH, sbatch, native coordinator, or retry entry point.
The old Job720730 single-job authorization is consumed. Proposed new native
budget (NOT authorized): 1 CPU, 6000 MiB, 22 min, 0 GPU, one job; R reference,
R observed, C reference, C observed, 300 seconds per cold child, coordinator
1260 seconds. A separately reviewed launcher/resource approval is still needed.

Local use from the repository root:

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_compiled_check_20260916/run_check.py local
```

Evidence uses a new unique directory and a portable source snapshot. Failures
and partial logs are retained, never relabelled as success. Cold cache temporary
directories created by this invocation alone are removed on exit. `verify`
rechecks recorded artifacts without running a model or contacting HAKUSAN.
Production-interference validation and readiness for GPU remain false.
