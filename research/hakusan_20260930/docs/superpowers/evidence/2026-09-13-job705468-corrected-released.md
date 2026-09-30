# Job705468：原地修正为A100，已单次解除暂扣

2026-09-13，用户回复“go on”，同意上一轮提出的同作业修正方案。
本轮只更新和放行**原作业705468**；新增提交0次、取消0次、重排/重提0次。
原单次提交仍只对应705468。模型对比结果尚未产生。

## 实际结果

- 18:39–18:40 JST：单次原地更新GPU类型，RPC退出0；仍为JobHeldUser。
- 18:41 JST：重新核对资源、51份来源及6份原始输入后，单次release退出0。
- 18:42 JST附近查询：`705468|PENDING|0:00|(None)`，无分配节点。
  暂扣已解除，Priority由0变为16437；等待调度，并非已经在运行。

| 资源项 | 修正前 | 修正后（scontrol与sacct均验证） |
|---|---|---|
| GPU请求 | ReqTRES为h100-20c；per-job/node未指定型号 | 1张nvidia_a100 |
| 分区 | GPU-1A | GPU-1A |
| CPU / 内存 / 时限 | 8 / 64G / 02:00:00 | 不变 |
| 作业/节点GPU限定 | gres/gpu:1 | gres/gpu:nvidia_a100:1 |
| JobID / nonce / runner | 原固定记录 | 不变 |

CPU/内存/时限没有扩大；原runner、AUTHORIZATION、SUBMIT_INTENT、
冻结清单、模型及科学数值阈值均未更改。旧错误和HELD_ALLOCATION保留为历史证据。
放行前后资源记录的独立比较仅发现Priority与Reason变化。

## 修改依据与安全范围

现场版本为Slurm25.05.5。对应版本的官方
[update_job.c](https://github.com/SchedMD/slurm/blob/slurm-25-05-5-1/src/scontrol/update_job.c#L943-L952)
支持TresPerJob和TresPerNode；保持作业暂扣，仅一次更新：

```text
scontrol update JobId=705468 TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1
```

新恢复脚本在原固定包之外，不修改旧控制器。它要求两处请求明确限定A100、
GPU总量为1、CPU8/内存64G/单节点/2h一致，调度器与记账记录一致、
未运行且仍由用户暂扣，相关队列只有本作业。接受Slurm实际输出中仅有
正确类型的`gres/gpu:nvidia_a100=1`，也支持同时存在且值为1的通用GPU总量；
**不接受H100作为别名，不放宽GPU型号或数量检查。**

更新与放行分成两次调用，各有本地/远端独占意图和完整回执；失败或不确定
不自动重试。更新后的实际资源经独立重验通过，才调用一次`release 705468`。
原始非类型请求为何曾出现H100记账仍未确立根因；本轮确认的是该作业当前
保存的请求已在各层一致限定为A100，不声称已经分配或运行A100。

## 验证和留痕

新脚本12项本地测试全部通过，包括真实暂扣记录重放、错误GPU/数量、
身份/CPU/内存/时限变化、重复字段、记账不一致、RPC失败禁止重试、
更新不放行、成功后仅一次放行等。测试为本地模拟，远端成功另由回执证明。

- [修正前审批与源码SHA记录](gpu-control-20260913-v1/SAME_JOB_REPAIR_REVIEW.json)
- [单次更新回执](gpu-control-20260913-v1/update-20260913T093954Z-5gjz49so/receipt.json)
- [单次放行回执](gpu-control-20260913-v1/release-20260913T094133Z-5_5vm7vu/receipt.json)
- [放行后只读查询](gpu-control-20260913-v1/status-20260913T094157Z-10s1h_vz/receipt.json)
- [修正脚本](../prototypes/targeted_gpu_control_20260913/repair_705468.py)
- [本地拒绝/单次操作测试](../prototypes/targeted_gpu_control_20260913/test_repair_705468.py)

更新回执SHA：`a1a7c7b8ec5571adfc272c68133a8a972d59aad4583be5d804d7b0eaaebd0d1a`

放行回执SHA：`2a30bab1fe481d9d6989c27fb4e8b23c3a935b0146288df689503501de7750ef`

恢复脚本SHA：`4a8445af98c9042d996aa98fca0168a105d56bb67612a12c5da4d091805adade`

原51份控制/运行包来源和完整请求、日志、回执重新逐SHA通过。
运行包SHA仍为`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`。

## 接下来

只查询705468，等待真实计算结束后回传并验证参考/观测工件。
不要再次运行submit、update或release。只读命令（Mac本地）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_control_20260913/control.py status
```

这是formal40的B2冷参考/观测诊断，不是最终三模型比较或独立测试集成绩。
角色仍为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
真实GPU执行、诊断工件验收、随后与作者checkpoint的完整比较仍未完成。
