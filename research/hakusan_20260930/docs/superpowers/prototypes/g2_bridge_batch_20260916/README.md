# G2 guarded compiled bridge: single CPU batch controller

Approved by the user on 2026-09-16: one new job, 1 CPU, 6000 MiB, 22 minutes,
0 GPU, no automatic retry. Old Job720730 is preserved and is not resubmitted.

The 30-file bundle reuses the exact 21-file local bridge candidate release
`70ed80ca0d3a39d562bcf06a289d259eeb4a616d8a9a229122625ff3a17029dd`.
The old candidate's README records its earlier, then-unapproved status;
the current authorization is recorded separately in the execution ledger.
No original source, model or freeze is modified.

Four cold children: R-reference, R-observed, C-reference, C-observed. Each uses
the original guarded two passes (32 synthetic trials, batch16 then1, AMP off).
Reference has no profiler; observed uses the pinned CellBridge/backend recorder.
Each child stops after 300 seconds; coordinator deadline1260, Slurm1320 seconds.
HOME is preserved; explicit temporary cache directories are unique per child.
Any failure stops later stages. No production checkpoint or GPU is loaded.

Deployment is write-once to a new private root:
`/home/s2510040/audattn_external_eval_diag/g2_bridge_cpu_2026-09-16_v1`.
Scheduler `--test-only` precedes one held submission. Durable local and remote
intents prevent a second submission after an ambiguous response. Exact held
resources/identity are checked before release, and again on the compute node.
Status/collection do not submit. An existing authenticated SSH master is required;
this controller does not collect passwords or reconnect automatically.

The separate BATCH_RELEASE binds controller/resources; original RELEASE binds
the unchanged child package. Downloaded source is never executed by review.
Review checks fixed local code, submission provenance, scheduler accounting,
artifact inventories, independent endpoint comparison and native compiler records.
Synthetic success is never GPU/production-interference or checkpoint comparison success.

Current local evidence: `docs/superpowers/evidence/g2-bridge-batch-20260916/local-tjfvm5j0`.
27 protection tests passed; actual packaged local D-observed completed two passes,
34 calls, in9.977 seconds. The unit-test native labels are explicit test doubles,
not real native execution. No remote work had occurred when this README was written.

Entry: `docs/superpowers/evidence/2026-09-16-g2-bridge-cpu.sh`.
Default/preflight is read-only. Do not call `submit` again after an intent exists.
