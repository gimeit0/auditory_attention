# Job 683154：编译缺文件与模块绑定变化的诊断记录

续记：用户已明确批准下述两项运行合同修复。独立v14已实施，本地645项通过，
同版本完整formal40 CPU验收进行中。原v13/v4不改、不重提；本页以下保留方案
提出时的事实与边界。[当前实施记录](2026-09-10-diagnostic-v14-runtime-import-repair.md)。

## 最新：两项最小复现已完成，尚未实施运行合同修复

用户恢复连接后，实际 master49656 可用，远端身份核验通过、相关队列为空。
PRECHECK/POSTCHECK 已补只读下载，五份核心原始文件固定 SHA 全部通过。
以下两项探针均在实际 Python3.11.5 / torch2.1.1+cu118 环境完成，
不加载科学模型、权重或音频，不运行 GPU 推理或提交作业。

### 1. 固定 PATH 下的 ldconfig 缺失已复现

实际导入 SHA 匹配的已安装 Triton2.1.0 `triton.common.build`，在新进程中
按 v13 固定 PATH 调用真实 `libcuda_dirs()`，返回：

```json
{"errno": 2, "filename": "ldconfig", "type": "FileNotFoundError"}
```

同一进程只读执行 `/usr/sbin/ldconfig -p` 返回0、stderr0bytes，证明该系统
工具存在，主要问题是固定 PATH 不含它所在目录。已先读取387字节包装器，
确认带 `-p` 时不会走更新缓存分支；未裸执行 ldconfig。
包装器 SHA `bfd5df90c7f070feab584435f106f254ffffaa268a04de5b5c3bd61d59c092f3`。

登录节点列表不包含 libcuda，这不等于计算节点没有 GPU 驱动，亦不据此改
库路径。此复现证明一个真实可达的冷编译阻塞；Job683154 日志没有 filename，
因此仍不宣称已证明该 GPU 作业只有此一个编译错误。

探针：[compiler-path-probe.py](2026-09-10-job683154-compiler-path-probe.py)，
SHA `e6e18423d39bc2dfc85ef5558f8637e006b25c88eeebb5bb37fd2e4841218077`。
正常exit0；语法、Ruff检查及格式检查通过。缓存仅在独立临时目录，正常退出清理；
原HOME和已安装文件未修改。

### 2. 模块清理后重新导入触发绑定拒绝，已在最小 CPU 路径复现

使用未修改、固定 SHA 的 v13 `_SnapshotLoader`，构造临时三层跨模块函数：
Toy.forward → src.custom_modules.helper → src.audio_transforms.transform。
只对8个CPU元素进行 Dynamo tracing，backend返回 graph.forward，不使用
Inductor，不进入科学前处理或正式数值评估。

| 构造后、封存前的模块状态 | CPU执行 | 绑定检查 | 新增模块 |
| --- | --- | --- | --- |
| 保留已核验模块 | 无异常 | 通过 | 无 |
| 清理src模块，模拟原加载器退出行为 | 无异常 | sealed frozen module bindings changed | src、src.audio_transforms、src.custom_modules |

这与实际GPU日志的前三个新增名及绑定错误一致，且不依赖编译失败才发生。
该最小测试只有3个新增模块，**不能据此猜测GPU日志未显示的第4个模块**；
也不能将“允许所有晚导入”当成修复。

探针：[import-lifecycle-probe.py](2026-09-10-job683154-import-lifecycle-probe.py)，
SHA `360f26381628e6b534b627e226c9900015965f768368b23c31b9406003b5ee45`。
实际torch2.1.1+cu118，两种情况均输出完整结果后正常exit0；Ruff/格式通过。

探针之后，原v4 manifest、lock、evaluator、runner四个固定SHA再次全部通过，
相关队列仍为空；没有修改生产版本、冻结内容或启动新作业。

### 待明确批准的修复范围

建议在独立候选 v14 中处理以下两个工程问题，原 v13 及其失败证据保留：

1. coordinator 与所有 worker 的固定 PATH 末尾明确追加 `/usr/sbin:/sbin`，
   不继承任意交互式 PATH，不改变现有目录优先级；同步更新运行合同及回归。
2. 修正模型加载与冻结导入的生命周期，使封存前使用的模块对象与模型实际依赖
   的已核验、已签发对象一致。不重载来替代既有对象，不丢弃scene/model依赖，
   不在封存后接受任意新增、替换或删除；冲突与未核验对象仍拒绝。
   具体绑定方案须先在隔离原型与真实同版本正式模型CPU准备路径中验证。
3. compile、AMP/TF32、随机性、batch设置、诊断矩阵、容差、权重和bank不变。
   原NLL差异未解释，不能先提高阈值让smoke过关。
4. 先本地回归/反例/同版本CPU验证，再审阅候选和冻结身份；通过后才可单次
   提交新的32条诊断。若需要进一步扩大范围，暂停说明，不自动改动。

