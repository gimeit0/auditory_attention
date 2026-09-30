# 低α扫描v3远端台账

日期：2026-09-28。用户指令：“不需要我批准 我希望你直接推进到第4步”，即按[48号文](../48_FINE_ALPHA_V3_SUBMISSION_QUEUE_FIX_20260928.md)下一执行批次1–4，一次完成上传/核验/原生预检、并发审阅、单次held提交、GRES修正和正式放行。预算上限不变：1 A100、8 CPU、64 GiB、6小时；异常停止，不自动重投、不扩预算。

## 当前状态：756262已完成，收集与离线验收通过

`FINE_ALPHA_COLLECTED_OFFLINE_VERIFIED_ANALYSIS_PENDING`。作业756262于 2026-09-29 04:01:15 JST 以 **COMPLETED / 0:0** 结束，Elapsed 05:17:14（协调器计时19,003秒，低于21,000秒截止和6小时上限）。三块记录齐全：A 126、B 120、C 120。VERIFY生成 `FINE_ALPHA_ARTIFACTS_VERIFIED`，219,600条预测（其中科学预测194,400条），3个冷启动进程，历史桥接作业750474。

- 看守：61次只读查询，0次查询失败，0次报警（[watch-756262-1](watch-756262-1/RESULT.json)）。
- 收集：一次成功，408个文件，675 MB，逐文件传输与落盘哈希核验通过（[collected-756262-2xu_4ag0](collected-756262-2xu_4ag0/RESULT.json)，RESULT SHA `5cfa8db7…`）。
- 本地用冻结包 `offline-check` 独立复验，结果与远端COMPLETE核心字段一致。A/B/C/VERIFY的stderr除既有torchaudio弃用警告外无其他输出。
- `scientific_report_complete=false`，`age_mapping_validated=false`：工程验收通过，不等于科学结论已完成，也不等于α已映射到儿童年龄。

| 步骤 | JST | 结果 | 回执SHA |
|---|---|---|---|
| 上传42文件+远端整包检查 | 21:01 | `FINE_ALPHA_V3_UPLOADED_AND_HASH_VERIFIED_NO_JOB` | [upload-v3-once](upload-v3-once/RESULT.json) `72d903e5…` |
| 原生只读导入预检 | 21:03 | `FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB` | [source-check-v3-once](source-check-v3-once/RESULT.json) `c0959fe2…` |
| 单次held提交 | 22:43:07–14 | 作业756262；`FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH`（站点改写为h100-20c） | [held-submission-v3-1](held-submission-v3-1/RESULT.json) `67d28d06…` |
| 唯一一次GRES修正 | 22:43:23–29 | `FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD`，updates=1 | [gres-correction-v3-1](gres-correction-v3-1/RESULT.json) `bf203c1e…` |
| 放行前只读并发抓取 | 22:43:3x | `FINE_ALPHA_V3_CONCURRENCY_REVIEW_CAPTURED`（仅754073+自身） | [queue-review-3mumz40q](queue-review-3mumz40q/RESULT.json) |
| 唯一一次放行 | 22:43:47–55 | `FINE_ALPHA_RELEASED_READBACK_VERIFIED`，release_invocations=1 | [release-v3-1](release-v3-1/RESULT.json) `37d22355…` |

## 各步要点

- **上传**：独立目录`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/package`，41个清单文件+RELEASE逐文件落盘核验；v1/v2远端RELEASE前后SHA不变；远端隔离`check`为`FINE_ALPHA_PACKAGE_CHECK_PASS`（194,400/219,600预测，`production_validated=false`）。
- **原生预检**：96个快照文件，manifest SHA `8febb19f…`，`hash_checked_source_only`；未加载checkpoint、未初始化CUDA。
- **并发审阅**：754073（新种子formal40数值预检）逐字段、入口脚本和spool SHA `a6a4a641…`均与审阅记录一致。它所有写入都在`auditory_attention_seed20260928`下；该目录的`cv_train`/`cv_clips`是指向原始树的软链接，属于与本扫描E1音频根共享的只读输入，扫描在推理前后逐条核验E1音频SHA。依据见[GPU审批](GPU_HELD_AUTHORIZATION_1.json)`concurrency_review_basis`（`scheduler_quota_verified=false`，不作账户并发额度断言）。初版审批文件的依据措辞有误（写成“读取自身cv_train”），未发出，改名保留为`GPU_HELD_AUTHORIZATION.superseded-unsent-basis-text.json`。
- **提交**：冻结提交器两次队列核查均`CONCURRENT_JOBS_REVIEWED_DISJOINT`；test-only通过；`sbatch --hold`一次。回读`ReqTRES=…gres/gpu:h100-20c=1`、`TresPerNode=gres/gpu:1`，与v1/753729相同的站点改写；其余8CPU/64G/6小时/GPU-1A均符合。冻结提交器按设计写STOPPED并返回1，外层驱动归类为held资源不符（返回2），spool与runner逐字节一致。
- **GRES修正**：先独占写`state/GRES_CORRECTION_INTENT.json`，再执行一次`scontrol update JobId=756262 Gres=gpu:nvidia_a100:1`；修正后`gres/gpu:nvidia_a100=1`、`TresPerNode=gres/gpu:nvidia_a100:1`，仍`JobHeldUser`/Priority 0；原提交日志与spool不变。
- **放行**：放行授权携带放行前新抓取的并发审阅（排除且仅排除自身held行），远端用冻结`inspect_queue`实时复核通过后写`QUEUE_RELEASE.json`，再写`RELEASE_INTENT.json`与`RELEASE_AUTHORIZATION.json`，执行一次`scontrol release 756262`。即时回读PENDING/Reason=None/Priority 16493，A100类型不变；随后调度为RUNNING。

