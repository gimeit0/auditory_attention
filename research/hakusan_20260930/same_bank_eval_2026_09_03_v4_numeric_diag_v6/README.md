# formal40 批大小数值诊断工具

状态：诊断 v6 本地修复及回归已完成，待候选复核与集群验收；尚未上传、冻结
或提交。下方远端命令不是
当前执行指令，须在新根只读预检、受控部署与最终校验完成后使用。
诊断 v1–v5、原冻结评估 v4 和失败作业证据必须保留，不能原地替换。

## v6 修复范围与验收边界

诊断 v5 Job 670830 在执行前读取外部 v4 input_freeze.json 时失败：
`noncanonical owner JSON`。原 v4 的 SHA 固定清单是 indent=2 的 JSON；
协调器错误地对它施加了诊断自身紧凑 JSON 的格式约束。audit/check-only
读取路径没有同样的格式要求；协调器测试夹具也错误地采用了紧凑格式。

v6 先用 SHA 核验过的真实 v4 序列化函数修正文件系统夹具，复现 PRE、matrix
入口及结果验证链路失败。修复仅增加固定 v4 清单专用读取入口，在解析前校验
原始字节 SHA，并按 v4 的缩进/排序/末尾换行规范核验；PRE/POST、matrix 和
成功结果验证共同使用该入口。绝不重排或回写原清单，也不重新设定可信哈希。
诊断自身的 freeze、journal、terminal 等仍使用严格紧凑 JSON 读取器。

新增 test_v4_manifest_json.py 覆盖真实 v4 格式、错误哈希、格式错配、重复键、
非有限数、符号/硬链接、读取期竞争与真实 PRE/POST、CPU 持久化矩阵结果复验。
CPU 合成矩阵不是实际 formal40/A100 实验；本地通过不能证明完整集群运行成功，
也没有解释 Job 646900 的 NLL 差异。模型、bank、SNR 和原数值容差均不变。

2026-09-08 本地验收：344 + 66 + 6 + 28 + 21 = 465 项测试通过；
五个入口分别在独立 Python 进程执行。Ruff check/format、runner bash -n 和
CLI help 检查通过。本地 Python 3.11.15 / torch 2.12.1；没有新独立代理审查，
没有连接集群，不能将该候选视为已发布或已完成 A100 端到端验收。
证据：`../docs/superpowers/evidence/2026-09-08-diagnostic-v6-json-boundary-repair.md`。

## v5 修复范围与验收边界

v4 独立复查发现：真实 strict_load_model 合法导入 src.spatial_attn_lightning
时，其模块绑定从未加载变为授权对象，仍被固定函数图误报。v5 的回归先在
未修复逻辑上复现失败，再限定处理为：只有固定 SHA 加载器签发的那个真实
strict_load_model 对象、那一条确定的 src 导入使用快照授权身份；不再于签发
阶段从进程搜索路径提前加载 src。在有效快照作用域内仍核对来源、声明与
模块绑定；普通函数、其他导入和 torch/yaml 依赖继续固定绑定。

专项覆盖授权 src 导入、未经授权替换、普通同名导入不获例外、缺失源声明、
封闭后新增导入，以及真实冻结 strict loader 加载临时 CPU checkpoint、封闭
模块绑定后再次推理并复验 evaluator 图。
后者使用小型夹具模型，不是真实 formal40，也不证明 A100 兼容性或原始数值
差异原因。冻结评估 v4、checkpoint、bank 和数值阈值均未修改。

## v4 修复范围与验收边界

v3 的真实 evaluator 在临时模块退出和合法导入后出现函数图误报。本候选仅对
固定 SHA 验证过的导入上下文读取器，使用进程模块注册表身份与冻结快照模块
授权检查；普通函数仍检查容器内容。冻结模块的替换、源码篡改、函数代码和
模块来源变化必须拒绝，作用域退出后回调失效。生产 worker 准备完毕后封闭
模块绑定集合。直接 import 的模块绑定和可解析属性仍纳入函数图。

