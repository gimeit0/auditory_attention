# Job685198：完整诊断已验收，批大小数值差异仍存在

## 实际终态与验证

2026-09-11 06:57:22–09:24:04 JST，spcc-a100g06，Slurm COMPLETED、ExitCode0:0，
Elapsed02:26:42。不是TIMEOUT。只有一次提交，没有重提或改变冻结参数。

12:45 JST开始的只读verify-results实际返回DIAGNOSTIC_RESULTS_VERIFIED、
results_verified=true、MATRIX_EVIDENCE_VERIFIED、VERIFY_RC=0。
全套114项工件（211343132字节）的目录清单、来源/提交身份、输入前后、参考
等价及四个cell结果通过当前验证器重验；这不是仅依赖Slurm退出0或完成标记。

- [Slurm和终态查询原始输出](v18-operation-status-20260911T034411193307Z/output.log)
- [完整结果验证原始输出](v18-operation-verify-results-20260911T034513970970Z/output.log)
- 验证输出SHA：9f8f9596ca8e5b91176a20675011e1a968a1ff84ca314f4c6c97d657cbe9491f
- Terminal SHA：4db7f8ba6c63bb58b354cc30486a0e839bb186e31c4845676baa26cd741b72c1
- 工件清单SHA：57e589dd8f679715f49ba65cf841ef26b9e099ccf437024f8d13741afebf228b
- Freeze SHA：bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178

首次验收只下载完成标记、原始日志、矩阵总结、参考等价和追踪需求共5个文件。
随后2026-09-11的下一轮已下载完整114项attempt工件并全部核对SHA，见
[原始工件与离线分析](job-685198-v18/README.md)。远端原件未改；副本仍不包含
全部checkpoint、音频和运行环境，不声称可无需其他输入离线重跑GPU推理。

## 已验证的32条formal40诊断结果

| Cell | 自动混合精度（AMP） | 两次批大小 | NLL最大绝对差 | 预测类别逐条相同 | 数值检查 |
|---|---|---|---:|---|---|
| A1 | 开 | 16 / 16 | 0 | 是 | PASS |
| A2 | 开 | 16 / 1 | 0.003428220748901367 | 是 | DIFF |
| B1 | 关 | 16 / 16 | 0 | 是 | PASS |
| B2 | 关 | 16 / 1 | 0.0024318695068359375 | 是 | DIFF |

原阈值仍为1e-6，没有放宽。A2按固定规则分类为REPRODUCED：预测类别完全
一致且NLL差超过原阈值，并非要求逐位重现Job646900的0.0077362060546875。
本次只有formal40、各组为独立冷进程，不能等同原三模型同时驻留的执行。

A1/B1所有记录边界逐位相同。A2/B2的场景/提示身份、归一化输入及特征相同；
第一处已观测边界差异为logits，之后传播到log概率和NLL。
四组模型状态及RNG检查均保持，没有输入或状态变化的已报告错误。
“第一处观测差异在logits”不是具体算子或底层数值根因的确定结论。

B2仅关闭autocast，TF32和compile仍保留。因此只能说单独关闭AMP未消除差异，
不能称为全严格FP32对照，也不能据此排除TF32、编译或批大小相关算子路径。
32条预测类别一致，不代表10k条或另两模型全部类别一致。

## 下一步边界

诊断验收通过不等于原三模型SMOKE_PASS，更不是最终三模型10k对比完成。
需要先审阅TARGETED_TRACE_REQUIRED及最坏样本索引，针对logits边界设计定点
追踪/对照，形成有证据的数值执行方案；不能直接放宽阈值、换成同批大小
冒充原16对1 canary通过，或改写旧冻结文件。
本轮只读取证与验收，没有修改生产代码、数值设置、冻结输入或提交新作业。

已读取并核对的TARGETED_TRACE_REQUIRED将后续范围限定为formal40 model forward
（cochleagram输入到native logits）；A2最坏trial_id=9000、B2=1428。
该文件是追踪需求，不是已经完成的逐算子追踪结果；需独立审阅后续方案。

最终比较仍须formal40主结果、valbest33补充、作者外部参考的完整smoke与10k
bank/既定control、成对统计与CI，并保留
REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST标签。当前不作模型优劣排名。

## 后续离线发现（2026-09-11）

完整logits/CSV复查确认：A2/B2各32条logits均变化，类别仍一致；NLL超过
1e-6的样本分别30/32和29/32。NLL最坏trial分别4126、2698，与原marker的
logits最坏9000、1428不同。CPU float64复算仍保留约0.00343/0.00243的NLL差异。
已写入[四目标追踪方案与观测有效性门禁](2026-09-11-job685198-offline-findings-and-trace-plan.md)。
仅离线工具及14项测试已完成；逐层追踪尚未实现或提交，不能声称已定位具体层。
