# V4 Job 646900 formal40 数值诊断设计

状态：已获用户批准，待制定实现计划  
日期：2026-09-03（Asia/Tokyo）  
诊断性质：工程数值诊断，不是独立测试，也不是科学评估结果

2026-09-10批准的v12增补：coordinator及每个cold child在数值库初始化之前
必须获得原v4 runner固定的CUBLAS_WORKSPACE_CONFIG=:4096:8、OMP_NUM_THREADS=8、
TOKENIZERS_PARALLELISM=false，不继承任意父值，保持精确环境核验与启动记录。
异常补充日志仅包含有限类型/位置和静态原因分类，不输出底层消息/局部变量。
保留原模型/AMP/TF32/compile/矩阵和容差；详见v12-runtime-repair证据文档。

## 1. 背景与已知事实

冻结的 v4 same-bank smoke 作业 `646900` 在同一张 NVIDIA A100-PCIE-40GB 上完成了两轮 32 条样本推理：第一轮请求批量大小为 16，第二轮批量大小为 1。两轮都走完了 32/32，但随后被冻结 canary 主动拒绝发布：

```text
Smoke batch-size canary differs: formal40_nll,
max_abs=0.0077362060546875
```

该失败是 evaluator 的 fail-closed 行为，不是 Slurm 调度失败。比较器按列顺序在首个超过 `1e-6` 的数值列上停止，因此现有证据只支持以下结论：

- 两轮的 trial、scene、cue 身份一致；冻结 scene hash 已通过。
- `formal40_pred_label` 与 `formal40_correct` 一致。
- `formal40_nll` 至少有一个 trial 的绝对差为 `0.0077362060546875`。
- 现有工件无法判定第一个数值分歧发生在 waveform normalization、cochleagram、CNN logits，还是 FP32 `log_softmax`。
- 现有工件也不能证明后续指标或另外两个模型是否一致，因为比较器已提前停止。

最强但尚未证实的假设是：CUDA FP16 autocast、TF32、`torch.compile` 以及不同 batch shape 触发的 shape-specialized CUDA/cuDNN kernel 共同造成可重复的浮点舍入差。PyTorch 的数值准确性说明也明确指出，批量计算与逐样本切片计算不保证逐位相同。本诊断的任务是收集区分这些解释所需的证据，而不是先行接受该假设。

## 2. 目标

第一阶段只诊断 `formal40`，使用 Job 646900 的同一冻结 v4 manifest 和同一 32 条 smoke trial，回答以下问题：

1. 同一 batch shape 重跑是否稳定。
2. `16` 与 `1` 的 batch shape 是否造成差异。
3. 关闭 CUDA autocast 后，跨 batch shape 的差异是否消失或显著改变。
4. 第一个可观测分歧边界位于 normalized waveform、cochleagram、logits，还是 NLL 派生计算。
5. 推理期间 formal40 的参数、buffer 或 RNG 状态是否发生变化。

诊断必须保留完整、可审计的数值证据，即使结果为 `DIFF`。`DIFF` 是诊断观测，不等同于作业失败。

## 3. 非目标

本阶段明确不做以下事项：

- 不修改、重跑或删除冻结 v4 的任何文件或失败 attempt。
- 不放宽 v4 的 `1e-6` canary 阈值。
- 不发布 `SMOKE_PASS.json`、`SAME_BANK_AUDIT_PUBLISHED.json`、`COMPLETE.json` 或任何科学成功标记。
- 不提交完整 10k audit。
- 不评估 `valbest33` 或 `author_external`；只有 formal40 诊断完成并证明有必要后，才另行评审扩展范围。
- 不运行 shuffled、silent 或 distractor control-cue 分支；Job646900 的首个失败字段是主 correct-cue 路径的 `formal40_nll`，第一阶段只隔离该路径。
- 不依据 32 条 smoke trial 报告模型 accuracy、置信区间或模型优劣。
- 不在第一阶段对模型内部所有 leaf module 安装广泛 hooks；如果边界诊断只能把分歧定位到 model forward 内部，再设计一个独立的定向 trace 阶段。
- 不在本阶段决定 v5 应修改精度模式、推理实现或容差合同。

