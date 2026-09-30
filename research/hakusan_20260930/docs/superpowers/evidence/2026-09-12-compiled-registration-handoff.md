# 编译登记候选：本地验证与同版本 CPU 交接

更新：2026-09-13用户已执行下述入口并通过；本轮独立核验15份源码、载荷、
输出与回执一致，见[完成记录及下一阶段](2026-09-13-compiled-cpu-verified-and-lifetime.md)。
不必重复单次前向入口。以下保留2026-09-12的原交接范围及当时状态。

记录日期：2026-09-12 JST。当前没有新 GPU 作业，最终模型对比仍未完成。

## 已实现及验证的范围

新增独立 [compiled_registration.py](../prototypes/targeted_compiled_20260912/compiled_registration.py)。
原 v18 的 28 份发布文件 SHA 全部仍匹配；上一版准备接口与生命周期源码不变。
不是给已冻结模型补装 hook，也没有跳过原编译器检查。

新候选精确绑定一个 OptimizedModule，在原严格加载后/身份签发前登记。
合成 CPU 探针仍要求原编译器 authority 签发成功，不接受本机 2.12.1
冒充超算 2.1.1；原准备 AST 和原 trace_predict_batch 不改写。
回调的可变记录器使用先前明确的独立生命周期检查，不宣称其内容受原
ContextVar 身份检查完整覆盖。CompiledLease 的状态/RNG/runtime 不变条件
仍保留，若首次编译不满足便失败，未做静默放行或重置 RNG。

本地首次 16 项测试通过，随后真实打包、临时目录、独立子进程复测：

- [打包复测回执](compiled-package-local-20260911T180158Z-ykjfojy4/receipt.json)
- PID 80066；Python 3.11.15，torch 2.12.1。
- 16 项、零跳过；unittest 1.154 秒，驱动 3.028 秒。
- 合成 compiled eager 内层调度一次、4 个阶段/4 份采集；完整字节重读一致。
- 原编译器版本拒绝、旧 eager 类继续拒绝编译模型、外/内类型错误、
  wrapper/绑定替换、阶段缺失、旧 hook、实例回调篡改等拒绝测试通过。
- 明确 original_compiled_guard_validated=false；没有真实模型、CUDA 或生产验证。
- 临时源文件执行前后 SHA 一致，临时目录清理确认。

复测输出 SHA：
`57d238e4f626bd5f48d1b065d79c28a7c7cf50220fcdcd4fc789235198be61fc`
（5430 字节）；回执 SHA：
`d0c483246f0e9412a16e0b1cb74e4b8e3923b94964d382b92c07bde2f5b31e9d`。
已独立重读输出 SHA 与回执的状态/计数/PID/清理/限制字段。

前一版 18 项原准备接口回归也通过：
[回归回执](preseal-preparation-local-20260911T180345Z-49fl7kzt/receipt.json)，
PID 80130，unittest 46.604 秒，驱动 48.818 秒。
仍为合成 A2/B2 各 34 次前向，原检查保留。没有把这 18 项记作编译验证，
本轮也未重跑 v18 全部 751 项。Ruff 与交接脚本 bash -n 通过。

## 可执行的下一步

[认证后立即做一次 CPU 编译探针](2026-09-12-compiled-registration-cpu-check.sh)

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-12-compiled-registration-cpu-check.sh
```

只在 Mac 终端执行。仅粘贴这两行，不粘贴提示符/输出。密码只在 SSH 提示输入。

当前 socket 不存在；本轮未尝试认证、连接或远端运行。
脚本检查连接工具、驱动及包 manifest，再认证后立即使用该连接做一次
60 秒限时的合成 CPU 子进程；不是提交脚本。引导 80 秒、本地传输 90 秒。
临时写入 /tmp，受控完成后清理；断网或外部强杀不能保证清理。
不修改 HOME，不加载 checkpoint，不写原评估/诊断目录，不运行 sbatch。

远端成功须有真实 2.1.1+cu118、一次加载/一次原受控前向、冷编译器进入、
4 个阶段/4 份捕获、输入/状态/RNG/运行设置检查、hook 清理、临时目录清理
及正确源码清单的回执。仍使用合成模型/eager 编译后端，完整 pass 数必须为 0，
cold_pair_interference_verified=false、ready_for_gpu=false。
失败保留日志，不自动重试，不借用本地 PASS。输出目录为 compiled-remote-cpu-*。

## 后续科学验收仍需完成

同版本一次前向 → 同版本完整冷参考/观测生命周期 → 真实加载器与 42 位置
整合 → 授权范围明确的 A100/Inductor 干扰验收 → 数值解释 → 三模型 smoke →
相同冻结 bank 的完整比较/置信区间。不能把当前候选认作科研结果完成。

实际同版本编译器拒绝的细节未知，必须以这次新探针的输出为准。
所有后续结果仍标注 REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。