本地 PyTorch 的 Dynamo 首次导入会包装 torch.manual_seed，因此必须在签发
不可变函数图前导入 Dynamo；签发之后不重新设定基线，也不放过函数替换。
新增 test_real_evaluator_scope.py 使用真实冻结 evaluator 源码和临时快照夹具，
不代表真实 checkpoint、音频或 A100 端到端验收。原始数值阈值保持不变。

## v3 修复范围

v2 实际 audit 在生产 capability 注册时失败：外层以 v4 根目录读取 evaluator，
加载器以 tools 为根目录，记录中的 relative_path 不同。v3 给加载器增加显式
allowed_root，外层传入同一个 v4 根目录；保持精确记录比较、哈希校验和路径
边界拒绝。其他调用者不传该参数时保留原先父目录基准。

新增 test_loader_record.py 覆盖真实双读取、真实 capability 注册、外层上下文
调用、错误 SHA 与越界拒绝。临时 evaluator 和科学 inventory/history 验证夹具
不等同于真实模型/GPU 端到端验收。诊断根和诊断协议提升 v3；v4 身份、32
trial 数值诊断设计、batch-size canary 阈值和模型角色不变。

## v2 修复范围

真实 v4 freeze 的五组输入共 24 项，加上 layout.evaluation_lock 共 25 项。
v1 错把布局锁纳入输入计数，并在下游要求锁属于该集合，导致 audit-inputs
在冻结前失败。v2 按冻结 v4 原始五组、仅遍历 mapping 的规则收集 24 个角色，
保留重复路径角色和顺序；布局锁另行核对固定路径、大小、SHA 与实际内容，
协调器 PRE/POST 仍绑定锁。没有把 24 改成 25，也没有放宽锁或数值门槛。
测试以带 layout 的真实结构形状为基础，并直接对照冻结 v4 源码中的遍历函数。
诊断根和诊断协议版本改为 v2；冻结 v4 身份及科学评估协议不变。

## 目标与已知事实

最终目标是 formal40、valbest33 和作者 checkpoint 的同 bank 对比。本包只解决
之前的数值一致性阻塞，不执行三模型完整 10k audit，也不重新训练模型。

v4 smoke Job646900 在 2026-09-01 完成两次 32-trial 推理后失败：
`formal40_nll max_abs=0.0077362060546875`。这证明批大小 canary 不一致，
并未证明模型损坏、预处理错误、AMP 或 TF32 是原因。本包不放宽原有阈值，
不修改 v4、bank、checkpoint、SNR、模型角色或科学协议，不发布 SMOKE_PASS。

所有产物仍属于 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，
不能称为独立测试成绩。作者模型最终只作为 system-level external reference，
不是任务条件完全匹配的模型排名。

本包仅加载 formal40，改变了 Job646900 三模型同时驻留的分配上下文。
即使 A2 不复现，也不能排除原始多模型驻留或编译器缓存上下文的影响。

## 文件与固定身份

十个文件：诊断入口 `diagnose_batch_invariance.py`、追踪原语 `numeric_trace.py`、
单次提交器 `submit_numeric_diag.py`、runner `run_numeric_diag.sbatch`、五个
`test_*.py` 和本 README。远端生产 tools 只放前四个文件；测试和 README 保留本地。

固定诊断根：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v6`

冻结 v4 根：
`/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4`

诊断协议：`formal40_batch_invariance_diag_20260903_v6`。
v4 协议：`fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1`。
训练 run：`fullpilot4_accum9_20260815_181000`，formal40 为 epoch40、global_step69440。

| 冻结对象 | SHA-256 |
| --- | --- |
| v4 evaluator | `31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4` |
| v4 runner | `b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495` |
| v4 input_freeze.json | `1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5` |
| v4 evaluation.lock | `63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710` |
| formal-final.ckpt | `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` |

其余输入身份由上述 v4 manifest、24 项 pinned files、冻结快照源清单、选定
32 个 trial 及所用音频清单共同绑定，不能用当前工作目录文件替代。诊断 freeze
是以后在新根生成的新文件，其哈希不是上表中的 v4 manifest 哈希。

## 本地校验与测试（Mac）

先进入本 README 所在目录。下面只读验证已记录的九个候选哈希，不是重新生成
expected 值。最终发布还须在外部验收记录核对 README 自身哈希。

```bash
sed -n '/^<!-- RELEASE_SHA256_BEGIN -->$/,/^<!-- RELEASE_SHA256_END -->$/p' README.md |
  sed '1d;$d' |
  /usr/bin/shasum -a 256 -c -
