# E1 750474：独立数值复算及剩余验收清单

状态：`INDEPENDENT_PRIMARY_SECONDARY_ARITHMETIC_PASS`；不是 E1_DEV_COMPLETE，也不是机制结论。

## 已完成复算

独立实现 `audit_e1_statistics_independent.py` 不导入主/次要分析的计算函数；直接从原始 npz 与冻结 bank 重新按 trial_id 关联。先重新调用冻结包 offline-check、逐数组校验 SHA，再复算。

bootstrap 使用另一种求和实现：将同 seed 抽出的簇索引转换为簇抽中次数矩阵，以矩阵乘法计算加权 trial 总和与分母，而非原分析逐次索引聚合。两者保留同一 PCG64 seed=20260926、10000 次与 linear percentile 定义。另用 logaddexp.reduce 独立重算 float64 NLL。

最新证据：[RESULT.json](release_e1_20260927_v3/independent-stat-audit-750474-epr_1shm/RESULT.json)。覆盖：

- 49 个分析单位，3170 个指标的点估计与 CI，包括全样本、重叠排除版本和 20 格分层。
- 每单位簇数、簇大小分布和共同抽样索引摘要。
- 54 个 A 进程数组的准确率、NLL、预测类别、并列最多类别、logit 最大值、样本 RMS 及 NLL float64 复算偏差。
- 17 项 main/clean 崩溃区判定与 3 项负对照的一致率/最大 logit 差。

均通过；浮点比较绝对容差 1e−10、相对容差 0。不能将“容差内一致”改写成所有重算结果逐位相同。来源与分析代码 SHA 已绑定。23 项统计/分类/审计合成测试通过，其中包括错误值、非有限数和维度变化必须被审计拒绝的负例。

初次复算目录 `independent-stat-audit-750474-orzlbt70` 保留，它尚未包含最后增加的 17+3 项检查；以 epr_1shm 为本次完整算术审计证据，不覆盖旧文件。

## 合同逐项出口：仍需关闭的项目

| 合同要求 | 当前证据 | 后续动作 |
| --- | --- | --- |
| 38400 预测、端点/冷重复、归档离线验收 | collected 原始归档及各分析入口重新 offline-check | 已完成，不重跑 GPU |
| D/c1/r0 与实测 α=0 NLL 残差 | 31 号与 primary-analysis；独立复算通过 | 已完成，保留残差口径 |
| 五点绝对准确率/NLL、clean 对照、三负对照、20 格分层、敏感性 | 32 号及 secondary-analysis；独立复算通过 | 数值已完成，完整交付图文待汇总 |
| 错误结构与标签碰撞 | 33 号，38400 条分类，计数/CI | 补 main correct 内 clean/mixed 分列；独立复核分类与汇总，不将测试替代实际复算 |
| P1–P9 来源 | 33 号来源表 | 汇总 A/B 全 pass 资源；明确 P5 时间范围缺口和 P9 外部签署覆盖 |
| 图文呈现 | 阶段表格与 JSON | 汇总报告须含 E0 网格修订动机、角色/局限、全部预定统计；若绘制跨 α 绝对 NLL 图须用对数或分区 |
| 最终标签门 | 尚未运行 | 先完成计算与来源清单，缺项时拒绝 E1_DEV_COMPLETE；不按有利主区间提前赋科学候选 |

P5 不能从当前 archive 恢复完整子进程生命周期 UTC，不以文件 mtime 编造补齐，不自动重跑。先完成仍可执行的本地交付工作，再明确报告合同完成状态与来源限制；不得把当前情况误报为全部研究结束。

本轮没有网络、SSH、GPU 提交或远端更改。
