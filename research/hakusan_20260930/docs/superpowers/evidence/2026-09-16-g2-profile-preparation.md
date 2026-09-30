# G2：四组设置的加载准备候选与本地验证

2026-09-16 JST。**完成本地准备单元，未完成真实G2数值对照；无SSH、上传、freeze或新作业。**
此前CPU Job718727的验收不变。本轮服务主计划G2，不继续扩展全部逐层追踪工具。

## 实现和检查依据

从固定来源读取，而非推测CLI参数的效果：

- 模型源码SHA `6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9`：
  构造时编译 `self.model`，forward仍调用该绑定；compile目标是内部模型而非整个Lightning对象。
- 原v4 evaluator SHA `31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4`：
  formal40 strict-load不允许编译前缀重写，只有author_external具备该兼容规则。
- 原v19 core SHA `c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d`：
  保留原加载/运行/状态保护链；适配在新模型inventory和attestation之前完成。

因此不是给 formal40 构造器传 `compile_model=False` 后放宽权重键检查。
新D/E先原样strict-load，再把同一内部模型从包装中取出作为forward目标；
R/C保留包装。全部参数/缓冲区对象、内容、运行设置及RNG适配前后核验。
新身份由独立派生源承载，适配记录绑定到新的加载报告SHA；旧源码/旧证明不冒用。

| 组别 | TF32矩阵乘/卷积 | precision实际读回 | compile包装 | AMP |
| --- | --- | --- | --- | --- |
| R | 开 | high | 保留 | 关 |
| C | 关 | highest | 保留 | 关 |
| D | 开 | high | 移除，底层对象不变 | 关 |
| E | 关 | highest | 移除，底层对象不变 | 关 |

所有组仍要求三项deterministic/cuDNN设置、固定seed、生产CUDA初始化前CUBLAS配置及原1e-6规则。
派生器7处替换能逐字节还原旧core；除准备函数和被禁用的main，其余275个顶层函数/类AST一致。
这只说明保留原定义，不宣称所有新组合的生产行为已得到证明。

## 实际测试结果

[候选与短命令](../prototypes/g2_profiles_20260916/README.md)。
本地Python3.11.15/torch2.12.1，22项全部通过、无skip；最终证据运行耗时21.109秒（总限120秒）。

- 四组精度读回、wrapper/底层对象绑定保持；错误模式、hook、可训练/非有限状态及额外包装拒绝。
- 适配期间模型内容或RNG变化拒绝；错误运行设置不被自动“修复”后冒充原参考。
- D/E分别在独立冷进程，以原hermetic fixture及原保护链执行32条合成样本、batch16→1，共34次模型调用。
  pred_label/NLL/p_target/p_probe逐位一致；随后修改模型buffer时原guard拒绝下一次推理。
- 本地包装端点等价使用CPU `backend='eager'`，不是Inductor对照；R/C的原生编译生命周期尚未验证。
- CUDA未初始化、真实模型未加载、作业提交数0。代码及固定来源在测试前后哈希不变。

本轮最初集成测试曾把D/E放在同一解释器中，触发原验证模块注册冲突，21通过/1错误。
改成每组独立冷进程后通过；没有清空注册表、跳过身份校验或放宽数值标准。
初次诊断输出在本轮终端记录，持久证据目录保存的是修正后最终运行，不冒称首跑即通过。

## 固定证据和复查

目录：[g2-profiles-local-20260915T153933Z-07dtorzu](g2-profiles-local-20260915T153933Z-07dtorzu)。
文件名日期为UTC，对应9月16日JST。
[回执](g2-profiles-local-20260915T153933Z-07dtorzu/RECEIPT.json)、
[结构化测试输出](g2-profiles-local-20260915T153933Z-07dtorzu/tests.stdout)、
[逐项测试日志](g2-profiles-local-20260915T153933Z-07dtorzu/tests.stderr)。
另保存R/C/D/E派生源和各自可逆变更清单。

回执SHA：`fe1f4d7484bcf34651d30a81bc9ecf6da3da8cd5ad9f96d235d26bab75f80395`。
新进程只读复查会重新哈希来源/日志/候选并重新派生比对；它不是GPU结果验收。
执行命令见候选README。原v4/v19源码、checkpoint、数据和旧失败工件未修改。

## 未完成项：不是新的可提交版本

1. 目标绑定的实际编译执行取证。旧`entered`只表明上下文进入；
   `_g2_backend_gate`目前仅判断条件，不能把调用方传入的布尔值升级为可信执行证明。
2. HAKUSAN2.1.1同环境兼容性、真实来源加载、R/C Inductor路径和生产端点/状态/采集等价。
   原v4 `predict_batch`在CUDA上启用AMP，不能直接当AMP-off基准。
3. 生产worker/coordinator、全部32条完整身份与旧B2的对应、限时/工件预算及独立结果验收。
4. 审定G2规格、资源和新freeze，再单次提交G2-M。拟议GPU预算仍未批准，不自动提交G2-R。

候选CLI被明确禁用；不提供能误触旧submit的命令。下一项是完成上述生产绑定和必要验证，
不是继续刷测试数量，也不是重跑旧失败作业。正式10k三模型比较及统计报告尚未完成。
最终报告仍须使用 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST` 标签。
