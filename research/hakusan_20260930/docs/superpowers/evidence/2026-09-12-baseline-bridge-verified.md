# 2026-09-12：原v18无新增hook基线桥接，本地验收

本阶段完成的是**基线推理接口与父数组核对组件的桥接**，不是完整生产worker
或真实模型逐层观测。原v18文件不改写、不替换；没有上传、冻结或GPU提交。
实现与使用说明见[baseline bridge](../prototypes/targeted_worker_20260912/README.md)。

## 实际完成

新组件直接调用原`run_trace_pass`，保留其scene/model操作及执行检查，在原
完整pass输出返回后核对32条数据。检查原commitment、逐批/逐trial记录、
完整身份、worker来源、原签发模型状态、torch实际runtime读回，以及新增
核对过程前后的RNG与数据字节。失败停止并撤销原worker身份，不重推理。
原pass中合法的初始化/RNG变化没有通过重设种子掩盖。

本地17项测试全部通过，零跳过，29.004秒；监督进程总耗时30.179秒，上限
180秒、无自动重试。Python3.11.15、torch2.12.1、NumPy2.4.6，测试子进程
PID79070，CUDA未初始化。

其中A2/B2成功场景各完整执行34次forward，scene/cue批次均为16、16、然后
32个单条批次；各只加载一次合成模型、配置一次runtime。原live attestation
和原state/来源检查真实执行，使用明确的`hermetic-test`域，而非生产域。

拒绝反例覆盖：缺失/伪造身份、非固定源码模块、完整trial身份错配、原scene
作用域退出、新增hook、模型状态改变、替换v18函数、runtime实际读回变化、
父数组摘要不匹配、核对过程引入RNG或结果字节变化，以及重复执行。
父数据不匹配时仅完成pass1的2次forward，不继续pass2，也不返回成功结果。

前一阶段36项数组核对单元测试本轮原样重跑通过（0.616秒），但不把它们
称为新增17项。Ruff通过；v18原28项release SHA及父数组组件SHA仍全部通过。
没有重跑v18的751项完整回归，源码SHA核对不能替代这些回归。

## 最终证据

- [17项测试原始日志](baseline-bridge-local-20260911T162945Z-8aed47e5/output.log)
- [子进程结果及A2/B2调用计数](baseline-bridge-local-20260911T162945Z-8aed47e5/child-result.json)
- [监督方回执](baseline-bridge-local-20260911T162945Z-8aed47e5/receipt.json)
- [三个固定源码SHA](../prototypes/targeted_worker_20260912/SHA256SUMS)

```text
output  081e07e6f3c7c86aafdf612c4e3503565e4d3881151ba4ec719c9eabfe278958
child   bc927e58f9e03a8d7cd5c7b103e5a420a524557ed8e220fc785acad3f19fdc3a
receipt b71e4aebcb47228b4e6243b6a609f8b469d14ee69976e8e0fbfcabd058416dcf
```

完成后另一个只读Python进程独立核对三个源码、两个工件SHA/长度、监督与
子进程PID、17项/零跳过、A2/B2调用数与34批顺序及非生产标记，得到
`INDEPENDENT_BRIDGE_RECEIPT_RECHECK_PASS`。这是回执/工件完整性检查，
不是再次执行推理或独立重算全部数值。

较早`baseline-bridge-local-20260911T162755Z-8sjzd6ob`是开发中间运行，保留
不覆盖；最终源码进一步去掉合成结果中可能误导的父作业成功标签，单独用
`HERMETIC_ARRAY_SCHEDULE_MATCH`和`parent_job_id=null`，并完整重测。
UTC目录16:29:45对应JST2026-09-12T01:29:45。

## 尚未完成与下一阶段

本次真实执行的是原v18软件接口；模型与输入仍是它原有的CPU合成测试
夹具，**没有加载formal40，没有重建真实32条输入，也没有运行Inductor**。
合成参考与候选在同一测试进程内先后执行，不能称为独立冷参考/观测对照。
测试合同来自合成预期值，不是Job685198的真实数组；默认非测试路径固定
真实父合同SHA，合成来源不能进入该路径。

组件没有新hook；新增hook反例目前被原执行检查正确拒绝。下一段需设计并
实现已登记观测器的受控生命周期，再验证同版本接口、生产scratch/父输入/
工件绑定与独立冷进程。不能直接把原检查关闭以运行观测器。非测试scratch
路径要求原实现，但本轮没有执行该生产分支或完整coordinator验收。

本轮`observed_worker_integrated=false`、`real_parent_replay_completed=false`、
`production_model_loaded=false`、`ready_for_gpu=false`，作业数0。新A100
作业需在接入检查后确认范围与预算，不能借用原作业授权无限重提。
最终三模型smoke、10000条same-bank比较及统计报告仍未完成；原1e-6
容差与`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`角色不变。
