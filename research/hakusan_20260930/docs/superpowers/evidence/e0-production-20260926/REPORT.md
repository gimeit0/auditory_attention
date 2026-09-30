# E0 真实模型小批验收：Job 746603 执行台账与验收结果

2026-09-27 建档（作业运行、收集与首次本地复核发生于 2026-09-26；此前只有 [REMOTE_PROGRESS.md](../../../../alpha_mechanism_local_20260923/release_20260925_v2/REMOTE_PROGRESS.md) 的流水记录，没有 evidence 下的正式台账）。对应[近期执行计划](../../../../2026-09-23_主课题_近期执行计划.md) §3 第 2 周 2.1（E0 真实模型验收）与 2.3（typed GRES 改写处理）；[主课题总计划](../../../../2026-09-20_选择性听取发达机制_主课题总计划.md) §5 “E0 验收”。验收规则为 [05 号文](../../../../alpha_mechanism_local_20260923/05_E0_REAL_MODEL_ACCEPTANCE_PLAN.md) §5 的 G0–G7 门（任务口径“G1–G5”对应该表）。

状态：**E0_ENDPOINT_PASS**（远端 `E0_COMPLETE.json` 记录；本台账离线复核 `E0_ARTIFACTS_VERIFIED`）。研究身份：`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，即复用 Job 728520 的验证 bank 做审计，不是独立测试集。`scientific_alpha_result=false` 的含义：该记录只说明工程验收（历史桥接、α 端点、负对照公式、冷重复、观测无干扰、归档）通过；它不是 α 机制的科学结果，不解读中间 α 或负对照的数值方向，也不能把 96 条工程覆盖集的表现报告为 bank 结果。本报告不写“机制成立”。

## 1. 执行台账

| 日期 | 动作 | 证据路径 | 关键值 |
| --- | --- | --- | --- |
| 2026-09-24 | v1 候选包冻结；远端提交前快照检查停止 | [13 号文](../../../../alpha_mechanism_local_20260923/13_PRODUCTION_PACKAGE_READY_20260924.md)、[14 号文](../../../../alpha_mechanism_local_20260923/14_SOURCE_ONLY_IMPORT_FIX_20260925.md) | v1 release SHA `05a1271f…`；远端因 SNAPSHOT_BYTECODE 停止，未提交 |
| 2026-09-25 | v2 本地冻结（源码导入隔离修正） | [BUILD_RECEIPT.json](../../../../alpha_mechanism_local_20260923/release_20260925_v2/BUILD_RECEIPT.json)（SHA `3d0c0150…`）、14 号文 | release SHA `abcaa1af63d019e5e4d8701a8522e47f1e280cc8d477f21b2e64225485fd2f17`；reference SHA `448b9dc4ed4a125cc557ce5b5e3fade210f0f8554aeb73af141411f40edbeee9`；状态 SOURCE_ONLY_IMPORT_LOCAL_TESTED_NOT_DEPLOYED；local_tests_passed=114；checkpoint_loaded=false；jobs_submitted=0 |
| 2026-09-25 | 远端独立目录发布与全包核验 | REMOTE_PROGRESS.md 9/25 段 | 目录 `/home/s2510040/audattn_e0/e0_20260925_v2`；PACKAGE_BYTES_PASS；`E0_V2_PACKAGE_PUBLISHED=PASS`；bootstrap（e0_entry.py）SHA `bfe2afcb4c96d7ebb16d8017ed7c62a9a3701807edfffb4cc99a83499fcee2e2`，与 RELEASE.json `files["e0_entry.py"]` 一致；v1 与旧缓存未改动 |
| 2026-09-25 | 原生 source-check（登录节点只读导入） | REMOTE_PROGRESS.md 原始回执 | exit_code=0；`NATIVE_SOURCE_ONLY_IMPORT_PASS`；manifest_sha256 `8febb19f…`；files=96；existing_bytecode_files=24；checkpoint_loaded=false；cuda_initialized=false；jobs_submitted=0 |
| 2026-09-26 | 提交前队列检查 | `state/QUEUE.json` | returncode=0，stdout 为空（用户队列无相关作业） |
| 2026-09-26 | `sbatch --test-only` | `state/TEST_ONLY.json` | returncode=0；stderr `sbatch: Job 746602 to start at 2026-09-30T03:15:46 a using 8 processors on nodes spcc-a100g03 in partition GPU-1A`（调度器预估与占位号，非实际作业；实际 02:32 开跑） |
| 2026-09-26 | 提交意图 | `state/INTENT.json` | `/usr/bin/sbatch --hold --parsable --export=NONE --no-requeue --partition=GPU-1A --account=student --nodes=1 --ntasks=1 --cpus-per-task=8 --threads-per-core=1 --mem=65536M --time=00:30:00 --gres=gpu:nvidia_a100:1 --job-name=audattn_alpha_e0 …`；budget_gpu_hours=0.5；release SHA 同上 |
| 2026-09-26 | 单次 held 提交 | `state/SUBMISSION_RESPONSE.json`、`state/SUBMISSION.json`；REMOTE_PROGRESS.md “单次 held 提交与资源核查”段 | returncode=0，stdout `746603`；**Job 746603**，SUBMITTED_HELD_NOT_RELEASED，automatic_release=false，automatic_retry=false；SubmitTime=2026-09-26T02:27:46；PENDING / JobHeldUser，Priority=0，RunTime=00:00:00 |
| 2026-09-26 | held 资源核查，发现站点改写 | REMOTE_PROGRESS.md 同段 | 请求 `--gres=gpu:nvidia_a100:1`，实际 ReqTRES=`cpu=8,mem=64G,node=1,billing=8,gres/gpu:h100-20c=1`，TresPerNode=`gres/gpu:1`；**停止释放**；远端包 runner SHA `88832a18df2a6f0da103ef9f44e4c7b40da14c5c9e0d2f11366d1c2fa042368d`（与 RELEASE.json `files["run_e0.sbatch"]` 一致）；该阶段未对 spool 字节独立哈希 |
| 2026-09-26 | 用户单独授权的同作业唯一一次修正 | REMOTE_PROGRESS.md “同作业唯一一次 GRES 修正”段 | `scontrol update JobId=746603 Gres=gpu:nvidia_a100:1`，exit_code=0；修正后 ReqTRES=`cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1`，TresPerNode=`gres/gpu:nvidia_a100:1`；squeue `746603|PENDING|JobHeldUser|gres/gpu:nvidia_a100:1`；CPU=8、mem=64G、TimeLimit=00:30:00、Partition、Account、Requeue=0 未变；Slurm spool 脚本 SHA 与冻结包 runner 一致，均为 `88832a18df2a6f0da103ef9f44e4c7b40da14c5c9e0d2f11366d1c2fa042368d` |
| 2026-09-26 | 用户授权放行 | REMOTE_PROGRESS.md “用户授权释放及首次运行状态”段 | `scontrol release 746603`，exit_code=0；EligibleTime=2026-09-26T02:31:55；StartTime=2026-09-26T02:32:01；首查 RUNNING，RunTime=00:00:12，NodeList=spcc-a100g04；AllocTRES=`cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1` |
| 2026-09-26 | sacct 终态 | REMOTE_PROGRESS.md “完成与本地离线复核”段（收集的 state 内无 sacct 原始回读文件，见 §4） | 746603 COMPLETED，ExitCode=0:0，Elapsed=00:11:16，节点 spcc-a100g04；Start=2026-09-26T02:32:01，End=2026-09-26T02:43:17（据 REMOTE_PROGRESS.md 转写，非 sacct 原始输出） |
| 2026-09-26 | 只读收集 | `collect-746603-SlcKgK/state/`（42 个文件）；`state/slurm-746603.log` | `attempt/E0_COMPLETE.json`：E0_ENDPOINT_PASS，scientific_alpha_result=false，pair_record SHA `ba621556a0e8d76d11e3aa7a152730d83a4e0ea86f41f1482e4ebe629d307c32`（1623 字节，本地重算一致）；slurm 日志仅 1 行 `E0_SCRATCH=/tmp/audattn_e0_Qv0C2Sp0` |
| 2026-09-26 | 作业内两进程与验收 | `attempt/PAIR_EXECUTION.json` | A PID 1039926、B PID 1040834，returncode 均 0；verification.status=E0_ARTIFACTS_VERIFIED，predictions=6048，reference_job_id=728520，scope=E0_FORMAL40_NATIVE_20260925_V2 |
| 2026-09-26 | 本地首次离线复核 | REMOTE_PROGRESS.md 同段 | `verify_package` 与 `production_e0.verify` exit_code=0，E0_ARTIFACTS_VERIFIED |
| 2026-09-27 | 本台账独立离线复核 | [offline-verify-20260927/](offline-verify-20260927/)：`offline_verify_746603.py`、`verify_stdout.json`（SHA `19fa6c1d…`）、`RUN.txt` | exit_code=0；`e0_entry.verify_package(package, release_sha)` 通过（清单 24 个文件、scope 与预算合同）；`production_e0.verify(root=state/attempt, records=PAIR_EXECUTION.workers, package, release=RELEASE.json, job_id='746603')` 返回 **E0_ARTIFACTS_VERIFIED**，返回字典与 `E0_COMPLETE.verification`、`PAIR_EXECUTION.verification` 三者完全相同；环境 `/opt/anaconda3/envs/audattn/bin/python -I -B`，Python 3.11.15 / NumPy 2.4.6 / torch 2.12.1（macOS arm64）；不加载 checkpoint、不推理、无网络 |
| 2026-09-27 | 证据清单 | [SHA256SUMS.txt](SHA256SUMS.txt) | **45 个文件**（state 42 个 + `package/RELEASE.json` + `BUILD_RECEIPT.json` + `REMOTE_PROGRESS.md`），`shasum -a 256 -c` 全部 OK（在项目根目录 `/Users/gigi/发表/超算` 执行）；不含 readout/ 子目录。本证据目录自身 8 个文件（REPORT.md、SHA256SUMS.txt、offline-verify-20260927/ 4 个、readout/ 2 个）不在清单内，其 SHA 见 [alpha README](../../../../alpha_mechanism_local_20260923/README.md) 2026-09-27 新增文件表 |

本批 1 次 sbatch、1 次 scontrol update、1 次 scontrol release，无重试、无替代作业。A、B stderr 各仅 1 条 torchaudio `kaiser_window` 弃用 UserWarning，无 traceback；stdout 各 1 行 `Using explicit dim specification for demeaning in audio transforms`。

## 2. 硬验收（05 号文 §5 G0–G7；离线复核由冻结包自身的 `production_e0.verify` 执行）

| 门 | 要求 | 结果 / 证据 |
| --- | --- | --- |
| G0 输入 / 加载 / 布局 | SHA、trial 顺序、分支计数、strict-load 覆盖 1.0、无漏权重 / 新参数 | 通过。包 24 个清单文件 SHA / 大小逐项通过；`E0_LAYOUT_96.json` SHA `f28160c857512c90533837d7a4f54a761a6deef6d6cf86aafadecd34138f7e90` 与 `reference/REFERENCE.json.layout_sha256` 一致，protocol `e0_formal40_layout_20260923_v1`，96 个 trial_ids、6 批 × 16、expected_predictions=6048；checkpoint SHA `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` 在布局、REFERENCE.json、A / B PROVENANCE.json 一致；REFERENCE.json 绑定 728520 原归档四文件（results.csv `c705f29e…`、logits.npz `54059d74…`、bank.csv `4d069a7d…`、RUN.json `e7a67259…`），reference.npz SHA `353edb36…`（REFERENCE_BINDING、REFERENCE_DATA_SHA）；load_report（A、B 相同）：loaded_trainable_numel_ratio=1.0（62,622,520 / 62,622,520），missing_keys=0，unexpected_keys=0，dtype / shape mismatch 为空，key_count=61，known_wrapper_removed=true，state_bindings_preserved=60，model_module `spatial_attn_lightning.py` SHA `6531a654…`，native_preprocessing `selftrain_singleton_per_example_leveling`，prefix_rule `exact`（LOAD_REPORT_COVERAGE、PROVENANCE_BINDING）。注：布局文件内 `scope` 字段为生成时的字符串 `LOCAL_CANDIDATE_NOT_AUTHORIZED`，已被 SHA 冻结，不表示当前状态 |
| G1 历史桥接 | A / B 的 original 与 728520 相同 trial / 条件 logits 逐位一致；alpha_1 与 original 逐位一致 | 通过。A、B 的 original、alpha_1 均 `HISTORICAL_ENDPOINT_BITS_PASS`（PROVENANCE.bridge）；离线用 `bridging_sink` 对 `00_original.npz`、`01_alpha_1.npz` 重新逐位比对 reference.npz 的 logits 与 FP32 NLL（BRIDGE_BITS、HISTORICAL_NLL_BITS），与 bridge 记录一致（BRIDGE_REPORT）；A / B 的 00、01 四个 npz 的 SHA 与 reference.npz 完全相同（`353edb36…`）；original 与 alpha_1 逐位一致（PAIR_ENDPOINT_BITS） |
| G2 α=0 端点 | alpha_0 与独立 bypass 逐位一致；前 4 个完整 control 批内相同 scene 换 cue 输出逐位一致 | 通过。explicit_bypass 与 alpha_0 逐位一致（PAIR_ENDPOINT_BITS；A、B 的 02、03 npz SHA 均 `c9f47674…`）；alpha_0 中 64 条 control trial 的 correct logits 字节与 shuffled / silent / distractor 三条件完全相同（OFFLINE_CUE_INDEPENDENCE，A、B 各自） |
| G3 冷重复 | A / B 全部 10 轮 logits 逐位一致；不同 PID 与重新加载证据 | 通过。10 轮 × 4 条件 logits 与 NLL 字节一致（PAIR_REPEAT_BITS）；PID 1039926 / 1040834（DISTINCT_WORKER_PIDS）；两份独立 load_report；returncode 均 0 |
| G4 状态与有效性 | FP32 logits `[n,800]` 有限；参数 / RNG / hook 不变 | 通过（离线可核部分）。21 轮 × 4 条件全部 float32、形状 `[n,800]`、有限（LOGITS_SHAPE_DTYPE、NONFINITE_LOGITS）；NLL 由 logits 以 FP64 logsumexp 复算，atol=2e-5、rtol=2e-6 通过（NLL_RECOMPUTE）。参数 / buffer / RNG / hook 不变属作业内 `audited_session` postcheck，收集的 state 只以 `postchecks_completed=true` 与 worker 零退出码记录（失败会写 WORKER_FAILED.json 且不发布 WORKER.json），没有单独数值字段，离线不能重演 |
| G5 三负对照公式 | 固定特征上独立参考计算 gain，atol=rtol=2e-6 | 通过。A 11 份、B 10 份，共 **21 份报告 × 32 项 = 672 项** `G5_FIXED_FEATURE_PASS`；atol=rtol=2e-6，参考 `numpy_float64_independent`；全部检查最大 max_abs 2.5905499567713264e-07，最大 mean_max_abs 1.0589969012819722e-07（均低于 2e-6）。离线仅核对报告数、项数、状态与容差字段（G5_REPORT_COUNT、G5_REPORT），未重跑 GPU 公式检查 |
| G6 观测无干扰 | alpha_05_observed 与同进程 alpha_05 逐位一致；8 处事件完整 | 通过。A 的 alpha_05 与 alpha_05_observed logits / NLL 逐位一致（PAIR_OBSERVER_BITS；npz SHA 均 `916cb848…`）；`OBSERVER.json` **144 事件**（8 处 gain 各 18：correct 48、shuffled / silent / distractor 各 32；batch 0–3 各 32、batch 4–5 各 8），150,222 字节 ≤ 262,144 预算（OBSERVER_BUDGET）；事件 device 均 `cuda:0`、dtype `torch.float32` |
| G7 归档验收 | COMPLETE、Slurm COMPLETED/0:0、6048 条无重漏、哈希 / 合同关联、独立离线复算 | 通过。E0_COMPLETE.json E0_ENDPOINT_PASS；sacct COMPLETED / 0:0；**6048 条**（PAIR_PREDICTIONS；A 3168 + B 2880，与 STAGES.predictions 一致）；文件清单与 npz / STAGES / PROVENANCE / OBSERVER / WORKER 哈希绑定（PAIR_FILE_INVENTORY、PAIR_OUTPUT_SHA、STAGE_REPORT_SHA、PROVENANCE_SHA、OBSERVER_SHA）；A 目录 10,438,612 字节、B 目录 9,353,011 字节，低于 64 MiB 上限；WORKER.json SHA A `4cf6cfbc…`（2478 字节）/ B `2a1bbea9…`（2181 字节）与 E0_COMPLETE.verification.worker_manifests 一致；本台账离线复核 E0_ARTIFACTS_VERIFIED |

## 3. 资源与成本

| 项 | 值 | 来源 |
| --- | --- | --- |
| 申请 | 1×nvidia_a100、8 CPU、65536 MiB（64 GiB）、00:30:00、GPU-1A / student；budget_gpu_hours=0.5；协调器硬期限 1500 s | INTENT.json；RELEASE.json（wall_minutes=30、gpus=1、cpus=8、host_memory_gib=64、coordinator_deadline_seconds=1500） |
| 实际 Slurm Elapsed | 00:11:16 = 676 s；0.1878 GPU 小时；30 分钟时限的 37.6% | REMOTE_PROGRESS.md |
| A 进程 | elapsed_seconds 259.0351708829403（11 轮，3168 条；0.0818 s / 条） | `attempt/A/STAGES.json` |
| B 进程 | elapsed_seconds 223.773228129372（10 轮，2880 条；0.0777 s / 条） | `attempt/B/STAGES.json` |
| A+B 阶段合计 | 482.808 s；6048 条 → **0.0798 s / 条** | 计算 |
| 按 Slurm Elapsed 换算 | 676 / 6048 = **0.1118 s / 条** | 计算 |
| 阶段外开销 | 676 − 482.8 = 193.2 s（28.6%）：包核验、两次进程启动与 strict-load、作业内验收、完成记录写出（`elapsed_seconds` 由 `execute_stages` 计时，不含加载） | 计算；`model_stage_driver.execute_stages` |
| 05 号文 §6 估算 | 总约 994 s（16.6 分钟）、forward 约 421.7 s | 实际 676 s 为估算的 68.0%；阶段合计 482.8 s 含 scene 重建、G5 固定特征检查与逐轮保存，不能直接与 forward 估算相减 |
| P08 Job 728520 参考 | 进程 3367 s / 48,000 条 = 0.0701 s / 条；Slurm 00:57:11（3431 s）/ 48,000 = 0.0715 s / 条 | [P08 台账](../p08full-production-20260919-r2/REPORT.md) §1、§4。E0 阶段单价为其 1.14 倍；E0 每轮仅 96 trial（6 批）、21 次布局重建并含 G5 与逐轮保存，摊销条件不同，**仅作参考**，不作效率结论 |

## 4. 来源字段缺口（如实记录）

方法：对 `state/` 下全部 42 个文件 grep `torch|cuda|cudnn|gpu|nvidia|A100|MaxRSS|max_allocated|reserved|rss|memory|version|deterministic|tf32|matmul|hostname|spcc|sacct|scontrol|Elapsed`，并核对包内源码写出的字段。

收集的 state 中**不存在**的字段：

1. torch、CUDA、cuDNN、Python 版本（数值字段）。
2. GPU 型号名（`torch.cuda.get_device_name`）。
3. 峰值显存（max_memory_allocated / max_memory_reserved）。
4. 进程 RSS 或 Slurm MaxRSS。
5. runtime 六项（deterministic、cuDNN deterministic、benchmark、matmul precision、两项 TF32）的实际值。
6. 节点名与 sacct / scontrol 原始回读（ReqTRES / AllocTRES、Start / End / Elapsed）；这些只出现在 REMOTE_PROGRESS.md 的流水文本，与 P08 台账保存 `held_readback_*.log`、`correct-gpu-*/` 的做法不同。
7. 进程级墙钟起止时间（只有 `execute_stages` 的 `elapsed_seconds`）。

实际**存在**的相关信息及位置：

- 设备与精度：`attempt/A/OBSERVER.json` 每个事件的 cue / mixture / output 记 `device=cuda:0`、`dtype=torch.float32`（144 事件）。
- Python 主版本与 torchaudio：A、B `stderr.log` 的路径 `/home/s2510040/miniconda3/envs/attn/lib/python3.11/site-packages/torchaudio/functional/functional.py:1371`（kaiser_window 弃用 UserWarning）。
- 加载来源：`PROVENANCE.json.load_report` 记录模型源码路径 / SHA / inode / size、键数、参数量与覆盖率、native_preprocessing、prefix_rule。
- 环境合同以**门槛**而非记录存在：包内 `audited_model_session.py` 的 `launch_gate` / `audited_session` 用 `require` 强制 Python 3.11.5、torch 2.1.1+cu118、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、CUDA 未预先初始化、`'A100' in get_device_name(0)`、`device_count()==1`、`SLURM_CPUS_PER_TASK==8`、`torch.version.cuda=='11.8'`、`cudnn.version()==8700`；runtime 六项由 pinned core `configure_runtime()` 设置并在加载后以 `runtime_values()` 核对不变（LOAD_CHANGED_RUNTIME）。worker 退出码 0 且 `postchecks_completed=true` 间接说明这些门槛通过，但任何 state 文件都没有写下这些值。
- 包内 `run_e0.sbatch` 导出 `CUBLAS_WORKSPACE_CONFIG=:4096:8`、`OMP_NUM_THREADS=8`、`PYTHONHASHSEED=0`、`PYTHONDONTWRITEBYTECODE=1`。
- `slurm-746603.log` 只有 1 行 `E0_SCRATCH=/tmp/audattn_e0_Qv0C2Sp0`（runner 的 printf）；worker 的 stdout / stderr 由监督器重定向到各自 log。

05 号文 §6 预算表中的“内存监测：记录 max allocated / reserved / RSS”在 v2 包里没有对应的归档字段，属于方案与实现之间的差距，在此如实记录。

建议：E1 包下次重新冻结时，在 PROVENANCE 或 RUN 记录中加入 torch / CUDA / cuDNN / Python 版本、GPU 型号、runtime 六项实际值、每阶段 max_memory_allocated / reserved 与 RSS、进程起止时间，并把 sacct / scontrol 只读回读作为收集文件保存。同包 `eager_compare.py` 第 840 至 847 行已有 environment 字典（python/torch/cuda/cudnn/device/hostname 六项在第 841 至 846 行）（python / torch / cuda / cudnn / device / hostname），第 918 至 926 行已有 `cuda_max_memory_allocated_bytes`、`cuda_max_memory_reserved_bytes`、`host_max_rss_kib` 的记录实现（均在 `run_small()` 内；E0 v2 包与 E1 package_ready 的该文件逐字节相同，SHA `09cb0c48…`），但 E0 / E1 生产路径未调用它们（`loaded_model_adapter.pinned_core()` 只加载该模块，包内无其他文件调用 `run_small`）；E1 重新冻结时可移植到 PROVENANCE / RUN 记录。这不改变 E0 的验收结论：05 号文 G0–G7 的判定依据是逐位比较、哈希绑定与计数，缺失的是环境与资源的可追溯字段，不是验收输入。

## 5. typed GRES 站点改写（第 9 次记录）

- 现象：提交器 argv `--gres=gpu:nvidia_a100:1`（INTENT.json），held 回读 ReqTRES=`gres/gpu:h100-20c=1`、TresPerNode=`gres/gpu:1`。
- 处理（依[主计划](../../../../2026-09-20_选择性听取发达机制_主课题总计划.md) §13 第 3 条、近期计划 §3 2.3）：保持 held 不释放 → 用户对同一作业 746603 单独授权唯一一次 `scontrol update JobId=746603 Gres=gpu:nvidia_a100:1` → 独立回读 ReqTRES=`gres/gpu:nvidia_a100=1`、TresPerNode=`gres/gpu:nvidia_a100:1`、仍 PENDING / JobHeldUser / RunTime 0、spool 脚本 SHA 与包一致 → 用户单独授权 release → AllocTRES=`gres/gpu:nvidia_a100=1`，节点 spcc-a100g04。没有二次修正、没有替代作业、没有自动化。
- 历史计数：主计划 §13 第 3 条写明“历史 typed GRES 改写已有 8 次记录；这不是未来自动修正授权”。第 5 次 [p05b](../p05b-production-20260918/REPORT.md)（Job 726428）、第 6 次 [p07conf](../p07conf-production-20260919/REPORT.md)（728280）、第 7 次 p08 首跑（728378，[held_readback_728378.log](../p08full-production-20260919/held_readback_728378.log)）、第 8 次 [p08 r2](../p08full-production-20260919-r2/REPORT.md)（728520）；更早 4 次见 evidence 下 2026-09-11 至 2026-09-17 的 job705468、job713897 等记录。本次为第 9 次；每次仍需该作业的单独授权。p05b 台账提出的“向集群管理员确认可保留 typed GRES 的提交方式”仍未落实，作为待办保留。

## 6. 结论与限制

- 工程验收通过：E0_ENDPOINT_PASS；本台账用冻结包自身代码离线复核得 E0_ARTIFACTS_VERIFIED，与远端完成记录逐字段相同。本批 1 次 sbatch、1 次 scontrol update、1 次 release。
- 不是科学结果：`scientific_alpha_result=false`。`PAIR_EXECUTION.json` 的 `production_verified=false` / `PAIR_EXECUTION_VERIFIED_NOT_SCIENCE_QUALIFIED` 与 `STAGES.json` 的 `LOADED_MODEL_STAGES_FINISHED_NOT_QUALIFIED` 是通用 seam 的固定字段，表示“不构成科学资格”，不是调度或验收失败；生产验收结论由 `E0_COMPLETE.json` 与 `production_e0.verify` 给出。
- 研究身份：`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。96 条为工程覆盖集（24 clean / 72 mixed / 64 control），不能报告其 Accuracy 为 bank 结果，也不能据此写机制成立（05 号文 §2、§5）。
- 中间 α（0.25 / 0.5 / 0.75）与三个负对照的数值读数不在本报告。科学读数另见本目录 `readout/` 子目录与 26 号备忘 `alpha_mechanism_local_20260923/26_E0_SCIENTIFIC_READOUT_746603_20260927.md`（由另一任务生成；本报告只引用路径，不描述其数字）。
- 05 号文 §5 的约定仍适用：中间 α 平坦或效果变差不属于工程失败，如实保留。
- 下一步：按主计划 §5 与近期计划 §4 编制 E1 预算并取得单独授权；本报告不授权任何提交。
