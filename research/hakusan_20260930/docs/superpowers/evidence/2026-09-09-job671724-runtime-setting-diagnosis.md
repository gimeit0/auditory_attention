# Job 671724：运行设置门禁失败取证

## 2026-09-09 续：集群探针回传及修复授权

用户在 HAKUSAN 的 attn Python 新进程中回传：

```text
TORCH_VERSION=2.1.1+cu118
AFTER_MEDIUM=medium
AFTER_TF32=high
RUNTIME_PROBE_RC=0
```

该短探针确认了当前安装的精度设置联动，与固定标签源码一致；未加载模型或
提交作业。它没有打印全部六个运行标志，也不是失败 Job 的原始内存快照。
前两次 heredoc 在 Bash 续行提示符处由 Ctrl-C 取消，不属于探针运行失败。
用户随后要求“执行下一步”：开始独立本地诊断 v7，先回归复现、再统一四处
运行设置校验，移除读取异常时伪造 medium 的回退。保持真实冻结配置调用
顺序与科学输入不变，保留 v6/Job 671724；本阶段不上传、不提交 GPU。
执行记录见 [v7 本地修复](2026-09-09-diagnostic-v7-runtime-contract-repair.md)。

以下保留探针回传前的取证过程，“待确认”指当时状态。

日期：2026-09-09。范围：读取用户回传证据、比对已发布 v6 本地源码及原冻结
v4 配置、查证 PyTorch 2.1.1 官方源码、进行独立本地进程的设置读回探针。
本轮不修改生产代码，不创建 v7，不改已发布版本、原配置、checkpoint、bank、
SNR、AMP/TF32 策略或数值容差，不提交或取消作业。

## 已核验的远端失败证据（用户回传）

- Job：671724，诊断协议 formal40_batch_invariance_diag_20260903_v6。
- Slurm：FAILED、2:0、00:01:10、spcc-a100g03。
- diagnostic 固定 SHA 与 v6 freeze SHA 再次检查 OK。
- verify-results：DIAGNOSTIC_FAILURE_RECORDED，VERIFY_RC=2。
- results_verified=false，numeric_results_interpretable=false。
- primary_error：code=EXECUTION_FAILED，error_type=DiagnosticError，
  message=`child exit is nonzero: 2`，phase=execution，notes=[]。
- post_errors=[]，表示本次没有报告事后检查错误，不能将失败记录验收等同于
  成功结果的完整 live-input/numeric 验收。
- 子进程继承的日志 stderr 明确写出：
  `diagnostic error: frozen runtime settings are not exact`。

| 证据 | SHA-256 / 大小 |
| --- | --- |
| v6 input_freeze.json | `c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc` |
| artifact inventory | `77ce0b0dd7c03e93a4e79dd1dc2c789e8e51c6def96b211d84bead1d45fd077e` |
| state/DIAGNOSTIC_FAILED.json | `5425b5f69dc41c782b816a608437321598793f8759aaa4c592fda0c3b7f2f999`，141759 字节 |
| logs/audattn_v4_numdiag_671724.log | `3de4659f788e6465cc78e3bab21177e0bcf67ecee097c986bb1c0390c2737248` |
| BOOTSTRAP_ENVIRONMENT | `17ab25671cb1263d2f7d543fb686abbdea0e47a8139b781c6b3ad188e0ba1a70` |

日志显示经过了每行 400 字符的截断；不将截断的 inventory 当成完整工件列表。
原远端文件没有在本轮下载或改写。EVIDENCE_RC=0 仅表示取证命令块结束。

## 代码确认：错误发生在模型加载前的运行设置比较

已发布 v6 的 `prepare_formal40_worker` 在调用原冻结 evaluator._configure_runtime
之后，读取六个设置并进行精确字典比较；不一致时在约 5108 行报上述错误。
`strict_load_model(..., "formal40", ...)` 位于该门禁之后。因此报错子进程尚未
进入 formal40 的严格模型加载，不是本次 canary 数值超阈值或模型成绩差。
父进程的 child exit 非零只是包装后的失败信息，不是根因描述。

原冻结 v4 `_configure_runtime`（约 2878 行）依次执行：

1. 确定性算法开启、cudnn.deterministic=True、benchmark=False。
2. set_float32_matmul_precision("medium")。
3. cuda.matmul.allow_tf32=True。
4. cudnn.allow_tf32=True。

v6 却要求上述步骤结束后 float32_matmul_precision 仍为 medium。
在 PyTorch 2.1.1 官方实现中，Context::setAllowTF32CuBLAS(true) 会把共享的
float32_matmul_precision 设为 HIGH，后续 getter 直接返回该字段。
因而标准 2.1.1 的这组调用顺序应读回 high，不是诊断器写死的 medium。
来源：[PyTorch v2.1.1 Context.cpp](https://raw.githubusercontent.com/pytorch/pytorch/v2.1.1/aten/src/ATen/Context.cpp)。

查证方式：网页工具无法读取该固定标签内容；首次受限网络请求 DNS 失败后，
经用户批准的只读 curl 请求成功读取上述官方标签源码，没有保存下载文件、
安装依赖或修改环境。未以 main 分支源码代替 2.1.1 标签作版本结论。

这是与现有日志吻合的代码级矛盾；失败消息没有序列化 runtime/expected 的
具体差异，故尚不能把某个实际读回字典伪装成 Job 671724 保存的原始证据。
需要使用集群同一 attn Python 的短进程探针确认该安装的 getter 行为。

## 为什么本地测试没有暴露这处矛盾

本地实际 torch 为 2.12.1，CUDA 构建字段为空。独立 Python 进程只调用六个
设置和 getter，没有构建张量、加载模型、申请 GPU 或运行推理，结果为：

```text
TORCH_VERSION=2.12.1
AFTER_MEDIUM="medium"
```

随后开启 TF32，再读精度时抛出 RuntimeError，指出混用了 legacy 和 new APIs；
另外五个设置读回 True、True、False、True、True，与预期一致。
已发布 v6 的约 5083–5090 行对该特定异常执行 `matmul_precision = "medium"`，
不是实际 getter 值。因此本地测试经过了兼容回退分支，而非集群 2.1.1 的
直接 high 读回路径；本地全绿不证明这项生产门禁正确。

`test_real_runtime_configuration_keeps_code_graph` 只检查函数图没有变化，没有
断言生产版本的最终六项设置。测试替身虽保持了配置调用顺序，运行环境仍是
本地 2.12.1，不能补足 2.1.1 getter 语义覆盖。

## 后续取证及修复边界

下一项提供登录节点短进程探针：打印 torch 版本、设置 medium 后的读回值、
按原顺序开启 TF32 后六个设置。仅影响该新 Python 进程内的标志，退出即结束；
不提交任务、不申请 GPU、不运行矩阵乘法、不写冻结文件。它是设置语义复现，
不是原已退出 GPU 子进程的内存快照，不能据此宣称数值问题已解决。

确认后如用户授权修复，须新版本、有回归、保持原 `_configure_runtime` 顺序与
实际行为；不能把末尾强行改回 medium 或重排调用来迁就断言，也不能接受
任意 runtime 值。运行设置的相同硬编码还见 `_require_equivalence_metadata`、
`_validate_cell_pass` 和 `_FROZEN_NUMERIC_RUNTIME`（约 5591、6136、9088 行），
不能只修改首次入口后忽略后续验收。错误输出应保存实际值、期望值和版本。
这些只是有界修复约束，本轮没有实施代码改动或发布新候选。

正式三模型 10k 对比仍未完成；原 Job 646900 的 NLL 差异 0.0077362060546875
尚未得到数值根因解释。
