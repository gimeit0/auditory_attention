# 三项本地任务交付（2026-09-23）

## 2026-09-28 当前优先任务：0.01低α加密评估

最新本地交付：**提交并发检查已修正并冻结v3，497项全目录回归通过，六个旧包214个清单文件保持不变。** 新增明确的独立作业审阅、实时路径/脚本/spool核验及提交前二次检查；不按audattn名称一律拦截，也不宣称账户并发额度。v3未上传、未连接远端、无新GPU审批或作业。见[48号修正与后续执行计划](48_FINE_ALPHA_V3_SUBMISSION_QUEUE_FIX_20260928.md)及[v3验收](release_fine_alpha_20260928_candidate_v3/LOCAL_ACCEPTANCE.md)。下一批为获准后的v3上传/哈希/原生预检和并发只读审阅，再单独申请GPU预算；下方v2及旧版本状态保留。

最新（19:07 JST）：**v2原生只读导入预检通过，无新GPU作业。** 96快照文件、受审回调源码导入、前后包检查通过；未加载checkpoint或初始化CUDA，13项预检回归通过。见[预检回执](release_fine_alpha_20260928_candidate_v2/source-check-v2-once/RESULT.json)及[台账下一门](release_fine_alpha_20260928_candidate_v2/REMOTE_PROGRESS.md)。提前确认冻结提交器仍有旧名称队列限制；若需并发提交，必须先修正并重新冻结，不能直接动当前包或把上传通过视为GPU授权。以下上传/待导入状态为历史时点。

最新（18:33 JST）：**v2已上传并通过41文件哈希及远端整包核验，尚未提交新GPU作业。** 已确认754073是独立新种子训练目录中的数值预检，上传入口改为验证该已审阅作业的精确身份/路径/脚本SHA，未知或变化仍停止；20项上传回归通过，冻结包未改。见[v2最新台账](release_fine_alpha_20260928_candidate_v2/REMOTE_PROGRESS.md)和[成功回执](release_fine_alpha_20260928_candidate_v2/upload-v2-reviewed-job-once/RESULT.json)。下一门为v2原生只读导入预检；GPU预算、提交及放行仍需新授权。以下停止和未部署文字为历史时点。

16:53 JST上传增量：用户已批准v2独立目录上传及哈希/包检查。单次调用在远端写入前因队列中`754073 / audattn_numcheck_seed20260928 / RUNNING`停止；**v2仍未部署，未提交新作业**，没有取消该作业或自动重试。名称匹配保护不等于已证实文件冲突。见[v2上传台账](release_fine_alpha_20260928_candidate_v2/REMOTE_PROGRESS.md)及[原始回执](release_fine_alpha_20260928_candidate_v2/upload-v2-once/RESULT.json)。

当前更正：753729于14:15:24 JST以`FAILED / 1:0`结束。A块输出126份数组后因环境版本字段类型验收失败，B/C未运行，不能称扫描完成。已收回并核验147份文件，未重投。用户批准修正后，[独立v2候选](release_fine_alpha_20260928_candidate_v2/LOCAL_ACCEPTANCE.md)已完成：453项本地测试及原生CPU类型回归通过，历史5个包174个文件不变。v2尚未部署、无新GPU授权/作业。详见[47号失败复盘与修正](47_FINE_ALPHA_PROVENANCE_FIX_20260928.md)。以下运行/挂起信息均为历史快照，不覆盖本条。

历史快照（12:50 JST）：`FINE_ALPHA_RUNNING_MONITORED`。用户已独立批准放行753729并跟进至终态验收；已唯一一次放行，12:27:03在spcc-a100g02开始运行。A100/8CPU/64GiB/6小时不变，该时点运行23:24、A观察24个npz、无attempt失败标记，尚未验收。

本地PID59368每5分钟只读监测，终态单次收集并离线验收，异常/断线停止，不重连或重投。[放行证据](release_fine_alpha_20260928_candidate_v1/release-753729/RESULT.json)、[监测入口](release_fine_alpha_20260928_candidate_v1/watch-753729/START.json)、[当前台账](release_fine_alpha_20260928_candidate_v1/REMOTE_PROGRESS.md)。本机需持续运行联网；计算作业本身已交由Slurm运行。目前没有新科学结论。

