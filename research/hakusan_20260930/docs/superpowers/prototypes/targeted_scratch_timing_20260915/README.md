# v19 合成 CPU 超时定位（只用于诊断）

本目录仅为 `test_scratch_integration.py` 建立内存中的计时副本。
原 163 文件载荷、运行包、模型、断言、样本、数组验收和数值容差不改变；不部署、不冻结、不提交 GPU。

## 新增观察

- 测试外围 17 个调用位置的 wall/process CPU 计时。
- 原 `PHASE_TIMING` 内存日志同步到有界输出，原 StringIO 内容/getvalue 断言仍保留。
- 导入前启动第 30 秒一次性 `faulthandler` 栈快照，不重复，不打印变量或环境秘密。
- AST 去掉日志包装并恢复 StringIO 构造后，必须与完整原测试 AST 一致，否则拒绝执行。

只改测试副本，不给模型加 hooks，不修改原核心函数、不跳过保护扫描。
插入日志仍可能影响耗时；AST 恢复证明调用/断言结构保留，**不等于已证明原生数值透明性**。

## 固定限制与状态

原生环境限定 Python 3.11.5 / torch 2.1.1+cu118、单 CPU，原 50 秒子进程/90 秒总监督器上限不变。
父传输上限 110 秒，仅使用已认证 SSH master，不重连、不自动重试。临时文件结束后清理。

`CPU_TIMING_EVIDENCE_CAPTURED` 只表示诊断证据完整，可能包含超时；查看
`instrumented_tests_completed` 才能知道计时副本是否结束。
即使计时副本结束，`original_native_compatibility_verified` 也始终为 false。
不会将旧失败改成 PASS，也不会把这些记录当作 formal40 与作者 checkpoint 的比较结果。

入口 `run_timing.py` 提供 `self-test`、`remote-cpu --receipt-directory ...` 和只读 `review`。
远端入口必须先通过同源码的本地计时副本，所有请求/源码/日志/事件和回执均绑定并复核。
不要把诊断入口当作日常反复运行脚本。
