# G2 推理连接候选：本地集成完成，生产验证未完成

2026-09-16。用户在Job720730验收后回复“好的”，本轮据此继续本地实现。
**没有SSH、远端查询、上传、输入freeze或新作业；GPU额度仍未批准。**

## 已完成的实现

新目录：[g2_worker_20260916](../prototypes/g2_worker_20260916/README.md)。
固定读取已通过的R/C/D/E准备候选和编译取证源码，不修改旧发布源码或证据。

- 连接strict-load后的模型和原v19受保护的`run_trace_pass`，固定AMP关闭、32条、16→1。
  不调用旧CUDA AMP开启的`predict_batch`来冒充AMP-off参考。
- 完整trial记录与bank身份、实际运行设置、原证据绑定、模型状态和RNG检查；单对象只用一次。
  复用原`_validate_cell_pass`，不改旧`CELL_SPECS`字典或旧比较函数的协议。
- R/C连接已验收取证器的真实目标对象，而非接受调用者填入`compiled=true`。
  新增编译依赖预载入口，要求在模型准备/执行图封存前调用；生产目标须与原compiler lifecycle同一对象。
  这段接线尚未在同版本原生编译或真实模型上执行验证，不能声称接通即通过。
- D/E要求移除目标编译包装，保持同一底层对象。四项官方输出按原1e-6比较，数值差异与执行无效分开。
  新组件对RNG变化采用拒绝策略；旧诊断RNG仅作上下文的规则及历史结论未被改写。
- 返回内存中的两份原始PassResult及摘要；不签发跨进程验收证明，不写生产完成标记。
  worker/coordinator、预算、完整持久工件和独立验收尚需实现。

## 最终本地验证

Python3.11.15 / torch2.12.1，CPU单线程、CUDA不可见。
最终16项测试全部通过、0错误/0失败/0跳过，unittest耗时23.400秒；总监督上限150秒。
3个新Python文件AST语法检查通过。

两个正常冷子进程分别检查D/E：

- 原hermetic fixture扩充为32条完整合成身份，同一模型strict-load一次、configure一次、forward共34次。
- 原始batch顺序为`[16,16] + [1]*32`；NLL/p_target/p_probe最大差0，类别完全相同。
- 完整身份、顺序、缺行、profile、bank内容、AMP标签、输出、伪造worker nonce和模型状态变更被拒绝。
  nonce反例即使重新计算内容哈希仍不能获得原worker身份。
- 模型状态改动触发原guard；连接对象重跑被拒绝。

另两个失败冷子进程在D/E第二轮第一条推理主动抛错：

- 第一轮2次模型调用完成；raw batch尝试到`[16,16,1]`即停止。
- 原异常保留，不返回部分成功结果；当前attestation撤销；同一连接对象不允许重跑。

其余测试覆盖源/函数替换、错误候选profile、关闭CLI、非有限输出/结构错误、原阈值和类别翻转。
数值变化超阈值返回`NUMERIC_DIFF`，不是执行异常；`NUMERIC_ACCEPT`也不等于科学结果验收。

**限制：**D/E都是合成模型和合成题目，未加载formal40；没有A100推理。
本地2.12.1不再有2.1.1的`most_recent_backend`字段，本地eager分支明确记录
`native_cold_state_verified=false`；生产仍强制精确2.1.1检查，不静默降级。
R/C本轮只通过源绑定与错误版本拒绝测试，没有原生compiled连接执行结果。
`production_ready`、`ready_for_gpu`、`production_interference_validated`、`independent_results_verified`均为false。

## 固定证据与复查

- [最终回执](g2-bridge-local-20260916T035404Z-7ol73pxk/RECEIPT.json)
  SHA `b135f56d1f3934f0bc645b2983d541609fef48be56f1320bcd4c782977ee0a81`。
- [逐项测试日志](g2-bridge-local-20260916T035404Z-7ol73pxk/tests.stderr)、
  [合成检查摘要](g2-bridge-local-20260916T035404Z-7ol73pxk/tests.stdout)。
- 同目录`sources/`保存本轮16份来源快照；回执记录测试前后路径、大小和SHA，相同。

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_worker_20260916/validate_local.py \
  verify docs/superpowers/evidence/g2-bridge-local-20260916T035404Z-7ol73pxk
```

本轮同时只读重验原22项准备候选固定证据和Job720730完整CPU证据，均通过；未重跑旧作业或旧测试。

开发中间记录保留，不冒称首跑通过：

- `g2-bridge-local-20260916T034913Z-prveehe_`：14项中2失败/1错误，原因是本地2.12.1缺少2.1.1字段；随后明确分离本地与生产检查范围。
- `g2-bridge-local-20260916T035020Z-e8k6_yqm`：修正后14项通过，后续增加异常退出测试。
- `g2-bridge-local-20260916T035142Z-tlso0knv`：16项中2失败；测试预期异常类型错误，实际原模型RuntimeError正确传播。
  只修正测试断言，没有为了测试通过包装或吞掉原异常。
- `g2-bridge-local-20260916T035253Z-oydxkv_b`：16项通过；之后补scratch绑定、伪造nonce重哈希拒绝和最终源码快照。

上述是中间代码版本日志；以最终固定目录为当前候选验证依据，不用当前源码冒充中间版本。

## 下一项及最终目标距离

1. 先在同版本环境验证R/C取证与原保护链的完整连接，并完成真实formal40严格加载与AMP-off参考/采集端点对照。
2. 补齐有界G2 worker/coordinator、真实32条与旧B2对应、完整工件/独立验收。原scratch API只认旧cell，不能直接套旧submit。
3. 审阅新生产包、冻结输入与G2-M GPU资源后，才单次运行真实R/C/D/E数值矩阵。

G2数值设置选定并独立重复确认后，仍须G3正式冻结、G4三模型smoke、G5完整10k/controls、G6统计、G7报告。
本轮没有得到模型优劣结论；最终仍标记`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
