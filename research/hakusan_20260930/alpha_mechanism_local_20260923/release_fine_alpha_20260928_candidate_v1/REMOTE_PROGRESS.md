# 低α加密扫描：远端发布台账

2026-09-28。当前状态：`FINE_ALPHA_TERMINAL_FAILURE_COLLECTED_NO_RETRY`。753729于14:15:24 JST在spcc-a100g02以FAILED/1:0结束，Elapsed 01:48:21。A块计算后来源字段验收失败，B/C未启动；未达到完整扫描验收。下方运行/挂起/监测描述为历史记录。

## 终态及收集增量

- 本地看守最后成功查询13:21:18 JST；13:26因共享socket消失停止。这不代表当时远端作业停止。
- 用户恢复连接后，首次squeue查询失败；改查sacct确认上述终态。随后单次只读收集，[回执](collected-753729-_dy7mbjl/RESULT.json)确认147份文件哈希核验通过，未重试/重投。
- [A错误日志](collected-753729-_dy7mbjl/state/attempt/A/stderr.log)：`PROVENANCE_ENVIRONMENT`；[A失败记录](collected-753729-_dy7mbjl/state/attempt/A/output/FAILED.json)记录126份数组。缺WORKER/COMPLETE，B/C不存在，部分产物不作正式科学结论。
- 用户批准修正后，在冻结包外修正并准备独立v2；原package及收集到的state文件不变。后续以[47号修正记录](../47_FINE_ALPHA_PROVENANCE_FIX_20260928.md)为准。

## 授权边界

首次用户指令为“上传”，授权范围为将已验收候选包发布到独立目录并核验哈希。上传完成后，助手提出下一步为原生只读导入预检，用户回复“开始吧”，本次据此执行该预检。两次授权均不视为6GPU小时预算、held提交、资源修正或作业释放的授权。

预检完成后，助手明确询问单A100、8CPU、64GiB、最多6小时及单次held提交，用户回复“好的”。本次据此记录[GPU_HELD_AUTHORIZATION.json](GPU_HELD_AUTHORIZATION.json)并提交；仅该预算及挂起提交获批，资源修改和放行未包含在内。

发现GPU类型不符后，助手明确询问“仅对753729修正GPU类型为A100一次，其他资源不变，继续保持挂起”，用户回复“好的 提交任务直到”。前半句确认该修正，后半句不完整，未据此扩展为放行/运行/重提授权。独立授权见[GRES_CORRECTION_753729_AUTHORIZATION.json](GRES_CORRECTION_753729_AUTHORIZATION.json)。原始GPU审批文件保持不变。

候选release SHA：`b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f`。

固定目标：`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v1/package`。

## 初次准备记录（连接恢复前）

1. 本地包自身的隔离`check`两次通过，40个清单文件及历史参考包保持匹配；未更改冻结包。
2. 本地共享socket `/Users/gigi/发表/超算/.hakusan-control/master.sock` 两次检查均不存在。未调用SSH，不自动重连。
3. 新增外置上传脚本`publish_fine_alpha.py`与标准库接收器`fine_alpha_upload_transport.py`；支持reference子目录，传输前整包验证、远端写入后逐文件复核、独立目录禁止覆盖、发布后只读包检查，不含提交或释放操作。
4. 新增6项上传安全测试全部通过（只使用本地临时目录，没有网络）：嵌套文件、发布后复核/拒绝覆盖、坏哈希写入前拒绝、路径越界/重复/符号链接拒绝、额外文件拒绝、入口外部SHA绑定。

该时点远端目录是否存在尚未查询；**没有上传尝试、没有新建远端目录、没有GPU作业号**。当时阻碍是缺少可复用的认证连接，不是执行包校验失败。以下新记录替代该历史状态。

## 连接恢复后的实际上传（2026-09-28 11:45 JST）

用户报告“成功了”后复核现有共享socket并复用连接；没有自动重连。外置上传脚本仅调用一次，返回码0。

- 本地隔离包检查、共享连接检查、远端发布和远端包检查四步返回码均为0。
- 远端只读队列查询返回0且输出为空；随后在固定独立目录创建并发布40个清单文件及`RELEASE.json`，共41个文件。原目标不存在，未覆盖任何旧包。
- 接收器先验证完整传输包，再写入并逐文件复核，返回`FINE_ALPHA_FILES_PUBLISHED`；发布SHA与上方固定值一致。
- 远端隔离入口返回`FINE_ALPHA_PACKAGE_CHECK_PASS`；科学预测数194,400、含验收预测数219,600。此检查不是实际推理，`production_validated=false`。
- 上传后本地冻结包复核通过；没有加载真实checkpoint，没有执行生产源码导入检查，没有初始化生产推理或提交/释放GPU作业。
- 上传证据：[RESULT.json](upload-d2tzvudd/RESULT.json)、[上传意图](upload-d2tzvudd/UPLOAD_INTENT.json)、[远端发布回执](upload-d2tzvudd/publish.stdout)、[远端包检查](upload-d2tzvudd/remote-package-check.stdout)。完成时间`2026-09-28T02:45:01.859036+00:00`。

