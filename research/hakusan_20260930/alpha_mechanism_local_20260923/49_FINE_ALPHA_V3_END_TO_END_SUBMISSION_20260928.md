# 低α扫描v3：从上传到放行的全过程说明

**最新（2026-09-29 04:06 JST）**：756262 以 COMPLETED/0:0 结束（Elapsed 05:17:14）。看守查询61次，0失败、0报警；收集408个文件并完成哈希核验；本地 `offline-check` 验收 `FINE_ALPHA_ARTIFACTS_VERIFIED`（219,600条预测）。状态为 `ANALYSIS_PENDING`，下文“运行中”“尚未完成”等表述指成文时点。详见[v3台账](release_fine_alpha_20260928_candidate_v3/REMOTE_PROGRESS.md)。

日期：2026-09-28。本文说明v3候选从本地冻结到在超算上运行的全过程：做了什么、为什么这么做、安全边界在哪里、证据在哪里。逐条回执见[v3远端台账](release_fine_alpha_20260928_candidate_v3/REMOTE_PROGRESS.md)，前置修正见[48号文](48_FINE_ALPHA_V3_SUBMISSION_QUEUE_FIX_20260928.md)。

## 1. 一句话结论

作业 **756262** 于 2026-09-28 **22:44:01 JST** 在 `spcc-a100g04`（NVIDIA A100-PCIE-40GB）开始运行，已通过启动时的运行时门槛，A块环境预检 `FINE_ENVIRONMENT_PRECHECK_PASS_NOT_INFERENCE_VERIFIED`。整个过程只提交一次、只修正一次GRES、只放行一次，未超出预算，未重投。

**运行中不等于扫描完成。** 运行结束后还需要收集、离线验收和54点读数，目前没有任何新的科学结果。

## 2. 背景：为什么有v3

| 版本 | 结果 | 问题 |
|---|---|---|
| v1（作业753729） | 运行1:48后 FAILED | A块结束时来源字段验收失败（`PROVENANCE_ENVIRONMENT`，torch版本对象类型问题） |
| v2 | 已上传、原生预检通过，未提交 | 冻结提交器以“队列中任何名称含audattn的作业”拒绝提交，而新种子数值预检754073正在运行 |
| v3 | 本文 | 提交器改为逐作业审阅（`EXPLICIT_INDEPENDENT_JOB_REVIEW_V1`），其余科学内容与v2相同 |

v3的科学合同与v2一致：formal40权重、54个α点（0–0.50步长0.01，加0.75、0.875、1）、E1输入、194,400条科学预测、219,600条总预测。只有scope从V2改为V3。

## 3. 授权范围

用户指令：“不需要我批准 我希望你直接推进到第4步”。据此一次执行48号文第5节的1–4步，不再逐步请示。授权记录在各步的独立文件里：

| 文件 | 内容 |
|---|---|
| [GPU_HELD_AUTHORIZATION_1.json](release_fine_alpha_20260928_candidate_v3/GPU_HELD_AUTHORIZATION_1.json) | 1 A100、8 CPU、64 GiB、最多6小时，单次held提交；含并发审阅 |
| [GRES_CORRECTION_AUTHORIZATION_1.json](release_fine_alpha_20260928_candidate_v3/GRES_CORRECTION_AUTHORIZATION_1.json) | 仅对756262修正一次GRES为A100，保持held |
| [RELEASE_AUTHORIZATION_1.json](release_fine_alpha_20260928_candidate_v3/RELEASE_AUTHORIZATION_1.json) | 仅放行756262一次；携带放行前新抓取的并发审阅 |

不变的边界：不自动重试、不自动重连、不重投、不扩大预算；`scheduler_quota_verified=false`，即不据此断言账户可以同时运行两个作业。

## 4. 执行过程

### 4.1 第1步：上传、核验、原生预检（21:01–21:03 JST）

- 新驱动 [publish_fine_alpha_v3.py](publish_fine_alpha_v3.py)：把42个文件（41个清单文件加RELEASE）上传到新目录 `/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/package`，逐文件落盘核验。目录已存在时拒绝写入，不覆盖任何东西。上传前后都确认v1、v2远端RELEASE的SHA未变。
- 远端隔离 `check`：`FINE_ALPHA_PACKAGE_CHECK_PASS`（219,600/194,400条预测，`production_validated=false`）。
- 新驱动 [preflight_fine_alpha_v3.py](preflight_fine_alpha_v3.py)：原生只读导入预检 `FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB`，96个快照文件，manifest SHA `8febb19f…`。未加载checkpoint，未初始化CUDA。

### 4.2 第2步：并发审阅

