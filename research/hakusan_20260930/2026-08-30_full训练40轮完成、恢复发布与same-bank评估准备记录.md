# full训练40轮完成、恢复发布与same-bank评估准备记录

## 最新进展：2026-09-08 诊断 v3 本地候选

全量训练已完成，最终三模型 same-bank 对比仍未完成。用户提供的诊断 v2
远端审计报 verified loader objects 校验失败，未进入冻结或提交。已本地复现：
同文件两次读取使用不同相对路径基准。按用户要求先记录，再创建独立 v3
候选统一基准，保留严格身份和路径验证；v2 七文件哈希保持不变。

本地独立进程测试：数值 344/344、提交/模拟集成 66/66、新专项 6/6，共
416 项通过。Ruff、Bash 语法与候选八文件哈希通过。合并 discover 的测试
模块重载冲突另有记录；这些是 CPU/临时文件测试，不是真实 GPU 成功证据。
候选尚未独立复查、上传、冻结或提交。详情见
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v3-loader-root-repair.md`。

- 首次记录日期：2026-08-30（JST）
- 阶段总览更新：2026-09-08（JST）；远端状态依据已归档作业证据，本次未实时查询 HAKUSAN
- 承接文档：[2026-08-23_full训练数据角色、SNR分层基线与40轮协议说明.md](./2026-08-23_full训练数据角色、SNR分层基线与40轮协议说明.md)
- RUN_ID：`fullpilot4_accum9_20260815_181000`
- 当前训练状态：40/40 轮在逻辑和数值证据上均已完成，最终状态已受控恢复发布
- 当前评估状态：v4 已部署并运行 smoke；Job `646900` 因 batch16 与 batch1 的 NLL 一致性检查失败而停止。独立数值诊断工具已推进至任务 8b，单次提交／队列检查／只读状态查询已有本地实现；完整模拟提交到五子进程的集成、操作 README 与整包验收仍待完成。尚无真实 A100 诊断结果，本轮三模型完整 10k 对比尚未完成
- 科学角色：`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`

## 0. 先看这里：最终目标、当前位置与下一步（2026-09-08）

最终目标没有改变：用同一份冻结的 10,000 条音频场景，比较自己训练的模型与作者提供的 checkpoint。最近的工作是在修复、验证这个比较所需的评估程序，不是在重新训练模型，也还没有得到“自己的模型比作者好或差”的正式结果。

完整路线与最终交付标准见[自训练模型与作者 checkpoint 对比：完整计划（2026-09-06）](./2026-09-06_自训练模型与作者checkpoint对比_完整计划.md)。原数值诊断的 12 项任务只是其中一个子计划，不是本次模型比较的最终交付。

本节是滚动阶段总览；第 1–16 节保留早期记录的历史时态，第 17 节按取得证据的顺序追加。旧段落中的“尚未上传”“等待 Job640258”等不再代表当前状态。

### 0.1 最后究竟比较哪几个模型

| 模型 | 文件 | 在最终比较中的位置 |
|---|---|---|
| 自己的固定 40 轮模型 `formal40` | `formal-final.ckpt` | 主结果：按事先固定的 40 轮训练协议完成 |
| 自己的验证集最优模型 `valbest33` | `epoch=33-step=59024.ckpt` | 补充结果：由训练内部 validation 选择，不替代主结果 |
| 作者模型 `author_external` | `epoch=1-step=24679-v1.ckpt` | 外部系统参考：同一 bank 上比较，但训练条件和部分音频处理不同 |

这里的“同一 bank”保证比较同一组场景，并不等于所有训练条件完全匹配。该 bank 已用于早期 pilot 的继续训练决策，所以本轮结果属于复用 validation/pilot bank 的审计，不能包装成独立测试集成绩或严格任务匹配的公平排名。

### 0.2 已经做完什么，目前卡在哪里

| 阶段 | 截至本次记录的状态 | 对最终比较的意义 |
|---|---|---|
| 全量训练与最终 checkpoint | 已完成 40/40；`global_step=69440`；完成状态已恢复发布并核验 | 已有可用的自训练模型，不需要因当前评估错误重新训练 |
| 比较输入准备 | 三个 checkpoint、配置、label map、冻结 10k bank 已审计；v4 manifest 已冻结 | 明确到底用哪些模型、哪些场景进行比较 |
| 小规模 smoke 验收 | v4 Job `646900` 已执行两轮各 32 条推理，但一致性检查失败 | 推理已经跑通；评估结果的数值一致性尚未验收 |
| 当前数值诊断 | 本地工具任务 1–4 已完成相应复审，任务 5–8b 为实现候选；提交工具 62/62、数值核心 338/338 通过 | 生产入口、runner、单次提交与状态查询已本地接通；完整模拟链路、README 与整包验收仍待完成；尚无真实 GPU 数值根因 |
| 本轮三模型完整 10k 比较 | 尚未完成 | 尚不能报告 formal40、valbest33 与作者模型的新完整对比表或优劣结论 |

关键失败证据是 2026-09-01 的 v4 Job `646900`：在 A100 节点 `spcc-a100g02` 上运行 1 分 54 秒后，以 `FAILED 2:0` 结束；原文错误为：

```text
Smoke batch-size canary differs: formal40_nll, max_abs=0.0077362060546875
```

含义是：相同 32 条场景，按每批 16 条和每批 1 条运行时，`formal40` 的 NLL（负对数似然损失）差异超过原 `1e-6` 检查阈值。它不是模型准确率，也不能单凭这条错误认定模型训练失败、checkpoint 损坏，或已经确认混合精度就是根因。此作业没有发布 `SMOKE_PASS.json`，也未进入完整 10k audit。

早期 Job `584990` 的 10k pilot 结果确实存在；它是早期 pilot 的证据，不是现在这次“40 轮最终模型对作者 checkpoint”的完成结果。训练日志中的 validation 指标同样不能冒充本轮三模型对比指标。

最近看到的 129、151、175、198、226、251 项通过，是诊断代码的本地回归测试数量，不是超算实验次数、训练轮数或模型成绩。最近的保存层、指纹、导入上下文、worker 和子进程启动工作，是为了准确保留两轮输出、排除输入变化并定位分歧；它们没有重新训练模型，也没有使 smoke 自动变为成功。

### 0.3 下一步如何回到最终比较

单个 worker、固定子进程启动、工件来源绑定、两轮参考等价与四格顺序／汇总已本地集成；任务 6c 接通外层身份核验、共享锁、输入 PRE/POST 与中断／终态内核，任务 6d 补齐终态清单及只读结果重验，任务 6e 接通生产执行入口、父子身份与缓存检查，任务 7 已有 Slurm runner，任务 8b 已接通耐久提交、队列检查和只读状态查询。接下来完成操作 README、完整模拟提交到五子进程的集成及整包验收。当前包仍不能直接作为完整诊断作业提交。

之后的第一个科学里程碑，是取得同一 32 条场景、仅针对 `formal40` 的真实 A100 诊断证据。根据结果决定是否以及如何修复评估路径；不能为了通过而直接调宽阈值或跳过检查。诊断完成本身也不等于三模型比较完成。

预定后续顺序为：完成并验收诊断工具 → 32 条 GPU 诊断 → 基于证据处理分歧 → smoke 通过并复核 → 三模型完整 10k same-bank audit → 汇总准确率、NLL、SNR／干扰条件分层和配对比较。

当前不需要用户重新训练、重新 freeze v4 或重复提交旧 smoke。已有 v2/v3/v4 失败证据继续保留；若后续需要改变冻结代码或协议，应使用新的版本与明确审批。最近这次续作推进了本地诊断代码并更新说明，没有查询或提交超算作业，也没有同步到项目仓库的“全量任务”镜像目录。

具体实现状态与测试范围见[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)；Job `646900` 的完整失败证据见第 17.11 节，最新提交／查询工具进度见第 17.26 节。

## 1. 历史文档范围与结论摘要（保留 2026-08-31 版本）

本节保留当时已知情况；当前阶段以第 0 节及第 17 节最新执行追记为准。

本文是 2026-08-23 阶段记录的事后续篇。旧文记录时 Job `614647` 仍在运行，只确认到 `epoch 20`，即总第 21/40 轮。本文不修改旧文的历史时态，而是补齐此后发生的训练分段、40 轮收尾、训练后 finalizer 误判、最终状态恢复发布，以及三模型 same-bank 评估的 v1、v2、v3 工程过程。

截至本文最后一次取证，可以确认：

1. full 训练确实完成了 `epoch 0..39`，最终 `global_step=69440`；
2. 最终 AMP 账本闭合为 `69440 = 69414 successful + 26 overflow`；
3. Job `628071` 的 Slurm 历史状态是 `FAILED 1:0`，但失败发生在训练完成后的 finalizer，不是训练少跑、模型数值失败或 checkpoint 损坏；
4. `formal-final.ckpt` 已冻结为固定 40 轮协议的唯一 primary checkpoint；
5. `epoch=33-step=59024.ckpt` 由内部 validation 选择，只是 secondary checkpoint；
6. 受控恢复工具已原子发布 `COMPLETE_RECOVERY.json` 和 `COMPLETE`，并再次得到 `ALREADY_PUBLISHED_AND_VERIFIED`；
7. 新评估使用的是已经参与 Job `584990` pilot GO 的冻结 10k validation/pilot bank，只能作 same-bank audit，不能称为独立 final test；
8. v1、v2 与 v3 均在产生可解释模型结果前 fail closed；v3 Job642803 暴露了冻结历史 evaluator 的延迟 `selftrain` 导入缺口。该缺口已在全新 v4 本地包中用回归测试复现并最小修复，但 v4 尚未上传或执行集群 smoke，因此仍没有完整 10k 三模型结果。

## 2. 从旧记录到40轮完成的分段时间线

每轮固定包含：

```text
examples/scenes per epoch       = 499,968
train microbatches per epoch    = 15,624
optimizer attempts per epoch    = 1,736
effective batch size            = 288
configured epochs               = 40
expected final global_step      = 69,440
```

四段 lineage 已由恢复审计逐轮核对：

| Job | 阶段 | 完整贡献的 epoch | 输入 step | 输出 step | 已核验说明 |
|---|---|---:|---:|---:|---|
| `575142` | pilot4/new | `0..3` | — | `6944` | 产生 `pilot4-final.ckpt`；Job584990 evaluator 随后给出 GO 判定，再经人工 review 与 release checker 发布 `PILOT4_GO.json` |
| `587802` | full/resume | `4..16` | `6944` | `29512` | 在下一轮 epoch17 约 33% 处触达四天 walltime；partial epoch 不计入完成量 |
| `614647` | full/resume | `17..29` | `29512` | `52080` | 8月23日旧文只看到 epoch20；后续 completion-recovery audit 证明完整贡献至 epoch29 |
| `628071` | full/resume | `30..39` | `52080` | `69440` | fit 达到 `max_epochs=40`，随后在训练后 finalizer 误判处退出 |

算术闭合为：

```text
40 × 1,736 optimizer attempts = 69,440
40 × 15,624 microbatches      = 624,960
40 × 499,968 scene presentations
                              = 19,998,720
