# E1 750474：P5 偏差处置草案（未批准）

状态：`DRAFT_NOT_APPROVED`。本文不构成用户签署、合同修订、GPU 授权或来源门通过。不得用自动续接消息或此前的作业批准替代本项决定。

## 已核实偏差

冻结代码 `package_ready/e1_worker_archive.py` 在 audited_e1_session 已加载模型、accept_loaded_formal40 通过后，才调用 execute_loaded。`e1_execution.py` 第 145 行的 process_started=utc_now() 在该函数内部，process_finished 同样在返回时记录；后续 session postcheck/归档写入发生在此之后。

因此字段覆盖已加载模型后的执行窗口，既不包含模型加载，也不包含所有结束后校验/归档。现有材料不能提供 A/B 子进程完整生命周期的 UTC 起止。已保存 PID、命令、退出码、每 pass 时间、执行窗口、整体 Slurm 开始/结束和 elapsed；不能将这些不同粒度的信息拼成未经观测的精确子进程时间。

原合同 28 号 §10 P5 要求进程级与每 pass UTC 起止；交付矩阵如实标 P5 部分满足，未写 E1_DEV_COMPLETE。冻结合同、包及原始归档保持不变。

## 影响与不影响

影响：无法完整还原每个 worker 的加载/执行/收尾在 UTC 时间线上的边界，来源要求不能原样全项通过。

已有数值证据：38400 预测与端点/冷重复验收通过；全部主/次要统计和错误结构独立复算通过。时间字段缺口本身不等于预测已损坏，也不是 checkpoint 对比作业728520的失败。这里没有证明缺失信息在任何用途下都不重要，只将范围说清。

## 建议选项 A：接受带披露的偏差交付，不重跑

需要明确确认的范围：仅对 E1 作业750474 接受上述 P5 来源记录限制；保留已验收原始结果和全部限制说明；不追溯改写合同或归档；不新增 GPU。

批准后应追加单独决定记录，绑定原28/29合同、v3 release SHA及交付 MANIFEST SHA，记载决定者、时间、适用范围。状态应使用 **E1_DELIVERED_WITH_ACCEPTED_P5_DEVIATION**，不能把原始合同未完全满足伪装成“无偏差全项通过”。科学读数仍为探索性，不能因接受记录偏差就宣布机制成立。

## 选项 B：不接受偏差，另行准备修复重跑

在新的候选版本修正监督器的进程创建/退出时间记录，并测试正常、失败、超时、收尾路径，保留旧包；新 GPU 预算和单次作业仍须独立批准。当前单次750474授权不能复用，不能自动提交。仅为补充时间记录而重跑会增加成本，故不作为默认动作。

## 当前授权检查

`docs/superpowers/evidence/e1-contract-signoff-20260927/` 当前仅有 SIGNOFF、GPU_HELD_AUTHORIZATION、GRES_CORRECTION_750474、RELEASE_750474 四份记录；没有 P5 偏差接受或新重跑授权。本次检查没有改变它们。

建议 A，但在用户明确决定之前，只能保持 **E1_ANALYSIS_DELIVERED_CONTRACT_INCOMPLETE**。数值分析成果可查阅和讨论，正式偏差处置未完成。

交付入口：[统一报告](release_e1_20260927_v3/delivery-750474-3wjt5pax/REPORT.md)、[验收矩阵](release_e1_20260927_v3/delivery-750474-3wjt5pax/COVERAGE.json)。
