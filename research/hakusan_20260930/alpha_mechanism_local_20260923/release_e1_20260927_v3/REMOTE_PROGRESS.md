# E1 v3 发布台账

## 2026-09-28 用户接受 P5 披露偏差，不重跑

用户在影响解释与不重跑建议后回复“好的”。单独记录已追加至项目 `docs/superpowers/evidence/e1-contract-signoff-20260927/P5_DEVIATION_ACCEPTANCE_750474.json`，绑定28/29合同、v3 release及原交付MANIFEST。当前 **E1_DELIVERED_WITH_ACCEPTED_P5_DEVIATION**，不追溯改写原矩阵的P5未满足事实。见项目 `alpha_mechanism_local_20260923/37_E1_ACCEPTED_DELIVERY_750474_20260928.md`。

偏差仅限此作业的完整进程UTC范围，不改变数值或探索性身份，不证明机制成立，无新GPU授权。本次未连接远端、未重跑，原交付与冻结包保持原字节。以下“等待P5决定”均为历史状态。

## 2026-09-28 P5 处置草案，未批准

再次核实冻结调用链：UTC 字段不含模型加载和全部结束后校验/归档。签署目录没有偏差接受或新重跑授权。项目 `alpha_mechanism_local_20260923/36_E1_P5_DEVIATION_DISPOSITION_DRAFT_20260928.md` 已列出接受带披露交付与修复重跑两种处置；建议前者，但不代签。主课题总计划同步当前交付状态。原交付包及13文件 MANIFEST 未改，无网络/GPU操作。

## 2026-09-28 统一交付已生成，合同门保留 P5 缺口

[统一报告](delivery-750474-3wjt5pax/REPORT.md)、[验收矩阵](delivery-750474-3wjt5pax/COVERAGE.json)、[全部主/次要指标](delivery-750474-3wjt5pax/ALL_METRICS.csv)和资源、错误结构、独立核验 JSON 已汇总。构建时重做 offline-check、检查来源链及 28 项测试；13 个交付文件的 MANIFEST 哈希全部通过。

状态 `E1_ANALYSIS_DELIVERED_CONTRACT_INCOMPLETE`；门正确拒绝 E1_DEV_COMPLETE，未赋科学标签。唯一未关闭 P5 完整子进程 UTC 起止，不能从现有执行窗口补造。接续需明确偏差处置或另行授权的修复重跑，当前不代用户接受偏差、不新增 GPU。原数据、合同和冻结包保持不变。

## 2026-09-28 错误结构独立核验与资源汇总完成

新错误报告 `error-analysis-750474-0tkyayan` 保留 clean/mixed 分列；独立核验全部 38400 预测、131 汇总、655 区间指标通过，见 [审计结果](independent-error-audit-750474-66dqor7h/RESULT.json)。25 项合成测试通过。A/B 资源和执行阶段 UTC 汇总在项目 `alpha_mechanism_local_20260923/35_E1_ERROR_AUDIT_AND_RESOURCE_SUMMARY_20260928.md`。

34 号的错误结构剩余项已关闭；最终交付报告/条款覆盖矩阵仍待生成，P5 完整进程时间范围限制仍保留。未标 E1_DEV_COMPLETE；无网络或 GPU 操作。

## 2026-09-28 独立主/次要算术复算通过

另一实现从原始数组复算 49 单位、3170 指标、54 数组摘要、17 崩溃判据与 3 负对照摘要，绝对容差 1e−10 内全部一致；不导入原统计计算函数。23 项合成测试通过。证据：[独立复算结果](independent-stat-audit-750474-epr_1shm/RESULT.json)；范围及剩余验收矩阵见项目 `alpha_mechanism_local_20260923/34_E1_INDEPENDENT_AUDIT_20260928.md`。

仍需错误结构分列/独立审计、完整来源与最终图文/结论门；P5 范围限制不因数值复算通过而消失。没有将目标标为完成，无网络或 GPU 操作。

## 2026-09-28 错误结构与来源范围审查

全部 38400 条预测已保存逐条错误分类，B 冷重复未混入样本数；19 项测试通过。分类区分标签碰撞、角色词重叠、main clean 零 cue 和新 clean 正确 cue。见项目 `alpha_mechanism_local_20260923/33_E1_ERRORS_AND_PROVENANCE_REVIEW_20260928.md` 与 [错误结构报告](error-analysis-750474-wyzfs1v7/REPORT.json)。

来源审查发现 P5 的 process UTC 字段只覆盖模型加载后的 execute_loaded 阶段，不是完整 OS 进程生命周期。报告须保留该范围限制，不能补造时间或称全部来源要求已满足。P9 的后续用户签署以外部 SIGNOFF 记录绑定，原包 PENDING 字符串不改。继续本地独立复算和全项证据矩阵；尚未 E1_DEV_COMPLETE。无新 GPU、远端或网络操作。

## 2026-09-28 本地次要统计阶段进展

13 项统计测试通过；次要分析入口重新离线验收原始归档并逐数组核验 SHA。已补齐绝对准确率/NLL、float64 复算偏差、预定崩溃区、20 格分层、clean 两 cue 及三负对照（含敏感性版），control 主指标与共用抽样摘要复现上一阶段结果。