## 驱动与验证

新增冻结包外驱动（均不修改冻结包）：[publish_fine_alpha_v3.py](../publish_fine_alpha_v3.py)、[preflight_fine_alpha_v3.py](../preflight_fine_alpha_v3.py)、[review_fine_alpha_v3_queue.py](../review_fine_alpha_v3_queue.py)、[submit_fine_alpha_v3.py](../submit_fine_alpha_v3.py)、[correct_fine_alpha_v3_once.py](../correct_fine_alpha_v3_once.py)、[release_fine_alpha_v3_once.py](../release_fine_alpha_v3_once.py)；测试`test_fine_alpha_upload_v3.py`、`test_fine_alpha_preflight_v3.py`、`test_fine_alpha_v3_chain.py`。

- 执行前经四轮多代理对抗审查/模拟：第1轮确认8项（2高），第2轮5项（3高），第3轮在仿真Slurm端到端运行中确认6项可恢复性问题，第4轮40个仿真场景619项检查全部通过、无二次hold/update/release，余2项中等问题已修。修正集中在：结果状态仅在所有后置检查后写入；放行使用放行前新抓取的并发审阅；各步写入前的纯检查失败只输出拒绝标记、不占用单次机会（提交/修正/放行均按尝试编号）；只读回读有界重试；超时覆盖最坏情况。
- 全目录回归552项通过（原497项+新增55项）。远端`/home`已确认支持硬链接与目录fsync（临时探针目录已删除）。

## 看守与收集（22:59 JST起）

新增只读脚本 [status_fine_alpha_v3.py](../status_fine_alpha_v3.py)、[watch_fine_alpha_v3.py](../watch_fine_alpha_v3.py)、[collect_fine_alpha_v3.py](../collect_fine_alpha_v3.py)（测试 `test_fine_alpha_v3_followup.py` 8项）。作业号和回执SHA都只从已验证的提交/放行证据中读取；不提交、不放行、不取消、不修改作业，也不自动重连。

- 每5分钟只读查询一次（squeue/sacct、attempt标记、各块npz数、日志大小）。进度显示按预期记录数A 126、B 120、C 120计算。
- 相对v1看守的改进：单次查询失败不会结束看守。遇到以下情况才退出报警：SSH主连接丢失需要用户重连、连续4次查询失败、出现失败标记、RUNNING状态下50分钟无任何进展、运行超过5小时40分钟仍未完成。
- 作业终态后一次性只读收集state（上限1500文件、3 GiB），逐文件哈希核验。COMPLETED且0:0时，用冻结包本地 `offline-check` 验收219,600条预测，并与COMPLETE核对。收集是只读的，传输失败时可换新目录重试，最多3次。
- 看守在 `caffeinate` 下运行，证据目录为 `watch-756262-1/`。首次观测：运行14:35，A块12/126，节奏与v1基本一致（v1的A块约1:48完成）。v1的失败点在A块结束后的来源验收，本次预计在约00:32 JST前后经过这一点。

## 读数（2026-09-29）

54点描述性读数已完成，见[50号读数文档](../50_FINE_ALPHA_READOUT_756262_20260929.md)与[readout-756262-y71mc3m7](readout-756262-y71mc3m7/REPORT.json)。0–0.50全部落在崩溃区；准确率单调不减；α≈0.30起开始恢复，0.50时为15.1%（mixed场景，正确提示）；提示收益从α≈0.42起恢复。独立盲重算与方法审查均已完成。

## 下一步

1. 用收集到的 `collected-756262-2xu_4ag0/state/attempt` 做54点读数：准确率、NLL等随α的曲线，以及与历史桥接对比。
2. 与E0的α塌缩结论（α≤0.5时formal40失效）对照，确定精细网格下的转折区间。
3. 另行讨论α与儿童年龄的映射；本扫描不提供这一验证。
