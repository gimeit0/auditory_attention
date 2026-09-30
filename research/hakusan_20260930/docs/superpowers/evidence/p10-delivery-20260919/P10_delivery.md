# P10 可复算交付：formal40 与作者 checkpoint 的固定同 bank 比较

2026-09-19。总计划 P10（S7）。唯一正式全量作业 **Job 728520**（COMPLETED/0:0，57 分 11 秒，spcc-a100g02）；冷重复基线 Job 728378（48,000 条预测逐位一致）。研究身份 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。

## 1. 结论（中文）

2026-09-19 解释更新：原始预测、P06 政策及 P09 统计保持不变；[数值敏感性勘误与离线复核](NUMERIC_ERRATUM.md)修正原“Accuracy/NLL 上界”的解释。本稿的 CI 均针对固定执行配置，不保证跨批配置显著性不变。

**差多少。** 在同一冻结的 10,000 条验证/pilot bank、同一场景与 cue、各自原生预处理下，正确 cue 的 Accuracy：formal40 0.4376，作者 checkpoint（author_external）0.4201，valbest33 0.4513。formal40 − author 的配对 Accuracy 差为 +0.0175（95% CI +0.0015 ~ +0.0337），交叉熵改善（author NLL − formal40 NLL）为 +0.0265（95% CI -0.0932 ~ +0.1451）：Accuracy 上 formal40 略优且区间不含 0，交叉熵上总体差异不显著。

**在哪些条件差。** mixed 的优势被 clean 的劣势部分抵消，总体差值依赖当前 90%/10% 场景权重。mixed 9,000 条 Accuracy 差 +0.0351（95% CI +0.0181 ~ +0.0517），交叉熵改善 +0.1261（95% CI +0.0034 ~ +0.2480）；clean 1,000 条则相反，author 更好（Accuracy 差 -0.1410（95% CI -0.1803 ~ -0.1021），交叉熵改善 -0.8699（95% CI -1.0817 ~ -0.6657））。低 SNR −10~−6 dB 的交叉熵改善 +0.6000（95% CI +0.4474 ~ +0.7494），−6~−2 dB 为 +0.4332（95% CI +0.2792 ~ +0.5848）；高 SNR 6~10 dB 的 NLL 方向相反（改善 -0.4081，95% CI -0.5938 ~ -0.2273），该层 Accuracy 差的 CI 则含 0。干扰数 1–4 各层 Accuracy 差方向为正，交叉熵区间多数跨 0。性别分层不用于推断模型×性别交互：一组显著、另一组不显著并非交互检验。cue controls 中三模型 correct 相对 shuffled/silent/distractor 均有正向差值；distractor cue 下 probe 概率变化点估计 formal40 约 +0.21、valbest33 约 +0.20，author 约 +0.11。它支持 cue 利用及误导 cue 敏感性，不直接证明模型间依赖强度差异或 gain 机制因果作用；后者需要配对差中之差/专门实验。以上分层 CI 为逐项区间，探索性解读，不声称多重比较校正或同时覆盖。

**补充模型。** valbest33（验证集选出的 epoch 33）在全部 10k 上优于固定的 formal40（Accuracy 差 -0.0137（95% CI -0.0236 ~ -0.0041），交叉熵改善 -0.1246（95% CI -0.1797 ~ -0.0706））。按科学合同，主模型仍是 formal40，此结果只作报告，不据此更换主模型。

**不确定性多大。** 以上区间为 target_speaker 成簇 bootstrap 10,000 次的固定配置 95% 区间（原 v4 seed 规则）。两次全量 48,000 条预测逐位一致。跨批设置未做全量验证：给定逐 logit 扰动≤0.004，margin≤0.008 的比例才提供条件性 Accuracy 变化界，formal40 0.63%、author 0.80%、valbest33 0.47%。若两模型每条 NLL 各扰动≤0.002，配对差的保守变化界是 0.004。包络本身来自有限样本，不能当作全量已证上界；原 P06-5 的 CI 半宽判据也不能证明靠近零的 CI 端点稳健。原 P09 按旧政策生成的字段保留以便追溯，当前解释以[勘误](NUMERIC_ERRATUM.md)为准。总体 Accuracy 条件性点估计范围为 +0.32~+3.18 个百分点，但这不是新的置信区间。

**哪些不能外推。** 这是复用验证/pilot bank 的审计，不是独立测试集，不声称泛化；author 是系统级外部参考，训练数据、预处理（其原生全局变换 vs formal40 的逐样本 leveling）与训练时长都不同，本比较回答“同一输入下谁更好”，不回答“同一训练配方下谁更好”；clean 场景仅 1,000 条且方向与 mixed 相反，不能把总体 Accuracy 优势外推到 clean 或高 SNR 条件。

## 2. 主表摘录（完整表见 [P09 报告](../p09-statistics-20260919/REPORT.md)）

| 分层 | n | Accuracy 差 formal40−author | 交叉熵改善 author−formal40 |
| --- | --- | --- | --- |
| 全部 | 10000 | +0.0175（95% CI +0.0015 ~ +0.0337） | +0.0265（95% CI -0.0932 ~ +0.1451） |
| mixed | 9000 | +0.0351（95% CI +0.0181 ~ +0.0517） | +0.1261（95% CI +0.0034 ~ +0.2480） |
| clean | 1000 | -0.1410（95% CI -0.1803 ~ -0.1021） | -0.8699（95% CI -1.0817 ~ -0.6657） |
| SNR −10~−6 dB | 1800 | +0.0889（95% CI +0.0641 ~ +0.1141） | +0.6000（95% CI +0.4474 ~ +0.7494） |
| SNR 6~10 dB | 1800 | -0.0272（95% CI -0.0595 ~ +0.0044） | -0.4081（95% CI -0.5938 ~ -0.2273） |

