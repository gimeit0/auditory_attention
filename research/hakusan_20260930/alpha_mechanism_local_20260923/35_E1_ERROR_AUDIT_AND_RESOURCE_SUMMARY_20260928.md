# E1 750474：错误结构独立核验与资源汇总

状态：`INDEPENDENT_ERROR_STRUCTURE_PASS`；尚不标 E1_DEV_COMPLETE。

## 分列与独立核验

错误报告新增 scene_kind 逐行字段，以及每个 pass/condition 的 clean/mixed 汇总和簇区间。旧报告不覆盖；新报告位于 [error-analysis-750474-0tkyayan/REPORT.json](release_e1_20260927_v3/error-analysis-750474-0tkyayan/REPORT.json)。

`audit_e1_errors_independent.py` 没有导入分类函数，从 60 个原始数组的 argmax 与 bank 角色标签重新计算每一条目标/干扰/cue 命中、标签碰撞、角色重叠、cue 实际来源及最终互斥类别。逐字段比对 CSV；重新按类别聚合并计算簇区间。

结果：[independent-error-audit-750474-66dqor7h/RESULT.json](release_e1_20260927_v3/independent-error-audit-750474-66dqor7h/RESULT.json)：38400 条预测、131 份汇总、655 个均值/区间指标全部一致，包含 clean/mixed 分列。区间使用独立复算的簇抽中次数矩阵；不把 B 冷重复当新样本。全部统计/分类/审计合成测试现为 25 项，通过。

这一证据关闭 34 号表中“错误结构分列与独立复核”项；不关闭来源时间范围限制或最终交付门。

## A/B 实测环境和资源

两进程均为 Python 3.11.5、torch 2.1.1+cu118、CUDA 11.8、cuDNN 8700，NVIDIA A100-PCIE-40GB，spcc-a100g06，作业 750474、8 CPU。与终态 sacct 节点相同。

| 进程 | pass 数 | 各 pass allocated 最大值（bytes） | reserved 最大值（bytes） | RSS 最大值（KiB） |
| --- | ---: | ---: | ---: | ---: |
| A | 17 | 5380726272 | 7340032000 | 2087836 |
| B | 2 | 5380726272 | 7340032000 | 2041148 |

数值由 `collected-750474-_rosoog2/state/attempt/{A,B}/STAGES.json` 的 pass_resources 实际取最大值得到。RSS 是 ru_maxrss 高水位，不能解读成单个 pass 独占的增量内存；CUDA 峰值来自各 pass 记录，不推断模型加载前阶段。

已记录的执行阶段 UTC：

- A：2026-09-27T13:54:23.167833+00:00 至 14:44:01.762844+00:00。
- B：2026-09-27T14:44:41.101025+00:00 至 14:49:46.716854+00:00。

这些时间由 execute_loaded 记录，不能替代完整子进程 UTC 创建/退出时间。Slurm 完整作业时间另为 2026-09-27 22:52:07–23:50:06（站点回读），耗时 57:59。保留原有 P5 限制，不补造记录。

## 下一出口

数值主/次要结果及错误分类已有独立核验。下一步整理统一交付报告、机器可读的条款覆盖矩阵与最终门：必须明确区分计算通过、来源限制、探索性科学读数。不能因统计方向有利而自动跳过 P5，也不自动增加 GPU 作业补录时间。

本轮全部为本地操作，原始归档和冻结包不变。
