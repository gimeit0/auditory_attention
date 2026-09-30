# GPU单次提交已获确认，尚需恢复认证连接

2026-09-13，用户对上一轮明确的资源确认问题回复“开始下一步”。
[本次授权记录](gpu-control-20260913-v1/USER_RESOURCE_APPROVAL.json)限定：
1次、1张A100、8CPU、64GiB、最多2小时，失败不自动重提；仅用于本候选
formal40冷参考/观测数值诊断，不扩展为三模型全量比较或其他作业。

执行前51份固定来源校验通过；此前test-only回执SHA
`edf2927a08d32a95b45ee4c781d50cbd62a9a8fb51b01f9c17f03509c6836cd7`
再次重读一致，本地LOCAL_SUBMIT_INTENT不存在。

2026-09-13T09:07:43Z附近，在沙箱外调用已固定控制器的只读status操作时，
本地报FileNotFoundError：`.hakusan-control/master.sock`不存在。
进一步检查共享连接目录仍为本用户700权限，但目录下没有socket。
控制器在master_check阶段退出1，早于SSH传输与任何提交意图。
**本轮没有调用submit或sbatch，没有远端查询结果，也没有新增提交。**
不能用上一轮空队列证明此刻远端完整状态；恢复认证后仍须查询和复核。
没有运行自动重连、写入密码、修改旧发布包或重跑部署/test-only。

下一步由用户在Mac终端运行已有连接脚本，密码仅在SSH提示输入：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-10-hakusan-connect.sh
```

出现`HAKUSAN_AUTHENTICATED=PASS`及`HAKUSAN_SHARED_CONNECTION=PASS`后，
可继续同一候选的单次提交流程，无需重复上传。继续前应先确认无已有
提交意图/真实作业，以及预检记录仍在24小时有效期；过期则只刷新预检。
如随后出现提交意图，必须按同一JobID/回执核对，不能依据本记录的
“尚未提交”历史快照盲目重复操作。
