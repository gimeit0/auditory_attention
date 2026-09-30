# 同版本单次编译前向已验收；完整生命周期候选

2026-09-13 JST。后续更新：[计算节点CPU Job703415已完成并独立复核通过](2026-09-13-compiled-cpu-job.md)。
参考/观测各34次前向，两pass/16端点对应字节一致；11工件/25源码重新校验通过。
仍未完成三模型正式比较，也没有新GPU验证。下文保留此前单次前向通过及
登录节点完整候选超时的历史；“没有Slurm作业/拟申请授权”仅指当时状态。

## 已完成的独立验收

用户完成认证后运行既有单次 CPU 入口。本轮从本地原始输出重新解析、
重建载荷、验证 15 份源码、输出/回执 SHA 及原驱动接受条件，全部通过。

- [原始回执](compiled-remote-cpu-20260913T030436Z-lr38eivo/receipt.json)
- [可重跑的只读核验程序](2026-09-13-compiled-first-batch-recheck.py)
- Python 3.11.5 / torch 2.1.1+cu118；真实子进程 PID 3076537。
- 严格加载后的合成模型，1 次加载、1 次原受控前向、4 阶段/4 份采集。
- 原编译器 authority 签发并实际进入，原推理检查保留；钩子移除、身份撤销，
  临时目录清理回执通过。eager 编译后端；没有 Inductor/CUDA/生产模型。
- output.log：12063 字节，SHA
  `2b3d8211b2641c6713ef521998cf1e2604409df7dccc593844e04da6557efc01`。
- receipt.json SHA
  `b64faae15a19fdeaff17cf104698ccbc428e291f5749dc4fb46487ee6e6baf42`。

preparation 中的 `compiled_guard_probe_completed=false` 和
`compiler_backend_entered=false` 是准备结束时的快照；最终子记录为
`HERMETIC_COMPILED_FIRST_BATCH_PASS`、`compiler_backend_entered=true`。
两者记录的时点不同，不重写历史准备快照。完整 pass 数为 0；这不是
34 批生命周期、观测无干扰、原 Job685198 重放或最终模型优劣结论。

## 下一阶段的限定范围

独立目录 [targeted_compiled_lifetime_20260913](../prototypes/targeted_compiled_lifetime_20260913/)
不覆盖已验收的单次候选、旧 v18、冻结清单、checkpoint 或任何旧工件。

两个全新 CPU 子进程，各严格加载 1 次同一合成模型，使用原 run_trace_pass
完成 32 条合成样本的 16→1 两 pass（每进程 34 次前向）。仅 synthetic B2：
autocast=false，但仍保留 high/TF32 原设置；不是严格 FP32 或真实 B2 重放。

参考进程不安装观测 hook，使用相同两条 AST 插入点在签发前取得原编译器身份。
观测进程使用已经验收的原 CompiledRequest/CompiledLease，不修改旧类规则。
全量导出 16 个端点的原 dtype/形状/字节、逐 trial/逐 batch 描述、4 项正式输出、
16 份阶段采集和 34 条事件。独立读取器核对原字节、顺序、覆盖、合成 Identity
阶段的已知输出，以及两个进程的端点是否完全一致，不用容差。

本地 16 项读取器正反例经新临时目录/新子进程打包复测通过：
[本地回执](compiled-lifetime-local-20260913T031816Z-2d_3z70k/receipt.json)。
本地 torch 2.12.1 仅确认 worker 拒绝未验收版本，未假造 2.1.1 或运行原编译检查。
Ruff 通过。本地读取器测试不等于同版本完整 worker 通过。

首次远端完整候选调用记录在
[本轮输出目录](compiled-lifetime-remote-20260913T031847Z-ngrjkotf/)。
远端总时限 80 秒、单子进程最多 60 秒、本地传输总计 90 秒；CPU 单线程，
CUDA 不可见；只写新 /tmp 临时树，不改 HOME，无认证提示、自动重连或重试。
失败/超时保留本地输出，不可记为完成或直接扩展登录节点运行时限。

## 本次完整候选的实际结果：超时，未通过

上述远端调用已经结束：[回执](compiled-lifetime-remote-20260913T031847Z-ngrjkotf/receipt.json)。
参考子进程 PID 3093606 在 60.214 秒触及单进程硬上限，由驱动终止进程组；
退出码 124。参考子进程输出为 0 字节，没有可用于确认准备/前向进度的记录，
因此不能断言是编译慢、某一层慢或已经完成了多少批。
观测子进程没有启动。引导进程返回 temporary_directory_removed=true，
回执/输出 SHA、唯一子进程模式、退出码和源码清单已经独立重新读取核对。

- 结果为 COMPILED_LIFETIME_NOT_VERIFIED，不是数值差异检验失败。
- output.log SHA：`fbdee660e9b766fdaf2532dac45a2ac3a15924a79808a7b4c9df4878bf2a60a7`。
- receipt.json SHA：`66af44c92055d13b3b4a5dde92257bf476503b244742d8ad8b644a568c984254`。
- 未自动重试、未提高登录节点时限、未修改已通过的单次候选。

随后只读 sinfo 查询确认 TINY/SINGLE 等 CPU 分区为 up、Gres 为 (null)。
这不是账户/资源请求已获调度器许可的证明，尚未验证具体分区的最小资源、
QOS 或账户限制。没有提交 CPU 或 GPU 作业。

下一步拟在计算节点做一次限时 CPU 验证，而非在登录节点继续加长探针。
建议申请上限：1 个作业、1 CPU、4 GiB、30 分钟、不申请 GPU；需先确认
授权与分区规则，再准备独立提交/回执/进度记录。不得直接改旧探针时限重跑。

真实 42 位置、生产 worker、A100/Inductor、数值根因、三模型 smoke/10k/CI
仍需后续单独验收。当前 ready_for_gpu=false。