用户要求先做任务2，暂不重训第二个模型。见[46号整批执行计划](46_FINE_ALPHA_001_EXECUTION_PLAN_20260928.md)：现有formal40、原E1输入/批次、54点、194,400条科学预测；加端点/桥接/冷重复共219,600条。新的`fine_alpha_*`实现不改E1/E2冻结包。单A100最多6小时预算及单次held提交已单独获批；上传/包检查/原生导入通过，753729已挂起提交，未释放或运行。下方无作业状态为较早时点，本地测试/导入预检不代表新科学结果。

最新（12:20 JST）：`FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD`。**753729**已按单独授权唯一一次修正为A100，8CPU/64GiB/6小时不变；仍`PENDING / JobHeldUser`、Priority0、运行0秒。包、前后spool及原始审批/提交/STOPPED记录均未变。[修正授权](release_fine_alpha_20260928_candidate_v1/GRES_CORRECTION_753729_AUTHORIZATION.json)、[修正证据](release_fine_alpha_20260928_candidate_v1/gres-correction-753729/RESULT.json)、[当前台账](release_fine_alpha_20260928_candidate_v1/REMOTE_PROGRESS.md)。下一门是正式放行审批，尚未运行，不重复提交或修正。

此前12:00 JST为`FINE_ALPHA_SUBMITTED_HELD_RESOURCE_MISMATCH`：站点将A100申请改为`h100-20c`，提交器按设计停止并保留挂起作业；见[本批预算/提交授权](release_fine_alpha_20260928_candidate_v1/GPU_HELD_AUTHORIZATION.json)、[提交证据](release_fine_alpha_20260928_candidate_v1/held-submission-20260928/RESULT.json)。这一历史状态已由上方单独授权修正记录更新，原始证据不改写。

本地准备入口：[prepare_fine_alpha_local.py](prepare_fine_alpha_local.py)。只做回归、旧冻结包哈希复核、新包构建及隔离入口检查，拒绝覆盖已有输出，不包含网络/调度动作。

本轮本地准备已完成：[候选验收](release_fine_alpha_20260928_candidate_v1/LOCAL_ACCEPTANCE.md)，398项回归（48项新增）通过；新包40个文件检查通过，旧包134个清单文件保持匹配。本地准备结束时状态为`FINE_ALPHA_LOCAL_CANDIDATE_VERIFIED_NOT_GPU_AUTHORIZED`；上传后的当前状态见下文，尚无新扫描结果。

后续用户批准“上传”：初次因共享SSH socket缺失而等待；新增6项本地上传安全测试通过。用户恢复连接后，2026-09-28 11:45 JST已单次上传41个文件（40个清单文件加RELEASE.json），远端逐文件哈希及包检查通过。该时点`FINE_ALPHA_UPLOADED_AND_HASH_VERIFIED_NO_JOB`，见[发布台账](release_fine_alpha_20260928_candidate_v1/REMOTE_PROGRESS.md)与[上传结果](release_fine_alpha_20260928_candidate_v1/upload-d2tzvudd/RESULT.json)。该时点尚未授权的原生检查已按下一条新授权完成；GPU预算、提交与释放仍未授权。

最新：用户回复“开始吧”后，11:50 JST原生只读预检通过，当前`FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB`。96个快照文件核验及哈希锁定源码导入通过，远端包前后哈希一致，未加载checkpoint/初始化CUDA。新增6项预检驱动本地测试通过；[真实预检证据](release_fine_alpha_20260928_candidate_v1/source-check-mmwdh22h/RESULT.json)四步返回码均0，无自动重连或重试。下一门为6GPU小时预算和单次held提交审批；无作业号、无新扫描结果。

2026-09-28 最新：用户已接受 E1 750474 的 P5 已披露记录偏差，不重跑GPU。当前 [E1_DELIVERED_WITH_ACCEPTED_P5_DEVIATION](37_E1_ACCEPTED_DELIVERY_750474_20260928.md)。原合同和验收矩阵不追溯改成全项PASS；科学身份仍为探索性复用验证bank。以下等待决定的文字保留为历史状态。

## 2026-09-28 当前交付入口

