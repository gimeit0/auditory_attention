# 定点追踪原型：仅合成CPU验证

当前：同一套28项合成测试在本地与超算torch2.1.1+cu118均通过。
不是v19生产发布，不加载真实模型，不是GPU诊断，不是科研比较结果。
原v18所有28个候选文件的release SHA再次核对通过，未改冻结文件或阈值。

## 已实现

- 原生float16/32/64张量的不可变字节快照，记录shape、dtype、stride及SHA。
- 按既定pass/batch/trial顺序和模块调用序号区分共享模块的cue/mixture分支。
- 缺失/额外/乱序事件、错误trial、重复批次、非法计划、超预算或非有限值拒绝。
- 采集前后模型参数/缓冲区摘要、eval/frozen状态、输入、RNG和六项运行标志检查。
- 观测/未观测端点逐位比较；输出不一致时拒绝解释逐层记录。
- 记录摘要检测生成后事件负载/身份变化；hook注册表变化亦拒绝。
- 只对已通过端点门禁的合成记录报告首个不同的观测边界。

全张量采集默认总16MiB、硬上限128MiB；单次状态扫描最多128项/1GiB，
参数和输入只保留摘要，不为每个batch长期保存完整权重副本。
这是小型原型的边界，不证明能够容纳真实模型的全部中间特征。

## 实际测试与发现

Python3.11.15、PyTorch2.12.1，28项测试通过，CUDA未初始化。
2026-09-11远端Python3.11.5、PyTorch2.1.1+cu118亦28项全通过，PROBE_RC=0，
CUDA未初始化，未加载生产模型。两环境运行同一套测试，不累计为56个用例。
编译测试使用Dynamo的eager后端，不是Inductor、A100或FP16数值验证。
测试用3维、恒等线性权重的合成模型；即使trial标签借用四个目标ID，
输入也完全是人工数值，不是这些trial的真实音频/特征。

初始检查抓到：无观测参考先在同一进程编译后，新模型上的hook可能被已有
编译缓存跳过，最终表现为缺失边界记录；检查器没有将其误报成功。
合成编译用例改为两次之间明确重置Dynamo缓存，完整事件及端点检查才通过。
此reset只用于合成工程测试；真实参考/观测仍须独立冷进程，不可把reset
偷偷加入原生产推理。另一个初始测试入口曾发现0项，最终入口强制精确28项，
0项、跳过、expected failure或任何错误都不会输出通过。

最新原始日志：
[本地内存引导自测](../../evidence/trace-local-bootstrap-20260911T052241253296Z-rhk5my_e/output.log)
（45dfa3285ab4e64cc66893bc14cf0b1f886832defea39d292a54fcc1af863b22）。
[回执](../../evidence/trace-local-bootstrap-20260911T052241253296Z-rhk5my_e/receipt.json)
绑定核心源码、引导载荷、驱动和原始输出SHA。此前自测日志保留，非最终版本
的日志不能替代这个回执。Ruff与shell语法检查通过。

同版本超算实际运行的[原始输出](../../evidence/trace-remote-cpu-20260911T092527649074Z-7wygs60j/output.log)
及[回执](../../evidence/trace-remote-cpu-20260911T092527649074Z-7wygs60j/receipt.json)
已核对源码/引导载荷/驱动/输出SHA。原始输出SHA为
0aea3517a2f978183fc51e5a245e86aafd695b15b63c25ac0e18a32d657ea5a5。
出现hook部分支持的warning，但无测试失败；仍不能推论Inductor或真实A100通过。

## 真实任务计划的绑定

build_bound_plan.py实际读取并SHA核对v18 freeze、原marker、离线分析和三份
冻结源码，生成FORMAL40_PLAN_CANDIDATE.json。保留32条完整顺序及16→1；
A2目标9000/4126，B2目标1428/2698；列出42个块级post-hook调用边界。
其ready_for_gpu明确为false。该计划生成不是42个真实边界已经被运行验证。

## 必须保留的限制

hook使用显式Dynamo禁用边界，可能改变图分段和数值。端点相同只是必要条件，
不能据此证明原编译执行的中间算子等价；输出中明确保留false。
分支标签来自已审阅的调用顺序，不能独立识别任意恶意模型交换同一模块的
两次调用。记录摘要是完整性检查，不是对执行中任意恶意代码的认证。
这不是v18约束系统的替代品，尚未集成真实加载器/源代码/执行能力校验。

尚缺：真实模型的独立冷进程参考、完整前处理
身份与源代码绑定、实际模型42边界清单匹配、flatten/pre-hook、块内算子、
真实内存/耗时/存储量实测和A100观测干扰验证。不得直接拿原型提交真实作业。

新增静态前置核对：生产返回外层Lightning模型，而CNN已由torch.compile
包装；相对路径需绑定到正确对象。B2仅首层两个分支×两个目标×两个pass
的float32完整快照就约760.46MiB，超过本原型128MiB常驻上限。
这是源码/shape静态下界，非显存实测；需另行设计有界采集并测试，不能直接部署。
详细依据见[最新进展](../../evidence/2026-09-11-targeted-trace-prototype-progress.md)。

## 命令

本地测试（不连接超算）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_trace_20260911/run_checks.py
```

超算同版本合成CPU测试入口（由用户在Mac运行）：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-11-targeted-trace-cpu-check.sh
```

入口校验连接脚本与CPU驱动SHA，交互认证仍仅由SSH密码提示处理。
接着用已有连接将三份SHA绑定源码发送至python标准输入，仅在内存执行，
不发布远端源码、不运行sbatch、不加载checkpoint/音频，CUDA不可见、CPU线程1。
它核对remote Python3.11.5/torch2.1.1+cu118，单次最多90秒，无自动重试；
输出及回执写入新的本地owner-only日志目录。退出0仍只表示合成CPU检查通过。
库自身可能有运行缓存行为；“不发布源码”不等于证明整个远端零文件写入。

用户已完成SSH认证和本次远端CPU检查；无需重复运行来完成本次验收。
没有读取或保存SSH密码，没有远端模型操作或新GPU作业。
