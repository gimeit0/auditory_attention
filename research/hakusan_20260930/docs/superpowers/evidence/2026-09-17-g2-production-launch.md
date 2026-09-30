# G2 新生产目录发布与单次作业执行台账

2026-09-17。**最终状态：Job724258 已单次提交、同作业A100修正并放行；实际运行34秒后FAILED/2:0。80份失败工件已下载并独立离线核验，无有效数值结果；不得重提/重排该作业。**

用户在明确列出 1 A100、8 CPU、64 GiB、最长 3 小时、仅一次且失败不自动重试的确认请求后回复 `goon`。
本轮开头已明确说明按同意该范围继续；不扩大为额外重复作业或最终全量比较授权。
具体范围保存于 `g2-production-20260917/AUTHORIZATION.json`。所有旧作业、源码、清单和失败证据保留。

## 已完成

- 09:09:24 UTC 现场只读查询成功：队列为空、GPU-1A UP 且 typed A100、新目录不存在，原 v4 清单及 lock SHA 不变。
- 新增发布/冻结/plan 入口 `g2_submit_20260917/stage.py` 和本地 `ship.py`，使用既有、固定 SHA 的共享 SSH 传输器；无重连或自动重试。
- 30 项提交控制回归通过。6 项新发布测试通过，包括真实本地临时目录中的完整32文件写入、哈希及布局；不包含原生生产模型或调度。
- 发布测试第一轮有一项断言误将载荷中的 `run_matrix.sbatch` 文件名当成执行命令；已改为核对载荷 AST 中 SPEC 为原数据。不是生产故障，原32文件包未改。
- 原32文件候选独立只读复验通过，release SHA `6becba7b27f8ba37657e66f0173bf991aec0136e8285afbd211eeeb65318d300`。
- 远端新目录 `/home/s2510040/audattn_external_eval_diag/formal40_numeric_profiles_20260916_v1` 发布成功；32执行文件及独立控制文件逐项验证；未冻结输入或提交作业。
- 发布回执及完整载荷/输出：`g2-production-20260917/deploy-20260917T091505Z-togkme_g/`。

新入口 SHA：

- `control.py`: `581fcaafc6e4d9ef59a1d534acce7d04532ba0a3e0a6bd35769d234910e60956`
- `stage.py`: `699f25d3db41431205978b5b19c903e25b4f2ce82b49554983aea48ebb8326b7`
- `ship.py`: `f9bf535aefb7cde2f514bec61d61439b6143bc34d83e480b2cf8dc17ece3dca5`
- `test_stage.py`: `c093d97269a989ee719a8d70c3ba383be7a362c6f2497b086baae89951ec31f8`

## 四组新 freeze 与固定 plan

R/C/D/E 均在独立原生解释器中调用原 freeze_inputs，32 trials、24 pinned files，科学输入关系核对通过；实际 freeze 已下载并回读校验。

| 组 | freeze SHA-256 | 本地证据目录（位于 g2-production-20260917） |
| --- | --- | --- |
| R | e462f3ceb2afeb0e3aac96b1598b7392fa118402e1a3a248f95accc0b571765b | freeze-20260917T092307Z-y354l4y5 |
| C | 336df44913d7d79186072e363cae65d1f388302416751d61ed8ee8dfc12f1b97 | freeze-20260917T092505Z-czchac2x |
| D | e1d80cd4cc8d6903deb23c03b2c66bb857209909ebe6ba9c036bad1c29bc8d4b | freeze-20260917T092542Z-3vwbppi_ |
| E | 9ab3d87bdd1377e3218a9873e2487bb462f90f39a071f0e9b193b29f4ba49164 | freeze-20260917T092617Z-cxzfl9dz |

执行 plan 已本地固定并在远端独占写入：

- SHA：`f8d8e491fe64c3430845b25d850e8e992ea71ecd79c52d744089a318b6e4e59e`
- nonce：`69ca46b61e7a414d8d29c3bcf1ca200d`
- 回执：`g2-production-20260917/plan-20260917T092739Z-qka5l_6f/`
- 不包含预先猜定 job ID；资源固定为已说明的单次范围。

## 原生复核、单次提交及暂扣

四组原生 check-only/关系核对及 scheduler test-only 全部通过，耗时127.545秒；没有在test-only阶段产生作业。
回执目录：`g2-production-20260917/test-only-20260917T092812Z-hhohxpae/`。
远端 TEST_ONLY.json SHA：`4a5d468e6bacbe39a7d7e041864033b78785cfd958408982a8bdb93a456f9579`。

09:34:42 UTC（18:34:42 JST）实际 sbatch **仅一次**，返回 **Job724258**。
命令明确带 `--gres=gpu:nvidia_a100:1`，实际Slurm保存为`TresPerNode=gres/gpu:1`、
`ReqTRES=...gres/gpu:h100-20c=1`；控制器拒绝放行、返回2。
这是提交后资源记录与批准范围不一致，不是模型推理失败；当前证据不能确定由哪个集群组件改写。
旧Job713897/715276曾出现同类问题，但它们不参与本次操作。