E1 750474 已正常完成（57:59），原始产物离线验收、主/次要统计与错误结构独立核验通过。见[统一交付报告](release_e1_20260927_v3/delivery-750474-3wjt5pax/REPORT.md)、[完整指标 CSV](release_e1_20260927_v3/delivery-750474-3wjt5pax/ALL_METRICS.csv)、[验收矩阵](release_e1_20260927_v3/delivery-750474-3wjt5pax/COVERAGE.json)。28 项测试、13 文件哈希清单通过。

当前 `E1_ANALYSIS_DELIVERED_CONTRACT_INCOMPLETE`，唯一未关闭来源项 P5：UTC 仅覆盖加载后执行窗口，不是完整子进程生命周期。统计结果已交付，但未赋科学标签、未标 E1_DEV_COMPLETE；需明确偏差处置，不自动重跑 GPU。以下旧“尚无结果/待放行”保留为历史记录。

## 2026-09-27 本轮修正后的当前入口

最新：750474 已按明确授权唯一一次放行，紧接回读为 PENDING / Reason=None / Priority=16701，A100 资源保持正确，未分配节点。尚无 E1 数值结果，下一步查询此作业并在终态收集验收。见 [放行证据](release_e1_20260927_v3/release-750474/RESULT.json)；下方“待放行”为历史状态。

最新：750474 已按单独授权唯一一次修正为 nvidia_a100，8 CPU/64 GiB/3 小时及 spool 复核通过，仍 JobHeldUser、运行时间 0；等待放行授权。详见 [v3 台账](release_e1_20260927_v3/REMOTE_PROGRESS.md)。下方 GPU 类型不符为修正前历史状态。

最新调度状态：E1 v3 作业 **750474** 已单次 held 提交，资源审查发现 ReqTRES 被改为 `gpu:h100-20c:1`，不符申请 A100；保持 JobHeldUser，运行时间 0，未修改资源、未放行、未重提。详见 [台账](release_e1_20260927_v3/REMOTE_PROGRESS.md)；下一门是该作业唯一一次 GRES 修正的单独授权。

最新远端结果（21:31 JST）：[v3 发布与只读检查](release_e1_20260927_v3/REMOTE_PROGRESS.md)已通过，27 文件、整包 check/post-check、96 快照文件原生 source-check 均成功；checkpoint_loaded=false、cuda_initialized=false、jobs_submitted=0。下面 SSH 阻塞记录属于此前时点。下一步 GPU 预算及单次 held 提交仍需明确授权，尚无 E1 作业号。

最新确认：用户已确认 28+29 号统计口径（δ=2 个百分点）并批准 v3 上传/哈希核验/原生只读检查；记录见 [SIGNOFF.json](../docs/superpowers/evidence/e1-contract-signoff-20260927/SIGNOFF.json)。导师意见未记录，GPU 未授权。发布目前因共享 SSH socket 不存在暂停，见 [v3 发布台账](release_e1_20260927_v3/REMOTE_PROGRESS.md)；未上传或提交。下方“待用户确认”是此前时点，不覆盖本条。

续接交接：[30 号整批执行与审批单](30_E1_V3_EXECUTION_HANDOFF_20260927.md)已整理；[本地交接检查](release_e1_20260927_v3/HANDOFF_CHECK.json)通过，v3 包与四份依据文档哈希匹配，新增 4 项交接负例测试通过。未代签统计合同、未连接远端、未批准 GPU。完整 bootstrap/报告仍待本地实现，配对算术归档不等于统计完成。

E1 当前候选为 [v3 本地验收](release_e1_20260927_v3/LOCAL_ACCEPTANCE.md)（release `558fa3fb953704b3fbf52952c9e474ef9824dead2e4c0eb2adaaa21a561dffd3`），替代 v2 待提交候选；v1/v2 保留不改。[29 号合同修正](29_E1_CONTRACT_V3_RESIDUAL_CORRECTION_20260927.md)覆盖 28 号的跨批恒零主张：保留完整 D、实测 α=0 残差，不强制置零。229 项回归及 38400 条三进程合成演练通过，未加载真实 checkpoint、未初始化 CUDA、未上传或提交。统计签署和 GPU 预算仍待批准。

R0 [新版失败停止核验](../docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927-v2/README.md)：七类核验通过，当前文本 384/384；旧错误文本非零退出，停止流程测试通过。以下记录及 SHA 表为历史版本快照，不覆盖本段当前入口。