α=.5 main correct 准确率 14.35%，α=1 为 44.30%；α=0、.5 属预定崩溃区，Q3 为 `Q3_NOT_INTERPRETABLE_COLLAPSE`。新 clean α=1 的 correct_cue−zero_cue 为 −3.00 pp，CI [−8.54,2.54]。状态仍 `E1_SECONDARY_STATISTICS_PARTIAL_NOT_DEV_COMPLETE`；错误结构、P1–P9 汇总、整体独立复算与结论门待完成。

项目说明 `alpha_mechanism_local_20260923/32_E1_SECONDARY_READOUT_750474_20260928.md`；[完整结构化阶段统计](secondary-analysis-750474-mo1tlyrm/REPORT.json)。本轮无网络或 GPU 操作。

## 2026-09-28 本地主对比统计阶段进展

已实现并通过 8 项测试的配对簇 bootstrap，按 28+29 合同在原始 npz 上重算主对比并核对冻结验收向量。400 control 的 D=+30.75 pp，95% CI [25.82,35.64]；排除 14 条重叠 control 为 +31.09 pp，[26.08,36.13]。α=0 top-1 残差全零，NLL 残差非零。状态 `E1_PRIMARY_STATISTICS_PARTIAL_NOT_DEV_COMPLETE`，不是最终科学判定。

详见项目 `alpha_mechanism_local_20260923/31_E1_PRIMARY_READOUT_750474_20260928.md` 和 [结构化阶段报告](primary-analysis-750474-f4ao34wq/REPORT.json)。剩余完整次要分析、clean/负对照、来源汇总及最终门继续本地执行；无网络或 GPU 操作。

## 最新：750474 完成，原始产物已收集且本地离线验收通过

2026-09-28 JST：复用现有 SSH 进行只读查询和收集，没有重连、重新提交、再次修正资源或放行。Slurm 回读 `COMPLETED / 0:0`，2026-09-27 22:52:07–23:50:06，Elapsed=00:57:59，节点 spcc-a100g06。终态作业不再出现在 squeue，不将其 Invalid job id 提示误判为执行失败。

远端完成标记为 `E1_EXECUTION_VERIFIED_ANALYSIS_PENDING`。收集 87 个文件，逐文件核对传输前后 SHA 与大小，并使用冻结 v3 包的 `offline-check` 在本地重新验收：`E1_ARCHIVE_VERIFIED_NOT_SCIENCE_QUALIFIED`、verified=true，38400 次预测、60 组数组记录。未修改冻结包、历史合同或远端产物。

证据：[收集结果](collected-750474-_rosoog2/RESULT.json)、[传输清单及 sacct](collected-750474-_rosoog2/COLLECTION_MANIFEST.json)、[本地离线验收](collected-750474-_rosoog2/offline-check.json)。收集实现位于项目 `alpha_mechanism_local_20260923/collect_e1_750474.py`；失败不自动重试。

当前出口：**执行与归档验收完成，统计分析待完成**。下一批按 28+29 号合同实现并测试配对说话人簇 bootstrap、D/c1/r0、NLL、clean/负对照及排除 19 条重叠样本的敏感性分析。不得标记 E1_DEV_COMPLETE，不得称为独立测试或已证实机制。

## 最新：750474 已获授权放行，回读为 PENDING（非 held）

2026-09-27 用户明确批准放行，记录于项目 `docs/superpowers/evidence/e1-contract-signoff-20260927/RELEASE_750474.json`。放行前再次通过整包 check、receipt、修正记录、资源和 spool 校验；唯一一次 `scontrol release 750474` 返回 0。未改变资源、未重提、未重试。

紧接回读：JobState=PENDING，Reason=None，Priority=16701（不再 JobHeldUser）；ReqTRES 仍为 cpu=8、mem=64G、node=1、billing=8、gres/gpu:nvidia_a100=1；TimeLimit=03:00:00，RunTime=00:00:00。该时点尚未分配节点，不把放行成功写成已经开始推理。

证据：[放行结果](release-750474/RESULT.json)、[完整检查与调度回读](release-750474/remote.jsonl)。下一步仅查询同一作业的运行/终态，再收集并独立验收；失败不自动重提。以下 held 记录为历史状态。

## 最新：750474 已唯一一次修正为 A100，仍 held

2026-09-27 用户单独批准该作业唯一一次 typed GRES 修正（项目 `docs/superpowers/evidence/e1-contract-signoff-20260927/GRES_CORRECTION_750474.json`）。修正前再次核对 JobHeldUser、Priority=0、RunTime=0、目标路径及预算；执行一次 `scontrol update JobId=750474 Gres=gpu:nvidia_a100:1`，返回 0。

回读确认 ReqTRES=`cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1`，TresPerNode=`gres/gpu:nvidia_a100:1`，TimeLimit=03:00:00。仍为 PENDING / JobHeldUser / Priority=0 / RunTime=00:00:00。spool 与冻结 runner 逐字节相同。**未放行、未重提，不得再次执行 GRES 修正脚本。**

