# GPU候选已部署，调度器预检通过；等待新资源授权

2026-09-13，在用户要求“开始下一步”后，完成此前约定的上传和调度器预检。
**实际提交次数为0，没有授权文件、提交意图、GPU前向或模型比较新结果。**
现在可以确认这次formal40数值诊断的资源授权；不应重复部署或运行旧提交脚本。

## 已执行与证据

- [上传回执](gpu-control-20260913-v1/deploy-20260913T075006Z-_qjtjxef/receipt.json)：
  `GPU_PACKAGE_DEPLOYED`，51份文件共1,882,473字节，退出0，9.726秒。
- [调度器预检回执](gpu-control-20260913-v1/test-only-20260913T075029Z-_tj_2qra/receipt.json)：
  `SCHEDULER_TEST_ONLY_PASS`，退出0，10.553秒。
- [发布后状态查询](gpu-control-20260913-v1/status-20260913T075145Z-yypsvfgq/receipt.json)：
  仅有发布日志；AUTHORIZATION、SUBMIT_INTENT和提交回执均不存在。
- [结束后的只读检查](gpu-control-20260913-v1/preflight-20260913T075146Z-uqm0586n/receipt.json)：
  6份原v4/v18固定文件SHA仍一致，相关队列为空，GPU-1A为UP，新目录存在。
- [独立重读校验记录](gpu-control-20260913-v1/DEPLOYMENT_REVIEW.json)：
  本地51份来源、全部4组请求/响应/回执和日志逐SHA复验一致，上传payload
  的每份文件与本地清单字节一致；没有授权参数或本地提交意图。

使用原已核验控制器和原已认证共享SSH连接，各操作只调用一次，无自动重连或重试。
部署在暂存区写入并逐份校验，再发布到新package目录；test-only另一次读取
核对全部51份已发布文件和原始保护文件。旧目录、模型、冻结文件和源码未改写。
本轮没有修改已固定候选的代码、清单、资源、运行设置或科学阈值。

固定新根目录：
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-13_v1`

控制器清单SHA：`22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646`

GPU运行包清单SHA：`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`

## 调度器输出的含义

此次唯一调度调用为固定脚本的`sbatch --test-only`，返回估计：

```text
sbatch: Job 704798 to start at 2026-09-18T23:38:40 a using 8 processors on nodes spcc-a100g06 in partition GPU-1A
```

这是预检估计，不是实际提交、排队回执、节点预留或保证的启动时间。
Slurm官方说明[`--test-only`只验证请求并估计启动时间，不提交作业](https://slurm.schedmd.com/sbatch.html#OPT_test-only)。
本次操作后的空相关队列以及缺失授权/提交记录也已核对。
不要把704798记为本实验的新作业ID；正式提交后必须以新的真实回执为准。

此次test ID：`a672261500eb428eb7add027ce274a27`

远端预检记录SHA：`c07fd769e2b1b2f466f32180cf1e16b144fc3bb343b092cbff9e187711112b73`

本地预检回执SHA：`edf2927a08d32a95b45ee4c781d50cbd62a9a8fb51b01f9c17f03509c6836cd7`

控制器正式提交须绑定上述成功回执，且远端记录不超过24小时。
超过期限应重新做test-only并复核新回执，不修改旧记录。

## 现在需要确认的下一项

拟议授权：**单次提交1个GPU-1A作业，1块A100、8CPU、64GiB、最长2小时**。
子进程最多50分钟，参考/观测两新进程总预算110分钟，失败不自动重提。
用途为B2 formal40数值诊断的真实GPU冷参考/观测对照，不是最终三模型比较。
原Job685198的旧授权不可复用；本轮用户仅同意上传及预检，尚未同意这次新资源。

获得明确授权后才能通过[固定控制器](../prototypes/targeted_gpu_control_20260913/control.py)
提交一次held作业，核对实际Slurm资源字段后放行该JobID一次。
提交/放行信息不明时保留日志和同一作业，查询处理，不自动重试/取消。
实际held字段、spool/计算节点环境、真实CUDA/Inductor与归档完整性仍需运行时验收。
此次预检不等于账户配额或计算节点scratch容量检查，也不保证脚本科学执行成功。

正式运行之后仍需回传全部工件、校验并解释数值结果；继而三模型smoke、
10k及控制条件比较与统计报告。当前角色仍为
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