新驱动 [review_fine_alpha_v3_queue.py](review_fine_alpha_v3_queue.py) 只读抓取实时队列，结果只有754073（新种子formal40数值预检，当时已运行约7–9小时，时限16小时）。

人工审阅了754073的实际spool脚本，结论如下：
- 它的所有写入都在 `auditory_attention_seed20260928/` 下：数值预检目录、快照、日志、`rolling.ckpt`、`PASS.json`。
- 该目录中的 `cv_train`、`cv_clips` 是软链接，指向原始 `auditory_attention/` 树，所以它和本扫描**共享E1音频目录，但双方都只读**。本扫描在推理前后逐条核验E1音频SHA，万一被改动也会失败，不会产生错误结果。
- 它不写原始树、`audattn_e2`、`audattn_external_eval`，也不写 `audattn_fine_alpha`。

审阅记录绑定作业号、名称、账户、入口、工作目录、日志路径、入口脚本SHA和spool SHA（`a6a4a641…`），任何一项变化都会停止。

> 更正说明：第一版审批文件把依据误写为“读取自身cv_train”。该文件从未发出，已改名保留为 `GPU_HELD_AUTHORIZATION.superseded-unsent-basis-text.json`，正式审批以更正后的 `_1` 为准。

### 4.3 第3步：单次held提交与GRES修正（22:43 JST）

**提交**（[submit_fine_alpha_v3.py](submit_fine_alpha_v3.py)，调用包内冻结提交器一次）：
1. 冻结提交器先只读核查队列（`QUEUE_INITIAL`），结果 `CONCURRENT_JOBS_REVIEWED_DISJOINT`。
2. 创建state，执行 `sbatch --test-only`，通过。
3. 再次核查队列（`QUEUE_FINAL`），结果相同，随后执行一次 `sbatch --hold`，得到作业号756262。
4. 回读资源：站点把 `--gres=gpu:nvidia_a100:1` 改写成 `gres/gpu:h100-20c=1`、`TresPerNode=gres/gpu:1`，和v1/753729完全一样。冻结提交器按设计写STOPPED后停止，驱动把结果归为 `FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH`。8 CPU、64G、6小时、GPU-1A均符合，spool与runner逐字节一致。

**GRES修正**（[correct_fine_alpha_v3_once.py](correct_fine_alpha_v3_once.py)）：
1. 先在远端独占写入修正意图文件。
2. 执行唯一一次 `scontrol update JobId=756262 Gres=gpu:nvidia_a100:1`。
3. 回读：`gres/gpu:nvidia_a100=1`、`TresPerNode=gres/gpu:nvidia_a100:1`，作业仍为 `JobHeldUser`、Priority 0，原提交日志和spool不变。结果为 `FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD`。

### 4.4 第4步：放行（22:43:47–22:44:01 JST）

1. 放行前重新只读抓取队列（[queue-review-3mumz40q](release_fine_alpha_20260928_candidate_v3/queue-review-3mumz40q/RESULT.json)）。只排除作业自身这一行held记录，其余仍然只有754073且与审阅记录一致。
2. 放行驱动（[release_fine_alpha_v3_once.py](release_fine_alpha_v3_once.py)）在远端再做一遍核查：整包check、作业仍held且为A100、spool一致、用冻结 `inspect_queue` 实时复核并发。
3. 全部通过后，依次写 `QUEUE_RELEASE.json`、`RELEASE_INTENT.json`、`RELEASE_AUTHORIZATION.json`，然后执行唯一一次 `scontrol release 756262`。
4. 即时回读为 PENDING、Reason=None、Priority 16493，A100类型不变，结果 `FINE_ALPHA_RELEASED_READBACK_VERIFIED`。约6秒后调度为RUNNING。

**启动后确认**：包内运行时门槛（`allocated_gate` 加 `approval_gate`）通过，A块已启动。环境预检记录 torch `2.1.1+cu118`、CUDA 11.8、确定性设置全开、TF32关闭；stderr只有既有的torchaudio弃用警告。22:50时A块仍在运行，运行6分24秒。

## 5. 安全设计：为什么不会重复提交或越权

| 风险 | 防护 |
|---|---|
| 重复提交 | 远端 `APPROVAL.json` 与 `state/` 用独占创建。冻结提交器拒绝已有state，本地尝试目录按编号且不可覆盖 |
| 重复修正 | 远端修正意图/结果文件已存在即拒绝，`scontrol update` 失败不重试 |
| 重复放行 | 远端 `QUEUE_RELEASE`、`RELEASE_*` 已存在即拒绝，本地只在前次**确证未触及放行命令**时才允许新尝试 |
| 队列里出现未审阅作业 | 冻结 `inspect_queue` 实时比对，任何未审阅作业、字段变化或脚本哈希变化都停止 |
| 预算漂移 | 每步回读都核对1 A100、8 CPU、64G、6小时、GPU-1A和单节点单任务 |
| 瞬时故障占用单次机会 | 写入前的纯检查失败时只输出拒绝标记、不写state，之后可以按新编号重试；只读查询有界重试；已触及写入的情况一律停止，等人工检查 |

