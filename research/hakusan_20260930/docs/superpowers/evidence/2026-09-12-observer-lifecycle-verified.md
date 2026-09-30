# 2026-09-12：受控观测生命周期，本地 CPU 验收

已实现[观测生命周期原型](../prototypes/targeted_lifecycle_20260912/README.md)，
接续无 hook 基线桥接。**25 项新增本地测试通过，零跳过**；不是生产
formal40、独立冷进程、Inductor/A100 或最终三模型对比的验收。

## 实际做了什么

固定回调在原身份签发前安装。测试通过原 v18 的 `model_to_load` 合成夹具
槽把带回调的模型交给原加载流程，再调用未修改的原准备/推理函数。没有
复制或替换科学函数，没有在身份签发后放宽 hook 检查或重算已有身份。

两条成功路径 A2/B2 各一次模型加载、一次 runtime 配置，32 条按 16、16、
随后 32 个单条批次执行，共 34 次 forward。每条路径的四个阶段调用 136
次，共采集 16 份目标张量、13184 字节；采集文件在接受前逐字节重读校验。
共享 stem 被调用两次。所有原 pass 输入/输出、正式指标和 commitment
通过既有数组 gate；新增观测输入/输出同时与原逐批 guard 摘要一致。

运行中的固定源代码/方法、模块、hook 和 flags、计划、批次和阶段覆盖、
追加账本、采集记录和预算被单独核对。原 v18 的 live、状态、来源和
runtime 检查保持。成功或失败结束后移除本组件 hook 并撤销相应旧身份；
失败不能继续第二 pass 或作为成功结果重用。

新增拒绝反例覆盖：签发后登记、活动作用域外调用、删换 hook、错序/缺失/
多余阶段、方法替换（类与实例）、计划/账本/预算改动、RNG/runtime/输入/
注册状态/端点变化、父摘要不匹配、重复运行与非测试域。预算不足在复制
前停止且不生成采集文件；端点/父摘要不同只执行 pass1 的两次 forward。

## 完整证据与复核

最终监督目录：
[observer-lifecycle-local-20260911T171555Z-_1x_15st](observer-lifecycle-local-20260911T171555Z-_1x_15st/receipt.json)。
UTC17:15:55 对应 JST2026-09-12T02:15:55。

- [25 项原始日志](observer-lifecycle-local-20260911T171555Z-_1x_15st/output.log)：25 项、零跳过，46.957 秒。
- [子进程结果](observer-lifecycle-local-20260911T171555Z-_1x_15st/child-result.json)：PID79506，A2/B2 调用及采集计数。
- [监督回执](observer-lifecycle-local-20260911T171555Z-_1x_15st/receipt.json)：returncode=0，总48.474 秒；上限180 秒，无自动重试。
- [三个固定源码 SHA](../prototypes/targeted_lifecycle_20260912/SHA256SUMS)。

```text
output  1e38674408b7aac774633dba6b72f957a3f1099a92c48ce53822d54f319fdb88
child   57fe16b428bbfa104526d66e50c212f9f9fd1bacef0a33ee5d6eb18de9c4651a
receipt 9a658e9b3ae747dda08801a20ffc1babcbd5368fe1537ff8fbff15e5fd897b9a
```

本机 Python3.11.15、torch2.12.1、NumPy2.4.6，CUDA未初始化。另一个只读
Python 进程复核源码/日志/结果 SHA与长度、PID、25项零跳过、A2/B2各
34/136/16计数及非生产标记，得到 `INDEPENDENT_LIFECYCLE_RECEIPT_RECHECK=PASS`。
这是回执完整性复核，不是重新计算全部推理数据。

原基线桥接17项原样重跑通过（29.518秒），Ruff通过；原v18的28项发布
文件SHA、原基线桥接三个源码SHA仍通过。没有重跑v18的751项完整回归。

较早开发运行 `observer-lifecycle-local-20260911T171433Z-xvbpzamx` 保留为失败
证据：25项中一项预期了新组件错误类型，实际由更早的原runtime检查正确
拒绝。只修正测试为预期原 `DiagnosticError` 并断言清理、一次forward和
未偷偷恢复被改标志；组件运行代码没有因此改变，随后整套重新验收。

## 不能由本次 PASS 推导的结论

固定 hook 通过 `ContextVar` 路由。v18 的原执行摘要不包含这个对象的当前
记录器内容；新生命周期检查是明确增加的独立约束，不是已经纳入生产
来源认证的能力，也不抵抗能任意同时修改 Python 对象/校验逻辑的攻击。

本次模型为小型CPU夹具、四个阶段，不是真实formal40的42位置；参考与
观测在同一测试进程内先后创建，不是独立冷进程。A2/B2的CPU测试标签不
证明CUDA AMP工作。没有真实父32条输入重建、同版本torch2.1.1复验或
Inductor执行。原型明确拒绝编译模型/生产域/GPU，不能直接提交到A100。

真实加载器的显式签发前登记接口、观测器源码来源绑定、首次编译允许的
状态/RNG变化、生产scratch和独立冷进程归档集成仍待完成。测试采集临时
文件随测试清理，当前留下的是日志/计数/摘要，不是完整真实特征归档。

本轮未连接超算、未上传/冻结/提交作业；生产接入和ready_for_gpu均false。
下一阶段先接通生产准备流程与真实绑定，完成同版本和冷进程检查后再确认
新GPU预算。原1e-6容差和`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`
角色不变；最终三模型smoke及10000条same-bank比较仍未完成。