证据：[修正结果](gres-correction-750474/RESULT.json)、[前后资源与命令原文](gres-correction-750474/remote.jsonl)。下一门：用户批准放行现有作业 750474；不得把本次修正授权视为放行授权。

## 最新：作业 750474 已单次 held 提交，GPU 类型不符，未放行

2026-09-27 22:24:39 JST 提交；用户批准 1 A100 / 8 CPU / 64 GiB / 180 分钟上限的单次 held 提交，见项目 `docs/superpowers/evidence/e1-contract-signoff-20260927/GPU_HELD_AUTHORIZATION.json`。receipt 状态 SUBMITTED_HELD_NOT_RELEASED。

只读检查：JobState=PENDING、Reason=JobHeldUser、Priority=0、RunTime=00:00:00、Requeue=0、Restarts=0。CPU=8、内存=64G、时限=03:00:00 均匹配；spool SHA `5f7fa068f203555c6f6ac42764ef70869b7b2488e341b4b25191d5a5adb32341` 与冻结 runner 逐字节一致。

**阻止放行的资源差异**：INTENT 申请 `--gres=gpu:nvidia_a100:1`，scontrol 与 sacct 实际 ReqTRES 为 `gres/gpu:h100-20c=1`。不将 TresPerNode 的泛型 gpu:1 当作类型正确。保持 held，不运行 E1。没有 scontrol update、release、cancel 或再次 sbatch。

下一步须用户单独批准：仅对现有作业 750474 做唯一一次 typed GRES 修正为 `gpu:nvidia_a100:1`，回读仍保持 held；放行仍另行批准。不新建作业。

完整原始证据：[remote.jsonl](held-submission-20260927/remote.jsonl)、[结果](held-submission-20260927/RESULT.json)。含提交回执、五份远端 journal 内容及 SHA、scontrol/squeue/sacct、spool 原文与匹配结果。历史“未提交”状态以下保留。

## 当前状态：发布与原生只读检查通过

完成时间：2026-09-27T12:31:28.824076+00:00（日本时间 21:31）。用户在终端恢复共享连接后续接原授权，没有自动重连。

- 初始远端只读检查确认 `audattn_e1` 基目录尚不存在；未发生上传。之后按批准范围创建基目录及唯一新目标 `/home/s2510040/audattn_e1/e1_20260927_v3`。
- 发布前队列为空。27 个文件经传输数据哈希、落盘逐字节复核后，从 staging 发布到 `package`；没有覆盖旧目录。
- 远端 `check` 与导入后的 `post-check` 均为 E1_PACKAGE_BYTES_AND_INPUTS_PASS，release SHA `558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3`。
- `source-check` 为 NATIVE_SOURCE_ONLY_IMPORT_PASS：96 个快照文件核验，24 个既有 pyc 保留且采用 hash_checked_source_only；checkpoint_loaded=false、cuda_initialized=false、jobs_submitted=0。
- 证据：[RESULT.json](publish-pyp4gob6/RESULT.json)、[原生导入输出](publish-pyp4gob6/source-check.stdout)、[整包后检查](publish-pyp4gob6/post-check.stdout)。结果 SHA `56e0bad96e94bc42cb39956d22d6f6db097c06786e188f87bcd572e26905452a`；原生输出 SHA `54c7f2c9f06f6196ebd1d613ecc20d2405b00405a26948dce67c3ce22cc8796a`。
- 本轮没有加载 checkpoint、初始化 CUDA、调用 sbatch 或 GPU 提交。只读预检不证明实际 E1 GPU forward 成功。

下一门：候选 1 A100 / 8 CPU / 64 GiB / 180 分钟（3 GPU 小时上限）的单次 held 提交需要用户明确批准；放行仍另行批准。不要重跑发布脚本；目标已存在会拒绝覆盖。本轮 LOCAL_CHECK.json 的 pending 列表是旧本地工具的静态提示，当前授权状态以外部 SIGNOFF 与本台账为准，不把其过时的“待发布授权”当作未批准。

## 历史：等待认证

2026-09-27：用户确认 28+29 号统计口径（δ=2 个百分点）并授权 v3 独立目录发布、哈希核验、原生只读 source-check，不包括 checkpoint 加载或 GPU 提交。确认记录：[SIGNOFF.json](../../docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json)。

确认记录项目相对路径：`docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json`；导师意见未记录。冻结包和合同原字节不变。

本地包与四份依据文件重新检查通过。随后只读检查发现 `/Users/gigi/发表/超算/.hakusan-control/master.sock` 不存在。因此状态 **REMOTE_PUBLICATION_BLOCKED_SSH_AUTH_REQUIRED**：未发起 SSH、未连接网络、未创建远端目录、未上传、未运行 source-check、未提交作业。没有自动重连或重试。

请用户在 Mac 终端运行已有 `2026-09-10-hakusan-connect.sh`，出现 HAKUSAN_AUTHENTICATED=PASS 和 HAKUSAN_SHARED_CONNECTION=PASS 后再继续。原发布授权保留，无需重新批准相同范围；GPU 仍未授权。
