# Job705468失败后的启动目录修正：本地已验证，未重新提交

2026-09-14 JST，用户请求“能接着下一步开始修正吗”。本轮只读核查旧证据、
增加本地独立修正候选和测试，不修改旧发布包、失败目录、模型或冻结输入。
未上传、重新freeze、更新/放行/重提GPU作业。

## 当前真实进度

[最近一次成功状态查询](gpu-control-20260913-v1/status-20260913T162250Z-la9_y098/receipt.json)
（2026-09-14 01:22 JST）显示：

```text
705468|FAILED|2:0|00:00:44|spcc-a100g10
coordinator: GPU_PAIR_NOT_VERIFIED
results_verified_locally: false
```

先前的“PENDING/已放行”已成为历史状态。此失败发生在参考子进程的scratch
入口、严格模型加载之前；没有成功的冷参考/观测结果，更不是模型优劣结论。
原单次提交授权已消费，不能重跑旧submit/update/release脚本。

上轮只读读取的reference日志关键报错如下，原日志记录为844字节，SHA256为
`53c785e8b117e130dd9cb51975fee02f17e250568a4be185ebfe46d323f74d14`：

```text
gpu_child.py:88: with scope(args, scratch_role) as scratch
scratch_adapter.py:57: with namespace["_worker_scratch"](args, role) as scratch
<private-scratch-preserve-home>:9440
FileExistsError: [Errno 17] File exists: 'reference_cold'
```

上轮coordinator记录仅有reference子进程，returncode2、约37秒，随后fail-fast；
observed没有启动。本轮再次只读尝试取该日志时SSH退出255，提示连接关闭；
按sandbox要求升级执行一次仍同样失败，没有自动重连。故上面的日志为
上轮读取内容的摘录，**不是本轮重新下载并完成整包归档的声明**。
远端完整失败工件的再次回传仍待连接恢复。

## 定位到的问题与修正

原coordinator先设置 `TORCHINDUCTOR_CACHE_DIR` 等十个变量，指向尚不存在的
`reference_cold` / `B2` 下级目录。旧gpu_child先导入数值库及整个候选链，
之后才调用要求目录此前不存在的原scratch工厂。

本地全新Python进程实际运行相同导入链，复现了同一个FileExistsError。
[mkdir审计与原顺序结果](gpu-startup-local-20260913T164839Z-8k9s5rji/old-real-reference.json)
记录本机torch2.12.1的调用链：`torch/_dynamo/package.py` →
`torch/_inductor/runtime/cache_dir_utils.py` → `os.makedirs`，先创建了
`reference_cold/torchinductor`及其父目录，随后原工厂独占mkdir失败。
这证实本地存在该顺序缺陷；超算2.1.1是否由完全相同的具体导入点创建目录，
仍须同版本复验，不能仅凭本地版本推断为已实测。

新[独立候选目录](../prototypes/targeted_gpu_startup_20260914/README.md)做三件事：

1. 数值库导入之前，运行固定v18原scratch工厂，独占创建空目录并持有描述符。
2. 导入后，以原加载器签发的执行模块建立scratch类型，绑定同一进程持有的
   同一组目录。不是允许旧目录复用，也不把 `exist_ok=False` 改成True。
3. 启动上下文纳入原try/finally，导入及目录创建失败均保存CHILD失败记录并清理。

适配仅修改启动顺序、目录绑定与清理；撤销差异后完整原run函数AST一致。
模型加载、32条16→1、科学精度/数值容差、编译、观测及匹配逻辑不修改。
真实HOME没有重新赋值；旧目录/符号链接拒绝、权限及描述符检查继续保留。

## 验证结果

[最终本轮回执](gpu-startup-local-20260913T164839Z-8k9s5rji/receipt.json)：
`LOCAL_STARTUP_FIX_VERIFIED`，五个独立子进程（测试套件＋四个probe），
源码前后未变，无自动重试。

- 15项新增测试零跳过：空目录/权限/环境、旧目录、符号链接、源码变化、
  进程身份、重复绑定/进入、描述符替换、原加载器签发、AST精确还原、
  导入失败和scratch冲突的实际候选run错误记录/清理。
- 旧真实库导入顺序复现FileExistsError；另一个显式模拟的缓存导入场景同样失败。
- 新reference：先建目录后真实库导入；原合成B2参考完整34次前向，四份
  spill/mmap文件、两轮归档及原pass证据解码重验通过。
- 新observed：先建目录后真实库导入，原执行模块签发及同描述符绑定通过。
  没有执行新的完整观测推理，不借用reference的通过作为observed生命周期验收。
- [原GPU候选回归](gpu-job-local-20260913T164544Z-6ovom4be/receipt.json)：42＋38项通过，
  45份运行包来源和51份控制包来源仍一致。不是95次真实模型试验。

本机Python3.11.15、torch2.12.1；全部CUDA未初始化、生产模型未加载。
原Linux挂载决策在本地测试中显式stub，其余原scratch工厂检查实际执行。
没有HAKUSAN同版本、实际Linux挂载或A100/Inductor前向验收结论。
最初12项版本的本地回执亦保留，但最终候选以15项回执及其源码SHA为准。

## 保留与下一步

原45文件运行包manifest SHA保持
`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`，
原51文件控制release SHA保持
`22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646`。
新增候选不是这两个旧SHA所授权的内容，没有接管旧root或新建GPU授权。

下一项为超算同版本的有界CPU启动复验（不加载模型、不执行forward或GPU提交），
随后才审核独立新GPU运行包、源清单与新单次资源授权。当前连接尚未恢复。
本轮 `jobs_submitted=0`、`ready_for_gpu=false`。

总目标仍是formal40与作者checkpoint的可重算比较，valbest33仅补充；
当前在修复数值追踪启动问题，三模型smoke和10000条正式对比仍待完成。
结果角色保持 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
