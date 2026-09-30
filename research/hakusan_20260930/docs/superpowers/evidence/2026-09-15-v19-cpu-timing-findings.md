# 原生 CPU 超时定位：停在合成预期结果生成，尚未进入待测 mmap 流程

日期：2026-09-15 JST。对应用户“开始吧”，本轮完成阶段计时与一次原生栈采样。
没有修改冻结运行包、模型、原测试、断言、样本数或容差；没有新 GPU 作业。

## 结论与限制

此次 HAKUSAN 定位运行在 `fixture.expected_contract()` 中耗尽原 50 秒子进程上限，
没有进入随后要测的 `archived_reference`、mmap/spill 和归档验收流程。
30 秒 watchdog 的一次栈快照显示，当时执行路径为：

```text
test_real_mmap_two_pass_original_cpu_lifetime
  → fixture.expected_contract
  → diag.run_trace_pass → trace_predict_batch
  → _invoke_attested_operator → _live_inference_attestation
  → _validate_frozen_capability_contents
  → _callable_graph_fingerprint_impl
  → _referenced_attribute_values → _static_attribute
  → _safe_instance_dict（模块字典键类型检查）
```

因此，后续排查应先针对**合成预期结果生成中的完整性扫描开销**，不应把这次超时直接归因于
mmap、实际归档或真实模型推理。单次栈只证明采样时的位置，不证明该行占据全部耗时，
也不能据此断言存在死锁、数值错误或某项优化一定能解决 GPU 超时。

## 实际观测

| 阶段 | 本地计时副本 | HAKUSAN 计时副本 |
| --- | --- | --- |
| 导入与 fixture 定义 | 约 0.934 秒 | 约 6.395 秒 |
| `fixture.expected_contract()` | 约 11.259 秒后返回 | 计时器约 6.747 秒处进入，终止前未返回 |
| 随后的 `archived_reference` | 约 5.351 秒，两轮均完成 | 尚未进入 |
| 既有内层阶段事件 | 36 条 | 0 条 |
| 外围阶段事件 | 42 条 | 10 条 |

本地 Python 3.11.15 / torch 2.12.1；原生 Python 3.11.5 / torch 2.1.1+cu118，CPU affinity `[0]`。
本地两个加计时的合成测试全部完成；原生子进程约 50.143 秒结束（含停止/回收），
RC=-9、`child deadline reached`；监督器载荷 50.189 秒，SSH 传输 58.309 秒。
原生临时目录清理成功。不同机器/版本和额外日志都会影响时长，表格不是 GPU 性能预测。

在导入阶段，原生 wall 时间约 6.395 秒而 process CPU 增量约 1.575 秒，说明 wall 时间不能简单当作
纯计算时间；该差值本身也不能区分 I/O 等待与调度竞争。预期结果生成没有结束计时，不能算出其完整 CPU 占比。

## 为什么“预期结果生成”本身会运行很多检查

固定 [test_baseline_bridge.py](../prototypes/targeted_worker_20260915_scan/test_baseline_bridge.py) 的
`expected_contract()` 对 A2、B2 两个合成条件分别运行 batch=16 与 batch=1 两轮，
每个条件断言 model 调用数为 34，即先做 68 次合成调用生成比较用数据。
之后 scratch 测试还会另做 B2 的 34 次调用；这些是测试准备和待测运行，不是真实模型的正式比较。

栈中 [v19 核心](../../../same_bank_eval_2026_09_03_v4_numeric_diag_v19/diagnose_batch_invariance.py) 的
`_validate_frozen_capability_contents` 会重算已绑定 evaluator callable 的图指纹；
`_safe_instance_dict` 对模块字典逐键检查是否为精确字符串类型。当前 v19 的已发布优化针对
`_live_protected_module_bindings`，不是此次采样落到的这一条检查链。
这些源码事实解释了有额外扫描工作的来源，但尚无调用计数/累计时间足以量化各子函数占比。

## 本轮诊断实现与验证

- [诊断入口目录](../prototypes/targeted_scratch_timing_20260915/README.md)：只在内存中派生测试副本，17 个外围位置加日志。
- 将原本写入 StringIO 的 `PHASE_TIMING` 同步到有界 stdout，同时保留原 getvalue 和全部断言。
- 去除日志包装并还原 StringIO 构造后，完整 AST 必须与原测试一致；不修改模型 hooks 或原核心函数。
- 单次 30 秒栈采样；原单 CPU、50 秒 child、90 秒 supervisor 和 110 秒传输上限不变。
- 10 项离线检查通过；先做一次本地计时副本，再做一次 HAKUSAN 原生定位，没有自动重试。
- 旧失败证据与原 163 文件载荷逐字节保留。栈、日志、源码与请求均可复核。

AST 恢复证明调用/断言结构保留，不等于证明计时副本与原执行数值完全透明。
`CPU_TIMING_EVIDENCE_CAPTURED` **只是取证成功**；此次原生 `instrumented_tests_completed=false`，
`original_native_compatibility_verified=false`，绝不是整体测试 PASS。

## 证据

- [本地回执](v19-cpu-timing-local_harness-20260915T051849Z-epoxgzfd/receipt.json)：`61475e02091802eb591ec3364cb8adf69e785e4197b3f62634537800067bb505`
- [原生回执](v19-cpu-timing-native_cpu-20260915T052238Z-ruc59wt8/receipt.json)：`d45ab178c012f66053aa70de00f508477216d6a64e720e9628cbd632c140c377`
- 原生子日志：`413979737e3513a6d467372359ba4d4c4523776ed2696e4494f4c72dc0b721eb`，5975 字节。
- [固定 SHA 只读复核脚本](2026-09-15-v19-timing-review.py)，不连接网络、不重跑测试。

## 下一项（尚未实施）

在独立性能候选中，量化 `_callable_graph_fingerprint` / `_safe_instance_dict` 的调用次数、
模块字典大小和累计开销，再选择不减少检查、不缓存可变对象验收结果的等价优化。
需要保留并回归对键类型、模块/函数替换、可变配置变化及副作用属性访问的拒绝能力。
也可评估将合成预期数据的生成与待测流程拆为独立的、内容绑定的测试阶段，但不能直接删除 A2、
缩小 32 个样本、跳过数据核验或把旧通过记录冒充新执行。

当前仍为 78 项原生完整核验、最后一组待验收；新 freeze、部署控制审核和 GPU 新授权尚未完成。
不重跑旧 submit 脚本，不改变资源限制，不将本结果解释为 formal40 对作者 checkpoint 的最终结论。