此处是方案，不是已实施变更。尚未创建 v14 或提交新作业。
本轮止于诊断与方案；等待用户明确批准运行环境及模块封存合同的改变。

以下保留此前尚待复现时的证据记录。

2026-09-10。仅保存已有证据、只读检查，不修改已发布 v13 或原 v4，未创建 v14、
未提交新作业。最终三模型对比仍未完成；原 smoke 的 NLL 差异尚未解释。

## 已确认的实际结果

- Job 683154 在 spcc-a100g01 运行 3 分 14 秒后 FAILED 2:0；
  开始 2026-09-10T14:34:01，结束 14:37:15（JST）。
- 既有 `verify-results` 返回 `DIAGNOSTIC_FAILURE_RECORDED` / VERIFY_RC=2，
  `results_verified=false`、`numeric_results_interpretable=false`、`post_errors=[]`。
- `matrix=null`。清单仅含 ENVIRONMENT、PRECHECK、POSTCHECK、RUNNING 四个 JSON，
  不能据此宣称数值诊断通过或得到模型优劣结论。
- PRECHECK 与 POSTCHECK 的记录 SHA 相同；这仅涉及已检查的输入状态，
  不等于运行时模块表没有变化。

## 本次日志新增的直接证据

本地原始日志固定 SHA：
`39162e1d7e52251577755c20a89b7fb5c23a13f549028ff2222946813a5034ab`。

`DIAGNOSTIC_EXCEPTION_CHAIN` 记录的链为：

1. reference prediction 包装错误；
2. 冻结模块绑定检查失败；
3. `torch._dynamo.exc.BackendCompilerFailed`；
4. 其 `inner_exception` 为 `builtins.FileNotFoundError`；
5. 下层 `concurrent.futures.process._RemoteTraceback`。

编译异常父进程栈经过 codecache 加载、生成代码模块、编译结果等待与 Future。
有限日志包含 `MISSING_PATH_MENTIONED`，但没有保存缺失文件的 `filename`。
因此尚不能仅凭此日志确定具体缺失可执行文件，也不能断言只有一个编译问题。

绑定差异明确为 added=4、removed=0、replaced=0。日志限长只保存前三个名称：
`src`、`src.audio_transforms`、`src.custom_modules`；第四个名称未知。
不能将所有新增导入自动视为合法，也不能豁免冻结后的绑定检查。

## 已读源码与需要继续验证的线索

超算已安装的 `triton/common/build.py` 经只读读取，SHA：
`3503228fd15303fce0ce19a7b2258d9bde34a92bdbb0168480dd25b296725810`。
其中 `libcuda_dirs()` 调用 `subprocess.check_output(["ldconfig", "-p"])`，
CUDA `_build()` 会调用该函数。

已发布 v13 的 runner 与 child_environment 都固定 PATH 为：

```text
/home/s2510040/miniconda3/envs/attn/bin:/usr/local/bin:/usr/bin:/bin
```

此前登录节点只读检查在此 PATH 下找不到 ldconfig，但看到 `/sbin/ldconfig`
和 `/usr/sbin/ldconfig` 可执行文件。**这是一条具体、可测试的编译阻塞线索，
尚不是对 Job 683154 GPU 子进程缺失文件的唯一根因证明。**
PATH 下找不到 ptxas 也不能单独证明异常：Triton 可能使用自己定位的 bundled ptxas。

原 v4 `strict_load_model()` 在 `_frozen_import_context` 中构造模型，退出时清除
临时 `src` / `selftrain` 模块并恢复先前模块表。这一事实与稍后出现新增模块
相容，但还需验证编译时导入链及其对象身份，不能仅凭相容性断言因果。

## 本轮恢复检查与阻碍

2026-09-10 15:31 JST 再次检查：共享 `master.sock` 不存在；非交互直接 SSH
返回 `Permission denied (publickey,password,hostbased)` / 255。因此本轮没有
远端新探针、补充下载或新的作业操作。

本地三份原始证据 SHA 复验通过；v13 候选十九文件固定清单复验全部通过。
PRECHECK / POSTCHECK 原始副本尚待补充，见[部分归档说明](job-683154-v13/README.md)。

## 恢复连接后的有界下一步

1. 补只读下载 PRECHECK / POSTCHECK 并验证既定 SHA。
2. 在同版本登录节点新进程中，使用相同固定 PATH 做最小 `libcuda_dirs()` 检查，
   仅输出异常类型、errno、filename；不加载 checkpoint，不做 GPU 推理，不提交作业。
   如需查看 ldconfig，只读取其源码或使用 `-p`，不得裸执行更新缓存。
3. 区分缺失工具路径与冻结模块绑定生命周期两个问题；先做隔离复现。
4. 如需要改变固定 PATH 或模块封存生命周期，先说明精确变更并取得明确批准。
   不自动放宽保护，不修改旧版，不改变 compile、AMP/TF32、阈值、bank 或权重。

本记录不是新的运行合同或部署授权。研究口径继续为
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
