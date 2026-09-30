# Job713897结果核验：参考子进程超时，未取得合格诊断结果

2026-09-14用户请求核验作业结果。本轮仅查询和下载失败证据；没有修改远端文件、
代码、权重、bank、阈值、时限或作业，没有重新提交。

## 确认的结果

- Slurm：`713897|FAILED|2:0|00:50:05|spcc-a100g04`。
- 开始2026-09-14 14:00:53 JST，结束14:50:58 JST。
- 请求与实际分配均为1张`nvidia_a100`、8CPU、64G、1节点；子进程记录的设备
  为NVIDIA A100-PCIE-40GB，Python3.11.5、torch2.1.1+cu118、CUDA11.8。
- 参考子进程PID2537707运行3000.031秒，监督器记录
  `TimeoutError: child deadline reached`，随后停止该进程组，returncode为-9。
- 这是内部参考子进程的3000秒（50分钟）预算到期，不是Slurm的2小时总时限到期。
  当前证据也不是OOM报告，不能只凭-9推断显存不足。
- `processes/TERMINAL.json`为PAIR_FAILED，协调器为GPU_PAIR_NOT_VERIFIED。
  顶层error为null不代表成功；实际错误在pair/children中。
- 只有reference子进程，observed未启动，故本轮不能验收追踪工具是否干扰输出。

## 已核验的证据与限制

[最新状态回执](gpu-control-20260914-v3/status-20260914T074026Z-q0xyosqu/receipt.json)
与[完整终态/日志收集回执](gpu-control-20260914-v3/terminal-evidence-20260914T074214Z-eg9mkxdw/receipt.json)
一致。[独立离线复核](2026-09-14-job713897-terminal-review.json)验证了请求/日志SHA、
结构化响应绑定、10个下载文件的长度/SHA、协调器与子进程记录一致性、PID/JobID/nonce/包SHA，
以及Slurm实际分配与工作进程环境。失败证据通过核验，不等于数值结果通过。

[本地下载目录](gpu-control-20260914-v3/terminal-evidence-20260914T074214Z-eg9mkxdw/download/)
保留完整361字节reference日志、7398字节协调器日志、环境、PRECHECK和终态。
收集器在只读下载前后逐SHA检查55份发布文件及原6个保护文件。

远端清单显示20个partial arrays，共522702496字节，说明不是此前705468
在scratch创建入口即退出的同一种表现。但本轮仅取得这些大数组的名称/大小等元数据，
未下载或核验其内容，不能把它们作为已通过的第一轮结果或最终指标。
缺少reference的CHILD.json、POSTCHECK.json和arrays/manifest.json；观测工件不存在。
原终态报告临时package/cache已清理，远端已落盘的失败工件保留。

reference日志仅包含音频变换提示和resampling弃用警告，没有耗时分段/栈信息。
协调器每约30秒的心跳说明监督器仍在等待，**不能证明GPU持续计算或每批仍有进展**。
目前无法区分耗时在编译、推理、校验、归档I/O或其他环节；不能认定具体算子根因。

## 后续

2026-09-14只读续查已完成：[文件时间线、已复现的启动环境遗漏和最小方案](2026-09-14-job713897-timing-localization-plan.md)。
第一轮20个数组在14:05:53前产生，之后约45分钟至超时；函数级根因仍未确定。
固定环境构造遗漏OMP_NUM_THREADS、CUBLAS_WORKSPACE_CONFIG、TOKENIZERS_PARALLELISM已由6例本地复现，
但不能据此断定超时因果。旧来源和远端工件未修改，新GPU提交0。

先依据固定源码和现有工件设计有界耗时定位，补足阶段耗时/停滞位置证据，
再决定修正方案；不直接扩大时限，不跳过数值检查，也不自动重提。
若需要新的GPU作业，必须另行确认明确资源范围，本次授权已消耗。

尚未完成完整32条16→1冷参考/观测验收；没有新的batch差异或hook等价性结论。
formal40与作者checkpoint（valbest33补充）的最终同bank比较仍未完成，
研究角色维持REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。
