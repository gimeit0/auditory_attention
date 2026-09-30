# 已有结果与主课题证据缺口

2026-09-23；本轮只做本地复核，超算暂停。

## 可以用于汇报的结论

在同一冻结10k复用验证bank、同一场景/cue、各模型原生预处理下，formal40相对作者checkpoint的总体Accuracy高1.75个百分点，但优势主要来自mixed场景，clean表现更弱。因此这是条件依赖的系统级比较，不是全面胜出，也不是训练配方受控的因果比较。

| 场景 | 样本数 | Accuracy差 formal40−author（百分点） | 95%区间（百分点） |
| --- | ---: | ---: | --- |
| 全部 | 10,000 | +1.75 | +0.15～+3.37 |
| mixed | 9,000 | +3.51 | +1.81～+5.17 |
| clean | 1,000 | −14.10 | −18.03～−10.21 |

总体Accuracy为formal40 43.76%、author 42.01%、valbest33 45.13%。主模型仍是预定formal40，不因valbest33更高而更换。总体NLL改善（author−formal40）0.0265，95%区间−0.0932～0.1451，不能声称总体NLL明确改善。

旧clean是target-only/zero-cue，不能解释为“正确cue帮助下的干净语音能力”。总体差值依赖90% mixed/10% clean比例。cue控制结果支持模型利用cue并受误导cue影响，但尚不能证明gain强度的因果机制，更不能直接称为儿童到成人的发展。

区间为固定执行配置、target-speaker簇bootstrap。探索性分层不具同时覆盖保证；性别一组显著另一组不显著不等于交互显著。两次48k预测逐位一致说明已测试配置的重复性，不证明所有batch形状一致。数值解释遵守P10勘误，不把有限样本包络当全量定理。

## 证据与图表

- [P10交付](../docs/superpowers/evidence/p10-delivery-20260919/P10_delivery.md)、[P09完整统计](../docs/superpowers/evidence/p09-statistics-20260919/REPORT.md)。
- [数值勘误](../docs/superpowers/evidence/p10-delivery-20260919/NUMERIC_ERRATUM.md)。
- [已有三幅图及图注](../docs/superpowers/evidence/p10-delivery-20260919/figures/FIGURES.md)：不重画、不改原图件。
- 本轮执行`shasum -a 256 -c docs/superpowers/evidence/p10-delivery-20260919/SHA256SUMS.txt`，23项全部通过；这是身份复核，不冒充重新做bootstrap或图文出版验收。

## 主课题证据缺口

| 要回答的问题 | 当前证据 | 缺口/下一实验 |
| --- | --- | --- |
| 自训与作者表现有何差异 | 同bank系统级比较已完成 | 独立确认集、训练/预处理差异限制 |
| 固定权重改变选择增益有何效果 | 有cue敏感性，没有α实验 | E0接口验收→E1固定输入α×cue/SNR |
| 能否用幅度改变解释α效应 | 未检验 | 均匀gain、conv-only、末层均值保持负对照 |
| 训练过程中如何出现选择机制 | checkpoint文件库存存在 | 阶段身份核验→E2交叉分析；单轨迹不作多seed因果推广 |
| α训练日程是否改变学到的能力 | 未执行 | E3配对种子、同训练预算日程实验 |
| 是否解释人类发展 | 尚无匹配的人类留出预测 | E4数据/任务匹配、竞争模型及独立预测；α不是年龄 |

独立数据线已有731名新女性文本候选；先导16人/62条本地解码完成，远端上传状态未知且暂停。不能将先导或开发过的旧bank称为最终独立测试。超算恢复之前不重试上传、训练或评估。