```

这里的 `scene presentations` 是在线训练中呈现的场景数，不表示存在约两千万个互不重复的落盘音频文件。

四段对应的冻结作业日志 SHA 为：

```text
Job575142  5cfcdb0558a9be4b81960be9a03d6e5491cf9ea4bd0bd81e365bdc9d4ba443d7
Job587802  7fff02e0c8d23fd71c77fc11b2c9c1125f4211a57f0b522561ec1c5765b64ea0
Job614647  1db5cbaf43595d8aed4587de24c36368ec56d79a9ac7fc9c78ebcd341cc5959d
Job628071  6052eb4fe9b6dc78ed41e0887d8028159671443f59a7ab3a7f9d24f57123adb6
```

8 月 25 日还准备并审查了安全自动续投 controller 方案，用于限制精确 run、checkpoint 边界和作业唯一性。现有本地材料没有保存 controller 自身的远端 Job ID/终态，因此本文只把它记录为操作方案与审计证据，不把它写成已经执行的科学步骤。

### 2.1 Job 587802

2026-08-20 的中期记录当时只确认到 `epoch 12`。完整日志 lineage 后来证明 Job `587802` 从 `pilot4-final.ckpt` 的 step `6944` 继续，完整完成 `epoch 4..16`，输出 step `29512`。它随后在 partial epoch17 约 33% 处触达 walltime，Slurm `TIMEOUT` 是分段调度结果，不是数值故障；partial epoch17 没有计入完成量，下一段从 epoch16 后的完整 checkpoint 边界继续。

相关证据：

```text
pilot4-final.ckpt SHA256
c61af82c1ce32071616a81f992bcf25edfb06476e6c3a87542103cf3eb2a28ba

epoch16 后 last.ckpt SHA256
11f79ce63d01a0c5f47c3d17d12442e64548503b181047573b314c228e8a9c44

Job587802 log SHA256
7fff02e0c8d23fd71c77fc11b2c9c1125f4211a57f0b522561ec1c5765b64ea0
```

### 2.2 Job 614647

Job `614647` 于 2026-08-21 15:51:44 JST 在 `spcc-a100g03` 从 step `29512` 的完整边界恢复。旧文在 8 月 23 日只确认到 `epoch 20`：当时累计 21/40 轮，`train_acc=0.734`、`val_acc=0.424`、`val_loss=2.86`，AMP 累计为 `36456=36444+12`。

后续恢复审计严格确认该段完整贡献 `epoch 17..29`，输出 step `52080`，再由 Job `628071` 从这个完整边界继续。现有本地说明材料没有逐字保存 Job614647 的最终 `sacct` 行，因此本文不根据 lineage 单独推断其 Slurm 终态；可确认的是完整 epoch 范围、step 边界和后续 resume 链没有断裂。

```text
Job614647 log SHA256
1db5cbaf43595d8aed4587de24c36368ec56d79a9ac7fc9c78ebcd341cc5959d
```

### 2.3 Job 628071

Job `628071` 从 step `52080` 继续，完整贡献 `epoch 30..39`。日志中存在：

```text
AMP epoch summary: epoch=39
`Trainer.fit` stopped: `max_epochs=40` reached.
```

最终内部 validation 为：

```text
epoch 39 val_acc  = 0.434
epoch 39 val_loss = 2.990
```

全 40 行内部 validation 中，唯一最大 logged `val_acc` 位于 epoch index 33，即第 34 轮：

```text
epoch index       = 33
global_step       = 59024
logged val_acc    = 0.453
logged val_loss   = 2.89
callback score    = 0.4525758922100067
AMP               = 59024 = 59001 + 23
```

这解释了为什么保留 epoch33 checkpoint 作 validation-selected secondary，但不改变 formal40 的 primary 角色。

```text
Job628071 log SHA256
6052eb4fe9b6dc78ed41e0887d8028159671443f59a7ab3a7f9d24f57123adb6
```

## 3. 为什么 Slurm FAILED 不等于训练失败

Job `628071` 的历史 Slurm 状态必须如实保留为：

```text
State    = FAILED
ExitCode = 1:0
```

但 checkpoint、日志和 AMP 证据同时表明训练已经结束：

```text
checkpoint epoch                         = 40
checkpoint global_step                   = 69440
fit_loop.epoch_progress.current.ready    = 40
fit_loop.epoch_progress.current.started  = 40
fit_loop.epoch_progress.current.processed= 40
fit_loop.epoch_progress.current.completed= 40
fit_loop.epoch_progress.total.ready      = 40
fit_loop.epoch_progress.total.started    = 40
fit_loop.epoch_progress.total.processed  = 40
fit_loop.epoch_progress.total.completed  = 38
```

PyTorch Lightning 2.1.1 在两次从 epoch-end `last.ckpt` 恢复后，使 raw `total.completed` 比真实完成量落后 2；`current.*`、`total.ready/started/processed`、四份冻结作业日志中的 40 条逐轮 summary、最终 step 和 AMP 账本都闭合到 40。原 finalizer 只依据滞后的 `total.completed=38`，因此在 fit 完成后误判并退出。

准确表述是：

> 40 轮训练在逻辑和数值证据上完整结束；Job 628071 随后因训练后 finalizer 对 Lightning 恢复计数的误判而以 FAILED 1:0 退出。

不能写成“只训练了 38 轮”，也不能把 Job 状态改称 Slurm `COMPLETED`。

## 4. 受控恢复最终发布

2026-08-28 创建了项目外 one-off 恢复工具，只恢复最终状态发布：不重训、不修改 checkpoint、不修改 run snapshot，也不改写历史 Slurm 状态。

```text
recovery tool SHA256
f7b682f61920d21d181a4721a32e87d4dc216d07df3d476392ee2de41f967959
```

恢复流程先以 `--check-only` 重验四份作业日志、`epoch 0..39`、checkpoint、snapshot/config、AMP 和 Job628071 的精确失败历史，得到 `CHECK_PASS`；随后以 no-overwrite 原子顺序先发布 sidecar，再发布兼容原 schema 的 COMPLETE：

| 产物 | size | SHA256 | 含义 |
|---|---:|---|---|
| `full/checkpoints/formal-final.ckpt` | 753,735,232 | `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` | 固定40轮协议终点 |
| `state/COMPLETE_RECOVERY.json` | 57,855 | `cec479dba062dc1e95e61bf6a2fb6f45e03a586ac695a797f0d6c4b646b622cd` | 事故、原始计数与完整证据 sidecar |
| `state/COMPLETE` | 1,138 | `fba9660a7cb7ca74ed2b2cbceb971f99ca6ea959ff32a7bb2ed8d9181a4e65c0` | canonical completion marker |

首次发布返回 `PUBLISHED`；第二次相同命令没有覆盖任何字节，只做全量复核并返回：

```text
ALREADY_PUBLISHED_AND_VERIFIED
```

run provenance 仍为：

```text
source semantic SHA256
496cf41c8abedb4673a83a4ec148bc74ea92e6c059ea4bc998610a0db1ab9038

full.yaml SHA256
3efe0f455d7c902c772f5d1a6fb30cf0a4f13e46f0b72024ff5bfa7b9f3229b4
```

## 5. 三个模型的冻结角色

| model_id | 精确角色 | checkpoint 身份 | 允许的解释 |
|---|---|---|---|
| `formal40` | `primary_fixed_40_epoch` | `formal-final.ckpt`; epoch40; step69440; SHA `2c2a0f...c9ff` | 预先固定40轮协议的 primary；不是“结果最好才选中” |
| `valbest33` | `validation_selected_secondary` | `epoch=33-step=59024.ckpt`; size 753,738,240; SHA `853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14` | 由内部 validation 选出的次要、带选择偏差的描述性对照 |
| `author_external` | `external_system_reference` | `epoch=1-step=24679-v1.ckpt`; epoch1; step24679; SHA `6fb23dde8455ef353a00d9bf676bf00f337961ac7c6d45f35f2c45a15cd88ed0` | 系统级外部参照；不是同训练任务、同预算、同 preprocessing 的公平消融 |

作者模型另绑定：

```text
author config SHA256
9878adc94e8d3e7088948fe363067c14d5c5535c5d2404aa51746a1686955439

