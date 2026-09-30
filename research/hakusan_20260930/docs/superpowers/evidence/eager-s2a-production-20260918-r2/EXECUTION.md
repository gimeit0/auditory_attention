# S2a投递修订r2：执行台账

更新：2026-09-18 08:47 JST。**Job725677已于08:28:44 COMPLETED/0:0，耗时3分30秒。43份文件收集校验及两次各159预测的独立复算通过。batch16冷重复逐位一致；16/1无类别翻转，但NLL存在差异，旧1e-6标准为DIFF，不自动授予数值资格或全量授权。** 详见[完整结果](review-725677/RESULTS.md)。下文连接和运行中记录保留为历史。

## 本次新增授权

用户对上一轮明确方案回复“好的”：在原有一个作业、1 A100/8CPU/64GiB/30分钟上限内，修订提交参数并先预检；单次held提交后若GPU类型被站点改写，仅修正该同一未运行作业，再独立核验后放行。没有授权取消、重新提交、requeue、额外GPU运行或全量评估。

原件：[AUTHORIZATION.json](package/AUTHORIZATION.json)。旧r1包及其test-only失败仍保留，不覆盖为成功。r2预检将校验r1完整文件SHA、原TEST_ONLY SHA、无提交/执行记录，同时重新验证S1基线、原v4和当前队列。

## 已实现与冻结

- 本地代码：`checkpoint_compare_workflow_20260917/qualification_r2/`。
- 已部署远端根：`/home/s2510040/audattn_external_eval_ops/eager_s2a_20260918_r2`。
- 协议：`same_bank_eager_s2a_20260918_r2`。
- nonce：`5a9d94b298654616b90eddbb59ca51c8`。
- [RELEASE.json](package/RELEASE.json) SHA：`d534169c3f437df0d6b7434f2187a870b62ee4bc186d59886f73c1bd71f31747`。
- 科学候选SHA保持`d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4`。
- 模型启动器与r1逐字节相同：SHA `a42124bd9c43f2902ecf637024fed264b979525aa9887475e4a81f488da04215`。
- 控制器SHA：`d21f3a7150ef5c3ae523662dc2812c4065d5eabe3f9f76bd00b041ba3a8d465b`。
- 本地投递器SHA：`edf3d4b74c5f1a3c2ca98707f19ee4edb668470967041d6f45c30f965e93b125`。

提交参数恢复到S1现场接受过的`--gres=gpu:nvidia_a100:1`，去掉r1双GPU参数；这不是认为站点一定保留A100，仍须重新test-only、held核验。实际运行要求保持typed A100总量及每节点请求，绝不运行H100。

新增`correct-gpu`操作严格绑定TEST_ONLY、SUBMIT_INTENT、SBATCH_RESPONSE、SUBMISSION的jobid/nonce/release/argv，以及实际Slurm脚本SHA。仅识别历史已知的“CPU8/64G/node1/billing8、H100-20c=1、每节点泛型gpu:1、无总GPU类型”错配；未知差异停在held。先确认队列唯一目标、elapsed0、无AllocTRES/attempt/release，再只调用一次：

```text
scontrol update JobId=<本次真实回执jobid> TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1
```

这不是给用户直接复制的命令。工具只从本次绑定回执获得ID；不使用724808或任何历史诊断ID。更新intent/response/readback独占写入；不重试。更新后再次核对scontrol/sacct和未改变的非GPU字段。release是另一个操作，会重新独立检查，不因update返回0就直接放行。

## 本地验证

[26项测试完整日志](local_wrapper_tests.log)，SHA `2e285986b356f54593984c8445d1869286f6e9149118994496b53ad0f2e2da21`。ruff、bash -n通过。

覆盖原两进程隔离/顺序/超时/失败阻断/回执检查，新增已正确资源不更新、仅一次GPU修正且不直接release、未知更新响应不重试、不合法CPU/GPU数量拒绝、调度脚本变更拒绝、提交回执ID变化拒绝、更新导致非GPU字段变化拒绝、r1实际错误类型使test-only失败时禁止提交。

调度RPC使用模拟，不能当成现场资源校验；模型进程隔离使用本机真实合成子进程，不能当成正式GPU结果。原科学89项回归沿用上一轮同源码报告，本轮未重跑或虚增计数。

## 08:08连接阻断（历史，08:16已恢复）

执行r2 `preflight`时，尚在本地`ssh -O check`阶段中止，未建立远端请求。Python解码SSH stderr出现`UnicodeDecodeError`；随后直接只读检查确认：