## 6. 执行前的审查与验证

驱动是这次新写的，所以真实提交前做了四轮多代理审查。每条发现都另由独立代理对抗性复核，只修复确认成立的问题。

| 轮次 | 方式 | 确认/否决 | 主要修正 |
|---|---|---|---|
| 1 | 4个视角静态审查 | 8 / 10（2高） | 放行时改用新抓取的并发审阅；只读拒绝不再占用放行机会；结果状态仅在所有后置检查通过后写入；GRES修正只接受h100-20c形态；超时覆盖最坏情况；审阅依据措辞更正 |
| 2 | 复审修正 | 5 / 4（3高） | 主连接检查失败、远端写入前停止都可以重试；提交后只读回读加有界重试；冻结提交器自身查询失败时以驱动回读分类；放行审阅必须晚于上次尝试 |
| 3 | 仿真Slurm端到端运行 | 6 / 2 | 冻结提交器在state之前停止时，用硬链接退役远端APPROVAL；提交和修正按编号区分尝试；修正加写入前拒绝标记；修正后squeue仅作证据；测试夹具固定 |
| 4 | 40个仿真场景、619项检查 | 2 / 1 | 提交远端加写入前拒绝标记；拒绝标记已送达但ssh返回255时仍判为干净拒绝 |

第4轮在所有仿真场景中都没有出现第二次 `--hold`、`update` 或 `release`。正常路径、GRES改写、无需修正、并发拒绝后重试、主连接失败、只读查询失败、崩溃残留等场景均符合预期。

其他验证：
- 全目录回归 **552项通过**：原497项，加新增上传9项、预检7项、链路39项。
- 远端确认 `/home` 支持硬链接和目录fsync（临时探针目录测完已删除）。
- 冻结包全程未修改。

## 7. 证据索引

均在 `release_fine_alpha_20260928_candidate_v3/` 下：

| 步骤 | 目录 | RESULT SHA前缀 |
|---|---|---|
| 上传 | `upload-v3-once/` | `72d903e5` |
| 原生预检 | `source-check-v3-once/` | `c0959fe2` |
| 提交用并发抓取 | `queue-review-w7nz2c2r/`（初次抓取 `queue-review-8_yqygng/` 仅保留） | — |
| held提交 | `held-submission-v3-1/` | `67d28d06` |
| GRES修正 | `gres-correction-v3-1/` | `bf203c1e` |
| 放行用并发抓取 | `queue-review-3mumz40q/` | — |
| 放行 | `release-v3-1/` | `37d22355` |

远端state：`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/state/`，含 APPROVAL、QUEUE_INITIAL/FINAL/RELEASE、TEST_ONLY、INTENT、RESPONSE、SUBMISSION、HELD_RESOURCES、STOPPED、GRES_CORRECTION_*、RELEASE_*、slurm-756262.log 和 attempt/。

## 8. 新增文件

| 文件 | 作用 |
|---|---|
| `publish_fine_alpha_v3.py` | v3上传与远端包检查 |
| `preflight_fine_alpha_v3.py` | v3原生只读导入预检 |
| `review_fine_alpha_v3_queue.py` | 只读队列抓取与并发审阅构建（`--own-held-job` 用于放行前） |
| `submit_fine_alpha_v3.py` | 单次held提交外层驱动（按编号区分尝试） |
| `correct_fine_alpha_v3_once.py` | 单次GRES修正（按编号区分尝试） |
| `release_fine_alpha_v3_once.py` | 放行前复核与单次放行（按编号区分尝试） |
| `test_fine_alpha_upload_v3.py`、`test_fine_alpha_preflight_v3.py`、`test_fine_alpha_v3_chain.py` | 对应测试 |

## 9. 尚未完成

1. **跟进到终态**：参考v1估计，全程约5.2小时（22:44开始），但耗时不保证线性，6小时为硬上限。v3的看守和收集脚本尚未编写；v1同类脚本绑定753729，不能直接复用。
2. **收集与离线验收**：终态后一次性只读收集state，用冻结包离线验收219,600条预测，并与远端COMPLETE核对。通过只标记 `ANALYSIS_PENDING`。
3. **科学分析**：54点读数、与历史桥接对比。**扫描完成不等于α已映射到儿童年龄。**
4. 如果失败：只归档，不重投、不扩预算，另行决定修正方案。
5. 并发作业754073预计最迟 2026-09-29 05:43 JST 结束，两者互不依赖。
