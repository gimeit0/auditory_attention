# S2a执行台账（2026-09-18）

当前：**TEST_ONLY_REJECTED_NO_JOB**。两进程执行包已实现、测试和部署，但原生调度预检拒绝GPU参数。没有S2a作业ID，没有新模型推理、没有16/1或冷重复数值结果。S1 Job724808仍为已验收基线，不受此次预检失败影响。

## 授权与固定范围

用户在明确预算后回复“好的”：一个新作业，1 A100、8CPU、64GiB、总上限30分钟；repeat16成功并校验后才执行独立batch1进程，各为原32条、三个固定模型及7条controls。两次应各159条预测。无自动重试、无额外作业、无全量。

[授权原件](package/AUTHORIZATION.json)明确：只有held资源匹配才放行，`resource_repair_authorized=false`。不得继承S1对724808的专用修复授权。

- 远端新根：`/home/s2510040/audattn_external_eval_ops/eager_s2a_20260918_v1`
- 协议：`same_bank_eager_s2a_20260918_v1`
- nonce：`6d336525da2a443596aa8e83b37410d8`
- [冻结RELEASE](package/RELEASE.json) SHA：`f72fd6a1f5f72683d576dde9ebece90bb16ce66cf4c6388442ce9deb587f1839`
- 科学候选SHA：`d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4`（未修改）
- S1外部回执SHA：`58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027`

## 实际执行记录

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| 原回归 | 21+56+12=89项通过，范围为本地CPU/合成数据 | [REPORT](../eager-local-execution-20260917/20260917T170344Z-orycdlad/REPORT.json) |
| 新包装测试 | 18项通过；包含真实本机子进程PID/顺序、失败阻断、超时终止自有子进程、独占输出；调度RPC为模拟 | [日志](local_wrapper_tests.log) |
| 现场预检 | 队列为空，S1 COMPLETED/0:0且回执/产物不变，v4固定SHA不变，A100分区存在，新目录不存在 | [RESULT](preflight-wu69n8fo/RESULT.json) |
| 部署 | DEPLOYED_NO_JOB，新目录和6文件+RELEASE，原文件未覆盖 | [RESULT](deploy-a5o9fmnh/RESULT.json) |
| CLI与test-only | launcher --help成功；sbatch --test-only返回1，外层ACTION_RC=2，无提交 | [RESULT](test-only-fppzj_ls/RESULT.json) |
| 后续只读检查 | 队列为空、attempts为空，state仅DEPLOY.json/TEST_ONLY.json；Slurm25.05.5，JobSubmitPlugins=lua | [RESULT](scheduler-inspection-m6w0jszn/RESULT.json) |

包装测试日志SHA：`cb3db36588d55db0866b34b28f76cd9c4475abd60ddae26696cafc6b1d27cb1f`。
本地预检RESULT SHA：`757155a9e51894f7a535f775620f4594d9f0cbd1f632b0aceec56e5539206c83`。
远端原始TEST_ONLY.json SHA：`523a62e8c7c0f7f25acdc8487a69ffa3b9eb927431aea129a622624c8197da0f`。

## 失败原因与证据边界

02:46 JST原生调度拒绝：

```text
allocation failure: Invalid GRES specification (with and without type identification)
```

本包使用`--gpus=nvidia_a100:1`加`--gpus-per-node=nvidia_a100:1`，未同时使用`--gres`。选择这两个参数本意是同时绑定总量和每节点类型；官方说明列明`--gpus-per-node`与`--gres=gpu`互斥，因此本包没有混用后一组合。[Slurm sbatch参数说明](https://slurm.schedmd.com/sbatch.html)

但通用参数语义和本地模拟测试不能证明HAKUSAN的实际接收行为。现场明确拒绝了本包的双参数请求。只读配置确认有Lua提交插件，`CliFilterPlugins=(null)`，`SelectType=select/cons_tres`，sbatch为ELF可执行文件；没有插件源码/服务端trace，不能宣称已定位具体改写语句。此次RPC环境已移除SBATCH_/SLURM_变量，runner无SBATCH指令。

对照S1历史：只指定typed `--gres`通过test-only，却在真实held提交后出现H100/泛型请求；后来获得单独授权才用`scontrol update`将同一个724808的TresPerJob/TresPerNode修为A100并验证。它证明旧参数不能仅凭test-only成功就安全放行，而非证明当前包可以自动修复资源。

这是**投递参数/站点兼容性阻断**，不是模型失败或新的数值差异。成功的89+18项本地测试不包含站点真实GPU参数接收，不能覆盖这次反例；预检成功拦在真实提交之前，但任务尚未完成。

## 下一步与停止边界

保留冻结包和本次失败，不重新计算清单伪装原包、不重复同一test-only、不跳过TEST_ONLY门槛。未执行submit、release、update、requeue、cancel。

两个明确选择：

1. 获取管理员确认的、能保留A100类型的站点提交方式，先做不创建作业的参数验证，再冻结修订后的投递包。
2. 另行授权在原预算内采用S1已经实测的流程：单次held提交，仅在GPU请求错配时对**新返回的同一个jobid**修正GPU类型/数量，核验无运行、预算/身份/脚本不变及scontrol/sacct资源一致后才放行；不取消、不重提。需新授权记录与限定工具，禁止照抄724808专用脚本。

当前授权排除了同作业资源修正，所以第二项不能自行执行。预算虽批准，仍没有实际提交新作业；没有理由增加GPU运行次数或延长时限。

得到有效执行后，固定三份只读比较为：S1 vs repeat16（cold-repeat）、repeat16 vs batch1（batch-size）、S1 vs batch1（交叉检查）。旧1e-6超标仍记DIFF，不改阈值，不据结果换模型。尾批/同伴重排/额外确认集及10k全量仍未覆盖。

## 可重复的只读查询（Mac）

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/qualification/inspect_scheduler.py
```

此入口只读队列、版本、选定配置和失败记录，保存新本地证据；不调用sbatch（仅`sbatch --version`版本查询）、不修改远端文件或作业。共享连接失效时停止，不自动认证/重连。
