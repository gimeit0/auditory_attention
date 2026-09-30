# Job705468已单次提交并暂扣：GPU请求记录与A100分区不一致

后续更新：用户确认同作业恢复后，已原地修正A100请求并单次放行，见
[修正与放行记录](2026-09-13-job705468-corrected-released.md)。下文保留原暂扣阶段历史，
不代表当前仍暂扣；不要重跑原submit。

2026-09-13，用户恢复认证后要求“开始”。按此前已确认的单作业资源范围，
复核51份来源、资源授权及成功test-only回执后，只调用一次固定提交控制器。
Slurm创建了真实作业**705468**，但资源核对未通过，因此没有放行。

当前核验状态：`PENDING / JobHeldUser`，运行时间`00:00:00`、无分配节点。
这是暂扣，不是普通排队等待资源；不处理并放行就不会开始运行。
没有GPU推理或新的模型比较结果，也没有重提、取消或更新作业资源。
此前预检输出704798不是该实验的真实JobID。

## 本轮发生了什么

1. 已恢复的共享SSH连接查询成功；远端先前没有授权/提交记录。
2. 本地51份固定来源及此前test-only回执重验通过；无已有本地提交意图。
3. 在本地持久写入独占提交意图；远端复核预检时效、来源、原始输入和队列。
4. 远端写入授权及提交意图，仅调用一次`sbatch --hold`，得到`705468`。
5. 核对Slurm保存的资源时，报`requested CPU/GPU/memory count differs`。
   控制器保存错误记录，退出2；没有执行`scontrol release`。
6. 随后仅做同一作业状态、保存资源记录、分区GPU类型和TRES表的只读检查。

退出2在这里**不表示未提交**。保存的提交回执证明作业已经创建。
新授权的单次提交机会已使用；原授权文件中“未使用”是提交前快照。
**不要重跑submit、删除意图或重建目录来尝试绕过这一状态。**

## 交叉检查

| 检查项 | 实际记录 |
|---|---|
| JobID / name | 705468 / audattn_b2_coldpair |
| 分区 | GPU-1A |
| CPU / 内存 / 时限 | 8 / 64G / 02:00:00，符合授权 |
| `ReqTRES`中的GPU | `gres/gpu:h100-20c=1` |
| `TresPerJob`、`TresPerNode` | 都是非类型限定的`gres/gpu:1` |
| `sacct`记账中的请求GPU | 同样为`gres/gpu:h100-20c=1` |
| GPU-1A十个节点公布的GRES | 都是`gpu:nvidia_a100:2` |
| TRES资源表 | nvidia_a100=1007，h100-20c=1015，通用gpu=1018 |
| 分配与运行 | AllocTRES为空、无节点、运行0秒 |

固定runner申请`--gpus=1`和GPU-1A，没有明确填写GPU型号。
本地用真实HELD_ALLOCATION记录重放原资源核对函数，稳定复现同一拒绝。
原检查要求通用`gres/gpu=1`；现场ReqTRES不仅缺少这个键，还出现与分区
公布类型不一致的`h100-20c`。不能只删除检查或视为普通字符串别名。

官方[GRES说明](https://slurm.schedmd.com/gres.html#Running_Jobs)允许请求限定GPU类型。
但上述现场信息还不足以确定是未指定类型的解析、站点提交规则，还是
调度器/记账资源映射造成不一致。**没有证据证明已分配H100或A100**；
此刻根本尚未分配。不得把该差异直接判为模型问题或强行放行。

## 证据与固定来源

- [提交回执](gpu-control-20260913-v1/submit-20260913T091737Z-qba28zs8/receipt.json)
- [提交后查询及远端日志](gpu-control-20260913-v1/status-20260913T091824Z-yvsk2kig/receipt.json)
- [实际保存的HELD_ALLOCATION](gpu-control-20260913-v1/HELD_ALLOCATION_READBACK.json)
- [分区节点GPU类型](gpu-control-20260913-v1/GPU1A_NODE_GRES_READBACK.txt)
- [TRES类型/编号](gpu-control-20260913-v1/SLURM_TRES_TABLE_READBACK.txt)
- [同一作业记账请求](gpu-control-20260913-v1/JOB705468_ACCOUNTING_TRES_READBACK.txt)
- [独立复核汇总](gpu-control-20260913-v1/JOB705468_HELD_REVIEW.json)

51份来源及三组操作的请求/响应/原始日志/回执逐SHA绑定再次通过。
本地意图、远端授权和意图内容一致；提交响应恰为`705468`。
没有RELEASE_INTENT、RELEASE_RESPONSE或RELEASED记录。

控制器清单SHA：`22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646`

运行包SHA：`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`

pair nonce：`b2a68a80c4fb4717901cc76230af53e8`

旧候选代码、清单、模型、冻结输入、阈值及历史失败证据保持不变。
上述资源检查只读；未修改集群配置、未运行新test-only或第二次sbatch。

## 下一项与边界

保持705468暂扣。建议用户确认后，只针对**同一作业**核查并修正GPU请求，
保持1A100/8CPU/64GiB/2h及原科学运行包不变，再完整复核后单次放行。
这需要新的、留痕的同作业恢复步骤，不能重跑已有submit入口。
若集群不允许原地修正或映射矛盾无法解释，则保留现场并报告，不能擅自
取消重提、更换GPU类型或放宽校验。此次尚未执行该修正/恢复步骤。

后续真实GPU冷对照验收、工件回传及三模型最终比较仍未完成。
