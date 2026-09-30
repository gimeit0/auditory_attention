# E0 v2远端发布/只读导入检查（2026-09-25）

用户明确授权：上传v2、核验哈希、执行原生只读导入检查。本轮不提交或release作业。

- 复用现有SSH master（pid28212），无自动重连。
- 队列检查为空，v2目标不存在；新建独立目录 `/home/s2510040/audattn_e0/e0_20260925_v2` 和暂存目录。
- 本地冻结包check通过；scp上传暂存后，入口与RELEASE.json独立SHA核验通过。
- 暂存全包`PACKAGE_BYTES_PASS`；移动至同级`package`后再次全包核验通过，`E0_V2_PACKAGE_PUBLISHED=PASS`。
- Release SHA：`abcaa1af63d019e5e4d8701a8522e47f1e280cc8d477f21b2e64225485fd2f17`。
- Bootstrap SHA：`bfe2afcb4c96d7ebb16d8017ed7c62a9a3701807edfffb4cc99a83499fcee2e2`。
- v1、原冻结快照及旧缓存未改动。

原生source-check执行：`python -I -B -u package/e0_entry.py source-check <release SHA>`，外层timeout120秒/TERM后5秒强制停止，无自动重试。实际正常退出，exit_code=0。

原始回执：

```json
{"status":"NATIVE_SOURCE_ONLY_IMPORT_PASS","snapshot":{"manifest_sha256":"8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb","files":96,"existing_bytecode_files":24,"required_import_policy":"hash_checked_source_only"},"checkpoint_loaded":false,"cuda_initialized":false,"jobs_submitted":0}
```

v1遇到的SNAPSHOT_BYTECODE阻塞已在v2原生只读导入路径验证解决：96项源码快照文件核验通过，24个缓存保留而不作为该导入器的代码输入；不是删除缓存取得PASS。

本轮授权三项全部完成。没有运行提交器、没有新作业号、没有模型推理；下一步可单次held提交并审查实际资源/runner，不自动release。此PASS不是E0真实模型结果。

## 2026-09-26 单次 held 提交与资源核查

- 用户授权继续 held 提交；复用现有 SSH master pid32943，无自动重连。
- 提交前远端 state 不存在、用户队列为空、冻结包 PACKAGE_BYTES_PASS。
- 提交器仅调用一次；返回作业 **746603**，状态 SUBMITTED_HELD_NOT_RELEASED，release SHA 与上文一致。
- Slurm SubmitTime=2026-09-26T02:27:46；JobState=PENDING，Reason=JobHeldUser，Priority=0，RunTime=00:00:00，Requeue=0，Restarts=0。
- Account=student，Partition=GPU-1A，CPU=8，mem=64G，TimeLimit=00:30:00，单节点/单任务。
- **资源不符，停止释放**：提交器请求 `--gres=gpu:nvidia_a100:1`，实际 `ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:h100-20c=1`，`TresPerNode=gres/gpu:1`。当前不能视为 A100 资源检查通过。
- 只读获取 Slurm batch script；远端包 runner SHA256=`88832a18df2a6f0da103ef9f44e4c7b40da14c5c9e0d2f11366d1c2fa042368d`。已查看脚本内容，未另行对 spool 字节做独立哈希比较。
- 回执路径：`/home/s2510040/audattn_e0/e0_20260925_v2/state/SUBMISSION.json`；调度器 Command/WorkDir/日志路径均指向此 v2 package/state。
- 未 release、未修改 GRES、未重试/重新提交、未执行模型推理。
- 下一步需要用户单独授权：对 **同一作业 746603 唯一一次**修正 A100 请求，然后只读复核；本记录不授权 release。

## 2026-09-26 同作业唯一一次 GRES 修正

用户明确同意上一轮的唯一一次修正并复核，仍不释放。