## 3. 正式结果包与 SHA 清单

- 逐 trial 宽表 `results.csv`、原始 logits `logits.npz`（48,000×800 float32）、`bank.csv`、`RUN.json`（环境/资源/运行时设置）、`LOAD_REPORTS.json`（严格加载覆盖率 1.0）、`pass.json`、`PROFILE.json`、`RECEIPT.json`：`docs/superpowers/evidence/p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k/`
- 执行台账与独立复算：[P08 台账](../p08full-production-20260919-r2/REPORT.md)；作业日志与全部回执在同目录 `frozen/`。
- 统计：[STATISTICS.json](../p09-statistics-20260919/STATISTICS.json)、[REPORT.md](../p09-statistics-20260919/REPORT.md)、[paired_strata.csv](../p09-statistics-20260919/paired_strata.csv)。
- 数值政策：[P06（原已审定版本，保留）](../../../../checkpoint_compare_workflow_20260917/P06_numeric_policy_draft.md)；解释更新：[数学勘误](NUMERIC_ERRATUM.md)。
- SHA-256 清单：[SHA256SUMS.txt](SHA256SUMS.txt)（23 个文件）。

## 4. 一条离线重算命令（不需要 GPU）

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/p09_statistics.py \
  --archive "$PWD/docs/superpowers/evidence/p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k" \
  --receipt-sha256 21a42644fd60e73a3668fd07cfe656a49b8ca95635438fd23ef6c7b92b8881ab \
  --output "$PWD/docs/superpowers/evidence/p09-statistics-recompute-$(date +%Y%m%d-%H%M%S)"
```

它重新核验回执/布局/声明与全量清单，从 `results.csv` 复算原版统计表；`STATISTICS.json` 除时间戳外应与原交付版一致。此命令仍生成历史 P06 解释字段，须与勘误一起阅读。补充敏感性复核命令见[勘误第4节](NUMERIC_ERRATUM.md)。逐 logits 的独立复算与两次全量逐位比较见 P08 台账所列命令。

## 5. 历史失败附录

18 个失败/超时作业、CPU 与传输层问题及其归因见 [失败总审计](../../../../2026-09-17_checkpoint对比_失败总审计与收敛方案.md)；本轮唯一失败 Job 728378（验证器 CSV 分块解析缺陷，模型阶段完整、产物已作冷重复基线）见 [P08 文档](../../../../checkpoint_compare_workflow_20260917/P08_full_run_batch.md)。站点插件改写 typed GRES 共 8 次（截至 2026-09-19；2026-09-26 E0 作业 746603 为第 9 次，见 [E0 台账](../e0-production-20260926/REPORT.md)），均以单独授权的同作业修正处理，[询问稿](../p05b-production-20260918/GRES_typed_request_inquiry.md)待发。

## 6. 出版图

2026-09-20 已生成三张图（[figures/](figures/)，图注与替代文本见 [FIGURES.md](figures/FIGURES.md)，来源与文件 SHA 见 [figures/MANIFEST.json](figures/MANIFEST.json)）：图 1 三模型按 SNR 段/clean 与干扰者数的准确率与交叉熵；图 2 与作者的配对差值森林图（95% 成簇 bootstrap 区间）；图 3 cue controls。全部由 `checkpoint_compare_workflow_20260917/p10_figures.py` 从 STATISTICS.json 确定性生成；Okabe–Ito 配色加形状冗余；PNG 600 dpi 不透明 RGB，PDF 矢量嵌字。投稿期刊未定，尺寸/格式待按目标期刊核对。

## 7. 尚未完成

最终图文核对已于 2026-09-27 以程序化方式完成，见 [R0_DELIVERY_VERIFICATION.md](R0_DELIVERY_VERIFICATION.md)；发现的 4 处措辞不一致已按下节更正。投稿适配待目标确定。

## 8. 2026-09-27 更正记录

程序化核对（345 项文本数字对照 STATISTICS.json）发现 4 处措辞不一致，均不涉及数据、统计或图件，仅更正文字：

- 本文 §1：formal40 的 distractor cue probe 概率变化点估计原写“约 +0.20”，数据为 0.2069，改为“约 +0.21”；valbest33 0.2036 仍为“约 +0.20”。
- FIGURES.md 图 3 图注：同一处“约 +0.20”改为分别给出 formal40 约 +0.21、valbest33 约 +0.20。
- FIGURES.md 图 3 替代文本：原写三模型 probe 概率变化“区间互不重叠”，实际 formal40 [0.1923, 0.2223] 与 valbest33 [0.1895, 0.2180] 重叠，只有 author 的区间与另两者不重叠，已改写。
- FIGURES.md 图 1 替代文本：干扰者数 4 时准确率范围原写“约 0.33–0.37”，author 为 0.3231，改为“约 0.32–0.37”。

“约”值统一按四舍五入到所写位数的规则；本文 §5 的 typed GRES 计数加了时效注。SHA256SUMS.txt 的 23 项上游文件未变；交付文本与图件的清单见 R0 核对目录。
