# P05b 四布局真实运行:Job 726428 执行台账与离线复算结果

2026-09-18 12:31 JST 批准,2026-09-19 04:00 JST 前完成收集与复算。对应总计划 P05 剩余覆盖(尾批与同伴重排)。状态 `P05B_OFFLINE_RECOMPUTED_NOT_QUALIFIED`:数值已记录并独立复算,**不是数值资格通过,不授权全量。**

## 1. 执行台账(只记实际发生的事)

| 步骤 | 时间(JST) | 结果 / 证据 |
| --- | --- | --- |
| 冻结前整包检查 | 09-18 12:31 | 本地 69+33=102 项测试通过 |
| 用户预算审批 | 12:31 | [AUTHORIZATION.json](AUTHORIZATION.json) SHA `dfbf0098…4955`;1 作业/1 A100/8 CPU/64 GiB/30 分钟/四顺序进程/单次提交/无自动重试或资源修正 |
| 本地冻结 | 12:32 | release SHA `dc0c81d8d1f07b2e8fbfbfb35fa1fdaf57ba19181caf88d944925d5d8d66059a`,[frozen/](frozen/) |
| 远端只读预检 | 12:33 | Slurm 25.05.5、GPU-1A 10 节点 A100 可见、基线 725677 COMPLETED/0:0、队列空、根目录不存在;`preflight-d7sgijgd` |
| 发布 | 12:34 | `PUBLISHED_NO_JOB`;`publish-d1pc2tv_` |
| test-only | 12:34 | `TEST_ONLY_PASS_NO_JOB`;`test-only-iu7ekv1o` |
| 单次 held 提交 | 12:35 | **Job 726428**,`SUBMITTED_HELD_NOT_RELEASED`;`submit-7hp89pjg` |
| 第一次 release 被拒 | 12:35 | 远端 held 核验发现 ReqTRES=`gres/gpu:h100-20c=1`、TresPerNode=`gres/gpu:1`(站点插件改写 typed A100,历史第 5 次);远端未写 RELEASE_INTENT、未执行 release;`release-ndzyd5f5`,原本地 intent 改名保留于 `frozen/LOCAL_release_INTENT.refused-attempt1-ndzyd5f5.json` |
| 用户单独授权 GPU 修正 | 12:4x | 仅同一 held 作业、唯一一次、预算不变、不重提不取消 |
| 唯一一次 GPU 字段修正 | 12:4x | `scontrol update JobId=726428 TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1` rc=0;回读 ReqTRES=`gres/gpu:nvidia_a100=1`,仍 held、RunTime 0;[correct-gpu-726428/](correct-gpu-726428/) |
| 独立核验后单次放行 | 12:45 | `RELEASE_REQUEST_ACCEPTED_QUERY_NEXT`;`release-vo797k29` |
| 排队 | 12:45 起 | Reason=Resources,20 张 A100 全忙;调度预估一度推迟到 22:32 |
| 终态 | 09-19 前 | `726428|COMPLETED|0:0|00:05:16|spcc-a100g04`;COMPLETE.json SHA `07001c952817b44c9a3ed9a6d16d690a993e3af0d0ab3c2db002ce6df4b93d3a`;`status-6ra7odmt` |
| 只读收集 | 04:00 | `COLLECTED_NOT_QUALIFIED`,全部文件逐项 size/SHA 校验;`collect-5ocfg78n` |
| 统一离线复算 | 04:0x | [offline-review-726428/REPORT.json](offline-review-726428/REPORT.json) SHA `3cc13490…84b4`;`paired_nll.csv` 987 行 SHA `720cb6c1…ab58` |

本批共 1 次 sbatch、1 次 scontrol update、1 次 scontrol release;无重提、无取消、无追加作业。环境:spcc-a100g04,Python 3.11.5 / torch 2.1.1+cu118 / CUDA 11.8,与 724808、725677 一致。

四个模型进程独立、顺序、PID 互异(3409553 / 3410029 / 3410289 / 3410513),各自 rc=0:bridge16 142.9 s(含首次冷启动)、cold1 63.6 s、peers16 54.0 s、tail17 48.6 s;每阶段独立验收 ≤1 s。

## 2. 数值结果(全部由 logits 离线重算,987 条配对记录,0 次预测翻转)

### 2.1 固定配置可复现性:逐位一致

| 对照 | 与什么比 | 结果 |
| --- | --- | --- |
| bridge16 | 725677 repeat16 | 三模型、全部条件 logits **逐位一致**;旧 1e-6 canary PASS |
| cold1 | 725677 batch1 | 三模型、全部条件 logits **逐位一致**;旧 1e-6 canary PASS |

跨作业、跨节点(g04 vs g02)、跨发布包,固定配置结果完全可复现。这把"实现不稳定"从解释空间中排除。

### 2.2 同伴重排(peers16 vs bridge16,32 条)

- **correct cue:三模型 32 条 logits 逐位一致,差值恰为 0。** 改变同伴与批内位置对正确 cue 路径没有任何影响,即**不存在批内串扰**。
- 7 条 control(distractor/shuffled/silent)有差异,但数值与 batch16/1 的差异几乎相同(如 valbest33/silent 1.029e-3 vs 1.030e-3,formal40/silent 8.678e-4 完全相同),说明重排只是改变了 control 子集实际落入的批形状;这是批形状浮点效应,不是串扰。
- peers16 vs cold1 的 correct 差值与 cold1 vs bridge16 完全一致(3.240e-4 / 6.828e-4 / 7.133e-4),与上一条自洽。

### 2.3 尾批(tail17 vs bridge16,17 条身份交集)

- 5 条 control 逐位一致。
- correct cue 17 条最大 NLL 差:author 1.278e-4、formal40 5.9e-5、valbest33 4.1e-5,均值 ~1e-6 量级;来源是末条 O[31] 从完整批变为单条尾批。

### 2.4 跨批形状敏感性汇总(所有非逐位对照)

| 量 | 范围 |
| --- | --- |
| NLL 绝对差最大值 | 4.1e-5 ~ 1.03e-3(最大在 valbest33/silent) |
| logits 绝对差最大值 | ≤ 2.13e-3 |
| 预测翻转 | 0 / 987 |
| formal40−author 配对 NLL 差距的变化 | ≤ 4.4e-5(差距本身 0.348,32 条 correct) |
| 旧 1e-6 canary | 所有跨批形状对照均 DIFF(永久保留,不改阈值) |

### 2.5 必须在 P06 面对的一个事实

最小 top1−top2 margin 低至 **0.003**(formal40/distractor)与 0.011(author/correct),而批形状扰动量级为 1e-3。本批 32/17 条上没有翻转,但在 10k 全量中接近平局的 trial 出现个别翻转是可能的;P06 政策必须明确如何报告这一点(例如按 margin 分层报告翻转率上界),不能以"本批 0 翻转"外推"全量 0 翻转"。

## 3. 限制

- 仍是原 32 条 / 17 条子集的重复对照,不是独立追加样本,不是 10k。
- 研究身份不变:`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
- 本批不决定数值接受政策,不测成本,不授权全量。

## 4. 总计划下一项

P05b 覆盖已完成。按既定出口:P06 数值政策(可据本报告 §2 起草,用户审定)→ 额外确认集与 P07 约 256 条成本测量(建议合并为一个作业)→ 全量预算审批 → P08。

站点插件改写 typed A100 的问题已连续 5 次重现;建议向集群管理员确认可保留 typed GRES 的提交方式,否则后续每个作业都需要一次单独授权的同作业修正。
