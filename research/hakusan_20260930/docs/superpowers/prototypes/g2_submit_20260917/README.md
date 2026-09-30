# G2 单次 held 提交控制候选

`control.py` 是独立于已固定 32 文件执行包的提交层，不修改模型、评估器、科学输入或数值阈值。
仅接受固定 GPU-1A、1 A100、8 CPU、64 GiB、3 小时的 plan；提交前必须获得用户授权。

入口：`test-only`、`submit`、`status`、内部冷进程 `check-profile`。
生产 CLI 仅接受固定 HAKUSAN 路径、Python 3.11.5、隔离解释器、本人登录节点环境；本地拒绝执行。
所有模式要求外部 plan/controller SHA。`submit` 还要求已核验 test-only 回执 SHA 和明确确认 token。
token 只是程序保护，不能代替用户批准；不要自行填入并提交。

提交意图先独占落盘，随后仅一次 `sbatch --hold`。新 job ID 与原 plan 绑定后，核对 held 作业资源并再检查来源，才释放运行。
任何不明确结果均保留，不能重跑 submit；status 不会重新提交。失败 held 作业需要只读定位后另作处置。

`stage.py` 与 `ship.py` 提供独立、一次性的发布、freeze、plan 和控制层调用；不改32文件执行包。
2026-09-17 已完成真实发布、四份输入freeze、原生profile检查和scheduler test-only。
`ship.py submit` 已实际调用一次 sbatch，返回 **724258**；资源检查发现实际保存的是 H100/泛型请求，未放行。
不能重跑 submit。`repair_724258.py` 仅处理该从未运行的暂扣作业，inspect/update/release彼此独立，
update和release各有独占意图记录；没有sbatch、取消、重排或自动重试入口。
修正为原来批准的A100之前及之后，均核对固定来源、原提交绑定、完整资源以及独立记账。

**724258已经完成同作业修正/放行并结束，FAILED/2:0。不要再次运行submit、update或release。**
R在正式模型加载前因CUDA冷启动顺序检查失败；C/D/E未运行。`collect_724258.py`只读收集了80份终态证据，
独立复核脚本为`docs/superpowers/evidence/2026-09-17-job724258-review.py`；复核通过不等于数值通过。

30 项本地提交测试使用模拟调度器；17项恢复测试回放实际下载的暂扣记录，但变更RPC仍是模拟的。
这些测试不代表GPU数值通过。最新实际状态、资源、回执及来源见
[执行台账](../../evidence/2026-09-17-g2-production-launch.md)。
更早的设计过程保留在[控制器记录](../../evidence/2026-09-17-g2-submit-control.md)。

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_submit_20260917/test_control.py
```
