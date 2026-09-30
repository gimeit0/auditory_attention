# P08 正式全量评估：Job 728520 执行台账与验收结果

2026-09-19。对应总计划 P08（S5）。原机器记录状态 `P08FULL_OFFLINE_RECOMPUTED_NOT_QUALIFIED` 保留，不作改写。**全量产物已独立复算；P09 统计现已完成，P10 正在交付收尾。** 固定配置全量重复成立；原文 P06-4/5 数值上界解释已由[交付勘误](../p10-delivery-20260919/NUMERIC_ERRATUM.md)澄清，不再据此笼统声明跨批数值资格在全尺度成立。下列原 margin 分层数据保留，不能将其直接作为严格上界。

## 1. 执行台账

| 步骤 | 结果 / 证据 |
| --- | --- |
| 首次运行 | Job 728378 FAILED/1:0（in-job 验证器 CSV 分块解析缺陷；模型阶段完整），见 [../p08full-production-20260919/](../p08full-production-20260919/) 与 [P08 文档](../../../checkpoint_compare_workflow_20260917/P08_full_run_batch.md) |
| 重提授权 | [AUTHORIZATION.json](AUTHORIZATION.json) SHA `0782a9db…`：用户选择“用修复包 v3r2 重跑一次（同预算）” |
| 修复包 v3r2 | 读取器 `low_memory=False`、bank 按规范文本比较、新增 `full-repeat` 对照；本地 74+33、原生 107/107（442 s）通过 |
| 本地冻结 | release SHA `fbcd791d08cf9efb24ac4a4cf650a561efda73bc9734d021eb6c7dadc6cc8a1c` |
| 预检 / 发布 / test-only | 通过（基线 728280 COMPLETED）；`preflight-al4a1s04`、`publish-qg2z5zaz`、`test-only-2bhbihpz` |
| 单次 held 提交 | **Job 728520**，`submit-7wnauldm` |
| 站点改写（第 8 次） | ReqTRES=`h100-20c`；唯一一次修正后回读 `nvidia_a100=1`；[correct-gpu-728520/](correct-gpu-728520/) |
| 放行 | `release-*`；随后几乎未排队即 RUNNING（spcc-a100g02，AllocTRES 1×nvidia_a100） |
| 终态 | `728520|COMPLETED|0:0|00:57:11|spcc-a100g02`；COMPLETE.json SHA `5e52d246bb4498c5dcef70700e4dffd3ee53cecd775007cb6ef78f34890c8d78` |
| 只读收集 | `COLLECTED_NOT_QUALIFIED`，46 文件逐项 size/SHA 校验；`collect-vvv4ed4a` |
| 离线复算 | [offline-review-728520/REPORT.json](offline-review-728520/REPORT.json) SHA `da3d0879…` |
| 全量冷重复 | [full-repeat-728378-vs-728520/report.json](full-repeat-728378-vs-728520/report.json) SHA `28be3115…` |

本批 1 次 sbatch、1 次 scontrol update、1 次 release。两个模型进程独立顺序、rc 均 0。

## 2. P08 硬验收（全部由离线复算独立执行）

| 项 | 结果 |
| --- | --- |
| trial ID 0..9999 无重复/缺失/错序；2,000 control；48,000 条模型—条件预测 | 通过（`validate_results(full_run=True)`） |
| scene/cue 身份与 Job584990 历史绑定一致；strict-load 覆盖率 1.0；eager FP32；状态/RNG/bank 不变 | 通过 |
| self32 vs Job 728280 bridge16（同布局） | 全部条件逐位一致，旧 canary PASS（六作业逐位链 724808→725677→726428→728280→728378→728520） |
| self32 vs full10k 对应 32 条 | correct cue 三模型逐位一致；control 在包络内（NLL ≤1.41e-03、logits ≤2.63e-03）；0 翻转 |
| **full10k（728520）vs full10k（728378）** | **12 个模型×条件组、48,000 条预测全部逐位一致，0 翻转，canary PASS** —— P06-1 全尺度冷重复成立 |
| Slurm 终态、返回码、节点、环境 | COMPLETED/0:0，spcc-a100g02，Python 3.11.5 / torch 2.1.1+cu118 / A100-PCIE-40GB |

## 3. P06-4 margin 分层（full10k，correct cue）

| 模型 | n | 最小 margin | ≤4e-3（Accuracy 不确定性上界） | (4e-3, 4e-2] | >4e-2 |
| --- | --- | --- | --- | --- | --- |
| formal40__correct | 10000 | 0.00012 | 29 (0.29%) | 256 | 9715 |
| author_external__correct | 10000 | 0.00006 | 36 (0.36%) | 379 | 9585 |
| valbest33__correct | 10000 | 0.00014 | 23 (0.23%) | 219 | 9758 |

P09 报告 Accuracy 时须并列给出这些上界；两次全量逐位一致说明固定配置下这些近平局 trial 不会翻转，但跨批形状仍按包络处理。

## 4. 成本（P07 事后核对）

full10k 进程 3367 s（估计 4,876 s）；scene+预测 3316 s，forward 3010 s（3333 次）；保存/重读 3.0 s；峰值显存 5.49 GiB，RSS 2.30 GiB。3 小时时限的实际用量 32%。

## 5. 正式产物（P09 唯一输入）

`frozen/collect-vvv4ed4a/collected/received/full10k/`：`results.csv`（SHA `c705f29ed97d61d2…`）、`logits.npz`（SHA `54059d741c0cadac…`）、`bank.csv`、`RUN.json`、`LOAD_REPORTS.json`、`pass.json`、`PROFILE.json`、`RECEIPT.json`（SHA `21a42644fd60e73a…`）。P09 只能从这些文件读取，不得沿用内存中的临时结果。

## 6. 限制

研究身份 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`；author_external 为系统级外部参考；未做统计推断；数值资格结论仅覆盖固定配置逐位与批形状包络。