- 修正前只读确认 746603 仍为 PENDING / JobHeldUser，运行时间为零。
- 唯一一次执行：`scontrol update JobId=746603 Gres=gpu:nvidia_a100:1`，exit_code=0，无自动重试。
- 修正后 `ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1`，`TresPerNode=gres/gpu:nvidia_a100:1`。
- CPU=8、mem=64G、TimeLimit=00:30:00、Partition=GPU-1A、Account=student、Requeue=0 未改变。
- `squeue` 返回 `746603|PENDING|JobHeldUser|gres/gpu:nvidia_a100:1`；Priority=0，RunTime=00:00:00，尚无分配节点。
- Slurm spool script 输出的 SHA256 与冻结包 runner 一致，均为 `88832a18df2a6f0da103ef9f44e4c7b40da14c5c9e0d2f11366d1c2fa042368d`。
- 本轮没有 release、没有重新提交、没有模型推理。资源请求复核通过，不等同于计算节点实际设备验证或 E0 验收通过。
- 下一步：获得用户单独授权后释放同一作业 746603；运行后收集与独立验收结果，不自动重试失败作业。

## 2026-09-26 用户授权释放及首次运行状态

- 用户批准释放同一作业。释放前再次只读核验 JobHeldUser、A100 请求及 spool/package runner SHA 一致。
- 执行一次 `scontrol release 746603`，exit_code=0；没有重新提交或再次修改资源。
- 调度器 EligibleTime=2026-09-26T02:31:55，StartTime=2026-09-26T02:32:01。
- 首次查询状态 RUNNING，RunTime=00:00:12，NodeList=spcc-a100g04，Reason=None。
- 实际 AllocTRES=`cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1`；TimeLimit=00:30:00，Requeue=0，Restarts=0。
- 这是调度启动与资源分配确认，尚非模型验收通过。运行中 ExitCode=0:0 不作为完成证据。
- 下一步只读查询完成状态，收集日志和双进程产物，独立验证 E0 验收；失败不自动重试。

## 2026-09-26 完成与本地离线复核

- sacct：746603 COMPLETED，ExitCode=0:0，Elapsed=00:11:16；Start=2026-09-26T02:32:01，End=2026-09-26T02:43:17，节点 spcc-a100g04。
- 远端 state 只读下载至 `collect-746603-SlcKgK/state/`；没有新提交或重跑模型。
- 完成记录 E0_COMPLETE.json：E0_ENDPOINT_PASS，scientific_alpha_result=false；PAIR_EXECUTION.json SHA=`ba621556a0e8d76d11e3aa7a152730d83a4e0ea86f41f1482e4ebe629d307c32`。
- 本地使用已冻结 package 的 `verify_package` 和 `production_e0.verify` 再次执行产物验收，exit_code=0，结果 E0_ARTIFACTS_VERIFIED，与远端完成记录和 pair 中 verification 完全相同。另核对完成记录 job/release、pair 文件哈希、双进程 PID 不同且退出码均为零。
- 离线验证环境 `/opt/anaconda3/envs/audattn/bin/python -I -B`，torch2.12.1 / NumPy2.4.6，仅校验已存数组/哈希/来源记录，不加载 checkpoint 或做推理。系统 Python 缺 NumPy、base conda 缺 torch 的两次本地环境探查/验证入口失败后，使用现有 audattn 环境成功；这不是远端作业重试。
- 两个独立进程 PID 1039926 / 1040834；21 passes，6048 条预测（不是6048条独立样本），固定96 trials。
- 再次验证通过：文件清单与数组哈希、IDs/NLL、跨进程逐位重复、original=alpha1、bypass=alpha0、观察器开关逐位一致、与728520原始/alpha1历史端点 logits及NLL逐位一致、alpha0 cue独立性、来源绑定与100%训练参数加载覆盖。
- G5 报告共21份，每份32项，合计672项固定特征公式检查通过；观察器144事件、150222字节，在预算内。G5此处核验归档报告与哈希，不是重新运行GPU公式检查。
- A/B stderr 只有 torchaudio kaiser_window 名称弃用警告，无 traceback。
- 结论：**E0 真实模型小批工程验收通过**。不是独立测试集结果，也不证明科学上的alpha效应；PAIR_EXECUTION的通用 production_verified=false/NOT_SCIENCE_QUALIFIED 字段不应被解释为本次调度失败，生产验收结论由E0完成记录及production_e0.verify提供。
- 后续：归档E0结果，按主课题计划明确E1开发子集、clean新基线、alpha条件和预算后申请下一GPU批次；本轮未授权或提交E1。