- 提交证据：`g2-production-20260917/submit-20260917T093435Z-y6un2bmv/`。
- RUN_REQUEST SHA：`7225bb609611114f84026e4eca7fc107ac5ccfb8db4946f2bceb81db9565e309`。
- 原始独立status：`g2-production-20260917/status-20260917T093537Z-bt0s90yb/`。
- 完整只读检查与四份原生check记录：`g2-production-20260917/repair-inspect-20260917T102141Z-ykt5oidb/`。
- 现场Slurm25.05.5、GPU-1A十节点均typed A100；该作业PENDING/JobHeldUser、Priority0、Elapsed0，无分配。

## 同一作业修正

新增独立 `g2_submit_20260917/repair_724258.py`，不修改已发布代码、四份freeze或plan。
源码SHA：`931cd810c24a2ba1db94ed1351630b2e5a621948ea35fe607c2bfb2a450ff8dd`。
17项本地回归使用实际下载的held与提交/check回执，变更RPC是模拟的；全部通过（0.101秒）。
覆盖原始授权/请求绑定、错误身份/资源拒绝、实际记账一致性、重复及不确定RPC拒绝、先更新后独立放行。

仅允许同一Job724258把TresPerJob/TresPerNode修正为`gres/gpu:nvidia_a100:1`，其他预算、代码和身份不变。
不新增作业、不重排、不取消；更新与放行是分别授权、分别记录的动作。任何不明确状态只读核实，不能重跑。
用户分别批准更新与放行操作。
更新成功且仍暂扣：`g2-production-20260917/repair-update-20260917T102452Z-9k201rwc/`；
scontrol和sacct均确认`gres/gpu:nvidia_a100=1`，其余资源和身份不变。
单次放行成功：`g2-production-20260917/repair-release-20260917T102700Z-et0hqfb_/`。
19:27 JST后只读status显示RUNNING、spcc-a100g06、实际分配1A100/8CPU/64G；
该中间运行状态已被下述终态取代。全程实际sbatch一次、update一次、release一次，没有新增第二个作业。

## 终态与完整失败证据

- Slurm：`724258|FAILED|2:0|00:00:34`，spcc-a100g06。
- 起止时间：2026-09-17 **19:27:29–19:28:03 JST**。
- ReqTRES/AllocTRES均为8CPU、64G、1张typed A100；本次失败不是误跑H100。
- 协调器`EXECUTION_INVALID / STOP_EXECUTION_INVALID`；仅启动R，C/D/E均`NOT_RUN`。
- R worker PID852000，正常返回非零2；不是1800秒超时或内存不足记录。
- R具体错误：`G2 preparation: CUDA already initialized before CUBLAS configuration check`。
- 实际子进程环境已含`CUBLAS_WORKSPACE_CONFIG=:4096:8`；不能归因为变量未传入。
- 原源码postcheck通过；没有ARCHIVE_RECEIPT、推理数组或可解释数值结果。
- 20:52 JST最后只读复查：本人队列为空，724258记账仍为FAILED/2:0、34秒，没有重复或遗留运行作业。
  回执：`g2-production-20260917/status-20260917T115232Z-ahinkrmc/`。

下载目录：`g2-production-20260917/terminal-20260917T114730Z-jwssu96n/`。
80份文件，总3248939字节，包含固定32文件执行包、4份freeze、提交/修正/放行日志、全部持久化attempt与日志。
收集器只读，不读取模型权重内容、不修改远端文件、不提交作业；对终态文件两次读回及本地保存逐SHA校验。
不声称包含计算节点`/tmp/audattn_g2_724258`的全部临时内容；该路径按原协议保留。

- 下载RECEIPT SHA：`e1393c2ec4f1baa02071c4495e2b8aa328e15d2dc54c30e0d9c8b0ce0ade0f13`。
- R TERMINAL SHA：`e2ee230f89c1cb17114a55cce74e870af6654d61435ce617faaa9f71c0c29275`。
- 只读收集器SHA：`778e93afa1b06845489d8c722dfab6da835a83796b05d09ccf056f318418b244`。
- 独立离线复核：[2026-09-17-job724258-review.py](2026-09-17-job724258-review.py)。
  返回`RECORDED_EXECUTION_FAILURE_VERIFIED`，核对80文件、32固定源码逐字节不变、4清单、原提交和同作业更新/放行、
  真实A100分配、launch PID/环境、失败与未运行分组一致性；没有模型运行或远程调用。

## 已定位边界与下一项

保存的R候选`prepare_formal40_worker`在第6065行调用`_g2_before_configuration`，此检查抛错。
原`evaluator._configure_runtime`及`strict_load_model`都位于它之后，所以此次没有进入该正式模型加载与数值比较。
`ProductionCell.runtime_check()`在更早处验证CUDA尚未初始化，随后发生编译后端预导入、冻结场景模块导入和来源复核。
现有终态只证明这一窗口内CUDA状态发生了变化，**未记录首次初始化调用栈，不能断言唯一触发者**。

下一项：在新的本地候选中定位该窗口，修正冷启动验证与导入的顺序/边界，补覆盖“导入可能初始化CUDA”的回归。
保留预导入CUBLAS配置、原seed一次、正式strict-load和所有数值阈值；不能直接删掉保护或把production改为hermetic-test。
旧32文件包、远端发布、四份freeze、请求、失败终态均保持原样。
新版本如需GPU验证，须另行确认单次预算；本次一次作业额度已使用，不以仅运行34秒为由重用授权。
正式checkpoint总体比较、冷重复及完整10k预测仍未完成，研究角色仍为复用验证bank审计而非独立测试集结果。