## 原生只读预检完成（2026-09-28 11:50 JST）

- 新增冻结包外的`preflight_fine_alpha.py`，只允许`check/source-check`，在执行远端入口前核验入口与RELEASE的外部SHA，复用已有SSH，不上传、不重新认证、不自动重试。每次远端子进程最多180秒，本地SSH调用最多210秒；CPU线程限制为1，CUDA设备不可见。
- 6项本地预检驱动测试通过，覆盖回执身份、缺失/错误安全字段、错误快照、非法模式及远端bootstrap语法。这是驱动测试，不替代真实导入结果。
- 11:49:46–11:50:46 JST：共享连接、远端pre-check、source-check、post-check四步均返回0；驱动仅执行一次。
- 真实原生回执`NATIVE_SOURCE_ONLY_IMPORT_PASS`：核验96个快照文件，manifest SHA `8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb`。24个既有pyc仅记录其存在，快照导入策略为`hash_checked_source_only`，不读取旧缓存代码或改写缓存。
- `checkpoint_loaded=false`、`cuda_initialized=false`、`jobs_submitted=0`；source-check.stderr为空。该PASS只说明固定源码及依赖能在原生环境导入，不证明模型推理/科学扫描通过，也不代替运行时音频与checkpoint核验。
- 远端前后包检查及结束后本地包复核通过，release SHA保持不变；没有改动冻结包，没有创建GPU授权或提交记录。
- 证据：[RESULT.json](source-check-mmwdh22h/RESULT.json)、[执行意图](source-check-mmwdh22h/SOURCE_CHECK_INTENT.json)、[原生回执](source-check-mmwdh22h/source-check.stdout)、[检查后回执](source-check-mmwdh22h/post-check.stdout)。

## 单次held提交与资源不符（2026-09-28 12:00 JST）

- 冻结包外新增`submit_fine_alpha_authorized.py`，本地固定证据目录与远端独占state双重阻止重复调用；审批文件仅在固定远端目录以独占方式创建，不修改包内文件。
- 9项既有提交/失败分支测试重跑通过，另新增9项外层授权及回执核验测试通过；均使用模拟调度结果，没有在测试中联系调度器。
- 实际远端调用仅一次：队列检查通过，`sbatch --test-only`返回0，然后`sbatch --hold --parsable --no-requeue`返回`753729`。test-only输出中的`753728`是该预检查输出，不作为第二份真实提交回执。
- 提交意图明确为`--gres=gpu:nvidia_a100:1`；实际`ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:h100-20c=1`，`TresPerNode=gres/gpu:1`。固定提交器按`SCHEDULER_TYPED_GRES`停止，回执已先行保存。
- 之后只读回读scontrol/squeue/sacct一致确认`753729`仍`PENDING / JobHeldUser`、Priority=0、RunTime/Elapsed=00:00:00、TimeLimit=06:00:00；NumCPUs=8、内存64G、单任务/单节点范围保持。作业尚未执行，不是模型或扫描运行失败。
- 实际spool脚本与冻结`run_fine_alpha.sbatch`逐字节相同，提交后远端整包哈希复核通过，release SHA未变。
- 冻结提交器返回1（资源拒绝），外层驱动返回2（保持挂起并要求人工处理）；不是第二次提交、没有修正GRES、没有放行或自动重试。
- 回执：job`753729`；state审批SHA `ad687521ea1179ca4a06ee467b886ce35af84afef250c0f130d45f519da54fee`，提交意图SHA `da33911ea6802ae6ec673ab661f88b800c49dcb7b864feb951699ffa513e34e6`，调度响应SHA `6fbfce2df8066126e373bc47b361f557c6e18e124763252275a84e2a898520ce`。
- 证据：[RESULT.json](held-submission-20260928/RESULT.json)、[本地调用意图](held-submission-20260928/LOCAL_INTENT.json)、[完整远端回执/日志/资源/spool](held-submission-20260928/remote.jsonl)。原始STOPPED记录保留，不改写为成功。

## 唯一一次GRES修正完成（2026-09-28 12:20 JST）

