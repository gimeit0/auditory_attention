# 共享认证恢复与 G2 单次提交控制候选

2026-09-17。当前尚未上传新包、冻结新输入或提交 GPU 作业；完整 checkpoint 对比未完成。

## 现场只读结果

远端时间 `2026-09-17 08:58:11 UTC`（17:58:11 JST），查询退出 0：

- 登录主机 `hakusan1`，账号 `s2510040`，uid 27831；共享 SSH 已恢复。
- `squeue -h -u s2510040` 输出为空。仅代表本次查询时该账号没有排队/运行作业。
- `GPU-1A`：`State=UP`、`AllowAccounts=ALL`、`AllowGroups=ALL`、`MaxTime=UNLIMITED`、`MaxMemPerCPU=9845`。
- 分区 GRES：`gpu:nvidia_a100:2(S:0-1)`；分区 TRES 含 `gres/gpu:nvidia_a100=20`。
- `/home/s2510040/audattn_external_eval_diag` 为本人所有、mode 700。
- 新 `formal40_numeric_profiles_20260916_v1` 路径不存在，亦非悬空符号链接。
- 原 v4 `input_freeze.json` SHA 仍为 `1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5`。
- 原 v4 `state/evaluation.lock` SHA 仍为 `63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710`。

本次资源查询不等于调度器已接受具体请求，也不等于分区当前有空闲 GPU。
第一次扩展查询被本机沙箱拒绝，随后经批准运行同一只读命令并成功；这不是再次认证失效。

## 新本地代码及验证范围

新增 `docs/superpowers/prototypes/g2_submit_20260917/control.py`，放在执行包之外，不修改既有 32 文件包或旧证据。

- 接收外部固定 plan SHA、controller SHA；plan 不预先包含 job ID。
- 四个 profile 各用冷解释器调用原 `check_only`，再核对新 freeze 与历史科学输入的关系。
- `test-only` 和 `submit` 分离；确认 token 不是自动生成的用户授权。
- 明确申请 GPU-1A / typed A100 1 张 / 8 CPU / 65536 MiB / 3 小时；不接受环境变量中的额外 SBATCH 参数。
- `INTENT.json` 独占创建并 fsync 后才调用一次 `sbatch --hold`。
- 返回唯一 job ID 后生成 `RUN_REQUEST = plan + job_id`，保存回执。
- 核对真实 held 作业的身份、typed A100、资源、命令、路径、nonce 与未分配状态；再次检查来源和请求后才 release。
- 提交超时/回执不明、held 查询失败、资源不符、来源漂移或 release 不明：保留证据，拒绝自动重试或再次提交；不自动删除/取消已有作业。
- `status` 仅查询，不从不明确的回执猜 job ID，也不恢复提交。
- 每条调度命令默认 30 秒及 1 MiB 合并输出上限；四项输入检查各最多 120 秒。这些准备检查不是 GPU 推理。

本地 `test_control.py` **30 项通过、0 failure/error/skip，0.203 秒**。
调度器和生产输入检查回执为显式模拟数据；独占日志写入、小进程 stdout/stderr、超时和输出限制使用真实本地操作系统。
测试覆盖不确定提交只能调用一次、错误 GPU 不释放、请求漂移拒绝、失败证据保留、只读状态不写文件，以及本地解释器拒绝生产入口。
尚未验证真实 HAKUSAN 控制器、原生四 profile 检查或真实 sbatch/release 路径，不能称为生产提交验收。

源码 SHA：

- `control.py`：`581fcaafc6e4d9ef59a1d534acce7d04532ba0a3e0a6bd35769d234910e60956`
- `test_control.py`：`5e34c17e540529be7d53d67d5919db6f382194c35d087056d265b5629a2c3216`

测试命令（仅本地，不提交）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_submit_20260917/test_control.py
```

原 32 文件候选的固定验证器再次返回 `LOCAL_G2_ENTRY_CANDIDATE_RECHECK=PASS`，release SHA 仍为
`6becba7b27f8ba37657e66f0173bf991aec0136e8285afbd211eeeb65318d300`。没有重建或替换该候选。

## 下一项实际工作和权限

认证不再是当前阻塞；具体 GPU 单次预算确认仍待用户答复。
下一项为新目录发布（含独立 controller）、四份真实新 freeze、固定无 job ID 的执行 plan、原生输入与调度 test-only。
以上通过且单次预算明确批准后，才执行一次 held 提交/核对/释放；此前不直接调用现有 sbatch 文件。
提交器本身不会创建目录、上传、冻结输入或构造 plan，也不处理自动重连。
真实 G2 数值矩阵、冷重复、三模型 smoke、完整 10k/controls 和最终报告仍未完成。