## 4. 冻结边界与固定身份

诊断程序必须精确验证下列冻结对象后才能运行：

| 对象 | 固定值 |
|---|---|
| v4 root | `/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4` |
| evaluator SHA-256 | `31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4` |
| runner SHA-256 | `b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495` |
| manifest SHA-256 | `1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5` |
| evaluation lock SHA-256 | `63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710` |
| formal40 checkpoint SHA-256 | `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` |
| protocol | `fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1` |
| scientific role | `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST` |
| diagnostic protocol | `formal40_batch_invariance_diag_20260903_v1` |

v4 root 在整个诊断中是只读输入。诊断不得调用 v4 的 `run_evaluation()`、attempt 创建函数、publication 函数或冻结 runner。允许从 SHA 已验证的 evaluator 模块白名单式复用纯读取、bank 选择、场景生成、模型加载和推理逻辑；即使为此加载整个模块，也不得解析或调用其 publication surface。所有诊断输出必须写入新的诊断 root。

建议远端诊断 root：

```text
/home/s2510040/audattn_external_eval_diag/
  same_bank_v4_job646900_2026-09-03_v1
```

运行前后分别计算 v4 root 的：

- 目录身份指纹：relative path、type、mode、size、mtime、device、inode、symlink target。
- 文件内容指纹：按相对路径排序后的所有普通文件 SHA-256 汇总。

任一指纹发生变化，整个诊断标记为 `INVALID_FROZEN_ROOT_CHANGED`，即使数值矩阵已经完成也不得解释其结果。

v4 root 之外的实际输入也必须形成闭环。coordinator 在运行前和运行后分别验证：

- v4 `input_freeze.json` 中全部 24 个 pinned file record 的 path、type、size 和 SHA-256。
- `snapshot/manifest.json` 所绑定、且本诊断 import 或执行到的全部 snapshot 文件。
- 32 条 trial 实际引用的全部音频 clip。
- 诊断自己的 `input_freeze.json`、源码、runner 和已提交 runner。

运行前后记录必须逐项匹配；任何文件在四个子进程期间发生变化，都将整个诊断标记为 `INVALID_BOUND_INPUT_CHANGED`。device/inode 只作诊断信息，跨 invocation 的强身份仍是 canonical path、regular-file type、size 和 SHA-256。