800-word label map SHA256
a7c30da14b78288806ebc2fb39fe7f8cfc77ee60dc3a743fecf18fcfe1f3b9e5
```

full 与 author 的网络架构和 800 类 label map 兼容，但 full config 开启 `per_example_leveling`，作者 config 使用其原生 global transform；作者训练分布、训练数据与当前 validation speakers 的重叠情况也不能假定等同。因此即使 future paired CI 排除 0，也只能报告 same-bank system-level delta，不能据此生成无条件的“模型优劣排名”。

### 5.1 严格加载与推理一致性门禁

三个 checkpoint 的冻结结构均为 61 个 state-dict keys：58 个 model keys 和 3 个 cochleagram buffers，共 63,271,260 个 tensor elements。formal40 和 valbest33 必须 exact-key、exact-shape、exact-dtype、`strict=True` 加载；author_external 先尝试 exact strict load，只有编译 wrapper 名称确实不同时，才允许唯一、确定、无碰撞且全覆盖的 `model._orig_mod.` ↔ `model.` uniform rewrite。任何 blanket `strict=False`、missing/unexpected key、随机初始化残留或小于 100% trainable-parameter coverage 都必须拒绝。

登录节点 v3 `check-only` 已通过三模型 strict structural load 和 100% trainable coverage。真正推理还要满足：

- 同一 trial 的 raw scene 和 raw cue 只构造一次，再供三个模型消费；
- regenerated scene SHA 必须逐 trial 精确等于 Job584990 历史 scene hash；
- 三个模型各走冻结的原生 preprocessing，不能看到结果后换 config；
- author 的 global RMS transform 必须逐 trial 单独执行后再 stack，避免 batch composition 改变输入电平；
- smoke 要把 requested batch 16 与 batch 1 的全部结果复跑比较，最大绝对数值差必须不大于 `1e-6`，identity 和 NaN pattern 必须完全一致；
- 推理前后参数及 buffers 的 version 必须不变。

完整 audit 的统计协议也已冻结：bootstrap seed 为 `20260829`，重复 `10,000` 次，以 `target_speaker` 为 cluster；三模型和所有 pair 在同一 stratum 使用同一套 speaker draws。pair 必须先逐 trial 对齐再求差，不能分别 bootstrap 三模型后相减，也不能用 row bootstrap。smoke 是稀疏工程 canary，不运行科学 bootstrap。

## 6. 冻结10k bank的身份与科学边界

旧冻结 bank 已重新以原 snapshot builder 的 `--validate-only` 验证：

```text
trials          = 10,000
mixed           = 9,000
clean           = 1,000
control subset  = 2,000
SNR×distractor cells = 20
target labels   = 738
target speakers = 795
target gender   = 5,000 female + 5,000 male
```

关键冻结身份：

| 证据 | SHA256 |
|---|---|
| `frozen_bank.tsv` | `d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091` |
| bank metadata | `fb0e79ab4614c3bd866c35d1f764d968aa2f59e5222a740b72ed935fe4f62941` |
| `PILOT4_BANK_FROZEN.json` | `790fdbb14b32f28d9ff358202b00ba69d67f9b9e29f12383c6762d9d053f8680` |
| Job584990 `per_trial_results.csv` | `5046ed08c2adf006167e64bd987e2833d45a9c28163f37482bf2b25f5d07cf6d` |
| Job584990 `PILOT4_EVAL.json` | `7fc915c7bbf0e4774cc74ae01b0144e3d990c22fa8776ae23a454473cd3fc5eb` |
| historical evaluator | `29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b` |

这个 bank 来自 validation speakers，并且其 Job584990 结果已参与 `PILOT4_GO`。所以后续无论运行 formal40、valbest33 还是 author_external，都必须带下面的精确角色：

```text
REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST
```

它可以回答：

- 同一 bank 上的配对描述性差值；
- 五档 SNR、1--4 名干扰者及 20 个联合 cells 的表现；
- correct/shuffled/silent/distractor cue controls；
- target-speaker cluster bootstrap 下的 audit-bank 不确定性；
- formal40 与 validation-selected epoch33 的描述性差异。

它不能回答：

- 未经选择偏差的 independent final-test 泛化性能；
- 根据 10k 结果重新选择 primary checkpoint；
- 作者模型与当前模型在完全匹配训练数据、预算和 preprocessing 下的公平排名。

当前没有新的、从未参与训练、pilot、调参或 checkpoint 选择的独立 final-test 结果。

### 6.1 anchor与speaker split取证

评估前还重新盘点了现有 anchor 与 speaker split：

| 文件 | size | SHA256 |
|---|---:|---|
| `train_anchors.tsv.gz` | 4,055,981 | `9294a24ea824296322eb99ace07e557a712d4460a3b49b4b0c6f91a130395a82` |
| `validation_anchors.tsv.gz` | 283,918 | `b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65` |
| `eval_speakers.txt` | 268,449 | `01bcc9f4b19c1c717238180952051ae1cc8d597fa91f98ff0b95b6966a4e504c` |
| `split_audit.json` | 2,193 | `88d7f6062d928acad7e0dedf3de9435b887cf134ca117718a53c5c550904c7d5` |

`eval_speakers.txt` 有 2,081 行，split audit 记录：

```text
all_eval_speakers                    = 2081
train_eval_speaker_disjoint          = true
validation_eval_speaker_disjoint     = true
```

当前受检 artifacts 中只有 train 与 validation anchors；对 `*test*anchor*` 的 inventory 没有发现已配置的独立 test anchor artifact。这与“尚无 independent final-test bank”的结论一致，不能把 validation bank 仅因 speaker-disjoint 就改称 final test。

## 7. same-bank evaluator v1：发现SNR浮点往返边界

v1 使用项目外新根：

```text
$HOME/audattn_external_eval/same_bank_2026-08-29
```

```text
v1 evaluator SHA256 = 221096ef601e63ddc5e0a14833b687c810d36095b2c6bc2d66f380ab90bf0040
v1 runner SHA256    = 3d35b416b4ece19459742d74e83cb3268d732cf25006c3f539878b5407affa21
```

其 `audit-inputs` 在任何 freeze 或 GPU 作业前 fail closed：

```text
ERROR: Job584990/bank identity mismatch: snr_db
```

冻结 bank TSV 与 Job584990 historical per-trial CSV 的 SHA 均正确。HAKUSAN 的 pandas 2.1.3 / NumPy 1.26.0 只读诊断表明，这是 TSV→DataFrame→CSV→DataFrame 的末位浮点表示差异：

```text
mixed rows                  = 9000
bit-exact unequal rows      = 56
maximum absolute difference = 8.881784197001252e-16
differences > 1e-12         = 0
mixed values finite         = true
clean values both NaN       = true
```

Job584990 的冻结 evaluator 原本就使用 `rtol=0, atol=1e-12`。因此 v1 的 bit-exact guard 比历史发布合同更严；这不是 bank、场景、混音或 SNR cell 漂移。v1 没有 freeze、没有 GPU 推理，也没有科学结果，根目录仅作失败证据保留。

## 8. same-bank evaluator v2：修复ULP后暴露跨节点NFS身份问题

v2 在 historical CSV 和新结果 CSV reload 边界统一使用：

```text
rtol = 0
atol = 1e-12
```

同时继续要求 mixed 两边有限且位于 `[-10,10]`、clean 两边均为 NaN、所有离散身份精确一致、逐 trial scene hash 精确一致。没有把容差用于场景音频 hash 或预测值。

v2 通过 `AUDIT_PASS`、一次性 freeze 和登录节点 `check-only`；冻结 manifest SHA 为：

```text
b8af6507fe3f820a1e595883235f3a3f108338e07f43e50adabe219274f8a09a
```

v2 重新绑定的 10,000 条 historical scene-hash vector SHA 为 `c16aa921ef4c6431dffca3382ce930185087e91d06d558275cdd359bd79e159a`。它的 evaluation lock 仍是 size 0、SHA `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` 的空文件；这也成为 v3 改用带 nonce 非空 canonical lock 的直接原因之一。

但 v2 smoke Job `637966` 的真实历史为：

```text
State     = FAILED
ExitCode  = 2:0
Elapsed   = 00:00:08
Node      = spcc-a100g03
```

runner trust bootstrap 和环境取证已经通过：

```text
GPU       = NVIDIA A100-PCIE-40GB
CUDA      = 11.8
cuDNN     = 8700
torch     = 2.1.1+cu118
Python    = 3.11.5
```

随后在 attempt 创建和模型推理之前退出：

```text
ERROR: Frozen evaluation lock device changed
```

根因是共享 NFS 上同一个文件在登录节点与计算节点可呈现不同的 client-local `st_dev`；v2 错误地把跨节点 `st_dev/st_ino` 当成持久身份锚。这个失败不是 GPU、checkpoint、bank、模型加载、CUDA 或 SSH 断线造成的，也没有产生可解释的预测结果。

v2 取证：

| 证据 | SHA256 |
|---|---|
| evaluator | `8a6d9ed8a082c6a59973064408338490cb430ec3e3d70779d2e28fb8e73ab9fa` |
| runner / submitted runner | `fe28d02c695b36608fcdd2d2e5796c6bbb985471850866aa355a6a327efb960e` |
| Job637966 log | `f98220239dd61542b557c536d213715a60338b158d1225ae530ed7ca5c5b4683` |
| environment JSON | `3f0687eae80701cb95b222f6e90e3f4213cf340037fad0b0bd12c41da126356b` |

v1、v2 根均永久只读保留：不删除、不覆盖、不 retry、不重新 freeze、不复用，也不把其中的文件复制或硬链接进后续根。

## 9. v3：NFS可移植身份策略

v3 只修改文件系统身份验证语义，不修改模型角色、bank、SNR 合同、scene hash、指标或科学解释。

```text
protocol_id
= fullpilot4_same_bank_audit_20260829_v3_nfs_portable_identity_v1

filesystem_identity_policy
= cross_invocation_path_size_sha_exact__dev_inode_diagnostic
```

跨 invocation、跨节点的权威身份变为：

```text
canonical absolute path
+ basename
+ regular-file / no parent or leaf symlink
+ exact size
+ exact SHA256
```

`device/inode` 仍会记录为诊断，但不再作为跨节点发布门。与此同时，同一进程内的 fd↔path、hash 前后、directory-fd、flock namespace 和原子发布仍严格比较 `st_dev/st_ino`，没有放宽 TOCTOU 防护。

`state/evaluation.lock` 改为非空 canonical JSON，并绑定一个由 `secrets.token_hex(32)` 产生的 256-bit nonce，从而检测常见的误删后重建空 lock；它不被宣传为抵抗同 UID 恶意复制的秘密。

v3 最终本地冻结字节：

| 文件 | SHA256 |
|---|---|
| evaluator | `f6a2b39779c299ba0b9826d6a9f75d66d994abbf404fa0143dce1daa020fc3d6` |
| evaluator tests | `2f9418216266785f39293edb46e9adf25132a543e19cc25ec30f46009a83a81d` |
| runner | `37403ee0867d8f75f9f66923cf75031f215cec3263b0f0b1bda5c93f914707ba` |
| runner tests | `a2a158542f019f3a9a7ccc3f2d0c525678e419434aad3f813a8e8685fc1c6332` |
| README | `968aa4cb2cadb143f7677fbd3520c58646e8a745882fa817656db3486930e9c9` |

本地联合回归为 `68/68 PASS`；`py_compile`、ruff `--no-cache`、`bash -n`、5 个子命令 help、unsafe/stale/cache 扫描均通过。

## 10. v3远端冻结与当前状态

v3 使用全新外部根：

```text
$HOME/audattn_external_eval/same_bank_2026-08-29_v3
```

工具经 staging SHA 校验后，以 hard-link no-overwrite 发布。`audit-inputs` 返回 `AUDIT_PASS` 且目录树 zero-write。随后只执行了一次成功的 `freeze-inputs`：

```text
input_freeze.json
size   = 19,285
SHA256 = 50f0799f66801a79be8e7d49e65a405d46414454e48af4b8f5d2d2780a5283df

