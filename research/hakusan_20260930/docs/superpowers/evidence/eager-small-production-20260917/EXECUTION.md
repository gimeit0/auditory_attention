# 首次精简小样本执行：Job724808 执行台账

建立2026-09-17，更新2026-09-18 01:35 JST。**Job724808已COMPLETED/0:0，耗时2分49秒；真实32条三模型产物已下载并独立校验/重算通过，P04/S1完成。** 00:16:10–00:18:59在spcc-a100g07运行，实际1 A100 / 8CPU / 64GiB。仅提交一次；仍是`SMALL_RUN_COMPLETE_NOT_QUALIFIED`，不表示batch16/1或冷重复通过，也不是10k全量完成。以下暂扣/修复/运行查询是保留的历史，最新验收见文末。

## 授权与范围

用户在明确的1 A100、8 CPU、64 GiB、30分钟、单次且不重试预算后回复“开始吧”。本轮开头按该范围确认后执行。
原32条、batch16、formal40/author_external/valbest33及原controls；不是10k全量，不追加batch1或重复运行。

授权原文和限制：[AUTHORIZATION.json](package/AUTHORIZATION.json)。
执行包：[RELEASE.json](package/RELEASE.json)，SHA `e513fb99de9e731d867c194414a466ee40be5a0bf32bd8cb77cdcc2e62509927`。
nonce `d43522ea059d47688fd05235f8adeccf`。
远端全新目录：`/home/s2510040/audattn_external_eval_ops/eager_small_20260917_v1`。

## 实际执行顺序

1. 现场只读核对通过，队列为空、原v4四项SHA不变、Python3.11.5、GPU-1A正常并有typed A100。磁盘查询为文件系统可用空间，不冒充用户quota证明。
2. 89项原本地回归再次通过：[报告](../eager-local-execution-20260917/20260917T143828Z-9ax4qwff/REPORT.json)，SHA `216dceebd43477c64df1d93869371fde9c1c9f8c2a90641d171cc3e506866e1f`。
3. 14项投递控制测试通过：[日志](submission_tests.log)。测试包含真实本地进程返回码/超时和合成Slurm记录；最初未覆盖实际Slurm冒号字段和节点范围，这个遗漏见下文。
4. 独占新目录上传、逐文件SHA校验完成：[发布回执](deploy-7il9obz1/RESULT.json)。旧候选、原v4和旧失败证据均不改。
5. 原生候选CLI帮助及 `sbatch --test-only` 通过：[回执](test-only-xxq23qv5/RESULT.json)。其中724807是test-only估计编号，不是真实提交；预计9/23启动不构成保证。
6. **23:40:37 JST实际sbatch一次，返回Job724808**：[提交回执](submit-xdv0z7y_/RESULT.json)。首次提交阶段只提交为held；后来获准单次update，见下节；全程没有release/requeue/cancel或第二次sbatch。
7. 独立只读查询：[原始状态回执](status-yyum1i2c/RESULT.json)，SHA `afc6a2dac5f33d9b4a4c3e2dca99277c4a9883ed230db5a9424b34aa16a6917a`。

## 初次提交时的两个问题（原始失败证据保留）

### A. 实际GPU请求被改写

提交命令含 `--gres=gpu:nvidia_a100:1`，但原始scontrol与sacct都记录：

```text
JobId=724808
JobState=PENDING Reason=JobHeldUser Priority=0
ReqTRES=cpu=8,mem=64G,node=1,billing=8,gres/gpu:h100-20c=1
TresPerNode=gres/gpu:1
AllocTRES=(null)
RunTime=00:00:00 TimeLimit=00:30:00
```

这是当时实际资源不符合批准范围，不是仅解析器误报。证据不能确定是哪一个集群组件改写。此错误请求已按下节修复；不得放行到H100，不得重新sbatch。

### B. 新投递解析器自身有三个兼容性遗漏

最先返回的错误是 `Scheduler mismatch Partition: GPU-1A AllocNode:Sid=...`，并非直接报告H100。