1. [已有结果与证据缺口](01_RESULTS_AND_GAPS.md)：完成本地摘要，23项原结果包哈希通过；沿用既有图件，不改原结果。
2. [α实验合同草案](02_ALPHA_CONTRACT_DRAFT.md)：定义公式、输入/分析、端点、负对照及预算门槛；不是最终确认性预注册。
3. [α增益原型](alpha_gain.py)及[测试](test_alpha_gain.py)：11项CPU测试通过，PyTorch 2.12.1。提取并验证本地受审源码中的真实gain类，但只测模块及八模块合成链，未加载完整checkpoint。

复现命令（无超算）：

```bash
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -v
```

通过项：α=1在CPU float32/64的原gain输出逐位相等（含mask）；α=0原样旁路且cue无影响；三个中间α公式；参数/输入/RNG不变；state_dict键兼容；非法α、additive和源码变化拒绝；输入数值梯度检查；α=1参数梯度与原类相同；α=0梯度旁路；八gain合成链旁路一致。

限制：α是固定标量，没有对α求导；α=0时cue/gain参数梯度是None而非零tensor，若用于E3训练需明确优化器weight decay/状态处理，不能仅凭推理端点推断训练日程等价。模型state_dict不含α，必须外存实验合同。生产模块安装、完整cue路径、训练中间α参数梯度、真实GPU桥接、负对照实现尚未完成；不得称“α实验完成”或“可直接提交”。

## 本轮增量：架构接入与三个负对照

上述11项是第一轮历史记录。现已增加哈希锁定架构加载器、临时安装/恢复适配器和12项架构/对照测试，总计 **23项本地CPU测试通过**。详见[本轮验收与限制](03_ARCHITECTURE_AND_CONTROLS.md)。上文“负对照实现尚未完成”已由本轮本地原型覆盖，但生产接入、真实checkpoint及GPU验收仍未完成。

下一安全本地步骤：扩展池化/实际尺寸配置覆盖，并准备新实验合同序列化、α条件与输出关联的离线回归。之后才能申请生产E0桥接；不能仅凭23项测试直接提交。原工程与冻结源码未改，SSH/上传/对齐/GPU全部保持暂停。

## 第二轮增量：配置与合同

上述下一步骤的本地部分已完成：新增Hann池化数值测试、生产配置meta形状检查和离线合同/输出绑定回归，现共 **30项测试通过**。见[范围及E0后续入口](04_LOCAL_COVERAGE_AND_E0_NEXT.md)。生产配置仅验证形状，未做真实权重数值计算；合同仍限合成用途。下一步编制E0候选规格并接入既有生产记录机制，不自动执行远端任务。

## E0小批提案

[真实模型E0验收方案](05_E0_REAL_MODEL_ACCEPTANCE_PLAN.md)已编制：formal40、96条历史完整批、6048条预测；拟申请1 A100×30分钟，尚未批准。样本提案及本地归档核查脚本已提供，实际批匹配和计数通过。下一步是实现单模型生产候选和独立验收，不直接运行旧提交入口。

## E0执行包第一步

[本地进度](06_E0_LOCAL_PACKAGE_PROGRESS.md)：96条布局已物化；288条历史参考提取、NLL复算及错配拒绝测试通过；共36项本地测试通过。6048条仅完成身份清单演练，完整生产执行/归档尚未接通，不能标E0_PACKAGE_LOCAL_PASS。下一步为单模型生产适配和独立bypass。

## 已加载模型适配接口

[接口与旁路进度](07_LOADED_MODEL_ADAPTER_PROGRESS.md)：接入历史predict/状态检查函数，独立bypass及12项接口测试通过，现共48项测试。测试使用合成外层/预处理，不加载checkpoint；真实strict-load worker、观察器与完整归档仍待实现。下一步为本地阶段协调与失败归档。

## 合成完整归档演练

[21轮归档记录](08_SYNTHETIC_ARCHIVE_PROGRESS.md)：6048条合成输出完整写入/独立重读、失败与超时处理完成，共56项测试通过。保留约19.5MB演练产物；A/B是单worker内逻辑标签，不是生产冷重复。下一步实现有界gain观察器及生产阶段接线，远端继续暂停。

## 八处gain观察器与模型forward阶段

