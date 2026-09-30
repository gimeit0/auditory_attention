# GPU 单次提交控制器：本地测试及超算只读预检

2026-09-13：上传、调度器预检、单次提交、查询入口已经实现。
本地34项测试零跳过通过；实际HAKUSAN只读预检通过。
**本轮没有上传新包、创建远端目录、签发资源授权或提交作业。**
仍处于正式formal40/A100/Inductor冷对照的准备阶段，不是三模型比较完成。

## 入口和固定来源

- [控制器说明](../prototypes/targeted_gpu_control_20260913/README.md)
- [命令入口](../prototypes/targeted_gpu_control_20260913/control.py)
- [51份文件清单](../prototypes/targeted_gpu_control_20260913/CONTROL_RELEASE.json)
- 控制器清单SHA：`22d8b009c314bed3255e3332b29821655bac597b8032cad3640bddeb34022646`
- 原GPU候选清单SHA保持：`56e74387b957a3b51506890ea874f98fa1a3c92961f1e3cbf8a86f3c82dcef5c`
- 计划新目录：`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-13_v1`

旧候选45份固定文件及此前42项新增/38项回归测试的日志、子进程结果、
回执重新逐SHA核对一致。本轮没有改旧候选、模型、冻结文件或科学阈值。

## 本地实际测试

[本地回执](gpu-control-local-20260913T071647Z-wdldovrt/receipt.json)、
[完整测试日志](gpu-control-local-20260913T071647Z-wdldovrt/output.log)、
[独立重验](gpu-control-local-20260913T071647Z-wdldovrt/INDEPENDENT_RECHECK.json)。

Python3.11.15，PID13599，34项、零跳过、退出0，父进程记录1.331秒。
ruff通过；51份源码/输入校验和、日志、子进程PID/结果及回执独立重验通过。
测试使用假调度器/SSH和本机临时目录；小型真实本地子进程检查stdin和超时。
覆盖实际候选字节往返、上传损坏/中断、禁止覆盖、回执变更/过期、重复提交、
提交/放行回执不明、资源字段不符和只读状态查询。
没有生产模型加载或CUDA；不能将这些测试视为真实Slurm/GPU验证。

## 实际超算只读预检

[预检回执](gpu-control-20260913-v1/preflight-20260913T074621Z-cb54xaol/receipt.json)、
[远端原始输出](gpu-control-20260913-v1/preflight-20260913T074621Z-cb54xaol/output.log)。

沙箱内共享连接检查失败，未运行远端操作；获得沙箱外只读权限后，
复用已有认证master执行一次预检。没有自动重连或索取密码。
退出0、10.462秒，原始输出和请求/响应/清单绑定已独立核对：

- 原v4 manifest、lock、evaluator、runner和原v18 manifest、tool：6份SHA一致。
- 相关队列为空；GPU-1A为UP，节点为`spcc-a100g[01-10]`。
- 计划新目录不存在。
- 文件系统可用空间321264085368832字节；**不是账户配额或计算节点临时盘验收**。
- 预检回执SHA：`51ba48f9803985e3c8ac29d3f6c2805ebb0ce3de05a537d51e957c2c2f13f26d`。

## 提交保护与下一项

上传仅允许创建上面的新目录，逐字节校验暂存文件后发布；中断保留现场，
不覆盖或自动重试。查询操作不会提交或放行作业。
调度器预检使用[`sbatch --test-only`](https://slurm.schedmd.com/sbatch.html)，
不创建作业；保存独立回执，真实提交须绑定24小时内的一份成功回执。

真正提交还需新的明确授权：拟议为1个GPU-1A作业、1块A100、8CPU、64GiB、
总2小时，子进程50分钟、进程对总110分钟。原Job685198的授权已用完，不复用。
授权后先写本地和远端独占提交意图，只调用一次`sbatch --hold`；核对实际
Slurm保存的JobID、用户、目录、资源和时限后，才对该ID放行一次。
信息不明或字段不符则保留hold与回执，查询处理，不自动重提/取消。
这些控制器逻辑目前只有本地测试；真实held-job格式尚未验收。

**紧接着的操作：上传候选包并运行调度器test-only，再复核回执、确认新资源。**
上述动作本轮尚未执行。实际A100冷对照及全量工件回传/数值验收、三模型smoke、
10k及控制条件比较与统计报告仍未完成。当前评估仍是复用验证集审计，
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