所有 Python 入口均使用隔离环境与 `-I -B`，并显式设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONNOUSERSITE=1`、`PYTHONHASHSEED=0`，防止在 v4 或冻结 snapshot 内生成 `__pycache__`。所有可写 cache 和临时目录都必须位于诊断 attempt 或 Slurm 临时目录，不能位于 v4 root。

## 5. 诊断包结构

本地新建独立包：

```text
same_bank_eval_2026_09_03_v4_numeric_diag_v1/
├── diagnose_batch_invariance.py
├── numeric_trace.py
├── submit_numeric_diag.py
├── run_numeric_diag.sbatch
├── test_numeric_diag.py
├── test_submit_numeric_diag.py
└── README.md
```

职责划分：

- `diagnose_batch_invariance.py`：验证冻结输入、选择 32 条 trial、运行单个矩阵 cell、写入 cell 工件。
- `numeric_trace.py`：无副作用的 tensor digest、差异统计、参数/buffer/RNG snapshot 和工件校验函数。
- `submit_numeric_diag.py`：创建 durable intent、检查官方 v4 与诊断 job 是否活动、且仅调用一次 `sbatch --parsable`、验证 Job ID、写 receipt。
- `run_numeric_diag.sbatch`：在一个 A100 Slurm allocation 内串行启动四个相互隔离的 Python 子进程，最后聚合结果。
- 两个测试文件：分别覆盖数值采集/比较合同与安全提交合同。
- `README.md`：记录边界、固定 hash、执行与结果解释方法。

代码不得写入 v4 root，也不得调用任何 publication surface。

## 6. 固定数据与推理语义

### 6.1 Trial 选择

从 SHA 已验证的 10k bank 读取数据，并精确调用冻结 v4 的等价选择规则：

```python
_select_smoke_bank(bank, 32)
```

程序将选择后的 32 个 `trial_id`、原始 bank 行号和身份列写入只读的诊断输入清单。四个矩阵 cell 必须逐 trial 完全一致；不得各自重新随机采样。

### 6.2 场景与 cue

每个 cell 使用冻结 snapshot 内的 `_raw_scene_batch` 与 `_correct_cue_batch`。每条 raw scene 的 SHA-256 必须与 Job584990 的冻结 `scene_sha256` 精确相等。四个 cell 的 raw scene 和 correct cue digest 也必须一致。

### 6.3 模型

每个 cell 在独立 Python 进程中：

1. 重置 Python、NumPy、Torch CPU 和 CUDA seed，使用 v4 的冻结 seed 与 runtime 配置。
2. 在 v4 已修复的冻结 import context 内加载 formal40。
3. 严格验证 checkpoint、config、state-dict 映射和模型角色。
4. 只加载 formal40；不加载另外两个模型，以缩小变量范围和显存占用。
5. 完成两个 pass 后验证全部 parameter/buffer 的身份、版本和内容 digest 均未变化。

seed 只在 cell 进程启动时重置一次，两个 pass 之间不重置，以保持原 canary 的时序语义。

除显式控制的 autocast 开关外，保持 v4 的其余 runtime 设置不变，包括 deterministic algorithms、cuDNN deterministic、cuDNN benchmark false、TF32 enabled 和 float32 matmul precision `medium`。第一阶段不得同时关闭 TF32，因为那会引入第二个自变量。

“只加载 formal40”是有意的变量缩减，也意味着 GPU 显存布局不同于同时驻留三个模型的 Job646900。如果 A2 未复现，不能据此排除共同驻留模型、分配顺序或编译缓存上下文的影响；该限制必须写入结果。

为阻止四个 cell 之间共享编译缓存，每个子进程使用自己位于受验证的 Slurm node-local 临时目录内的 `TORCHINDUCTOR_CACHE_DIR`、`TRITON_CACHE_DIR` 和 `CUDA_CACHE_PATH`。每个 cache 必须在 cell 启动时为空且路径不能落入 v4；其路径和清空前提写入 runtime 工件，但 cache bytes 不属于持久结果。A2 在空 cache 上首先执行；这提高 cell 隔离性，但也属于相对 Job646900 的已记录环境差异。

### 6.4 冻结 ON 路径等价门禁

冻结 v4 的 `predict_batch()` 硬编码 CUDA autocast ON，且不返回 cochleagram 或 logits。诊断因此需要一个可切换 autocast 并返回边界 tensor 的 `trace_predict_batch()`，但它不能未经验证就作为测量工具。

实现必须逐句保持冻结路径的运算顺序：singleton native preprocessing、label/probe transfer、`torch.inference_mode()`、autocast context、scene cochleagram、cue cochleagram、model forward、`logits.float().log_softmax()`、probability、argmax、NLL 和 gather。边界 tensor 只在该 batch 的全部正式输出已经计算完成后才转到 CPU、求 digest 或写文件，避免在算子之间插入 host synchronization。

等价门禁使用两个相互独立、初始条件对称的冷启动进程，不能在同一进程中先跑 reference、再试图只靠恢复 RNG/parameter 来恢复 CUDA allocator、编译器和 cache 隐状态：

1. `REFERENCE_COLD` 加载 fresh formal40，使用自己的空 cache，并以冻结 v4 `predict_batch()` 对同一 32 条 trial 运行 `16→1` 两个 pass；它只写最终输出、输入 digest 和 state/RNG 证据。
2. `TRACE_COLD` 就是矩阵 cell A2。它在另一个 fresh 进程、另一组空 cache 中加载 formal40，并以 autocast ON 的 `trace_predict_batch()` 对同一 trial 运行 `16→1`。
3. coordinator 分别按 pass 和 `trial_id` 对齐两边，要求 raw identity、shape、dtype、`pred_label`、`nll`、`p_target` 和 `p_probe_distractor` 全部逐位相等，并要求两边各自的模型 state 未变化。

执行顺序固定为 `REFERENCE_COLD → A2/TRACE_COLD → equivalence comparison → A1 → B1 → B2`。两个冷启动进程具有相同 seed/runtime，使用互不共享的 node-local cache；不宣称能够重置进程外的 GPU/driver 全局状态。

等价门禁失败时写 `INVALID_TRACE_PATH.json` 并终止；已生成的 A2 工件保留为无效诊断证据，不解释 A2，也不运行 A1/B1/B2。`REFERENCE_COLD` 不是第五个矩阵 cell，不参与四格结果矩阵。

## 7. 四格实验矩阵

每个 cell 是独立 Python 进程；四个 cell 在同一个 Slurm job、同一张 GPU 上串行执行。每个 cell 都重新加载 formal40、重置 seed，并运行两个 pass：

| Cell | CUDA autocast | Pass 1 batch | Pass 2 batch | 目的 |
|---|---:|---:|---:|---|
| A1 | ON / FP16 | 16 | 16 | 检验同 shape 重跑稳定性 |
| A2 | ON / FP16 | 16 | 1 | 重放 Job646900 的 formal40 主路径对比 |
| B1 | OFF / native dtype | 16 | 16 | 检验关闭 autocast 后的同 shape 稳定性 |
| B2 | OFF / native dtype | 16 | 1 | 隔离 autocast 对跨 shape 差异的贡献 |

每个 pass 都按 `trial_id` 对齐输出，不能按 batch 调用序号对齐。

同一 cell 的两个 pass 不重新加载模型，以保持 Job646900 的 canary 语义；不同 cell 使用新进程和新模型实例，以避免 cell 间状态污染。

四格内部顺序为 `A2 → A1 → B1 → B2`；A2 是第一个矩阵 cell，但在它之前有 §6.4 的 `REFERENCE_COLD`。完整顺序和每个子进程的环境必须写入 job summary。

表中的 `native dtype` 表示禁用 autocast 后由模型权重和输入 dtype 决定的执行路径；它不等同于“禁用所有低精度硬件路径”。由于 TF32 仍按 v4 配置启用，结果必须表述为 autocast OFF，而不能笼统称为严格 IEEE FP32。

## 8. 采集边界与比较方法

### 8.1 每条 trial 的采集边界

每个 pass 至少采集：

1. raw scene digest。
2. raw correct cue digest。
3. singleton native preprocessing 后的 normalized scene/cue digest。
4. scene/cue cochleagram feature 的逐 trial digest、shape、dtype、finite 状态和摘要统计。
5. 完整 formal40 logits，按 `trial_id` 保存为逻辑形状 `[32, 800]`。
6. native logits dtype、FP32 `log_softmax`、target logit、FP32 `logsumexp`、target log-probability、NLL、target probability、probe probability、predicted label 与 correct。

为了控制工件体积，不默认持久化全部 cochleagram tensor。程序在内存中完成逐 trial 差异统计，并保存：

- 每条 trial 的 digest 与摘要统计。
- 全局最大绝对/相对差、median、p95、p99。
- 最坏 trial 的 left/right/difference cochleagram tensor。
- 若 cochleagram 完全一致但 logits 不一致，则保存最坏 trial 的完整 logits 和差值；全体 `[32,800]` logits 始终保存。

### 8.2 状态与 RNG

在每个 cell 的 `before`、`between_passes`、`after` 三个时点记录：

- 每个 parameter/buffer 的 name、kind、shape、dtype、device、`_version`、内容 SHA-256。
- Python、NumPy、Torch CPU 和每个 CUDA device RNG state 的 SHA-256。
- CUDA runtime、GPU 名称、Torch/CUDA/cuDNN 版本、determinism 与 TF32 设置。

RNG snapshot 只用于解释，不要求两个 pass 的 RNG digest 必然相等；判定必须结合输出、模型状态和代码路径。

### 8.3 比较合同

对身份字段使用精确比较；对浮点 tensor 同时报告：

- NaN/Inf pattern。
- bitwise equality。
- exact mismatch count。
- maximum absolute difference。
- maximum relative difference，定义为 `abs(left-right) / max(abs(left), abs(right), 1e-12)`，并在工件中记录 `relative_denominator_floor=1e-12`。
- median、p95、p99 absolute difference。
- 最大差位置对应的 `trial_id`、class index 和 left/right 值。

shape、dtype 或 trial alignment 不一致不是有限数值 `DIFF`，而是 cell schema invalid，并导致诊断失败。tensor 级分位数在所有对齐的有限 element 的 absolute-difference 扁平数组上计算；trial 级分位数在每条 trial 的最大 absolute difference 上计算。p50、p95、p99 均固定使用 NumPy `quantile(method="linear")`。

保留 v4 的 `1e-6` 作为“是否会触发原 canary”的参考字段，但第一阶段不把超过阈值当作诊断作业失败，也不据此决定新容差。

每个有效 cell 同时输出细粒度 boundary 状态和一个兼容 v4 的 `canary_status`：身份/离散字段精确相等且正式输出字段最大绝对差不超过 `1e-6` 时为 `PASS`，数值有限但不满足该条件时为 `DIFF`。身份、shape、dtype、trial alignment 或 finite 检查失败时 cell 为 `INVALID`，不生成误导性的 `PASS/DIFF`。边界上的小于阈值非零差异仍被记录，不能被 `PASS` 隐藏。

A2 的重放分类固定为：

- `REPRODUCED`：身份与 formal40 预测标签精确一致，且主路径 NLL 最大绝对差大于 `1e-6`。
- `NOT_REPRODUCED`：身份与 formal40 预测标签精确一致，且主路径 NLL 最大绝对差不大于 `1e-6`。
- `DIFFERENT_NUMERIC_BEHAVIOR`：身份仍正确，但出现预测标签差异或不符合上述两类的其他有限数值行为。

不要求再次得到精确的 `0.0077362060546875`；该值只作为 Job646900 的历史观测与测试 fixture。

### 8.4 第一分歧边界

聚合器按以下顺序报告首个观测分歧：

```text
raw → normalized waveform → cochleagram → logits → log_softmax/NLL
```

如果 cochleagram 一致而 logits 分歧，则第一阶段只能定位到 formal40 model forward。此时生成 `TARGETED_TRACE_REQUIRED.json`，其中列出首个需要检查的子图和最坏 trial；不得在同一实现中自动启用广泛 hooks 或给出更深层根因结论。

## 9. 工件合同

远端诊断 root 的每个 cell 使用独占 canonical 目录：

```text
attempts/slurm-<job-id>/cells/{A1,A2,B1,B2}/
```

等价 reference 使用独立的 `attempts/slurm-<job-id>/reference_cold/`，其中保存两个 pass 的输入 digest、最终输出、runtime、state/RNG 与文件清单，但它不具有 cell 状态。

每个 cell 至少产生：

- `CELL_INPUTS.json`：cell 配置、固定 trial、所有输入 hash。
- `RUNTIME.json`：环境与数值 runtime 设置。
- `STATE_BEFORE.jsonl`、`STATE_BETWEEN.jsonl`、`STATE_AFTER.jsonl`。
- `RNG_BEFORE.json`、`RNG_BETWEEN.json`、`RNG_AFTER.json`。
- `TRIAL_OUTPUTS.csv`：两个 pass 的逐 trial 标量结果。
- `BOUNDARY_DIGESTS.jsonl`：逐 trial 各边界 digest 与摘要。
- `LOGITS_PASS1.npy`、`LOGITS_PASS2.npy`。
- `WORST_CASES/`：受控大小的完整 tensor 与差值。
- `COMPARISON.json`：该 cell 的全量比较结果。
- `CELL_COMPLETE.json`：文件清单、size、SHA-256 和 cell 状态。

提交前还必须原子创建不可变的 `input_freeze.json`，绑定诊断源码/runner SHA、全部 v4 固定身份、选中的 32 个 trial、package schema 和诊断协议 ID。提交状态使用诊断 root 的 `state/`，runner 与矩阵工件使用 `attempts/slurm-<job-id>/`。至少产生：

- `input_freeze.json`：诊断自身的冻结输入清单。
- `state/INTENT.json`：提交前持久化的唯一意图。
- `state/SUBMISSION_RECEIPT.json`：Job ID、提交命令摘要和 runner SHA。
- `attempts/slurm-<job-id>/ENVIRONMENT.json`。
- `attempts/slurm-<job-id>/RUNNING.json`。
- `attempts/slurm-<job-id>/MATRIX_SUMMARY.json`。
- `state/DIAGNOSTIC_COMPLETE.json` 或 `state/DIAGNOSTIC_FAILED.json`。
- `logs/` 中的 Slurm stdout/stderr，以及 `submitted_runners/<job-id>.sbatch`。

`DIAGNOSTIC_COMPLETE.json` 只表示四格及工件完整性验证完成。它不得包含 `SMOKE_PASS` 或科学发布语义。

`WORST_CASES/` 每个边界最多保存一个 worst trial 的 pass1、pass2 和 difference tensor；全部文件合计硬上限为 `1,073,741,824` bytes。写入前计算预计大小，超过上限时诊断以工件预算错误失败，不静默截断或改采样。

## 10. 失败语义

以下情况返回非零并写 `DIAGNOSTIC_FAILED.json`：

- 冻结 hash、路径边界、manifest、bank、checkpoint 或 scene binding 不匹配。
- v4 root 前后身份或内容指纹不一致。
- 任一 cell 缺失、进程异常退出、产生非有限 tensor 或工件不完整。
- 四个 cell 的 trial identity、raw scene 或 correct cue 不一致。
- `REFERENCE_EQUIVALENCE` 未逐位通过。
- formal40 参数/buffer 在推理期间发生变化。
- 无法验证唯一 Slurm 提交或提交 runner 身份。

以下情况仍可成功写 `DIAGNOSTIC_COMPLETE.json`：

- 任一数值边界存在非零有限差异。
- 任一差异超过 v4 的 `1e-6`。
- A2 成功复现或未复现 Job646900。

换言之，作业成功表示“诊断证据完整”，不表示“模型数值一致”。

coordinator 是 terminal marker 的唯一写入者。它捕获正常 Python 异常及 `INT`、`TERM`、`HUP`，尽力原子写入 `state/DIAGNOSTIC_FAILED.json`；但 `SIGKILL`、节点宕机或文件系统中断无法保证执行 trap。若 Slurm 已终止而 `DIAGNOSTIC_COMPLETE.json` 与 `DIAGNOSTIC_FAILED.json` 都不存在，该 attempt 状态定义为 `INCOMPLETE_UNTRAPPED_TERMINATION`，必须结合 `sacct`、log 和残留 `RUNNING.json` 审计，且禁止自动重投。

## 11. 结果解释矩阵

| 观测 | 允许的解释 |
|---|---|
| A1 PASS、A2 DIFF、B1 PASS、B2 PASS | 证据与 autocast × batch shape 联合作用一致 |
| A1 PASS、B1 PASS、A2/B2 均 DIFF | 存在独立于 autocast 的 batch-shape 依赖 |
| A1 DIFF | 同 shape 重跑已不稳定，不能把 A2 单独归因于 batch size |
| B1 DIFF | 关闭 autocast 后仍有同-shape 不稳定，优先检查状态、RNG 或隐藏的非确定路径 |
| state 内容变化 | 模型状态变化证据成立；诊断完整性失败 |
| state 稳定但 RNG 变化且同-shape DIFF | 随机路径成为候选解释，仍需定向验证 |
| state/RNG 解释不足，首分歧为 coch 或 logits | 证据与 shape-specific 数值/算子路径一致，但不能仅凭此命名具体 kernel |
| 四格全部 PASS 或 A2 未复现 | 当前受控环境未复现 Job646900；不得宣称根因已找到 |
| v4 指纹变化或 cell/工件缺失 | 整个诊断无效 |

`PASS`/`DIFF` 在此表中指上一节定义的 v4-compatible `canary_status`，不是逐位相等、模型质量或科学通过状态。

## 12. Slurm 与耐久提交

诊断使用独立 job name，例如：

```text
audattn_v4_numdiag
```

固定资源申请为 GPU-1A、1 node、1 GPU、1 task、8 CPU、`01:00:00` walltime，并设置 `--no-requeue`。runner 使用绝对 `--chdir` 和绝对日志路径，不依赖 SSH 终端或 tmux 保活。

Slurm runner 内的 coordinator 父进程以只读方式打开 v4 的 `state/evaluation.lock`，先取得同一个非阻塞 shared flock，再生成任何 v4/input pre-fingerprint；它持续持锁直到等价门禁、四个子进程、聚合、全部 post-fingerprint 和 terminal marker 写入完成。所有 cell 都是该 coordinator 的子进程，不得各自释放后重新获取锁。现有正式 evaluator 的 Python 核心获取 exclusive flock，因此核心评估不能与诊断并发。无法获取 shared lock 时诊断 fail closed。

该 shared flock 不能阻止一个后来提交的正式 v4 runner 在尝试 exclusive lock 之前先写入 v4 的 log、environment 或 submitted-runner 文件。因此不能声称“shared lock 阻止 v4 的所有写入”；提交前 `squeue` 检查用于降低该风险，而 post-fingerprint 是发现竞态并使诊断无效的最终门禁。

提交器必须：

1. 验证所有本地/远端脚本 SHA 和冻结对象 SHA。
2. 验证诊断 `input_freeze.json`，并拒绝 symlink、非普通文件和越界路径。
3. 同时拒绝活动中的 `audattn_samebank_v4` 与 `audattn_v4_numdiag` job。
4. 在调用 `sbatch` 前原子创建 `INTENT.json`。
5. 精确调用一次 `sbatch --parsable`。
6. 只接受返回码 0 和纯数字 Job ID。
7. 写 `SUBMISSION_RECEIPT.json`；实际 Slurm runner 启动后从 `$0` create-once 归档 Slurm 执行的 spool bytes 到 `submitted_runners/<job-id>.sbatch`，并要求其 SHA 与提交前 reviewed runner SHA 精确一致。
8. 若 receipt 写入失败，保留 intent 与 Slurm 响应并禁止自动重投。

所有状态与结果文件使用 create-once 的原子写入；已存在目标、symlink、hard-link 数异常或路径逃逸均 fail closed，禁止覆盖。

SSH 或 tmux 断开不影响已提交的 `sbatch` 作业。tmux 仅用于观察，不是作业存活条件。

## 13. 测试策略

实现必须采用 RED→GREEN。最低测试集：

- 矩阵精确包含 A1/A2/B1/B2，且每个 cell 独立进程。
- A1/B1 的两个 pass shape 相同；A2/B2 精确为 `16→1`。
- 32 条 trial 由 `_select_smoke_bank(bank, 32)` 的等价规则固定并按 `trial_id` 对齐。
- 数值 `DIFF` 不导致提前退出，四格与全部工件仍完成。
- 使用 `0.0077362060546875` fixture 时，A2 会记录原 v4 canary 差异而不是丢失后续证据。
- tensor recorder 正确处理 tensor、tuple/list 输出和无明确 batch axis 的拒绝路径。
- 参数/buffer 与 RNG snapshot 在数值 DIFF 时仍被写出。
- v4 root 模拟目录在诊断前后 tree/content fingerprint 完全不变。
- 源码和 runner 不含 publication marker 写入或 v4 `run_evaluation()` 调用。
- active official/diagnostic job 阻止提交。
- durable intent 先于且仅先于一次 `sbatch`；非法 Job ID、超时和 receipt 失败都禁止自动重投。
- 独立冷启动的 autocast ON `trace_predict_batch()` 必须在两个 pass 上通过冻结 `predict_batch()` 冷启动 reference 的真实输出等价门禁。
- 全部 manifest-bound 外部输入及实际使用的 snapshot/clip 文件必须通过前后复验。
- SIGTERM 能产生 fail marker；模拟不可捕获终止时，无 terminal marker 的状态只能解释为 incomplete。
- 聚合器拒绝缺失 cell、trial 错位、非有限值、hash 不符或不完整工件。

真实 GPU 中先执行 `REFERENCE_COLD`，随后执行第一个矩阵 cell A2；二者通过等价门禁后，用 A2 检查受控 formal40 核心路径能否重放 Job646900 的现象。由于本诊断排除了另外两个模型、control 分支并增加了边界采集，它不是对原作业进程的逐指令复刻。无论是否复现，都继续完成其余三格；最终 summary 必须明确标记 `REPRODUCED`、`NOT_REPRODUCED` 或 `DIFFERENT_NUMERIC_BEHAVIOR`，而不是为获得预期结论而改变设置。

## 14. 验收标准

本阶段完成需同时满足：

- 本地单元与集成测试全部通过。
- 静态检查和 SHA-256 清单通过。
- 远端诊断 package 使用全新 root，未改变 v4。
- 只提交一个受审查的 Slurm job，并能从 intent/receipt/sacct 证明其唯一性。
- 四个 cell 都有完整、可重新验证的工件。
- `MATRIX_SUMMARY.json` 明确报告每个边界和每个 cell 的数值差异。
- v4 前后 tree/content fingerprint 完全一致。
- 只发布 `DIAGNOSTIC_COMPLETE.json`，不产生任何科学成功标记。
- 总说明文档在结果出来后补充：Job646900 失败证据、诊断版本/hash、作业身份、四格结果、允许与不允许的结论。

## 15. 后续决策门

完成本诊断后，根据证据选择且只选择一个后续方向：

1. 若分歧明确由 autocast × batch shape 触发，单独设计 v5 的推理/容差合同并重新评审。
2. 若 autocast OFF 仍有跨 shape 分歧，进一步分离 TF32 与 compiled/eager，但不得把这些变量混入本阶段。
3. 若首分歧只定位到 model forward，建立针对最坏 trial 和最小子图的第二阶段 trace 设计。
4. 若 A2 未复现，冻结本次环境与工件，先分析 Job646900 与诊断环境差异，不直接重跑 v4。

任何后续 v5 或正式评估都必须保留 v4、Job646900 和本诊断的全部证据链。

## 16. 参考

- PyTorch 2.1 Numerical accuracy：<https://docs.pytorch.org/docs/2.1/notes/numerical_accuracy.html>
- PyTorch 2.1 deterministic algorithms：<https://docs.pytorch.org/docs/2.1/generated/torch.use_deterministic_algorithms.html>