- 新增冻结包外的`correct_fine_alpha_753729_once.py`及5项本地保护测试，覆盖原始资源回读、预算/身份/挂起漂移、错误/额外GPU、授权范围及本地/远端保护一致性，全部通过。
- 修正前核验固定包、实际spool、job753729、8CPU/64GiB/6小时、挂起且未运行；回执SHA为`97579946e89d4efaf2f98909c9e2c7641105c7ade5c1a290328d0e55f10cffa7`，并逐项绑定审批、提交意图和调度响应。
- 以独占方式先写远端`state/GRES_CORRECTION_753729_INTENT.json`，仅执行一次`/usr/bin/scontrol update JobId=753729 Gres=gpu:nvidia_a100:1`，返回0；无重试。
- 修正后`ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:nvidia_a100=1`，`TresPerNode=gres/gpu:nvidia_a100:1`。作业仍`PENDING / JobHeldUser`，Priority=0、RunTime=00:00:00；其他资源保持批准范围。
- 前后spool与冻结runner逐字节相同，SHA `c7ac014fc70070923ebbc919dd8da83a63bf8acf0f04fb3178fea05bbf44b80c`；冻结包及原始APPROVAL/INTENT/RESPONSE/SUBMISSION/STOPPED记录均未变化。
- 远端新增`state/GRES_CORRECTION_753729_RESULT.json`，状态`FINE_ALPHA_A100_CORRECTED_VERIFIED_STILL_HELD`；本地驱动返回0。没有放行、重新提交或加载checkpoint。
- 证据：[修正RESULT](gres-correction-753729/RESULT.json)、[本地修正意图](gres-correction-753729/LOCAL_INTENT.json)、[前后回读及唯一update记录](gres-correction-753729/remote.jsonl)。

## 正式放行与持续跟进（2026-09-28 12:26–12:50 JST）

助手明确询问“正式放行753729，并跟进到运行结束及结果验收；异常时停止，不自动重投”，用户回复“好的”。[独立放行授权](RELEASE_753729_AUTHORIZATION.json)绑定release、提交回执、runner、修正结果及6小时预算，最多放行一次；不改原始预算/提交审批，不授权重连或重投。

- 新增冻结包外放行驱动及5项本地测试，包含与冻结包真实approval_gate兼容性。放行前复核包、回执、修正记录、资源及spool，独占创建RELEASE意图和运行入口所需授权文件。唯一一次scontrol release 753729返回0，即时PENDING/Reason=None/Priority16639，A100不变。放行授权SHA `1168d500b56e93bb3c1d389c98c09d3a8eb8ba7d2f8db490376b358c29005bfd`，1151字节；包及历史日志不变。[放行RESULT](release-753729/RESULT.json)、[原始回读](release-753729/remote.jsonl)。
- 12:30:03首次独立查询确认RUNNING，sacct Start=12:27:03，节点spcc-a100g02，A子进程PID3304015。日志仅见既有torchaudio弃用警告，不把活跃状态当作验收。[首次运行证据](status-753729-c6e8_m0v/remote.json)。
- 新增只读状态、终态收集和看守脚本，另5项合成测试通过。12:35:02启动本地PID59368，存活已复核；每300秒查询，最长48小时是本地看守边界，不延长GPU预算。目前4次快照的运行时间为8:05/13:12/18:19/23:24，A观察文件数6/12/18/24，B/C尚未开始，无attempt失败标记。文件数不是已验收进度，原始state/STOPPED.json仍只代表放行前资源拒绝。
- 确认Slurm终态后只收集一次固定state目录，限制1000文件/2GiB，拒绝符号链接和越界路径，核验源文件前后、传输及本地落盘哈希。COMPLETED且0:0时用冻结包offline-check验收219600条预测，并与远端COMPLETE核心字段比对。通过只标FINE_ALPHA_COLLECTED_OFFLINE_VERIFIED_ANALYSIS_PENDING，不代替科学统计/绘图或年龄映射。失败终态只归档；连接、收集或验收错误停止，不重连/重试/重投。
- 本地监测需要电脑持续运行联网、SSH有效；睡眠/断线可阻断跟进，但不会因此取消Slurm作业。[监测START](watch-753729/START.json)、[第4次观察](watch-753729/OBSERVATION_0004.json)。终态/停止时才生成watch-753729/RESULT.json，当前尚无终态结果，不重复启动看守。

## 当前下一阶段

保留753729失败证据；完成独立v2修正及无GPU回归，再申请新版本发布和新作业授权。不继续看守已结束作业，不重启旧提交/放行入口，不补写成功标记或放宽门槛。

## 放行前的历史下一门（已按新授权完成）

等待用户单独批准放行现有753729。放行前再次只读核验A100/8CPU/64GiB/6小时、审批与提交回执及包/spool；仅一次放行，后续异常保留证据，不重提、不增加预算。预计含验收pass约5.19小时，加载/哈希/归档另计，耗时不保证线性；排队时间另计。不要重复上传、提交或已完成的GRES修正入口。

## 历史续接命令（上传已完成，不再重复调用上传入口）

用户在Mac终端运行以下命令，密码只在终端输入：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

此前连接恢复后使用的上传入口如下，已成功调用一次；保留用于追溯，不应再次执行：

```bash
/opt/anaconda3/envs/audattn/bin/python -B \
  "$HOME/发表/超算/alpha_mechanism_local_20260923/publish_fine_alpha.py" \
  --execute-authorized-upload
```

若出现超时/连接中断，先检查保存的上传证据及远端状态，不盲目重复此命令。脚本不创建GPU的APPROVAL或RELEASE_AUTHORIZATION文件。
