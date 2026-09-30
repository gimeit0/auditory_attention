# HAKUSAN科研代码与结果快照

本目录保存截至2026年9月30日整理的选择性听取主课题代码、计划和聚合结果，补齐前次2026年8月24日的GitHub同步。当前状态以[科研进度首页](../../RESEARCH_PROGRESS_20260930.md)为入口；下列历史文档按原字节保存，其中“下一步”“尚未上传”等表述可能属于更早时点。

## 阅读顺序

1. [主课题总计划](2026-09-20_选择性听取发达机制_主课题总计划.md)及[近期执行计划](2026-09-23_主课题_近期执行计划.md)。
2. [模型比较交付](docs/superpowers/evidence/p10-delivery-20260919/P10_delivery.md)、[统计报告](docs/superpowers/evidence/p09-statistics-20260919/REPORT.md)和[数值敏感性勘误](docs/superpowers/evidence/p10-delivery-20260919/NUMERIC_ERRATUM.md)。
3. [E0科学读数](alpha_mechanism_local_20260923/26_E0_SCIENTIFIC_READOUT_746603_20260927.md)、[E1主分析](alpha_mechanism_local_20260923/31_E1_PRIMARY_READOUT_750474_20260928.md)、[82点α合并读数](alpha_mechanism_local_20260923/52_FINE_ALPHA_COMBINED_READOUT_20260929.md)。
4. [新种子训练执行台账](2026-09-28_formal40重训_同种子复现与换种子计划.md)。其追加事件比文末残留的早期“下一步”描述更新，当前已进入续训，不应重复提交预检或pilot。
5. [历史失败审计](2026-09-17_checkpoint对比_失败总审计与收敛方案.md)，用于理解加载、编译、数值、调度和验收问题如何逐步排除。

## 代码布局

- `checkpoint_compare_workflow_20260917/`：固定题库比较、统计、图件与回归。
- `alpha_mechanism_local_20260923/`：gain观察器、E0/E1/E2接口、低α扫描、独立验收与回归。
- `same_bank_*/`：历次评估、布局和诊断源码，供版本追溯。
- `docs/superpowers/prototypes/`：追踪、编译、隔离与CPU原型。
- `docs/superpowers/evidence/`：选定的人类可读报告、聚合统计与图件；不是整个原始证据目录。
- `patch_stage_next/`、`recovery_tools/`：训练安全及恢复工具的本地源码快照。

## 包含与排除

原始复制文件逐项列于[SYNC_MANIFEST.json](SYNC_MANIFEST.json)，SHA用于检查本次同步的字节保真。新写的两个导航文档由Git提交记录覆盖，不在原文件清单中。

公开快照排除权重、音频、逐样本预测、logits/npz/npy、SSH私有日志与socket、凭据、原始终端/调度日志、会议幻灯片和其他任务的未提交修改。保留的图件均为已有聚合结果，不在本次同步中重算或重绘。

`release_*/package/`只同步源码子集及原RELEASE记录，未同步其数据附件。因此这些目录**不是完整冻结执行包**，其原RELEASE清单可能引用本次有意排除的文件。全套回归或离线科学复算需要原始受控附件；本次同步仅检查源文件语法、复制哈希和选定聚合文件格式，不声称重新运行了全部科学验收。

历史脚本保留原路径与作业编号以便审计。不要直接执行上传、提交、GRES修正或release脚本；运行任何新GPU任务前仍须按当前方案重新核验与授权。

## 科学解释边界

比较和α扫描都复用了验证数据，不能称为独立测试。α扫描为探索性描述，不自动等同儿童发育阶段。新种子pilot通过不代表新种子40轮模型已训练完成，也不能提前判定它优于formal40。
