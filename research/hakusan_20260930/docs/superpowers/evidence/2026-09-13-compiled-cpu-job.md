# 编译生命周期：获授权的计算节点 CPU 作业

2026-09-13 JST。用户在明确资源上限后回复“开始吧”，授权一次纯 CPU 验证。

最新结果：另获替补提交授权后，**Job703415 已完成并经本地原始字节复核通过**。
Slurm：COMPLETED、0:0、00:02:52、1 CPU、4G、lcpcc-062；未请求 GPU。
这次验收限于合成 B2 / CPU / eager 编译后端，不是三模型正式比较。
首次 Job703335 因本次新增解析器误判在排队时取消，0秒/0已分配CPU；
两次历史提交均保留，见下文，不能将其写成“总共只提交过一次”。

## 硬上限与范围

- 每次明确授权的单次提交：1 节点、1 task、1 CPU、4096 MiB、30 分钟，不请求 GPU。
- TINY 分区只读检查：UP、AllowAccounts=ALL、AllowQos=normal,tiny、
  每 CPU 最大内存 6000 MiB。具体请求还需 sbatch --test-only 和实际分配核验。
- 参考/观测两个全新子进程顺序运行；每个最多 900 秒，协调器执行总预算 1710 秒，
  Slurm 总时限 1800 秒。失败立即停止，不继续启动下一子进程，不自动重试。
- 保留原 worker、观测器、16→1 顺序、同版本编译器/状态/RNG/原推理检查及所有容差。
- 合成 CPU、B2、eager 编译后端；不是 formal40 真实前向、Inductor/A100 或三模型比较。

## 新增入口与边界

[独立运行工具](../prototypes/targeted_compiled_cpu_job_20260913/)：
child_entry 只在外部提供启动行与每120秒线程栈输出，不修改原 worker；
coordinator 在计算节点复制 SHA 固定源码到私有临时树并运行两子进程。
线程栈用于定位无输出/缓慢阶段，不作为模型数值证据。环境限制 CPU 线程和
缓存目录，但不覆写 HOME。日志和终止回执保存在新共享目录，SSH 断开不影响
已提交的 Slurm 作业。临时树正常结束后清理；外部强杀可能不产生清理回执。

首次 v1 部署的远端目标（保留，不再使用）：
`/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v1`。

发布清单固定25份源码/runner，SHA：
`2f18d4b50b3a9b1c262fedc88dbb80d53b29ef9ce8fa9c116ca718031577d2e4`。
旧19份依赖逐SHA保持，包括前一次超时的原 worker。新增6份仅用于作业运行、
提交、栈诊断和控制测试。

控制器在本地/远端创建排他提交意图后最多调用一次 sbatch；断网/响应不明时
不得重试提交。先做 test-only；正式提交后核对 NumCPUs/NumNodes/任务/内存/
时间/分区/GPU。若分配超出或不同于授权请求，则只对该新作业请求取消并保留记录。

## 本地验证

新增16项标准库单元测试通过：资源限制、GPU隐藏、无作业拒绝、排他写入、
源文件SHA/符号链接、调度器资源核对、test-only与提交区分、runner限制。
原16项端点/字节/顺序读取器测试再次通过。Ruff、bash -n、25文件SHA核验通过。
这些是控制/读取器测试，不是完整同版本编译执行通过。

本轮部署、调度预检查、提交、状态与原始结果均记录在
[独立操作证据目录](compiled-cpu-job-20260913-v1/)。
只有取得实际作业号和完整结果核验后，才能报告相应提交或验收成功。

三模型正式对比仍未完成；ready_for_gpu=false，科学结果不可由此补写。

## v1 实际提交与解析误判

Job703335 已真实提交，但仍在 PENDING 时被新控制器取消。不是资源超标：
调度器原始记录为 NumCPUs=1、NumNodes=1-1、NumTasks=1、CPUs/Task=1、
MinMemoryNode=4G、TimeLimit=00:30:00、无 GPU。控制器错误地只接受
NumNodes=1，没有接受语义同为单节点的待运行范围 1-1。

责任在本次新增解析代码，不是用户输入、Slurm 分配或原模型数值问题。
[原始资源记录](compiled-cpu-job-20260913-v1/fetch-20260913T044031Z-_lytjl8g/SCHEDULER_ALLOCATION.json)
SHA：`caf190d2cda051e6a5bfb65533273f77d0c1e167e735eab175c12d479f97dfbc`。
[最终查询](compiled-cpu-job-20260913-v1/status-20260913T044136Z-y09zmdjx/receipt.json)
确认 CANCELLED by 27831、Elapsed=00:00:00、AllocCPUS=0、None assigned。
没有运行子进程、模型前向或占用计算 CPU。不得将该次提交隐去，也不可说
“从未提交过作业”。

## 独立 v2 修正与获授权的替补提交

新目录 [v2 控制工具](../prototypes/targeted_compiled_cpu_job_20260913_v2/)保留
v1 原始文件、清单、意图和取消回执。只接受 NumNodes=1 或 1-1，继续拒绝
1-2 等多节点范围；用上述真实资源记录增加回归用例，19项本地测试通过。
另增前置核对：703335 必须已取消、0秒、0已分配CPU，才允许新部署/预检/提交。
所有模型/观测/worker源码和资源上限不变；外部工具目录、作业root和日志独立。