state/evaluation.lock
size   = 424
SHA256 = 70e535851bf7dde13cf180e193131edb75b7e180a143cf021b7be7703c72e62d
nonce  = 43f44285ae8ad61ae4e7a2a7a5aa31f1f387b2db490ed6572f97ad1a0a9818c4
```

登录节点 `check-only` 已得到：

```text
status                = CHECK_PASS
verified_files        = 24
fresh_recovery_status = CHECK_PASS
MANIFEST_UNCHANGED    = PASS
LOCK_UNCHANGED        = PASS
LOGIN_ZERO_WRITE_TREE = PASS
```

运行计算节点只读预检前记录的 v3 根指纹为：

```text
tree identity SHA256 = 5ac9a4fb153e0414740c18b4cd2cf1af55315e5847e41b80338e534b921410ca
file content SHA256  = 697f78ff1317c709c0fac4756d97d598b81b2b5ab6bc3642e85fa3de703f091c
```

随后通过直接 `srun` 请求了一个计算节点上的 zero-write `check-only`：

```text
Slurm Job = 640258
最后观测 = queued and waiting for resources
时间锚   = 2026-08-30 JST（终端输出未显示分钟级时间）
```

Job `640258` 不是 smoke。它不应创建 attempt、不应归档 runner/environment，也不应写入 v3 根。本文截止时尚未取得它的终态、ExitCode 或 `CHECK_PASS` JSON，因此：

- `COMPUTE_ZERO_WRITE_GATE` 尚不能写成通过；
- v3 smoke 尚未提交；
- `state/SMOKE_PASS.json` 尚不存在；
- 完整 10k `run-audit` 尚未提交；
- 目前没有 formal40、valbest33、author_external 的新准确率、SNR 分层或 paired CI 结果。

## 11. 操作层插曲及其影响

期间出现过几次终端粘贴或换行错误，包括 Python `-c` 被换行、命令参数缺少续行反斜杠、freeze 命令前误带 `~`、以及指纹函数中 `/usr/bin` 被拆行。这些命令分别表现为 `SyntaxError`、RC127、参数缺失或 pre-write canonical-path 拒绝。

这些都没有被当成科学失败，也没有授权删除或覆盖：

- v1 的正确只读诊断随后成功，固定得出 56 个 ULP mismatch；
- v2 第一次 freeze 调用在布局初始化前即拒绝，目录仍保持 pre-freeze，随后一次合法 freeze 成功；
- v3 参数缺失的 audit 调用保持 zero-write，修正后 `AUDIT_PASS`；
- v3 compute gate 的早期错误粘贴使 gate 保持非零并阻止 smoke；
- 后续重新核验得到 `RUN_COMPUTE_GATE=0` 后，才启动直接 `srun` 的 Job640258；它仍只是计算节点只读预检，本文把它记录为未完成。

## 12. 历史完成项与未完成项（初始正文快照，非当前状态）

### 已完成并核验

- full 训练 `epoch 0..39`，40/40；
- final `global_step=69440`；
- AMP `69440=69414+26`；
- formal-final checkpoint 冻结；
- completion recovery 的 check、原子 publish 和重复验证；
- formal40 / valbest33 / author_external 三角色冻结；
- old bank、Job584990、config、label map、历史 evaluator 和三 checkpoint 身份核验；
- v3 本地 68/68 回归；
- v3 `AUDIT_PASS`；
- v3 一次性 freeze；
- v3 登录节点 `CHECK_PASS`、24 文件复核和 zero-write 验收。

### 尚未完成

- Job640258 的计算节点 `check-only` 终态与输出复核；
- 计算节点检查前后 tree/content 指纹相等验收；
- v3 smoke；
- `SMOKE_PASS.json` 的独立重算；
- 完整 10k same-bank audit；
- 三模型逐 trial 结果、SNR/干扰人数/cue-control summary 和 paired cluster-bootstrap CI；
- 真正独立、未参与任何选择过程的 final-test bank 与一次性结果。

## 13. 历史后续门禁（v3 阶段，非当前操作指令）

后续只能依次进行：

1. 等待 Job640258 结束，记录精确 `sacct State/ExitCode`；
2. 要求 compute `check-only` 为 `CHECK_PASS`、`verified_files=24`，并解析 protocol/policy；
3. 比较计算前后 tree identity 与全文件 content 指纹，必须完全不变；
4. 只有 `COMPUTE_ZERO_WRITE_GATE=0` 时，才可在同一 shell 单次提交 v3 smoke；
5. smoke 必须在 A100 上 `COMPLETED 0:0`，三模型 strict load、scene hash 和 batch16-vs1 canary 全部通过，并原子发布可复核的 `SMOKE_PASS.json`；
6. smoke 后再次运行只读 `check-only`，确认 marker、attempt、runner 和 environment hashes；
7. 只有上述全部通过，才允许提交完整 10k `run-audit`；
8. 完整 audit 也必须 `COMPLETED 0:0`、发布 marker 并由只读 validator 重算后，才能报告数字。

任何 FAILED、partial、RUNNING 或无 canonical marker 的中间 CSV 都不能用于科学结论。需要修改代码、阈值、batch、preprocessing 或协议时，必须使用新的版本根和新的 manifest；不能修改已经冻结的 v3 根。

## 14. 历史结果解释模板（2026-08-31，当前概述见第 0 节）

在完整 audit 尚未完成前，可对外使用的准确简述是：

> full-distribution 模型已按固定协议逻辑完成40轮训练，并在项目外、fail-closed 的受控恢复审计后安全发布 formal-final checkpoint。训练的最后一个 Slurm 分段因训练后 Lightning 恢复计数误判而显示 FAILED，但四份冻结作业日志中的40条逐轮 summary、global step、checkpoint loop state 和 AMP 账本共同证明训练完整。后续三模型比较使用的是已参与 pilot GO 的冻结 validation/pilot bank，因此属于 same-bank audit，而不是独立 final test。v3 smoke Job642803 在任何模型预测前因冻结 evaluator 的延迟导入缺口 fail closed；该工程缺口已在独立 v4 本地包中完成 RED→GREEN 修复与静态/回归验证，但 v4 尚未执行集群 smoke，仍没有可报告的新模型表现。

## 15. 证据索引

- [2026-08-20_Job587802_full训练第一分段_epoch4至12中期记录.md](./2026-08-20_Job587802_full训练第一分段_epoch4至12中期记录.md)
- [2026-08-16_Job575142_full-distribution四轮pilot训练记录.md](./2026-08-16_Job575142_full-distribution四轮pilot训练记录.md)
- [2026-08-23_full训练数据角色、SNR分层基线与40轮协议说明.md](./2026-08-23_full训练数据角色、SNR分层基线与40轮协议说明.md)
- [full训练安全自动续投控制_2026-08-25.sbatch](./full训练安全自动续投控制_2026-08-25.sbatch)
- [full训练最终发布恢复_2026-08-28.md](./recovery_tools/full训练最终发布恢复_2026-08-28.md)
- [same-bank v1 README](./same_bank_eval_2026_08_29/README.md)
- [same-bank v2 README](./same_bank_eval_2026_08_29_v2/README.md)
- [same-bank v3 README](./same_bank_eval_2026_08_29_v3/README.md)
- [same-bank v4 README](./same_bank_eval_2026_08_29_v4/README.md)
- [Job584990 full-pilot冻结10k科学评估记录](./2026-08-17_Job584990_full-pilot冻结10k科学评估记录.md)

恢复发布、v2 Job637966、v3 audit/freeze/check 与 Job642803 的“已执行”状态，另由 2026-08-28 至 31 日用户提供的 HAKUSAN 终端输出，以及远端 canonical `COMPLETE`、`COMPLETE_RECOVERY.json`、`input_freeze.json`、`evaluation.lock`、Job log/environment artifacts 的路径、size 与 SHA 共同证明；上列 README 主要是操作合同，不能单独替代执行证据。v4 README 与本地测试输出只证明修复包准备完成，不证明任何远端 v4 作业已经运行。

## 16. 更新规则

2026-09-06 补充阅读规则：文首元数据与第 0 节作为滚动导航，明确标注更新时间和证据范围；早期正文保留历史事实与时态，不将后来的结果回写为当时已知。新的执行事实仍追加在第 17 节。

本文正文的初始截止状态固定为 Job640258 排队。后续取得新证据时，应在本文末尾新增带 JST 时间的“执行追记”，保留旧状态，不回写成仿佛当时已经知道结果。每次追记至少记录：

- Job ID、JobName、State、ExitCode、Start/End/Elapsed/Node；
- log、environment、attempt、marker 和结果文件的 SHA256；
- 前后 zero-write 指纹；
- canonical status/engineering status/scientific role；
- 哪些门禁通过、哪些仍未执行；
- 对科学解释是否有影响。

## 17. 执行追记：Job640258终态与登录节点JSON解析边界

### 17.1 Job640258已完成，但原compute Gate没有闭合

2026-08-30 重连 HAKUSAN 后，通过 `sacct` 取得了第 10 节中尚在排队的计算节点只读预检终态：

```text
JobIDRaw = 640258
JobName  = env
State    = COMPLETED
ExitCode = 0:0
Elapsed  = 00:01:46
Start    = 2026-08-30T03:50:49
End      = 2026-08-30T03:52:35
NodeList = spcc-a100g10
```

该次 `srun` 的 evaluator 进程也曾在原 shell 打印：

```text
COMPUTE_CHECK_RC=0
COMPUTE_JSON_BYTES=20599
```

这证明 compute 节点上的 `check-only` 命令本身以 0 返回；出现的 torchaudio `kaiser_window` 弃用提示只是 warning。随后 SSH 连接被远端关闭，原 shell 中尚未完成或没有保留下列同会话证据：

- 对 `COMPUTE_CHECK_JSON` 的规范语义解析；
- 运行后的 tree-identity 指纹；
- 运行后的全文件 content 指纹；
- 与运行前指纹的精确比较；
- `COMPUTE_ZERO_WRITE_GATE=0` 的条件计算及最终 `test`。

因此不能仅凭 Slurm `COMPLETED 0:0` 和 `COMPUTE_CHECK_RC=0` 把这次运行补写成完整 compute Gate 通过。Job640258 仍然不是 smoke，也没有授权提交 smoke。

重连后的只读 inventory 没有发现 smoke/audit attempt、submitted runner、日志或发布 marker；当时只看到已有的空 `attempts/{smoke,audit}` 目录和 `state/evaluation.lock`。人工审定的两个冻结哈希仍为：

```text
input_freeze.json SHA256
50f0799f66801a79be8e7d49e65a405d46414454e48af4b8f5d2d2780a5283df