```

```bash
P=/opt/anaconda3/envs/audattn/bin/python
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
"$P" -I -B test_numeric_diag.py
"$P" -I -B test_submit_numeric_diag.py
"$P" -I -B test_loader_record.py
"$P" -I -B test_real_evaluator_scope.py
"$P" -I -B test_v4_manifest_json.py
/bin/bash -n run_numeric_diag.sbatch
ruff check --no-cache .
ruff format --check --no-cache .
```

各命令必须退出 0。模拟集成启动五个真实本地进程，但使用合成 CPU 张量、GPU
元数据和调度器响应；实际验证了传输、持久记录和验收链路，不代表 A100 结果。
五个测试入口必须分别使用独立 Python 进程；合并 discover 会因现有模拟集成
重新加载诊断模块而触发 `_numeric_trace_verified` 名称占用保护。

## 发布流程：仅在 Task 9 发布复审通过后

1. 在 Mac 核对外部验收记录中的 README 哈希及上面的八个文件哈希。
2. 只使用固定的新诊断根；若已存在，停止并只读检查，不能删除、覆盖或自动重试。
3. 在新根 staging 上传四个生产文件，逐一核对本 README 的预期哈希；拒绝符号链接。
4. 以 create-once 操作发布到 tools，核对最终文件身份后才清理本次 staging。
   不能覆盖既有 tools，也不能修改或清理 v4 与失败作业证据。
5. audit → freeze → 人工核对新 freeze 哈希 → check-only → 单次提交。

这是受控部署流程，不是授权执行。实际创建／上传命令由 Task 10 根据远端只读
检查结果给出，不能靠重复运行整个部署块恢复。

## 远端命令契约（HAKUSAN；现在不要运行）

以下命令仅用于发布批准后已创建、已核验的根。使用短变量和数组，避免把参数
中间的换行当成新命令。不要把中文说明或提示符复制进终端。

```bash
R="$HOME/audattn_external_eval_diag"
R="$R/same_bank_v4_job646900_2026-09-03_v6"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
S="$R/tools/submit_numeric_diag.py"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
"$P" -I -B "$D" audit-inputs
```

audit 通过后，只 freeze 一次。失败时保留现场，不重新创建根或复用 v4 的 freeze。

```bash
A=(freeze-inputs --confirm-protocol)
A+=(formal40_batch_invariance_diag_20260903_v6)
"$P" -I -B "$D" "${A[@]}"
```

从已审阅的 freeze 输出／外部记录输入新诊断 freeze SHA，不能自动对当前文件
计算哈希后把它当作可信 expected 值。check-only 通过后才考虑提交。

```bash
read -r -p 'Reviewed diagnostic freeze SHA-256: ' F
A=(check-only --expected-input-freeze-sha256 "$F")
"$P" -I -B "$D" "${A[@]}"
```

下列提交器先验证输入、队列和持久记录，然后最多调用一次 sbatch。不要直接
调用 runner、协调器或内部 `_child-*` 入口。

```bash
A=(submit --confirm-action)
A+=(SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC)
A+=(--confirm-v4-job-id 646900)
A+=(--expected-input-freeze-sha256 "$F")
"$P" -I -B "$S" "${A[@]}"
```

输出不确定、断线、超时、已有 INTENT／执行证据时，只查 status，绝不自动重提。
确认 sbatch 成功后，作业由调度器负责，不依赖 SSH 或 tmux 连接；tmux 只用于
观察。交互式 srun 不是这里的提交方式。

```bash
"$P" -I -B "$S" status
```

status 只报告调度／记录状态，不证明数值结果有效。Slurm COMPLETED 也不等于
通过。作业结束后，从已核对回执输入诊断 Job ID，并运行真正的只读结果验证：

```bash
read -r -p 'Diagnostic job ID from reviewed receipt: ' J
A=(verify-results --expected-input-freeze-sha256 "$F")
A+=(--job-id "$J")
"$P" -I -B "$D" "${A[@]}"
```

## 执行矩阵与产物

依次运行五个独立进程：reference_cold → A2 → A1 → B1 → B2。
参考走冻结 predict_batch；各 cell 为相同 32 个 trial 的两次推理。

| cell | autocast | 两次 batch size |
| --- | --- | --- |
| A2 | 开启 | 16、1 |
| A1 | 开启 | 16、16 |
| B1 | 关闭 | 16、16 |
| B2 | 关闭 | 16、1 |

每个子进程使用独立 scratch／缓存，父进程绑定 PID、参数、输入哈希、完成记录
及持久文件。正式产物在 attempts/slurm-JOB 下，含 reference_cold、cells、
输入／环境记录、边界与输出证据、比较摘要及工件清单；state 存终态记录，
submitted_runners 保存实际 runner，logs 保存作业日志。schema_version 为 1，
每份结果同时绑定协议、Job ID、freeze SHA、trial／源身份及大小／哈希清单。
序列化数组和受控工件有全局 1 GiB 最坏情况预算，不能改成无限 dump；日志和
scratch 不是可用这一预算替代管理的正式数值工件。

## 如何解释结果

- DIFF：身份和数值有效，但超过固定一致性判据；这是诊断发现，不自动判实验失败。
- INVALID：非有限值、来源／结构／追踪等有效性失败；不得解释成可比较模型结果。
- DIAGNOSTIC_COMPLETE：协调器完成证据链；仍须 verify-results 重新核验文件及比较。
- DIAGNOSTIC_RESULTS_VERIFIED：只读结果验证通过，才进入人工数值原因分析。
- DIAGNOSTIC_FAILURE_RECORDED：失败证据可核对，不代表数值结果可解释。
- Slurm 已结束但缺少终态：未完整结束，需要调查；不得补写成功标记。
- ACCOUNTING_PENDING／STOP_AMBIGUOUS：等待再次只读查询或调查，不自动重试。

诊断不会自动修复 v4、放宽阈值、发布 smoke 成功、提交新评估或推导三模型排名。
之后须审阅 A2 复现、冷参考等价和边界差异，再决定有证据支持的修复与新的 smoke，
最后才是完整 10k 对比。

## 九文件候选哈希

下面是机器可读取的固定值。README 自身哈希只记录在外部报告，避免自哈希循环。

<!-- RELEASE_SHA256_BEGIN -->
459613c3e9ca701bde52f5f4aea6d6190a032f6d869431a2860f3c86467a6dd9  diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b  numeric_trace.py
890f2c05f3982d3a53a526b3f07634ea2f811101865d83652431bd3cb94cd6b3  submit_numeric_diag.py
d054496a73755ccd0ce29f9a666dec32b7be382f30682ceb4d6afdfc6a330416  test_numeric_diag.py
4fcbe4a6307a9fb70f8bf35f11d5099246b89180eba415282d186bfccc7b055b  test_submit_numeric_diag.py
33232a2d085bb7dcdd1d11dc9cf34646bbc9042b9f868dcbabfe122bd5c05d29  run_numeric_diag.sbatch
4af79705c62f3f9951ba5f99bd100270913d4997edca7a1ccc3b2120e39cd2b5  test_loader_record.py
e478b24126141cbc6b54c89ffc44f74321c1493bbc0572aefd428598357b82d9  test_real_evaluator_scope.py
418b875c356286ca470c263fa91abbb270d2eff6a4bef691a57a8b25a625565f  test_v4_manifest_json.py
<!-- RELEASE_SHA256_END -->
