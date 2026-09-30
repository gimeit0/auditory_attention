# 真实 formal40 回调登记：一次 CPU 作业

2026-09-13，用户明确同意开始：独立提交一次 1 CPU、4 GiB、最多30分钟、无GPU的计算节点检查。
检查真实formal40严格加载、42位置/27模块/29回调登记、原冷编译器权限签发与撤销、
状态/RNG/运行设置不变和清理。**不做forward，不签发原生产worker，不产生模型比较结果。**
失败不自动重试，不更改冻结模型、v4/v18源码、旧作业或数值阈值。

## 提交前验证

- 原候选17份文件保持不变，候选manifest SHA：
  `4c72fc9779fe48373908eca2638b69bcf5ed173a9cd9db52062b119128a876d5`。
- [本地候选复验](real-registration-local-20260913T053114Z-w3j_rcqr/receipt.json)：
  24 tests、0 skips、rc0；Python3.11.15/torch2.12.1；仅合成结构，不证明远端真实加载通过。
- 新作业工具29项stdlib测试通过；资源、重复意图、调度器单节点范围1-1、结果身份、
  严格加载、清理和禁止推理/GPU声明均有拒绝用例。Ruff与bash -n通过。
- 旧Job703415独立原始证据复核仍PASS，原25文件不变。
- [新运行包](../prototypes/targeted_real_registration_cpu_job_20260913/RELEASE.json)：26文件，SHA
  `38b9130fdbd5c135c179cd91edf2635876e0de8b33208692306a50a641bb0a17`。

远端独立根：`/home/s2510040/audattn_external_eval_diag/real_registration_cpu_2026-09-13_v1`。
包按SHA逐文件验证后发布；sbatch --test-only不提交；本地与远端分别以独占意图防重复提交。
真实子进程限1710秒，Slurm总时限1800秒，超时清理自己的进程组并保留完整日志。
临时目录仅计算节点/tmp内，权限0700，不重定义HOME。

## 实际部署与单次提交

- [部署回执](real-registration-cpu-job-20260913-v1/deploy-20260913T053236Z-liam7uep/receipt.json)：26份文件远端SHA通过，未提交。
- [调度器预检查](real-registration-cpu-job-20260913-v1/test-only-20260913T053301Z-d06gmlv5/receipt.json)：通过。
  输出703750为test-only预测编号，不是正式提交回执。
- [唯一正式提交](real-registration-cpu-job-20260913-v1/submit-20260913T053318Z-4rzqb9ed/receipt.json)：
  Job **703751**；1 CPU、4GiB、00:30:00、TINY、ReqTRES无GPU、Requeue=0。
  nonce=`61b4cc32809f411ea095d4d7452f2e00`，jobs_submitted=1。
- [首次运行查询](real-registration-cpu-job-20260913-v1/status-20260913T053436Z-u9mfj151/receipt.json)：
  RUNNING，节点lcpcc-054，协调进程294740，真实登记子进程294747，累计58秒。
  此时尚无结果，不视为成功。

不要再次执行submit动作；后续仅查询、回传和离线复核。

## 最终结果：真实 CPU 登记检查通过

[终态查询](real-registration-cpu-job-20260913-v1/status-20260913T053700Z-tk0tukne/receipt.json)：
Job703751 **COMPLETED，0:0，00:02:32，lcpcc-054**。仅1CPU/4GiB，无GPU。
子进程PID294747，实际113.377秒；协调检查113.61秒，均在批准时限内。

- 真实formal40严格加载一次：61个checkpoint键；62,622,520个训练参数元素全部加载，
  missing/unexpected/shape/dtype差异均为空，prefix_rule=exact，加载比例1.0。
- 42个计划位置、27个实际模块、29个原CompiledLease回调，登记后已全部移除。
- 60条注册状态与原Job685198的A2预前向状态逐SHA一致；登记与清理前后状态/RNG/runtime不变。
- 原torch2.1.1冷编译器权限成功签发并撤销，compiler_backend_entered=false。
- 仅恢复原loader已签发的10个模块对象，没有重新执行源文件。
- forward_calls=0、captures=0、CUDA未初始化、生产worker未签发；临时目录已清理。

[10份原始工件回传](real-registration-cpu-job-20260913-v1/fetch-20260913T053810Z-dv7nljhm/receipt.json)，
[本地独立复核结果](real-registration-cpu-job-20260913-v1/JOB703751_LOCAL_RECHECK.json)：
**REAL_REGISTRATION_EVIDENCE_RECHECK_PASS**。
复核26份固定源码、回传工件/base64/大小/SHA、提交nonce/资源、真实进程号、原始日志和严格结果字段。

关键SHA：

- registration.log（2878字节）：`8fb4e726af4a129b656741e1b41dc77a459b6d3a41ec2b12dbbddc0374057eef`
- TERMINAL.json：`8c22741f559282703e59441368d94c7a3d83b3efb33ac1cce0ddd2efc2a3d6c3`
- fetch原始输出：`bdacb53d89e63161d3358c86534e3986335110a2a4c0d09ddc8a91e82cd7068c`
- status原始输出：`2fff442fdae05df1db0204f9a650809052fe2823fe80c5a96bb927aa876dcad7`

仅离线复核的命令（不连接/不重提交）：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-13-real-registration-cpu-recheck.py \
  docs/superpowers/evidence/real-registration-cpu-job-20260913-v1/fetch-20260913T053810Z-dv7nljhm \
  docs/superpowers/evidence/real-registration-cpu-job-20260913-v1/status-20260913T053700Z-tk0tukne
```

## 科研边界

本检查已通过，但只证明真实模型的冷登记/清理可执行；不证明42位置动态观测、
生产worker衔接、Inductor/A100一致性、父结果回放或三模型最终对比已完成。
最终评估仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