2026-09-25远端最新：[v2发布与原生检查通过](release_20260925_v2/REMOTE_PROGRESS.md)。v2上传/全包SHA核验完成，原生source-check通过（96快照文件、24旧pyc保留）；checkpoint_loaded=false、cuda_initialized=false、jobs_submitted=0。下一步单次held提交/资源审查，尚无作业号。

2026-09-25最新：[缓存导入隔离修正](14_SOURCE_ONLY_IMPORT_FIX_20260925.md)。v2只编译固定SHA源码，不读/写旧pyc；114项本地测试通过，独立包已冻结，v1保持不变。待远端部署与source-check，尚无作业号。

2026-09-24最新：[生产候选包已完成本地检查](13_PRODUCTION_PACKAGE_READY_20260924.md)。三项缺口（统一生产入口、便携历史参考、单次held提交）已补齐；104项测试及冻结包隔离校验通过。未部署/提交，下一步远端预检与独立目录发布。

2026-09-24：[提交前检查](12_SUBMISSION_READINESS_20260924.md)。用户要求启动E0，实际尚未提交（执行包不完整）；已补两独立模型进程6048条完整CPU演练，不能当作真实checkpoint验收。

最新续接：[原生加载/音频与进程监督](11_NATIVE_LOADING_AND_PROCESS_PROGRESS.md)。86项本地测试通过；真实加载/音频/两个完整模型worker仍未验收，未部署、未提交。

最新续接：[G5与worker桥接接口](10_G5_AND_WORKER_BRIDGE_PROGRESS.md)，78项本地测试通过；新增672项固定特征独立公式检查及历史桥接错配拒绝接口。真实checkpoint桥接未运行，strict-load/音频provider/独立进程整包仍待接通。

[接入报告](09_GAIN_OBSERVER_STAGE_INTEGRATION.md)：定点摘要观察器及已加载模型阶段driver已完成本地接入；67项测试通过，另保存21轮6048条缩小随机模型forward归档，144观察事件，与无观察器输出逐位一致。未加载formal40，预处理仍为合成，真实G5/历史桥接/两进程与GPU验收尚待完成。

## 2026-09-26 至 2026-09-27 增量

### E0 v2 生产运行与验收（作业 746603，2026-09-26）

- v2 包（release SHA `abcaa1af63d019e5e4d8701a8522e47f1e280cc8d477f21b2e64225485fd2f17`）单次 held 提交，SubmitTime 02:27:46；ReqTRES 被站点改写为 gres/gpu:h100-20c=1（第 9 次记录），用户单独授权后唯一一次 scontrol update 改为 gpu:nvidia_a100:1；02:31:55 放行，02:32:01 开始，02:43:17 结束，COMPLETED 0:0，Elapsed 00:11:16，spcc-a100g04。
- E0_COMPLETE.json 状态 E0_ENDPOINT_PASS，scientific_alpha_result=false；6048 条预测（21 pass × 288，不是独立样本）；A/B 双进程 PID 1039926/1040834，十个共享 pass 逐位一致；G5 672 项检查；观察器 144 事件；本地 production_e0.verify 复核 E0_ARTIFACTS_VERIFIED（exit 0）。
- 证据：[REMOTE_PROGRESS.md](release_20260925_v2/REMOTE_PROGRESS.md)、[collect-746603-SlcKgK/state/](release_20260925_v2/collect-746603-SlcKgK/state/)、归档报告 [REPORT.md](../docs/superpowers/evidence/e0-production-20260926/REPORT.md)（执行台账、G0–G7、成本表、来源字段缺口）、[SHA256SUMS.txt](../docs/superpowers/evidence/e0-production-20260926/SHA256SUMS.txt)（45 文件）、[offline-verify-20260927/](../docs/superpowers/evidence/e0-production-20260926/offline-verify-20260927/)。
- E0 是工程验收，不是 α 机制成立的证据；研究身份 REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。

### E0 科学读数（2026-09-27，事后描述性）