```text
Control socket connect(.../.hakusan-control/master.sock): No such file or directory
ssh exit code: 255
ls: .hakusan-control/master.sock: No such file or directory
```

SSH诊断输出对中文路径采用混合转义/非UTF-8字节，导致严格UTF-8解码掩盖了底层“socket不存在”信息。这不是新的Slurm/GPU失败；未修改冻结包来掩盖异常。当时缺少可用共享连接，需要用户在自己的终端认证，不能把密码交给代理或写入脚本。用户随后回复“ok”，08:16现场预检通过，确认连接恢复。

Mac终端运行：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

看到`HAKUSAN_SHARED_CONNECTION=PASS`后继续。无需再次批准同一GPU预算；不会自动创建第二个作业。

## 已执行的现场步骤

| 步骤 | 真实结果 | 证据 |
| --- | --- | --- |
| 只读预检 | 队列为空，S1仍COMPLETED/0:0，旧r1完整包/失败记录及原v4未变 | [preflight](preflight-bqo6kgec/RESULT.json) |
| 部署 | 新根独占部署成功，无旧文件覆盖 | [deploy](deploy-m9qt7aox/RESULT.json) |
| test-only | rc0；725676仅预估编号，不是实际作业 | [test-only](test-only-rq_2wsdc/RESULT.json) |
| 唯一一次提交 | 08:23:25，实际Job725677；held，GPU被保存成H100-20c/泛型 | [submit](submit-p172331v/RESULT.json)、[修正前独立查询](status-2t3wd0r6/RESULT.json) |
| 唯一一次GPU修正 | 同一725677，仅TresPerJob/TresPerNode改为1 A100；仍held | [correct-gpu](correct-gpu-1679bxac/RESULT.json) |
| 修正后独立查询 | scontrol/sacct请求均1 A100/8CPU/64G，Elapsed0，Priority0，JobHeldUser，无AllocTRES | [status](status-gvo8i8xf/RESULT.json) |
| 唯一一次放行 | 08:24:58，重新校验脚本、回执、资源、记账后release rc0 | [release](release-97p4_6fa/RESULT.json) |
| 放行后独立查询 | 08:25:14 RUNNING，spcc-a100g02；ReqTRES与AllocTRES均1 A100/8CPU/64G | [status](status-p1zcirc8/RESULT.json) |
| 启动后再查 | 08:27:01 RUNNING，Elapsed1分47秒，Reason=None；LAUNCH.json已生成，无COMPLETE/FAILED记录 | [status](status-35lktuvj/RESULT.json) |

初次RUNNING查询处于Prolog阶段，不用它声称模型已经完成加载。硬结束时刻为08:55:14 JST。没有新作业重提、cancel、requeue、延长时限或修改科学代码。提交回执中的`SUBMITTED_HELD`是保留的历史状态，当前状态以最新squeue/scontrol/sacct为准。

## 后续只读查询和收集

**不要再运行prepare/deploy/test-only/submit/correct-gpu/release。** 查询命令可重复，绝不会创建作业：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/qualification_r2/ship_s2.py status
```

本轮已完成`collect`，独立重算两个159预测产物，并完成S1 vs repeat16、repeat16 vs batch1、S1 vs batch1三份预定报告：[收集记录](collect-_r8bke38/RESULT.json)、[独立验收](review-725677/INDEPENDENT_REVIEW.json)、[中文结果与复算命令](review-725677/RESULTS.md)。新增mean/std/max_abs为离线计算，不消耗新GPU额度。额外覆盖测试和正式全量仍未执行。

## 原执行顺序（留档，前六项已完成，不重复执行）

使用`qualification_r2/ship_s2.py`，不是r1或S1专用修复器：

1. `preflight`：只读核验旧包/基线/原始输入/队列/分区。
2. `deploy`：新根独占上传冻结r2。
3. `test-only`：原生参数检查；失败即停止，禁止submit。
4. `submit`：唯一一次held提交，保存实际jobid与原始资源记录。
5. 若且仅若已知GPU错配，`correct-gpu`；否则正确时跳过，未知错配停止。
6. `status`和`release`：再次检查资源/脚本/记账/预算后单次放行。
7. `status`：观察真实终态；`collect`仅终态可取回，随后独立验证两个159预测产物并执行三份预定比较。

所有修改动作都有独占本地及远端intent，响应不明时只查询、不重复。科学出口不变：冷重复和16/1报告不是全量比较完成；旧1e-6超标仍记DIFF，不事后改阈值。