v2 发布清单 SHA：
`e4f73042e3a7ffbe9026acd9a0539db8695f118bfc48d424fcc2016b4c1c0ca5`。
替补作业不能借用原单次授权自动重提；正式替补提交前另行明确取得授权。

本轮已通过工具审批明确取得替补提交授权；不是自动重试。
[实际提交回执](compiled-cpu-job-20260913-v2/submit-20260913T044909Z-8p71emn2/receipt.json)：
Job703415，nonce `a214e11a54234ebc95cc94a4c2780cb1`；资源检查通过。
v2 远端目标：
`/home/s2510040/audattn_external_eval_diag/compiled_lifetime_cpu_2026-09-13_v2`。
703403 只是 test-only 预览编号，不是本次实际运行作业。

## 完成与独立验收

[最终状态及 Slurm 记账](compiled-cpu-job-20260913-v2/status-20260913T050241Z-iw5uq0t2/receipt.json)
确认 Job703415 COMPLETED / 0:0，耗时 2分52秒，实际分配1 CPU。
squeue 此时返回 Invalid job id，因为已不在活动队列；不能将它解释为提交失败。

[11份远端原始文件](compiled-cpu-job-20260913-v2/fetch-20260913T050308Z-7r3gmq7x/)
已回传并重新读取，逐一验证原始字节、大小和SHA。
[本地只读复核程序](2026-09-13-compiled-cpu-job-recheck.py)重新验证25份固定源码、
传输载荷、提交身份/nonce、资源请求、Slurm结果及日志绑定，再调用提交前已固定的
标准库读取器，从两个完整子日志重新核验配对数据；不是只接受终止标记。
[保存的本地复核结果](compiled-cpu-job-20260913-v2/JOB703415_LOCAL_RECHECK.json)
同时记录复核程序自身SHA，可重复运行上面的同一程序核对。

| 项目 | 本次实际证据 |
|---|---|
| 环境与范围 | Python3.11.5、torch2.1.1+cu118；合成32样本，B2，eager编译后端，CUDA未初始化 |
| 参考进程 | PID787357；1次加载、34次原受控前向、完整16→1两pass；84.761秒，rc0 |
| 观测进程 | PID787426；1次加载、34次原受控前向、完整16→1两pass；48.091秒，rc0 |
| 观测覆盖 | 136次阶段调用、34条批次事件、16份阶段采集；全部字节重读通过 |
| 配对检查 | 两进程对应pass的16个端点和4项输出逐字节一致；顺序、dtype、形状、runtime一致 |
| 原检查与清理 | 原编译器身份检查实际进入；state/RNG检查保留；钩子移除、身份撤销、临时目录清理记录通过 |
| 独立结论 | CPU_JOB_EVIDENCE_RECHECK_PASS / SYNTHETIC_COMPILED_COLD_PAIR_PASS |

关键SHA：

- reference.log：`a8e9344e0f375c355a4725eacf47d2f2cafa225914777224e31f71a03b4f97a3`，761112字节。
- observed.log：`149d4075d20cfc0deb16181a54867679d74883059614646d2a81d2c33298301a`，806211字节。
- TERMINAL.json：`4058586969c46aedafa35e5837dd70c0e9b1816fd349dc8aa8b1d0e9bba6b947`。
- 原始回传output.log：`3398b87b03a732c71098fc9b09b795de84b9c3b5ed32b8498ebd03a36444f41d`。

可在本地重复执行的只读复核（不联网、不提交、不运行模型）：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-13-compiled-cpu-job-recheck.py
```

完成后19项控制工具测试、16项配对读取器测试再次通过，Ruff通过。
另对新复核程序进行7项内存替换反例：参考日志、观测日志、终止记录、回传输出、
状态输出、读取器源码的字节改动，以及重复结果记录，全部被拒绝；磁盘原件未改。
终止摘要中的 jobs_submitted=0 是子进程/读取器自身未提交作业，不代表没有
Slurm作业；实际执行Job为703415，首次被取消的Job703335亦记录在上文。

## 结论边界与下一项

此前登录节点参考进程60秒超时是历史未通过记录，未覆盖或改写；新计算节点
参考进程实际用了84.761秒，但环境不同，不能据此断言旧超时的具体内部原因。
观测日志仍有PyTorch编译hook支持范围警告；本次合成CPU端点一致不能将其
推广为真实网络或Inductor的无干扰证明。

本次证明：在指定合成模型、32样本和B2/eager条件下，原受控编译接口能与
观测器共同完成完整生命周期，且两新进程的对应输出没有可见字节差异。
它不解释Job685198的真实批大小NLL差异，不是formal40真实前向，也不是
GPU准备完成：ready_for_gpu=false、real_parent_replay_completed=false。

下一项应接通已核验的真实formal40加载器与42个观测位置，先完成生产准备接口
的本地检查和有界CPU验收，再单独审批A100/Inductor与父结果重放验证。
本轮到获授权的CPU作业结果验收为止，不继续提交CPU/GPU作业或改写冻结输入。
最终目标仍是formal40、valbest33和作者checkpoint的smoke、10k/controls、配对统计与报告。