[26 号备忘](26_E0_SCIENTIFIC_READOUT_746603_20260927.md) 与 [readout/](../docs/superpowers/evidence/e0-production-20260926/readout/)（E0_READOUT.json、e0_readout_table.csv），脚本 [e0_readout_746603.py](e0_readout_746603.py)，测试 [test_e0_readout.py](test_e0_readout.py)。一句描述性读数（96 条试点，无区间）：α≤0.5 时 correct 准确率 0 至 6/96、NLL 46 至 632；.75 与 1 两点的准确率高于 shuffled 且 |logit| 量级与 original 同阶；E1 网格是否修订待用户/导师决定。状态 E0_READOUT_DESCRIPTIVE_NOT_INFERENTIAL：不做统计推断、不改 E0/E1 包、不做决定。

### E1 文档索引（15 至 25 号）与 package_ready 三分说法

- [15](15_E1_DEVELOPMENT_PLAN_20260926.md) E1 开发子集、基线与 α 扫描实施提案（E1_PLAN_READY_NOT_FROZEN_NOT_AUTHORIZED；预测数 36,200 为历史估计，冻结值 38,400）
- [16](16_E1_SELECTION_REVIEW_20260926.md) 本地选择与 clean 来源检查（E1_METADATA_CANDIDATE_NOT_INPUTS_FROZEN）
- [17](17_E1_ANCHOR_DECODE_REVIEW_20260926.md) 冻结 anchor 及本地解码验收（E1_PINNED_ANCHOR_AND_LOCAL_DECODE_PASS）
- [18](18_E1_CLEAN_INPUT_PROGRESS_20260926.md) clean 正确 cue 路径与冻结进度（E1_CLEAN_INPUT_LOCAL_TEST_PASS_REMOTE_HASH_BLOCKED）
- [19](19_E1_REMOTE_AUDIO_AND_DATA_FREEZE_20260926.md) 远端音频核验与数据身份冻结（E1_DATA_IDENTITIES_FROZEN_PRODUCTION_NOT_READY）
- [20](20_E1_NATIVE_COMPATIBILITY_FAILURE_20260926.md) 原生 CPU 检查失败与本地 v2 候选
- [21](21_E1_NATIVE_CLEAN_V2_PASS_20260926.md) clean v2 原生真实音频检查通过（单次授权探针）
- [22](22_E1_EXECUTION_BODY_20260926.md) 执行主体与数组验收第一阶段（E1_LOADED_BODY_AND_ARRAY_VERIFIER_LOCAL_PASS；矩阵 38,400 条 / 60 记录）
- [23](23_E1_SESSION_ARCHIVE_LOCAL_20260926.md) 加载接口、进程与归档接入（E1_SESSION_ARCHIVE_LOCAL_TESTS_PASS）
- [24](24_E1_PORTABLE_INPUT_GATE_20260926.md) 便携输入入口与归档明细核验（E1_PORTABLE_INPUT_GATE_LOCAL_PASS）
- [25](25_E1_LOCAL_RELEASE_BATCH_PLAN_20260926.md) 本地生产包整批交付计划（E1_LOCAL_RELEASE_CANDIDATE_PASS）
- [release_e1_20260926_v1/package_ready](release_e1_20260926_v1/package_ready/)（[LOCAL_ACCEPTANCE.md](release_e1_20260926_v1/LOCAL_ACCEPTANCE.md)）：release SHA `ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176`，entry `4bd2f1d8…`，runner `5fa0901b…`，合同 `f3fcacec…`。三分说法：① 数据身份冻结（E1_DATA_FREEZE_20260926_v1.json，SHA `6c4df571…`）与执行包冻结成立；② 统计合同/科学口径未审定（RELEASE.json scientific_status=DEVELOPMENT_PROTOCOL_STATISTICS_APPROVAL_PENDING）；③ GPU 预算未批准（候选 1 A100 / 8 CPU / 64 GiB / 180 分钟），E1_INPUTS_FROZEN 不能提前填写（15 号文 §6 第 3 条）。未上传、未提交。同目录 package、package_final 是中间候选，不部署。

### 复现命令更新（2026-09-27）

```bash
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py' -q
```

214 项通过（此前 205 → 213 → 214，26.351 秒为 213 项时的用时；新增 test_e0_readout.py 9 项）。读数脚本：`/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/e0_readout_746603.py --out <新目录>`，拒绝覆盖已有输出。

### R0 交付核对状态（2026-09-27）