- 字段正则不认识带冒号的键（`AllocNode:Sid`、`ReqB:S:C:T`），导致相邻字段值串接。
- 暂扣记录的 `NumNodes=1-1` 是精确一个节点的范围表示，不应误判为两个节点或格式不合法。
- `AllocTRES=(null)` 表示未分配，不能因为字符串非空而判定已经分配。

用刚下载的真实状态创建8项回归：[本地测试源码](../../../../checkpoint_compare_workflow_20260917/submission/test_scheduler_native.py)、[日志](native_scheduler_tests.log)。
首次定位时，三个修复仅在测试内存副本应用，没有更改已上传控制器、冻结包或待运行作业。后续经用户另行批准，已按下节部署。
修复后仍正确拒绝实际H100请求；人工构造“已正确修复GPU”的测试副本才允许暂扣检查通过，绝不把该副本写成真实远端证据。

## 2026-09-18：获准修复、实装及单次GPU更新

用户对“修正同一待运行作业的资源请求和投递控制，保留原包，不新增作业、不直接放行”回复“好的”。修复授权保存于远端 `repairs/job724808/REPAIR_AUTHORIZATION.json`，且包含在末次只读回执的 `control_amendment.authorization` 中。

修复没有修改或重新提交Slurm批脚本：`scontrol write batch_script 724808 -`取回的实际脚本SHA始终等于原`run_small.sbatch`。该只读取回方式参考[Slurm官方scontrol说明](https://slurm.schedmd.com/scontrol.html)。脚本引用的Python控制文件在启动时读取，因此在held期间更新该文件无需新建作业。

操作：

1. 35项本地回归通过（原投递14项、真实记录解析8项、修复13项），[日志](repair_local_tests.log)，SHA `e25698afde8ac9fa8d002ed7883ee351e1d059679dab28d61f1ee6c54fea161c`。新增测试实际走临时目录的归档、替换及校验；调度RPC仍是模拟，不冒充GPU验证。
2. 原生只读确认原包、四份提交日志、Slurm脚本、未运行状态：[安装前回执](repair-inspect-p6qqe0ef/RESULT.json)。
3. 完整原包与RELEASE独占归档到远端 `repairs/job724808/original/`，逐文件核验原SHA。追加 `state/CONTROL_REPAIR.json`，绑定原release、固定job/nonce、四份原日志、唯一更换文件及新SHA。
4. 只原子替换 `tools/remote_control.py`。原版保存在上述归档，可恢复；候选推理源码、launcher、sbatch、原授权和原RELEASE均逐字节保留。修复版从真实路径加载并核验通过：[安装回执](repair-install-5mwd_hdu/RESULT.json)，SHA `dd5541deecd76eadf87b5776a1d6004cd3e40d529dead7ae8e355385ece6b1aa`。
5. 仅一次RPC：`scontrol update JobId=724808 TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1`。其余预算、身份、路径及held状态不变：[更新回执](repair-update-gpu-irfme3vl/RESULT.json)，SHA `0e37553471fde73cada87d9f8b68a7abb2aa514d9aef3bdb7a50233525391878`。
6. 新的独立只读核验通过：[末次核验](repair-inspect-6ty1jjww/RESULT.json)，SHA `10bbe7dd2ed9c17ee47d0772754578f3379fe0e43ed94369e21427d322c60df3`。scontrol与sacct均显示1 A100 / 8 CPU / 64G / 30分钟；`JobHeldUser`、Priority0、Elapsed0、无AllocTRES，队列仅该作业。

固定修复源码与绑定：

| 项目 | SHA-256 |
| --- | --- |
| 原控制器（归档） | `fc8617224ba852e3d57fc68ee9ac07b64e38a46289a1fd00018cbbfc2f66d037` |
| 修复控制器 | `d0fb9e2c295765c0aea835490d9ef78c01126d8e9a73b9541bc53c3ca665e503` |
| 专用修复工具 repair_724808.py | `5a365141361327b8b3f4526dff86a47d83126a49f784b64bca02609a5b2c3625` |
| CONTROL_REPAIR.json | `5e17eeea9e88102d8f2c6c5926c1a0f58190f0ec3e873f48990835be784dd163` |

原RELEASE并未改写。它仍描述原包；修复说明明确声明只覆盖控制文件，不把原SHA“重新计算后冒充未变”。运行前后同时校验原包归档、原提交日志及修复后的活动文件。`release_authorized=false`仅说明本次修复未授予放行权；未来必须另行保存放行授权与操作记录。

## 修复完成时的操作边界（00:07历史，放行记录见下节）

- 已提交一次，额度不允许自动创建第二个作业。
- 当前没有release、GPU分配或checkpoint输出；不是数值资格失败，更不是全量比较完成。
- 控制兼容性与A100资源均已修复。下一步是单独批准放行同一Job724808，再核对实际分配及计算结果。
- 本次修复代码没有release动作。修复后的旧`release_job`入口也明确拒绝自动放行，不能用旧脚本绕过。
- 原`ship_small.py`绑定原始控制源码，现已不适合本次修复后的操作；不要重新prepare/deploy/submit/test-only或用它status。当前held阶段采用下方只读检查脚本。

Mac上的只读查询命令：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-18-eager-small-724808-held-check.sh"
```

该入口只复用现有共享SSH，不自动认证/重连。它核验当前“尚未放行”的阶段；放行后应换用对应运行状态检查，不把held检查失败当成作业失败。共享连接失效时先用原连接脚本在终端认证，密码不写入文件。

## 2026-09-18 00:16：单独授权放行，已开始运行

用户对“是否现在放行724808，开始32条样本的三模型验证；不是全量checkpoint对比”回复“好的”。此次授权独立于先前仅允许修复的授权。未更改原包、修复说明、候选、launcher、sbatch、预算或原提交回执。

1. [新的只读复核](repair-inspect-gxetqkio/RESULT.json)确认仍为JobHeldUser、Elapsed0、typed A100、原归档/修复/提交记录一致。
2. 新增专用`release_724808.py`，只有单次release和只读status；必须确认固定Job724808。放行前重新核验现场scontrol、sacct、队列身份、原Slurm脚本、四项原v4 SHA和修复后的活动包。独占写入本地意图及远端RELEASE_INTENT后仅一次release RPC；超时/失败保留意图，不自动重试。
3. 42项本地控制测试通过（35项原回归+7项放行测试）：[日志](release_local_tests.log)，SHA `c17799c7fbe98fe4332567c20d65344116bf6c7841fd08f5375603aecd13ea32`。新增测试使用真实临时文件和模拟调度器，不是模型/GPU验证。
4. [单次放行回执](job724808-release-once-1fb7s1rg/RESULT.json)：`scontrol release 724808`返回0，远端授权意图时间00:16:04 JST。放行源码SHA `c0b4ff2d9d1962f421485f0d868a644727c270e2d9b6a0156f0d64e4e3696067`，RELEASE_INTENT SHA `3281646fd12a5effb0457d36b211cdc506ea2883e1a52c70b865a34336d6341e`；RELEASE_RESPONSE SHA `ba2a33e0b55ab71db0ba9a09c68fbcdade0c4ce637fd506ad9c696a8bf24e32b`。
5. [独立运行查询](job724808-status-97l5y6l0/RESULT.json)：squeue、scontrol、sacct均为RUNNING，StartTime=2026-09-18T00:16:10，NodeList=spcc-a100g07，ReqTRES与AllocTRES均为1 A100/8CPU/64G，TimeLimit=00:30:00。启动器通过实际资源验证，生成`LAUNCH.json`（SHA `ce97333a77c50ec46abf7351cdbc639a9189620a057cd8ad801f85cc38e9bc05`）。这证明启动，不证明科学结果通过。

交接前[00:18只读复查](job724808-status-jzl_ucwp/RESULT.json)仍为RUNNING、Elapsed00:02:01，实际资源不变，无终态回执。

当前只允许继续查询/收集/核验此作业，不重复release或sbatch。原`SUBMISSION.json.status=SUBMITTED_HELD`记录提交瞬间，保留不改；当前状态以新调度查询为准。

已放行阶段的只读命令（Mac）：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-18-eager-small-724808-status.sh"
```

不要再用held-check：其“尚未放行”断言在当前阶段会按设计拒绝。下一步是核验作业终态、日志及真实产物；本次不包含冷重复、batch1或10k全量作业。

## 2026-09-18 01:35：终态与S1产物独立验收通过

用户要求“检查”。本轮只有远端只读查询/取回与本地重算，无重提、放行、模型重跑或远端代码修改。

- [终态查询](job724808-status-n16rnl9m/RESULT.json)：sacct=`COMPLETED`，ExitCode=`0:0`，Elapsed=`00:02:49`，开始00:16:10、结束00:18:59 JST，节点spcc-a100g07，ReqTRES/AllocTRES均与批准预算相符。squeue空；scontrol已不保留该作业并报Invalid job id，不能将其误读为计算失败。
- 回执外部固定SHA：`58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027`。状态为`SMALL_RUN_COMPLETE_NOT_QUALIFIED`。
- [完整只读收集记录](collect-724808-8lr7w3yd/RESULT.json)：37文件、747658字节，新本地目录逐文件校验SHA；SHA `4d589c81a87fa62e06f10e99369575669b17a64265fff041ed5e61eabbbb48c7`。仅复用现有`collect`分支，重新绑定已批准修复后的控制SHA；不调用旧submit/release。
- [独立复算报告](collect-724808-8lr7w3yd/INDEPENDENT_REVIEW.json)：SHA `3170f61ffad8635a9ee4043500af82560f47ead5c8d1f0b016d507be8230c05a`。使用本地已固定的候选与v4 core，调用`review_runs.read_archive`重新读入文件清单、checkpoint身份、32条trial、历史scene、cue、运行设置及加载报告，并从保存的FP32 logits以NumPy重算预测/NLL/概率。另与Slurm终态、实际分配及LAUNCH的job/pid/hostname交叉核对。此次本地核验没有导入Torch或执行模型。
- 三模型各严格加载62622520个可训练参数，覆盖率1.0；运行声明为eager FP32、无AMP、无compiled forward、TF32关闭，模型/RNG/bank状态检查通过。
- 原32条均有三模型correct-cue预测；其中7条各有shuffled/silent/distractor额外控制：`32×3+7×3×3=159`条模型—条件预测，12组logits均验证通过，无FAILED标记。
- [完整计算日志](collect-724808-8lr7w3yd/archive/logs/small_724808.log)：SHA `e0918b480a4f5efbd334cc29b96d0755751057480bc04ed558b886a407231f20`。所有阶段完成，无Traceback/STAGE_FAILED；有已知torchaudio重采样名称弃用警告，未中断执行。实际scene/预测阶段19.012秒，其余主要是运行时初始化、输入核验与首次模型加载；不据此直接承诺全量耗时。

仅供核对的32条固定诊断样本correct-cue结果（不是总体性能估计）：

| 模型 | 正确/样本 | Accuracy | 平均NLL |
| --- | --- | --- | --- |
| formal40（主模型） | 11/32 | 34.375% | 3.754475 |
| author_external | 12/32 | 37.500% | 3.406161 |
| valbest33（补充） | 13/32 | 40.625% | 3.417651 |

不能用这个小诊断子集宣布模型优劣或重新选主checkpoint。研究身份仍是复用验证bank的审计，不是独立测试。

结论：P04/S1已验收。下一阶段是P05/S2的独立冷重复、batch16/1及覆盖检查；其预算需另行批准，本轮没有提交。原始1e-6 canary政策没有放宽，数值资格仍`NOT_ESTABLISHED`，全量比较仍未完成。
