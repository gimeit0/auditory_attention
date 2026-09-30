# 原v18基线执行与父数组核对桥接

2026-09-12：实现**不新增hook的基线接口桥接**。本地通过17项集成/反例测试，
实际调用未修改的v18推理函数和执行检查，但数据与模型使用v18原有的合成
CPU测试夹具。不是formal40实际推理、真实父作业重放或A100验收。

代码：[baseline_bridge.py](baseline_bridge.py)；测试：[test_baseline_bridge.py](test_baseline_bridge.py)；
本地驱动：[validate_local.py](validate_local.py)；[固定源码SHA](SHA256SUMS)。
[最终验收与原始证据](../../evidence/2026-09-12-baseline-bridge-verified.md)。

## 接通了什么

`load_v18(path)`读取原固定SHA源码，直接执行其原始字节，不改写AST、函数
或模块。桥接只接受该加载器创建的同一模块及其原准备器签发的worker对象。
模块函数被替换或代码对象被改写时拒绝继续。

`BaselineBridge(...).run()`直接调用原`run_trace_pass`两次，批大小16、1。
每轮只在原模型已计算完正式输出、原有边界采集完成后，读取返回的CPU
PassResult；不额外推理目标样本，不插入预热，不重新加载或重设随机种子、
编译器、精度设置，不重新生成原pass commitment。

在每轮结束后，将原32条顺序分成原批次交给已固定SHA的父数组核对组件。
除16项数组与4项实际正式输出，还核对原逐批/逐trial/聚合记录、完整trial
身份与bank行号、签发的worker/model nonce及pass commitment。

核对前后调用原v18实时执行检查和签发模型状态检查；六项runtime从真实
torch getter读取，并与上下文标签比较。额外核对消费数组不改变RNG、模型
状态或原结果字节。这里不要求推理前后的RNG始终相同：原推理过程可能有
合法初始化，禁止的是新增核对过程本身改变RNG；不通过重设种子掩盖变化。
任何失败后实例不可重用，并撤销原worker attestation。

原执行流程仍先产出完整PassResult。本组件不是新的流式推理实现，也不
解决整个进程内存峰值。非测试路径要求原`_WorkerScratch`，保留原spill、
verify_spills与两pass生命周期。实际生产scratch/coordinator接入尚未执行。

## 测试范围

独立测试子进程中的A2/B2成功用例各实际加载一次合成模型，配置一次，
执行34次forward；scene/cue批大小均为`[16,16] + [1]*32`。模型、图像音频
数据均是旧测试夹具，不是formal40/checkpoint或Common Voice真实输入。
同一测试进程内另用原接口生成合成预期值；**不是独立冷参考/观测对照**。
没有测试Inductor、安装逐层hook或初始化CUDA。

反例覆盖：缺失/伪造身份、错误模块或源码、完整trial身份错配、退出原
scene作用域、模型状态变化、新增hook、函数替换、精度实测与标签不符、
父数组不匹配、核对过程引入RNG或结果字节变化、实例重复使用。
父数组不匹配时在pass1的两次forward后停止，不继续pass2。

显式`hermetic_test=True`仅接受原`hermetic-test`域对象，返回
`HERMETIC_V18_BASELINE_BRIDGE_PASS`与`HERMETIC_ARRAY_SCHEDULE_MATCH`；
嵌套结果`parent_job_id=null`，不能冒充真实Job685198重放。
默认非测试路径固定真实父合同SHA，并要求原production域/CUDA对象；
不能用合成合同、自行生成SHA或CPU测试身份进入。仍不签发生产授权。

## 尚待完成

这一阶段是基线桥接的本地接入测试，不等于整个真实worker完成。下一段
需要明确、验证已登记观测器的生命周期，使逐层采集可以与原来源/执行/
参数/RNG检查共存。直接在原封闭worker里加hook目前会被正确拒绝；不能
关闭原检查或把失败改成PASS。

之后需同版本真实流程验证、原完整32条输入重建、生产scratch/工件/进程
核验，以及经确认范围和预算的新A100对照。本组件不调用Slurm、写生产
完成标记、修改旧冻结目录，`ready_for_gpu=false`。原1e-6容差未修改。
三模型smoke、最终10000条same-bank比较与统计报告仍未完成。

## 可选本地复验（本轮已完成，无需重复）

最多180秒，单次执行，不自动重试；只新建本地证据目录：

```bash
P=/opt/anaconda3/envs/audattn/bin/python
S="$HOME/发表/超算/docs/superpowers/prototypes"
"$P" -I -B "$S/targeted_worker_20260912/validate_local.py"
```

结果角色仍为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