R0：程序化最终核对完成（[R0_DELIVERY_VERIFICATION.md](../docs/superpowers/evidence/p10-delivery-20260919/R0_DELIVERY_VERIFICATION.md)），R0_FIGURES_PRESENT 保持，R0_DELIVERY_VERIFIED 未达成：345 项文本数字中 4 项措辞不一致待用户决定是否修改交付文本。

2026-09-27 更正后复核：4 处措辞已在 P10_delivery.md §8 与 FIGURES.md 更正记录中修正；核对脚本归档到 [r0-verification-20260927/](../docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927/)（读取实际文本、绑定 17 个文件哈希、附旧文本灵敏度测试），重跑七类全部通过（文本数字 384/384），**R0_DELIVERY_VERIFIED 达成**。同日新建 [27 号 E1 修订决策稿](27_E1_REVISION_DECISION_DRAFT_20260927.md)：干预公式与网格为两个独立决定，披露 E0/E1 19 条 trial 重叠（5 条 clean），E1 任何修订后都须重新冻结并单独批准。

### 2026-09-27 新增文件（SHA256 与字节数由本次写入前实际计算）

| 文件 | SHA256 | 字节 |
| --- | --- | ---: |
| [e0_readout_746603.py](e0_readout_746603.py) | `cf27eafa1799633a272fee9e8564cc9625dbed349fc9d0481f99b9e641dc1841` | 14776 |
| [test_e0_readout.py](test_e0_readout.py) | `3ac47f646789f064e8fe539982abaf5dfa12446639debe008b3630c1de9bec2c` | 10501 |
| [26_E0_SCIENTIFIC_READOUT_746603_20260927.md](26_E0_SCIENTIFIC_READOUT_746603_20260927.md) | `10f33a654f79647152f4f40936703d02c3a3c0028f119d0700cb00a1016d383d` | 16301 |
| [readout/E0_READOUT.json](../docs/superpowers/evidence/e0-production-20260926/readout/E0_READOUT.json) | `8ea0b79d70d35981fc6e769400381e03d1773c372de348e4fedb965af74a9ebb` | 80003 |
| [readout/e0_readout_table.csv](../docs/superpowers/evidence/e0-production-20260926/readout/e0_readout_table.csv) | `5ec6ff77795416880b97e4d336d810e42fa2505f7de1e13ccbc96efc935be20b` | 12321 |
| [e0-production-20260926/REPORT.md](../docs/superpowers/evidence/e0-production-20260926/REPORT.md) | `2f463621243b0687940897cb28fb6ab91bf2d9d7b7aa549280833bc7941bc58a` | 21690 |
| [e0-production-20260926/SHA256SUMS.txt](../docs/superpowers/evidence/e0-production-20260926/SHA256SUMS.txt) | `4a113d6536cb8bd487d1a48d0b792747561a600ddc84b5efd2377a1dab632b3a` | 7546 |
| [offline-verify-20260927/offline_verify_746603.py](../docs/superpowers/evidence/e0-production-20260926/offline-verify-20260927/offline_verify_746603.py) | `5c96698934cd20194b5f8c8d28fa8db9c04b6263abcd8d9e3e178f5ce03dd000` | 9449 |
| [offline-verify-20260927/verify_stdout.json](../docs/superpowers/evidence/e0-production-20260926/offline-verify-20260927/verify_stdout.json) | `19fa6c1db75c1af12a111471eb3ee0fd3d7c1fc0c055c39d5559d5a6e943788b` | 7920 |
| [offline-verify-20260927/verify_stderr.log](../docs/superpowers/evidence/e0-production-20260926/offline-verify-20260927/verify_stderr.log) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 0 |
| [offline-verify-20260927/RUN.txt](../docs/superpowers/evidence/e0-production-20260926/offline-verify-20260927/RUN.txt) | `72c30838e113a935f6a33c68c1bc8c695f31df2ee22ade9210eb18b4c469a503` | 505 |
| [p10-delivery-20260919/R0_DELIVERY_VERIFICATION.md](../docs/superpowers/evidence/p10-delivery-20260919/R0_DELIVERY_VERIFICATION.md) | `91be274d138c49bcfff303a6c498e5d5862264676faab4b47a4d43f03aa144d0` | 29110 |
| [27_E1_REVISION_DECISION_DRAFT_20260927.md](27_E1_REVISION_DECISION_DRAFT_20260927.md) | `bc90afd78cebb4968a1e92bb6dab486a4d19cbd8782e9b7408d8925d45cd5811` | 33423 |
| [28_E1_STATISTICS_CONTRACT_V2_20260927.md](28_E1_STATISTICS_CONTRACT_V2_20260927.md) | `d9dd0eca574ba529c0b0596ba3ed26f557917222b1fa965112e21105d91a7c5f` | 27690 |
| [release_e1_20260927_v2/package_ready/RELEASE.json](release_e1_20260927_v2/package_ready/RELEASE.json) | `964a00837fb0df1e0bd13e0da09dbe3c6c584289b70f229f506685b084318e99` | 18049 |
| [release_e1_20260927_v2/LOCAL_ACCEPTANCE.md](release_e1_20260927_v2/LOCAL_ACCEPTANCE.md) | `4c9a2b50a41268f88feb7d4ccffb371e248e27db81fe333529037c114a50c076` | 5067 |
| [p10-delivery-20260919/P10_delivery.md（2026-09-27 更正）](../docs/superpowers/evidence/p10-delivery-20260919/P10_delivery.md) | `d85dae243e020868dbfc5fe6dd5969aca744b138a2652d9245671c2cd9e52aa6` | 9216 |
| [figures/FIGURES.md（2026-09-27 更正）](../docs/superpowers/evidence/p10-delivery-20260919/figures/FIGURES.md) | `6a963a59eb5a5a2a4c689c6b0346c9cd138048347c18d35dadce8aacfab3e26c` | 5511 |
| [r0-verification-20260927/check2_numbers.py](../docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927/check2_numbers.py) | `36b1cc707741df83db4c97621b6ac6f5e156fb36e7281d3ca1bd5de2aefa75b1` | 45574 |
| [r0-verification-20260927/SHA256SUMS_delivery.txt](../docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927/SHA256SUMS_delivery.txt) | `4486286eb6a5add2405273d23f66587463b365d7fb0a31d1d6fe0d76ac30b879` | 9343 |