state/evaluation.lock SHA256
70e535851bf7dde13cf180e193131edb75b7e180a143cf021b7be7703c72e62d
```

### 17.2 tmux恢复与登录节点check-only复核

为了避免下一次 SSH 断线丢失排队命令及 shell Gate，创建并恢复了 tmux 会话：

```text
session = samebank_v3
window  = samebank_0:bash
```

tmux 底部绿色状态栏只表示当前正在 tmux 会话中；它不是 Slurm 作业状态，也不表示评估正在运行。`Ctrl-C` 只向当前前台命令发送中断，不会退出 tmux；安全脱离会话应使用 `Ctrl-b` 后按 `d`，之后可用 `tmux attach -t samebank_v3` 恢复。

在该 tmux shell 中重新运行登录节点 `check-only` 后，命令本身返回：

```text
LOGIN_CHECK_RC=0
LOGIN_JSON_BYTES=20574
```

最初的 Python `-c` 与 `jq` parser 多次失败并不是 manifest 或模型失败，而是两个操作层问题：

1. 长 Python 单行在终端粘贴时被实际换行截断，产生 `IndentationError`、`SyntaxError` 或空输入 `JSONDecodeError`；
2. `LOGIN_CHECK_JSON` 的标准输出并非从 `{` 开始，而是先含有三行模型导入提示：

```text
Using explicit dim specification for demeaning in audio transforms
Using explicit dim specification for demeaning in audio transforms
Using explicit dim specification for demeaning in audio transforms
```

因此 `jq` 对原变量稳定报 `Invalid numeric literal at line 1, column 6`。这不是 JSON payload 损坏，而是非 JSON stdout 前缀污染。以首个仅含 JSON object 起始的 `{` 行为边界，只读提取后得到：

```text
CLEAN_JSON_RC = 0
CLEAN_BYTES   = 20373
```

干净 payload 的语义复核结果为：

```text
status   = CHECK_PASS
protocol = fullpilot4_same_bank_audit_20260829_v3_nfs_portable_identity_v1
policy   = cross_invocation_path_size_sha_exact__dev_inode_diagnostic
files    = 24
recovery = CHECK_PASS
LOGIN_PARSER_RC = 0
```

原始 stdout 必须保留用于诊断；parser 只能对从第一个 JSON object 起始行截取出的副本运行，不能编辑冻结 manifest、evaluator 或 runner 来消除提示。v3 evaluator 和 runner 的冻结 SHA 仍不可改变。

### 17.3 本追记后的精确Gate状态

截至本追记证据边界：

- 登录节点新一次 `check-only` 的命令退出码、JSON 语法和五个关键语义字段均已分别通过；
- Job640258 的 Slurm 与 evaluator 退出码均为 0；
- Job640258 因 SSH 断线缺少同一 shell 的 compute JSON parser 与 AFTER 指纹闭合，`COMPUTE_ZERO_WRITE_GATE` 仍不得写成 0；
- v3 smoke 仍未提交，`SMOKE_PASS.json` 仍不存在；
- 完整 10k `run-audit` 仍未提交，也没有新的模型表现数字。

下一次 compute Gate 应在现有 `samebank_v3` tmux shell 内重新执行。parser 必须先从 stdout 首个 JSON object 起始行提取干净副本，再验证 `CHECK_PASS`、协议、文件系统策略和 `verified_files=24`；之后必须计算 AFTER 两个指纹并与 BEFORE 精确相等。只有最终明确打印 `COMPUTE CHECK-ONLY ZERO-WRITE GATE: PASS`，才能在同一 tmux shell 单次提交 smoke。

这里的重新执行是只读 `check-only`，不是重跑 `freeze-inputs`。禁止手工把任何 Gate 变量设为 0，也禁止修改或覆盖 v3 冻结根中的工具、manifest、lock 和已有证据。

### 17.4 2026-08-31追记：Job641979闭合compute zero-write Gate

为补齐 Job640258 因 SSH 断线缺失的同一 shell 证据，在 `samebank_v3` tmux 会话中重新执行了一次计算节点只读 `check-only`。本次 Slurm 记录为：

```text
JobIDRaw = 641979
JobName  = env
State    = COMPLETED
ExitCode = 0:0
Elapsed  = 00:01:14
Start    = 2026-08-31T07:14:25
End      = 2026-08-31T07:15:39
NodeList = spcc-a100g01
```

compute 命令与捕获输出状态为：

```text
COMPUTE_CHECK_RC     = 0
COMPUTE_OUTPUT_BYTES = 20599
```

对完整 stdout 只读定位唯一的顶层 JSON 起始边界，再解析其完整后缀，得到：

```text
STARTS      = 1
BOUNDARY_RC = 0
SYNTAX_RC   = 0
PARSER_RC   = 0
CLEAN_BYTES = 20398
```

parser 同时核验 `status=CHECK_PASS`、精确 protocol、顶层与 `verification` 内的文件系统策略、`verified_files=24`、`fresh_recovery_status=CHECK_PASS`，以及人工审定的 manifest SHA。三行 demeaning 初始化提示仍作为 stdout 诊断保留，没有修改 frozen evaluator。

运行前后的登录节点 v3 根指纹完全一致：

```text
tree before  = 5ac9a4fb153e0414740c18b4cd2cf1af55315e5847e41b80338e534b921410ca
tree after   = 5ac9a4fb153e0414740c18b4cd2cf1af55315e5847e41b80338e534b921410ca

content before = 697f78ff1317c709c0fac4756d97d598b81b2b5ab6bc3642e85fa3de703f091c
content after  = 697f78ff1317c709c0fac4756d97d598b81b2b5ab6bc3642e85fa3de703f091c

AFTER_RC: TREE=0 CONTENT=0
TREE_MATCH=0 CONTENT_MATCH=0
```

最终条件计算及测试得到：

```text
COMPUTE CHECK-ONLY ZERO-WRITE GATE: PASS
COMPUTE_ZERO_WRITE_GATE=0
TEST_RC=0
```

提交 smoke 前的同会话只读 preflight 还确认 evaluator、runner、manifest 和 lock 的审定 SHA 全部 `OK`，目录布局有效，无同名 active smoke 作业，且 smoke attempt、submitted runner、log 和 `SMOKE_PASS.json` 尚不存在：

```text
STATIC_RC=0
LAYOUT_RC=0
SQUEUE_RC=0
ACTIVE_SMOKE=''
SMOKE_PREFLIGHT_GATE=0
```

因此截至此追记，v3 跨节点 NFS 可移植身份修复已经通过计算节点实证；下一阶段被授权的是一次新的 smoke 工程 canary。此处仍没有 smoke 结果、完整 10k audit 或可报告的三模型科学数值。

### 17.5 smoke首次提交命令在sbatch前安全停止

在 `SMOKE_PREFLIGHT_GATE=0` 后准备单次提交 smoke 时，最初提供的 shell 片段把 Bash 参数展开：

```bash
${SMOKE_SUBMISSION_ATTEMPTED:-0}
```

错误地拆成了多个物理行。Bash 在执行任何有效 `sbatch` 提交前报告：

```text
-bash: ${
    SMOKE_SUBMISSION_ATTEMPTED:-0
  }: bad substitution
-bash: [: : integer expression expected
```

该次命令的最终门禁输出为：

```text
SMOKE_SUBMIT_RC=99
SMOKE_JOB=
SMOKE_SUBMISSION_GATE=2
STOP: smoke was not safely submitted
```

这些值表示没有取得 Slurm Job ID，submission gate 保持 fail-closed；它不是 smoke 作业失败，也没有 smoke 结果。根据现有终端证据，不能把这次操作记录成已提交，更不能生成或推断 `SMOKE_PASS.json`。

根因只在提交包装命令的 Bash 换行，不在冻结 evaluator、runner、manifest、checkpoint、compute Gate 或 HAKUSAN 调度器。修正版把默认值参数展开保持为单个完整命令：

```bash
SMOKE_SUBMISSION_ATTEMPTED="${SMOKE_SUBMISSION_ATTEMPTED:-0}"
```

并在真正调用 `sbatch` 前再次检查同名 active job、smoke attempt、submitted runner、log 和 marker，使用内存中的重复提交 guard。修正版截至本追记尚无已执行输出；下一次操作必须先得到新的 `SMOKE_RECHECK_GATE=0`，再只提交一次，并以非空数字 Job ID 与 `SMOKE_SUBMISSION_GATE=0` 作为唯一提交成功证据。

因此本追记后的准确状态仍为：compute zero-write Gate 已通过；smoke 尚未形成有效提交；完整 10k audit 尚未开始。

### 17.6 smoke Job642803已单次提交并进入Slurm队列

在修正 Bash 参数展开、重新检查 active job 与输出树均为空后，同一 `samebank_v3` tmux shell 得到：

```text
RECHECK_GATE=0
ACTIVE_NOW=''
SUBMIT_RC=0
SMOKE_JOB=642803
SUBMISSION_GATE=0
```

这组输出证明 smoke 的单次 `sbatch` 提交成功，返回了非空数字 Job ID `642803`。提交后的即时 Slurm 状态为：

```text
JobID    = 642803
JobName  = audattn_samebank_v3
State    = PENDING
Reason   = Priority
Elapsed  = 00:00:00
Start    = Unknown
End      = Unknown
NodeList = None assigned
```

此时 `sacct` 显示的 pending `ExitCode=0:0` 不是作业成功证据；只有作业真正结束后的 `COMPLETED 0:0` 才能用于 smoke 终态判断。`Priority` 只是调度等待原因，不是失败。

Job642803 已由 Slurm 持久排队，不依赖 SSH 或 tmux 持续连接。严禁再次执行提交区块或创建第二个 smoke Job。下一步只能等待该 Job 结束，然后核验：

- `sacct` 最终状态与 ExitCode；
- canonical log、submitted runner 与 environment JSON；
- 唯一 smoke attempt 的完成状态和文件 SHA；
- `state/SMOKE_PASS.json` 是否由 evaluator 原子发布；
- 新一次只读 `check-only` 是否能重算并验证全部绑定。

因此本追记后的准确阶段是“smoke 已成功提交、等待调度”，不是“smoke 已通过”。完整 10k audit 仍未提交，也没有新的科学结果。

### 17.7 smoke Job642803在首批场景生成前因冻结导入上下文缺口fail closed

Job `642803` 离开 active queue 后，`sacct` 给出的最终状态为：

```text
JobID    = 642803
JobName  = audattn_samebank_v3
State    = FAILED
ExitCode = 1:0
Elapsed  = 00:00:38
Start    = 2026-08-31T09:14:21
End      = 2026-08-31T09:14:59
NodeList = spcc-a100g01
```

此处 `squeue: Invalid job id specified` 只表示作业已经不在 active queue；最终状态以 `sacct` 的 `FAILED 1:0` 为准。runner 已执行到调用 evaluator 的第 555 行，因此在它之前的 runner 归档、哈希复核和环境指纹生成步骤均已越过。计算节点环境指纹为：

```text
cuda_available = true
cuda_runtime   = 11.8
cudnn          = 8700
device         = NVIDIA A100-PCIE-40GB
hostname       = spcc-a100g01
python         = 3.11.5
torch          = 2.1.1+cu118
slurm_job_id   = 642803

environment JSON SHA256
38493aa274bc9f707ab11fb195bcfa9d10dd68cde95f83d47ed1c3744bc0dc15
```

完整 traceback 将失败位置锁定为首批共享原始场景生成，而不是 Slurm 调度、GPU 初始化、checkpoint strict load 或模型预测：

```text
locked_same_bank_eval.py:3604  main -> run_evaluation(smoke=True)
locked_same_bank_eval.py:3348  run_evaluation -> _evaluate_prediction_pass
locked_same_bank_eval.py:3027  _evaluate_prediction_pass -> raw_scene_batch
snapshot/files/selftrain/scripts/eval_full_pilot.py:247
    from selftrain.data.diotic_attention import crop_centered, sum_equal_rms
ModuleNotFoundError: No module named 'selftrain'
ERROR: line 555 exited with 1
```

根因是 v3 evaluator 的冻结导入上下文生命周期过短。它在 `_frozen_import_context(snapshot_files)` 内导入冻结的 `selftrain.data.diotic_attention` 与 `selftrain.scripts.eval_full_pilot`，取出 `WaveformCache`、`_raw_scene_batch`、`_correct_cue_batch` 和 `_role_batch` 后便退出上下文。退出会恢复原 `sys.path` 并移除临时载入的 `selftrain.*` 模块。随后 evaluator 在上下文外调用 `_raw_scene_batch`；该冻结历史函数在真正执行时才再次导入 `selftrain.data.diotic_attention`。runner 又按设计清除了 `PYTHONPATH`，因此这个延迟导入无法解析。受检冻结历史 evaluator 的 SHA 仍为：

```text
29414207e3fac53ff8805e61fcf4cee48fb155c4c60d0e736e35526c80dfae5b
```

这也解释了为什么登录节点和计算节点的 `check-only` 可以通过：`check-only` 会在受控上下文内完成三个模型的 strict load，但不会执行真实 `_raw_scene_batch`。Job642803 到达 evaluator 第 3348 行，说明三个模型 load loop 已结束；失败发生在第一次 batch 的音频读取、scene hash 和任何模型 prediction 之前。

该 attempt 的落盘状态为：

```text
attempts/smoke/slurm-642803/
  RUNNING.json  size=1879
  FAILED.json   size=486

state/SMOKE_PASS.json absent
```

因此 Job642803 是一次被正确隔离和记录的工程 smoke 失败：没有 `SMOKE_PASS.json`、没有可发布的 per-trial 结果、没有新的三模型表现，也没有启动完整 10k audit。它不推翻此前已经独立闭合的 40/40 训练、formal-final 发布、冻结输入审计或 compute zero-write Gate，但证明 v3 的真实场景生成路径存在本地单元测试未覆盖的集成缺口。

后续不得原地修改或重复提交已由 manifest 绑定的 v3。应保留 v3 根、Job642803 日志、environment artifact 与失败 attempt 作为证据，另建 v4：先增加能够真实触发冻结历史 `_raw_scene_batch` 延迟导入的回归测试，再让冻结导入上下文覆盖场景生成和推理生命周期；重新生成工具哈希、项目外版本根、manifest 与 lock，并从 audit/freeze/check/compute-zero-write/smoke 门禁重新开始。完整 10k audit 仍不得在新 smoke 原子发布并复核通过前提交。

### 17.8 v4以RED→GREEN关闭冻结延迟导入缺口并完成本地发布级验证

2026-08-31 在保留 v3 与 Job642803 全部失败证据不动的前提下，新建了独立本地目录：

```text
/Users/gigi/发表/超算/same_bank_eval_2026_08_29_v4
```

创建时先核对 v4 目标不存在，并确认复制前 v3 的五个发布文件仍保持原始 SHA。v3 evaluator 与 runner 分别仍为：

```text
f6a2b39779c299ba0b9826d6a9f75d66d994abbf404fa0143dce1daa020fc3d6  locked_same_bank_eval.py
37403ee0867d8f75f9f66923cf75031f215cec3263b0f0b1bda5c93f914707ba  run_locked_same_bank_eval.sbatch
```

修复前先运行 v3 原始测试基线：evaluator `55/55`、runner `13/13`，合计 `68/68`。这证明旧测试全部通过仍不足以覆盖真实场景函数的延迟导入。随后在尚未修改生产逻辑的 v4 副本中新增行为级回归测试：它通过真实 `run_evaluation(smoke=True)` 控制流加载一个冻结测试包，让 `_raw_scene_batch` 在执行时再导入 `selftrain.data.diotic_attention`。第一次执行得到预期 RED：

```text
test_run_evaluation_keeps_frozen_imports_alive_during_prediction ... ERROR
locked_same_bank_eval.py:3348 -> _evaluate_prediction_pass
eval_full_pilot.py:2 -> from selftrain.data.diotic_attention import delayed_value
ModuleNotFoundError: No module named 'selftrain'
Ran 1 test ... FAILED (errors=1)
```

该 RED 与 Job642803 的生产 traceback 同构，证明测试捕获的是上下文生命周期缺口，而不是 Slurm、CUDA 或 checkpoint 问题。测试随后加强为同时验证：requested batch pass、batch-size-1 smoke canary、`strict_load_model` 的嵌套冻结上下文，以及退出后的 cwd、`sys.path`、`src/selftrain` 模块恢复。

生产代码只做了一个有界行为修复：`run_evaluation` 中原有的单个 `_frozen_import_context(snapshot_files)` 不再在取出 callback 后提前结束，而是继续覆盖三个模型的 strict load、首轮场景生成/预测、smoke 第二轮可重复性预测和模型 tensor version 不变检查；结果校验、CSV、summary、marker 发布仍在上下文外。没有修改冻结 `eval_full_pilot.py`，没有永久追加 `PYTHONPATH`，没有放宽 snapshot 路径验证，也没有改变 bank、checkpoint、SNR、模型角色或统计协议。

v4 的工程身份更新为：

```text
protocol_id    = fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1
remote root    = $HOME/audattn_external_eval/same_bank_2026-08-29_v4
Slurm JobName  = audattn_samebank_v4
```

README 同时把 v3 根、Job642803、`FAILED 1:0`、失败 attempt、缺失 `SMOKE_PASS.json` 和 environment SHA 作为只读历史证据硬绑定；v1/v2 的既有取证边界也原样保留。v4 不复用 v3 manifest、lock、nonce、attempt 或工具文件。

在准备进入远程上传时，一次独立只读审计又发现 README 的 compute `check-only` parser 仍把完整 stdout 直接交给 `json.load(sys.stdin)`。由于三个模型的 strict load 会在最终 JSON 前输出 `Using explicit dim specification...` 诊断行，受控复现稳定得到 `JSONDecodeError: Expecting value: line 1 column 1`。这是操作合同的 stdout 边界缺口，不是 evaluator 计算失败。

按 RED→GREEN 又新增了五个直接提取并执行 README 命令程序的回归测试：混有前导提示行的唯一尾部 JSON 必须可解析；顶层与 `verification` 内的 identity policy 必须同时匹配；compute prerequisites 失败时绝不得调用 `srun`；已有 active `audattn_samebank_v4` 作业时，smoke 和完整 audit 均绝不得再调用 `sbatch`。旧 README 分别在 parser、无条件 `srun`、重复 smoke 和重复 full-audit 提交测试上呈现预期 RED；最小修订后全部 GREEN。这一轮只修改 README 和 README 行为测试，没有改动 evaluator、runner、bank、checkpoint、阈值或协议常量；evaluator/runner 的已审定 SHA 因此保持不变。

最小修复后，同一个回归测试转为 GREEN；最终独立发布级验证结果为：

```text
evaluator unittest     56/56 PASS
runner unittest        18/18 PASS
total                   74/74 PASS
Ruff                    PASS
Python AST              3 files PASS
Bash syntax             PASS
CLI --help              5/5 PASS
v3/v4 scientific audit  26 constants equal PASS
```

科学常量等价审计覆盖 schema、filesystem policy、lock purpose、RUN_ID、历史 Job、三模型角色、全部冻结输入 SHA、checkpoint epoch/global step、AMP/epoch 账本、bootstrap seed/repetitions、10k/9k/1k/2k trial 计数和 `SNR_IDENTITY_ATOL_DB=1e-12`；唯一预期差异是 protocol generation 从 v3 升为 v4。

清理测试缓存后，v4 最终五文件 SHA-256 为：

```text
1e573f7f68fbda0f37f6fb8f90cd13b7cbd383d2f89382a21afa44b122a3642b  README.md
31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4  locked_same_bank_eval.py
b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495  run_locked_same_bank_eval.sbatch
dc043ec7c4ce29e7584255b561685b501af6df60170dfe74fbe8b332ef36d779  test_locked_same_bank_eval.py
e8b33b2c1da14b9f458067a09d73c47c805199a6fe2e387f08c6cf1edf54a836  test_run_locked_same_bank_eval.py
```

其中 evaluator/runner 哈希已分别在 README 和 runner contract 测试中独立绑定并复核。v4 目录最终只有上述五个普通文件，没有 `__pycache__` 或 `.ruff_cache`。

本追记的准确终态是“v4 本地发布包与操作合同已准备完成”，不是“v4 集群评估成功”。截至本次记录：远端 v4 根尚未创建，工具尚未上传，新的 `input_freeze.json`、`evaluation.lock` 与 `lock_nonce` 尚未生成，v4 compute zero-write、smoke 和完整 10k audit 均未执行。因此没有新增模型表现或科学结论。下一阶段必须按 v4 README 从 one-shot 远端根创建与哈希上传开始，重新走 audit-inputs → freeze-inputs → login/compute check-only → smoke；只有新的 `SMOKE_PASS.json` 被原子发布并经 `check-only` 验证后，才允许提交完整 10k audit。

### 17.9 v4远端发布、输入冻结与只读审计完成

2026-09-01 已在 HAKUSAN 新建独立远端根：

```text
/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4
```

v4 evaluator 与 runner 经 staging、SHA-256 核对和 no-overwrite 发布后，仍为：

```text
31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4  locked_same_bank_eval.py
b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495  run_locked_same_bank_eval.sbatch
```

`audit-inputs` 重新验证了 10,000 条冻结 bank、三模型角色、40/40 完成恢复证据、val-best epoch 33 选择双证据、历史 Job584990 scene binding 与 24 个受检文件，终态为：

```text
status            = AUDIT_PASS
protocol_id       = fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1
evaluation_role   = REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST
verified_files    = 24
recovery_status   = CHECK_PASS
```

随后 `freeze-inputs` 已成功原子生成 v4 manifest 和非空 lock：

```text
1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5  input_freeze.json
63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710  state/evaluation.lock
lock_nonce = 6f7488407ef4b2193ae48efffa29a2dc40990318004a7219af2a80a2ef265546
```

登录节点 `check-only` 返回 `CHECK_PASS`，但手工 compute 命令的 shell 变量受大段粘贴和 stdout 前导诊断影响，出现 `COMPUTE_JSON_BYTES=0`/parser gate 假失败。这些 shell 输出不能作为 compute zero-write 通过证据，也没有产生 smoke 提交。为避免再由交互式 shell 组装关键命令，后续将 audit/check/fingerprint/active-job/evidence/intent/receipt/`sbatch` 门控收敛到项目外的单进程 ops helper。

此阶段已确认 v4 科学包与冻结输入完成；但仍没有 `SMOKE_PASS.json`、smoke 科学数值或完整 10k audit 结果。

### 17.10 首个 v4 ops helper在提交前因embedded NUL安全失败，ops-v2已本地审定

首个 v4 ops helper 被发布到：

```text
/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01
245e272a6c6b953ae3a8007f6a042b7b6aa906fef173d5deed906ec542b943c4  resume_v4_smoke.py
```

它在登录节点 `check-only` 后进入首次冻结树指纹，尚未进入 compute `srun`、durable intent 和 `sbatch` 时失败：

```text
ProductionGateway.fingerprint
subprocess.run(...)
ValueError: embedded null byte
RESUME_HELPER_RC=1
```

根因是 Python 源码中 GNU `find -printf` 的格式字符串以 `\0` 结尾；Python 在构造 argv 时已将它解释成真实 NUL，`subprocess` 因而在启动 `/usr/bin/find` 之前拒绝该参数。正确实现必须让 argv 含有字面反斜杠与数字 `0`，再由 GNU `find` 解释。

远端失败现场只有：

```text
resume_v4_smoke.py
resume_state/workflow.lock  (empty)
```

没有 `intent.json`、`receipt.json`、Slurm Job、v4 log、submitted runner、smoke attempt 或 marker。因此这是一次有界、fail-closed 的提交前工程失败；不能解读为 smoke 已提交或已通过。旧 ops 目录必须原样保留，不得覆盖或删除。

按 RED→GREEN 在新的本地 ops-v2 目录中做了有界修复：

```text
/Users/gigi/发表/超算/same_bank_eval_2026_08_29_v4_ops_2026_09_01_v2
```

修复只将 production fingerprint 中的参数改为向 GNU `find` 传递字面 `\0`；没有改 evaluator、runner、manifest、lock、bank、checkpoint、SNR 或三模型角色。同时新增两类硬门控：

- 生产 fingerprint argv 不得含 `\x00`，并必须以字面 `\0` 结尾；
- 旧 ops 目录必须精确等于“旧 helper + 空 workflow lock”，任何 intent、receipt、非空 lock、额外文件或旧 helper 哈希变化都必须 fail closed。

最终本地验证为：

```text
unittest                 32/32 PASS
Ruff check               PASS
Ruff format --check      PASS
README Bash syntax       PASS

3f4d21762c4d178ceb104959518a211f9e6037a74c0ba76c61ed698b90b9ef50  resume_v4_smoke.py
399cd75bc0ab9e084fe6587d8ed9527cfc3b8da0a1ada17f5ec2aaaf511c3feb  test_resume_v4_smoke.py
```

ops-v2 只允许发布到新目录：

```text
/home/s2510040/audattn_external_eval_ops/same_bank_v4_2026-09-01_v2
```

本追记的准确终态是“embedded-NUL 根因已关闭，ops-v2 本地包已通过测试与独立审查”，不是“smoke 已提交”。截至本记录，ops-v2 尚未上传 HAKUSAN，没有新 Job ID；下一步是按 ops-v2 README 的 no-overwrite 流程创建新 ops 根、上传并校验 helper，然后只运行该 helper 一次。

### 17.11 ops-v2唯一提交Job646900，v4在batch-size数值canary处fail closed

2026-09-01，ops-v2 helper 经远端 SHA-256 复核后只执行一次，并成功向 Slurm 提交 v4 smoke：

```text
status          = SMOKE_SUBMITTED
job_id          = 646900
manifest_sha256 = 1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5
protocol_id     = fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1
helper_rc       = 0
```

Job `646900` 的最终 Slurm 状态为：

```text
JobName  = audattn_samebank_v4
State    = FAILED
ExitCode = 2:0
Elapsed  = 00:01:54
Start    = 2026-09-01T21:51:48
End      = 2026-09-01T21:53:42
NodeList = spcc-a100g02
```

这是 evaluator 主动抛出 `EvaluationError` 后由 runner fail closed 的退出码，不是排队、节点分配、CUDA 初始化或 checkpoint 加载失败。运行环境为 NVIDIA A100-PCIE-40GB、Python 3.11.5、PyTorch 2.1.1+cu118、CUDA 11.8、cuDNN 8700。环境指纹和 canonical log 为：

```text
a29047d9f64f16b3a4628c3317ef8a083f9b3a4d8e6fa1377812755e3afa76f5  submitted_runners/646900.environment.json
124290c8769e5d1f0c96bf4594d21f703ec0620723ddc41e4919474612252304  logs/audattn_samebank_v4_646900.log
```

日志证明 v4 已越过 v3/Job642803 的冻结延迟导入缺口：三个模型成功加载，32 条 smoke trial 的 requested-batch pass 与 batch-size-1 pass 都完成。runner 未显式传入 `--batch-size`，因此 requested batch 使用 evaluator 默认值 16；第一轮日志为 `16/32`、`32/32`，第二轮为 `1/32` 至 `32/32`。两轮中的每个 raw scene 都重新生成并逐 trial 对照冻结 Job584990 scene SHA；否则对应 pass 会在模型预测前终止。

双路径完成后，v4 在第一个超限连续数值列主动停止：

```text
ERROR: Smoke batch-size canary differs: formal40_nll,
       max_abs=0.0077362060546875
ERROR: line 555 exited with 2
```

`compare_smoke_passes` 按 DataFrame 列顺序比较，且在首个超过 `1e-6` 的数值列立即抛错。`formal40_nll` 之前的 identity、scene/cue SHA、`formal40_pred_label` 与 `formal40_correct` 已经 exact-match。因此现有证据可以确认：这 32 条 trial 中 formal40 的类别预测和正确/错误判断没有因 batch 16 与 batch 1 改变；可确认的首个差异是逐 trial NLL，最大绝对差为 `0.0077362060546875`，约为冻结门槛的 7,736 倍。该值不是平均差，也不是所有模型和字段的全局最大差；比较器提前停止，后续概率、control 指标、valbest33 与 author_external 的全部数值差尚未被完整枚举。

失败 attempt 被正确保留：

```text
0a715ab4381b4f511ab680a5ff1f967f8d8ffa7891fda43811e0298d570ab5a3  attempts/smoke/slurm-646900/RUNNING.json
c7e45015d21661ac1ed44648d6a2f404bad2d498d52d438e2888cbd07d2f2618  attempts/smoke/slurm-646900/FAILED.json

FAILED.error_type = EvaluationError
FAILED.error      = Smoke batch-size canary differs: formal40_nll,
                    max_abs=0.0077362060546875
```

canary 在 per-trial CSV、long CSV、summary、`COMPLETE.json` 和 canonical marker 写入前失败，因此没有 `SMOKE_PASS.json`，也没有可解释或可发布的模型性能结果；完整 10k audit 仍未获准提交。Job646900 只能记录为工程 smoke 失败，不能记录为 formal40、valbest33 或 author external 的科学评估结论。

当前最强单一根因假设是跨 batch shape 的混合精度数值差异，而不是输入变化或分类翻转。推理把 cochleagram 与整个 CNN forward 放在 CUDA FP16 autocast 中，模型由 `torch.compile` 包装，运行时同时允许 TF32。batch 16 与 batch 1 可采用不同 shape-specialized CUDA/cuDNN/compiled kernel 和不同浮点归约顺序；`torch.use_deterministic_algorithms(True)` 保证相同输入和执行路径的确定性，不保证不同 batch shape 得到逐位相同结果。`0.0077362060546875 = 507/65536` 也呈现二进制量化格点特征，但这只能支持假设，不能单独证明算子级根因。

现有 artifact 还不能把第一处分歧定位到 normalized waveform、cochleagram feature、compiled CNN logits 或 FP32 log-softmax，也不能完整证明两轮之间所有模型注册 tensor 未变：canary 抛错发生在最终 model tensor-version 检查之前。虽然模型处于 `eval()`、dropout 已关闭，所审架构使用 per-example LayerNorm/conv/linear 且未发现 BatchNorm，但正式定根因仍需一次独立、只读、非发布诊断。

下一阶段不得原地修改 v4、放宽 `1e-6`、删除 Job646900 attempt、重复提交 v4 smoke 或绕过 smoke 直接提交 10k audit。应完整保留 v4 与 Job646900 证据，并在独立诊断根中只加载 formal40、重放同一 32 条 smoke selection：先比较 16→16 同 shape 重跑与 16→1 跨 shape，再记录最差 trial 在 singleton-normalized waveform、coch feature、完整 logits、target logit、`logsumexp` 和 NLL 各边界的差异；最后仅在诊断 harness 中关闭 autocast 做单变量 A/B。只有这些证据确认分歧层和精度来源后，才可用 RED→GREEN 设计新的版本和可辩护的 canary 合同。

本追记后的准确终态是“v4 真实双路径 smoke 已执行并在 batch-size 数值 canary 处正确 fail closed；分类输出未变，数值根因假设尚待独立诊断确认”。

### 17.12 2026-09-06追记：独立数值诊断工具的本地实现进展

后续工作转入已批准的独立诊断设计：只加载 formal40，在同一 32 条冻结 smoke
trial 上比较 16→16、16→1，以及 autocast 开/关的四个组合，并通过冷启动的
冻结参考路径核验诊断记录是否改变了推理结果。诊断设计没有放宽 v4 的
`1e-6` 阈值，也没有在 v4 原目录修改代码或发布成功标记。

截至本次记录，输入/文件/张量/状态记录及冻结源码加载模块（任务 1–3）已完成
本地实现和复审。推理路径与身份保护模块（任务 4）的第五轮修复已完成本地
验证：修改前的专项为 69 个测试、25 个失败、0 个错误；修复后全套 129 个测试
通过，3 个 Python 文件语法解析通过。该候选版本仍待独立代码复审。

本次主要补齐了音频列表子模块的状态检查、校验凭据的不可伪造检查，以及
严格加载完成到首次推理之间的参数/缓冲区内容和存储身份绑定。校验过程使用
静态属性读取，并限制调用图遍历规模，避免检查本身运行自定义对象方法或无限
展开。只读快照还补入了原 v4 evaluator 参考文件，支持在独立临时目录复现测试。

当前尚未完成后续结果落盘、四组合协调器、提交器及远端 A100 诊断，因此
`0.0077362060546875` 分歧首次出现在哪个计算层仍未确定。本次续作没有提交新
Slurm 作业，不能记作 smoke 通过或 10k 评估完成。全量训练 40/40 的既有完成
结论仍以原 COMPLETE、恢复 sidecar 和 checkpoint 证据为准。

持续更新的开发状态、精确 hash 和原始日志入口见
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

### 17.13 2026-09-06续记：推理模块复审通过，开始结果比较阶段

第 17.12 节的“任务 4 待独立复审”现已推进：独立只读审查核对源码与参考
文件 hash，专项 69/69 通过；在本次源码／CPU 审查范围内没有确认的阻塞项。
这不替代真实 formal40／A100 集成验证。

随后完成任务 5a 的差异分类及正式输出无损编码。新比较器区分有限数值
`DIFF` 与身份、状态或非有限数值导致的 `INVALID`；v4 的 `1e-6` 阈值保持
不变。它会记录 A2 重放分类、首个观测分歧边界，并按 trial ID 对齐两轮
结果。正式输出以原始浮点字节保存到可序列化记录，避免 CSV 舍入影响后续
逐位等价检查。现有 Task 4 CPU 推理的两轮原始记录也已直接接通比较器。

本次新增 22 项测试，当前全套 **151/151 通过**，三个 Python 文件语法检查
通过。初始失败与修复日志、源码 SHA、只读快照均记入
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

任务 5 尚未整体完成：接下来是不可覆盖的结果文件发布、worst-case 大小
限制、完整工件验证及 worker 串接，之后才是协调器和提交工具。本次没有
访问 HAKUSAN 或新提交作业；真实 GPU 数值根因仍未确认，不能记作 smoke
成功或 10k audit 完成。这里更新的是本地超算工作区说明，尚未同步到项目
仓库“全量任务”镜像目录。

### 17.14 2026-09-06续记：数值诊断结果保存层基础完成

本次继续实现任务 5b 的保存层基础，尚未完成整个任务 5。新增了固定目录内
不可覆盖的 NPY 发布、流式 SHA 校验、普通文件／链接／目录清单检查，以及
四个 cell 共用的 worst-case 1 GiB 预算预检。NPY 保留原始数值类型与字节序，
预算包含文件头；不允许绕过预算直接写单个 worst-case 文件。

新增 24 项回归测试。补充失败测试发现并修复了预算绕过、异常时文件描述符
未关闭，以及文件被换成 FIFO 后可能卡住的问题。当前全套 **175/175 通过**；
只读源码快照复制到独立临时目录后再次 **175/175 通过**，语法检查通过。
完整源码 hash、失败／通过日志和待完成事项见
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

下一部分是将两轮推理记录接入保存层，完成 reference/cell 的完整文件清单、
无损证据重验、worst trial 选择、完成标记最后发布及 worker 串接。协调器的
独占执行和真正 A100 诊断仍未实施。本次未改冻结 v4、未提交超算作业，不能
记作 smoke 通过、数值根因已确认或 10k audit 完成；项目仓库镜像尚未同步。

### 17.15 2026-09-06续记：两轮结果接通完整保存与重验

已把既有两轮推理记录接入完整 reference/cell 文件发布：保存原始输出字节、
pass commitment、逐 trial 边界记录、runtime、state/RNG、完整 logits 和
worst-case 三件组。完成标记在载荷验证后最后写入；reference 不混入 cell
数值状态，cell 的 PASS、有限 DIFF 与 INVALID 分开记录。

只读重验会重新计算正式输出的 canary/A2 分类，并检查保存的差值 tensor。
同一次操作中，即使文件被替换成相同内容，也会报错；跨节点的 device/inode
差异仍按原 NFS-portable 合同处理。两个真实调用已有 Task 4 CPU 路径的测试
已分别接通 reference 与 trace 的两轮原始结果，保存时没有重新推理。

本次新增 23 项测试，全套 **198/198 通过**；只读快照独立目录复测同样通过，
语法检查通过。具体 hash、RED→GREEN 日志、验证范围及限制已补入
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

剩余工作是生产 worker 启动、scratch／进程生命周期集成及四组合协调器。
本次没有改冻结 v4、没有提交超算作业或同步项目镜像；GPU 数值根因仍待诊断，
不能据本地工程测试宣称 smoke 或 10k audit 已通过。

### 17.16 2026-09-06续记：接通单个诊断 worker 和 scratch

reference/cell worker 函数已实现：一次加载 formal40、连续跑两轮、不在两轮
之间重置 seed；冻结导入上下文一直保留到保存和重验结束。新增独立缓存／
临时目录边界检查，完整 cochleagram 只在各轮输出完成后暂存到 scratch，
不扩大持久结果范围，也没有调整原 1e-6 canary 阈值或 1 GiB 保存上限。

本次新增 28 项回归测试。专项 **97/97**、全套 **226/226** 和只读快照复测
**226/226** 全部通过。测试确认了已有 CPU 推理路径能接通该生命周期，并
覆盖缓存非空、文件替换、缺失 attempt、错误源码位置和输入变化时的拒绝。

当前是任务 5 的本地实现候选；下一阶段仍需实现任务 6 的受控子进程启动、
reference/A2 等价核验、四组合协调、回执绑定及最终状态。当前代码尚不提供
可提交的完整诊断流程，本次没有提交 HAKUSAN 作业、修改冻结 v4 或同步项目
镜像；GPU 数值根因、smoke 和 10k audit 状态没有因此变为成功。

具体代码 hash、RED→GREEN 日志与限制见
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

### 17.17 2026-09-06续记：先补齐面向最终比较目标的阶段说明

按用户“先记录说明文档”的要求，本次核对现有训练完成记录、Job `646900`
失败证据、数值诊断执行记录及开发进度账本，在文首新增目标／模型角色／
阶段状态／后续路径总览，并把旧摘要与操作模板明确标成历史快照。此前
文首“v4 尚未上传或执行”已滞后于第 17 节的实际追记，现已纠正阅读入口，
但没有删除或改写原有失败记录。

本次确认的是：40 轮训练已完成；本轮完整三模型比较尚未完成；当前工作为
正式评估前的数值诊断工具本地实现候选。226/226 属于已记录的本地回归测试，
本次文档整理没有重新运行测试，也没有取得新的 GPU 结果或数值根因。

本次没有改代码、checkpoint、bank、冻结 manifest 或评估阈值，没有查询／
提交 HAKUSAN 作业。此更新仅落在本地超算工作区，项目仓库“全量任务”镜像
尚未同步，不能把文档整理记作实验推进或远端状态确认。

### 17.18 2026-09-06续记：诊断子进程启动与回执边界已实现

继续原计划的任务 6a，已实现 reference 与四个诊断 cell 的固定启动参数、
独立缓存环境和单独进程组；回执必须是有界规范 JSON，并绑定本次启动的
PID、job、freeze、角色与固定 marker 路径。日志不作为 JSON 解析；进程
失败、超时或中断时不能因 marker 已存在而冒充成功，也不自动重试。

新增 25 项本地测试。补充测试发现并修正了主目录缓存边界遗漏。专项
122/122、全套 251/251 和隔离只读快照复测 251/251 均通过；源码语法及
限定静态检查通过。完整 RED→GREEN 日志与源码 hash 已记入
[数值诊断执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md)。

这只是完整协调器的启动／回执部分，不是整个任务 6 完成。接下来仍需
持久来源与工件绑定、共享锁、参考等价和四组运行顺序、输入前后复验及
唯一终态。当前代码尚不可直接提交诊断；本次未访问 HAKUSAN、未提交作业、
未改冻结 v4 或科学协议、未同步项目镜像。GPU 根因与正式三模型对比状态
没有变为完成，训练也没有重跑。

### 17.19 2026-09-06续记：明确以模型对比结果为终点的完整计划

按用户“先给出完整计划”的要求，新增总路线图，明确最终要交付同一冻结
10k bank 上的三模型逐条输出、准确率／NLL 表、SNR 与干扰人数曲线、既定
cue-control／配对统计、解释边界以及本地结果归档与说明镜像。

原 12 项数值诊断任务被定位为总路线前段的子计划；整体按“诊断包收尾 →
32 条 GPU 诊断 → 基于证据审定评估路径 → 三模型 smoke → 10k audit →
结果解释与归档”推进。独立 test bank 单列为后续研究，不混作本次比较的
隐藏前提；不因本总计划而放宽冻结阈值或预先批准某种数值修复。

本次仅写计划并增加主记录入口，没有改诊断代码、模型、bank 或已批准设计，
没有实时查询 HAKUSAN、提交作业或同步项目镜像。当前实现仍停在任务 6a
本地候选；本轮正式模型比较状态仍为未完成。

### 17.20 2026-09-06续记：开始执行总计划 M1，接通四格证据集成

本阶段测试和说明收尾于 2026-09-07（JST）；精确 SHA 的独立临时副本也已
复测 275/275 通过。独立副本指执行目录隔离，不等于新增独立代码复审。

按用户“开始执行”的指示，推进任务 6b：父进程保存退出回执后重新核验
子进程工件，并将两轮结果与本次 PID、模型状态、软件／GPU、缓存与冻结
来源绑定；参考与 A2 必须两轮逐位等价，之后才执行 A1、B1、B2。

已用本地 CPU 工件验证：有限 `DIFF` 会继续收齐四格，等价失败会保留证据
并停止后续三格；末尾重新核验早期结果，防止后续进程改坏已有文件。
新增 24 项测试，专项 124/124、全套 275/275 通过。补充测试发现并修复了
跨冷进程初始参数／buffer 内容一致性检查的遗漏。

这完成了完整协调器中的证据／顺序组件，不代表整个 M1 已完成。外层
提交回执／runner 认证、共享锁、输入 PRE/POST、信号／终态和发布入口
仍待接通。没有修改冻结 v4、模型、bank、精度或阈值，没有访问 HAKUSAN、
提交 GPU 作业或同步项目镜像。真正三模型比较仍在 smoke 验收之后。

### 17.21 2026-09-07续记：M1 外层协调器与失败保护

完成 Task 6c 本地组件：最多 120 秒等待匹配提交回执、严格绑定 intent／
原始 Slurm response／receipt、精确 spool 归档、create-once attempt、持续
shared flock、全部冻结文件与 v4 目录指纹的 PRE/POST，以及中断和唯一终态。
发现主推理失败时仍尝试输入复查，两类失败同时保留；不靠重试获取成功。

32 项专项和全套 307/307 本地测试通过。真实子进程测试确认收到 TERM 后
先终止／回收子进程，再执行 POST。文件测试覆盖 checkpoint、clip、snapshot、
源码、freeze、归档 runner 改动及 v4 runner 写日志的竞态。

这不是完整协调器发布验收：公开结果验证／终态文件清单和生产 CLI 接线
仍待完成，随后才是 runner／提交器及发布。没有改变冻结 v4、checkpoint、
bank、精度或阈值，也没有远端操作、GPU 提交或项目“全量任务”镜像同步。
完整原始测试证据、实现 SHA 和剩余边界见数值诊断执行记录的 Task 6c 节。

### 17.22 2026-09-08续记：M1 结果验收与只读验证器

完成 Task 6d 本地组件：终态绑定 attempt 全文件／目录清单；完成标记写入
前重新核验实际矩阵工件和输入。只读 `verify-results` 从提交 journal、归档
runner、owner 环境与 PRE/POST 接到五个冷进程的两轮结果，重新验证参考
等价并计算四格汇总，拒绝仅有完成字样、错误汇总或缺失／改动／额外文件。

本地专项 48/48、全套 323/323 通过，含有限 DIFF、跨节点 device/inode
差异、临时缓存清理、伪造环境、缺少回执、失败与缺少终态等测试。
这些是模拟 CPU 数据与文件系统测试，不是新的模型准确率或 A100 实验。

后续仍需生产执行入口、runner、提交器与发布验收，然后才取得真实 32 条
诊断结果。没有放宽 `1e-6`、修改 v4、重新训练、提交作业或同步项目镜像。
目标仍是经 smoke 验收后完成三模型冻结 10k 对比，而非止于诊断代码。

### 17.23 2026-09-08续记：接通生产执行入口，下一项为运行与提交工具

Task 6e 已把 coordinator／reference／cell 命令行接到现有实现，补上实际
启动参数、冷解释器、环境白名单、私有缓存及 Linux 父进程身份与提交证据
的关联检查。缓存变化也纳入 PRE/POST 失败记录；拒绝启动时不加载数值库。

新增 15 项测试，专项 38/38、全套 338/338 通过。测试仍是本地 CPU／文件
fixture 和隔离 Python 子进程，不是新 A100 结果或模型对比成绩。
下一项是薄 Slurm runner 和耐久提交器，再完成整包验收及实际 GPU 诊断。
没有修改 checkpoint／bank／v4／数值阈值，没有提交超算作业或同步项目镜像。

### 17.24 2026-09-08续记：Slurm runner 本地实现，接下来完成提交器

新增固定资源的运行脚本与 stdlib 启动验证：绑定 freeze／实际 spool／生产
源码／INTENT，拒绝重复 attempt 和归档，建立独占节点本地缓存并记录环境
指纹，再启动现有协调器。没有直接执行 sbatch，也没有产生新模型结果。

runner 专项 18/18、既有回归 338/338 通过；Bash 语法、AST、选定 Ruff
检查通过。Linux mount 与最终 exec 的正向测试使用模拟，不能当作 A100 验收。
完整模拟提交链路待 Task 8 耐久提交器实现后补齐，再做整包发布验收。
当前仍属于 M1 本地工具准备；目标仍是拿到三个模型的冻结 10k 对比。

实现、hash 和测试边界见[Task 7 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-7-runner-report.md)。

### 17.25 2026-09-08续记：完成耐久提交记录层，尚未开放提交命令

Task 8a 新增排他锁、不可覆盖的提交意图／原始响应／SHA 绑定回执。即使
外部调用超时、响应不明确或回执写入失败，也会留下意图阻止自动重投；
有效回执能被既有协调器验证接受。

提交记录层 19/19、连同 runner 的测试 37/37 通过，覆盖本地文件与锁、
异常输出和持久化失败，不是新的超算实验或模型结果。当前提交脚本 CLI
明确拒绝执行：接下来还需 Task 8b 调度器、队列检查、只读 status、单次
sbatch 接线，以及整包模拟集成和验收。

没有远端登录或提交，没有修改模型／bank／v4／数值阈值。详细记录见
[Task 8a 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-8a-journal-report.md)。

### 17.26 2026-09-08续记：接通单次提交和只读查询，下一步整包验收

Task 8b 接通固定路径调度器、完整只读输入审计、两次队列检查、先写意图
再单次提交及只读 status。查询能区分排队／运行、记账延迟、有诊断终态
标记，以及 Slurm 已结束却缺少终态记录；不会把 COMPLETED 当作数值验收。
查询期间终态或 freeze 变化时拒绝混合状态，要求再次查询。

专项 25/25、运行／提交工具 62/62、数值核心 338/338 通过。两套测试合计
400 项，不是 400 次超算实验。真实 sbatch／squeue／sacct 均未调用；测试
使用模拟响应，并检查回执发布前的 runner bootstrap、单次调用和 v4 零写入。

当前 CLI 已接通，但尚未完成 Task 9 的操作 README、完整五子进程模拟
链路、安全／格式／hash 与发布复审，不能直接部署。没有新 GPU 结果，也
没有修改模型／数据／阈值。详细证据见
[Task 8b 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-8b-gateway-report.md)。

### 17.27 2026-09-08：Task 9a 本地静态子关卡通过

完整 Ruff／格式检查已通过；数值核心 338/338、提交工具 62/62 回归通过。
格式化引起追踪文件哈希变化，已同步更新诊断器固定长度／哈希并核验。
冻结 v4 evaluator 没有修改，数值阈值不变。本轮没有上传或提交作业。

Task 9 尚未整体完成：下一项是完整模拟提交至五子进程及结果验证器的链路
测试，之后补齐安全测试、操作 README 与发布复审。仍无三模型最终 10k 对比。
候选哈希、初始失败和验证结果见
[Task 9a 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9a-style-report.md)。

### 17.28 2026-09-08：Task 9b 本地模拟全链路通过

模拟提交经实际记录／runner bootstrap／协调器，启动五个真实本地 CPU 测试
子进程并通过实际工件验证。合成有限 DIFF 可以完成；错误 PID 会安全失败，
执行后重复提交被拒绝。新增两个集成和两个调用面测试，总提交套件 66/66、
数值核心 338/338 通过。仅改测试文件，未改生产工具、冻结证据或数值阈值。

这些是合成数据与模拟调度器，不是 A100 数值诊断；仍无三模型最终 10k 对比。
下一项是操作 README、最终哈希及发布复审。本轮没有 SSH、上传或提交。
[Task 9b 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9b-integration-report.md)。

### 17.29 2026-09-08：Task 9c 操作说明和候选校验完成

新增七文件包 README，写明冻结身份、部署／提交／查询／验收流程、短命令、
数值结论限制和不自动重试规则。六项内嵌 hash、八段 Bash 命令语法均通过；
README 编辑后重跑核心 338/338、提交／集成 66/66 通过，静态与隔离加载通过。
七文件候选哈希保存在
[Task 9c 报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9c-operator-release-report.md)。
当前还缺独立发布复审，不能据主代理自检开放远端部署。本轮未 SSH、上传、
提交或改动数值阈值，尚无新的三模型对比结果。

### 17.30 2026-09-08：Task 9 独立复审通过，开放下一阶段预检

用户明确授权一个只读审查子代理；独立审查结论 Ready，没有确认的阻塞问题，
审查者独立执行 4 项测试通过。README 顶部更新复审状态，生产文件未修改。
主代理最终核心 338/338、提交／集成 66/66 和七文件哈希检查通过。

Task 9 本地验收完成。下一阶段为 Task 10：先只读检查 HAKUSAN，再按新根、
不可覆盖原则部署工具。本轮没有 SSH、上传、GPU 运行或作业提交；最终模型
对比仍待数值诊断和后续 smoke／完整评估。
[独立审查与最终验收记录](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9-independent-release-review.md)。

### 17.31 2026-09-08：真实清单兼容性失败及 v2 有界修复

v1工具已在HAKUSAN发布，但audit报“必须24项”：用户只读确认v4清单SHA未变，
五组24项、加layout锁25项。原因是诊断器扩大收集范围，并在下游错误要求锁
属于24项。此前合成fixture和发布审查漏检；本次没有执行freeze或提交。

用户授权后，新建本地v2，严格对齐原v4五组mapping遍历；锁固定路径／SHA／
大小／实际内容继续单独校验并加入PRE/POST。v1七文件和远端现场均保留。
新增6项回归（含直接对照冻结v4 walker），核心344/344、提交66/66及独立复查
33/33通过。仅诊断根／诊断协议版本改v2，科学阈值、模型和bank不变。

下一步v2新根预检／部署，再实际audit/freeze；没有上传v2或提交GPU作业。
[v2修复报告](.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v2-manifest-scope-repair.md)。
