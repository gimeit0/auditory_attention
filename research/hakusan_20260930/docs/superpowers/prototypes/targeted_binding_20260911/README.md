# 冻结 formal40 的真实 CPU 加载与追踪位置接入检查

2026-09-11，独立原型，不修改 v18、旧追踪器/分块器及其 SHA 清单。
不是 v19 发布，没有 GPU 作业或最终模型比较结果。

## 范围

本地新增 15 项输入/反例/回执检查已通过，无跳过；Ruff 通过。
远端检查使用已认证的 SSH 连接，一次性在私有临时目录放置 SHA 固定的
观察器、计划和 CPU 检查入口。子进程最多 240 秒，不自动重试；不修改 HOME。
CPU 单线程；原 v4 六项精度标志由原配置器设定并原样读取。

读取原 v18 诊断源码（不改代码）、原 v4 manifest / evaluator / checkpoint、
冻结 snapshot 与 Job685198 的 A2 推理前状态证据。先检查相关队列为空，
持有原 evaluation.lock 的非阻塞共享读锁；不重写 freeze、锁或状态文件。

检查项目：

- 原 v18 的 read_frozen_context 及冻结 source loader，原 v4 strict_load_model。
- formal40 原始 checkpoint 严格加载，所有训练参数完整覆盖。
- 保留原 BinauralAttentionModule → OptimizedModule → 原始 CNN 调用结构。
- 42 个候选 post-hook 调用位置对应 27 个不同的实际模块；检查精确类型。
- A2 目标9000/4126、B2目标1428/2698；全部32条、16→1、每cell34批次的计划不变。
- 60条已注册参数/缓冲区按名称、dtype、shape、完整字节SHA与原A2状态比较。
  跨进程对象id、设备、version不用于跨进程相等；同一进程前后则完整比较。
- 在真实对象上安装/移除27个hook，但不调用record、模型forward或音频变换。
  不生成真实中间张量；采集store应为0字节。验证参数/RNG/运行标志未改变、
  冻结模块对象绑定未改变、compiler lifecycle未进入、CUDA未初始化。
- 再验冻结源码与原24条固定文件；正常结束删除临时源码、缓存和空store，
  在本地保留原始输出、bootstrap与回执。

## 本次实际结果：已通过

一次远端运行完成，REAL_BINDING_CPU_VERIFIED、returncode=0：

- 原模型61个state_dict键严格加载；62,622,520个训练参数元素全部覆盖，
  missing/unexpected/shape/dtype差异均为空。
- 60条去重后的已注册参数/缓冲区记录，与Job685198的A2推理前记录逐SHA一致。
  61个state_dict键和60条去重注册项是不同计数口径，不能互换。
- 42个计划位置、27个实际模块、两个cell的全部32条及34批次计划绑定通过。
- 真实对象上27个hook的空安装、校验和移除通过；没有forward调用和张量采集。
- 状态、RNG、六项精度标志保持；compile包装保留，lifecycle没有进入。
- temporary_directory_removed=true；临时源码、依赖缓存与空store正常清理。
  生产文件未发布，原输入未修改，jobs_submitted=0。

证据：

- [原始输出](../../evidence/real-binding-cpu-20260911T135151Z-cyfcf4vd/output.log)
  SHA：0e0347a3c6778186432237ef052fc5eb91aa8c805b4928d9b14181f2776b1b94。
- [回执](../../evidence/real-binding-cpu-20260911T135151Z-cyfcf4vd/receipt.json)
  SHA：16825475e8818492a0876c398aa7a4cc33464650a295a32fc24d28539ade2b7e。
- [实际引导载荷](../../evidence/real-binding-cpu-20260911T135151Z-cyfcf4vd/bootstrap.py)
  SHA：352bcdda057c93a19a2bc0dc5cdc7825263c7e4b580852a1cdb46a4180509993。
- [源码清单](SHA256SUMS)：3份新增代码精确绑定；载荷另绑定4份已有原型输入。

已独立重算driver、全部传输文件、bootstrap、完整输出及回执中的成功字段，
INDEPENDENT_REAL_BINDING_EVIDENCE_CHECK=PASS。旧追踪原型7项、分块原型9项
和v18原28项release SHA全部仍一致；没有为了这次检查修改旧实现。
Matplotlib私有字体缓存建立、torchaudio弃用提示不影响此次通过，也不是GPU结果。

## 科学与工程限制

这是 CPU **加载/绑定/空hook接入**验证，不调用生产 prepare_formal40_worker。
后者对生产输入要求CUDA，本原型没有修改或伪造该门禁。
source loader 验证和结构/状态验证不能被写成完整生产执行能力认证。
production_execution_authority_verified=false，ready_for_gpu=false。

没有运行模型forward，没有观测真实42层的调用顺序、形状、数值或内存峰值。
计划中的cue/mixture标签仍基于已核验的源码顺序，不是本次动态观测。
空hook的安装/移除成功也不证明其在Inductor/A100推理时没有图分段或数值干扰。
后续仍需独立冷进程参考/观测、真实输入重建及SHA绑定、端点门禁、跨进程
工件校验，以及生产执行能力的明确接入方案；不得绕过v18已有保护。

当前仍是 REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。
未完成最终三模型smoke、10000条bank比较、统计置信区间或论文结果。

## 入口

默认仅检查本地载荷，不连接远端：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_binding_20260911/run_real_binding.py
```

本地15项测试（不导入torch，不加载模型，不连接SSH）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover \
  -s docs/superpowers/prototypes/targeted_binding_20260911 \
  -p test_binding_inputs.py -v
```

`--run`才会执行上述单次真实CPU读取检查；不必重复运行已经通过的检查。
若SSH失效，只在终端认证，不把密码写入脚本或聊天。