远端状态：上文各段“远端暂停”为 9/23 至 9/25 的时点状态；9/24 至 9/26 用户按每个动作单独授权使用 SSH 完成发布、预检、提交、修正、放行与收集；2026-09-27 核实本地无活动 SSH master（`.hakusan-control/master.sock` 不存在），恢复需用户终端认证。今日无远端动作、无 GPU、未修改任何冻结包。

## 2026-09-27 晚增量：E1 决定 A 至 E 与 v2 重新冻结

用户按 [27 号决策稿](27_E1_REVISION_DECISION_DRAFT_20260927.md) §9 的推荐定下五项决定：A 保留公式；B 网格 {0, .5, .75, .875, 1}；C 保留并披露 19 条 E0/E1 重叠 trial（5 条 clean）并附敏感性版本；D 不做探针；E 预算候选上限不变。[28 号统计合同 v2](28_E1_STATISTICS_CONTRACT_V2_20260927.md) 成文（签署记录外置，δ 待签署人决定，见其 §4.4 保留意见）；[15 号文](15_E1_DEVELOPMENT_PLAN_20260926.md) 追加 §8 修订段。

源码改动：`loaded_model_adapter.py` 与 `gain_formula_check.py` 增加 alpha_875；`e1_execution.py` 改 ALPHAS、execution_spec 记录网格修订、pass 映射、试点暴露与必需来源字段，execute_loaded 记录每 pass 起止时间、显存峰值与 RSS；`e1_worker_archive.py` 写入 environment 并由 verify_archive 验收来源字段；`e1_inputs.py`/`e1_entry.py`/`run_e1.sbatch` 改为 v2 标识与远端路径；`build_e1_package.py` 写入 decision_record 并绑定 26/27/28 号文 SHA。复现命令同上，现共 **220 项测试通过**。

[v2 包](release_e1_20260927_v2/package_ready/) release SHA `964a00837fb0df1e0bd13e0da09dbe3c6c584289b70f229f506685b084318e99`，check 通过，三进程合成演练 38400 条通过，见 [v2 LOCAL_ACCEPTANCE](release_e1_20260927_v2/LOCAL_ACCEPTANCE.md)。v1 `package_ready`（`ebe4dfb9…`）作废为历史，保留不覆盖。未上传、未提交、无远端动作。
