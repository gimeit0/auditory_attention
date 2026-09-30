# Job713897：单次提交、同作业A100修正与放行

后续终态已确认：[reference子进程50分钟超时，Job713897于14:50:58 JST失败结束](2026-09-14-job713897-reference-timeout.md)。
失败证据已核验，尚无合格数值结果；observed未启动。以下12:00排队信息为历史记录。
不要再次提交、更新或放行713897。

2026-09-14 12:00 JST 查询：**PENDING / Resources**，尚未分配节点，运行0秒。
暂扣已解除，现在等待资源；不是程序运行失败，也不是科学结果已经通过。

本次用户已确认1张A100、8CPU、64GiB、最长2小时的一次诊断作业。
连接恢复后实际sbatch一次，返回713897；该授权已消耗，不得再次submit。
同作业GPU字段修正一次、放行一次，没有新增第二个作业。
旧705468、v1/v2包、失败证据、模型、数据及数值阈值保持不变。

## 实际过程

- 11:34：[提交回执](gpu-control-20260914-v3/submit-20260914T023407Z-8zy3ngas/receipt.json)
  对应真实Job713897，nonce为`899e59b8732346d782e54b091d6f05e6`。
  控制器发现GPU请求错配而返回2，保留JobHeldUser，没有放行或自动重提。
- [暂扣状态](gpu-control-20260914-v3/status-20260914T023611Z-jod13kgb/receipt.json)
  与[独立记账复查](gpu-control-20260914-v3/inspect-20260914T024441Z-t17norbp/receipt.json)
  均确认无分配、0秒；ReqTRES为h100-20c、TresPerNode为泛型GPU、TresPerJob缺省。
  已固定runner实际为typed A100。现有证据不足以判定是哪个集群组件改写请求；
  test-only通过不等同于实际提交后的资源记录正确。
- [修正回执](gpu-control-20260914-v3/update-20260914T024949Z-hrdv1x3f/receipt.json)：
  仅对同一Job713897调用一次scontrol update，把TresPerJob和TresPerNode设为
  `gres/gpu:nvidia_a100:1`。CPU8、64G、2h、1节点及原提交标识不变。
  更新后仍暂扣；scontrol和独立sacct均确认单张typed A100。
- 11:57：[放行回执](gpu-control-20260914-v3/release-20260914T025722Z-ivw1d9j3/receipt.json)。
  再次核对原授权、固定来源、保护输入、已验证更新及现场记账后，只放行713897一次。
  Priority从0变为16437，JobHeldUser解除；GPU请求未变。
- 12:00：[只读状态](gpu-control-20260914-v3/status-20260914T025952Z-ag_imzup/receipt.json)
  确认PENDING/Resources、无节点、0秒。历史SUBMIT_ERROR和HELD_ALLOCATION保留，
  不可把这些旧记录当作修正后的当前状态；SUBMISSION_RECEIPT的SUBMITTED_HELD也是初次提交事实。

## 修正及复核

恢复脚本为独立的[repair_713897.py](../prototypes/targeted_gpu_control_20260914_v3/repair_713897.py)，
SHA256为`dcc76f61a7a66a3379e9e0e76862468843d3d41231103ffd3f6b0fde57b1270c`。
它不属于已冻结的CONTROL_RELEASE清单，没有改动或重新发布运行包。
仅允许固定JobID和nonce；原授权支持恢复到已经批准的A100请求，不扩大资源。
更新、放行各自先写独占意图及回执，通信不确定时不重试；它没有sbatch入口。
不要再次运行该脚本的update或release。

[15项本地恢复测试](2026-09-14-job713897-recovery-local.json)通过：重放实际暂扣记录，
拒绝错误GPU/数量/身份/额外资源、未经验证更新的放行、源码改变、重复放行和失败RPC重试。
这些是本地模拟RPC测试，不是GPU计算通过。

[独立离线复核](2026-09-14-job713897-recovery-review.json)核验6组真实操作的
请求载荷SHA、原始日志SHA、结构化回执绑定、原始授权与单次提交、更新和放行证据。
55份固定文件仍逐SHA一致；运行包SHA
`2adce67a2b4a0b0d38ff3bf6fbb682863b6e58fccf65743dd213b927d185c687`，
控制发布SHA `355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52`。

## 后续边界

仅查询/等待同一713897；结束后先验收协调器终态、两个冷进程的完整数组与168项采集。
PENDING或Slurm退出0都不能替代结果验收。若失败保留工件，不自动重提。
本作业仍是formal40 B2参考/观测诊断，不是formal40与作者checkpoint的最终完整比较。
最终还需要据可信诊断决定数值处理，再完成smoke和三模型同bank比较/统计/报告。
研究角色维持`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，不得标成独立测试集结果。
