# Job685198已验证诊断：本地原始工件与离线分析

本目录保存5个从超算只读下载、字节未修改的原始文件：完成标记、完整作业
日志、矩阵总结、参考等价记录、后续定点追踪需求记录。各SHA见SHA256SUMS。

随后在2026-09-11的下一轮处理中，完整114项/211343132字节attempt工件
已只读下载至[slurm-685198](slurm-685198/)，按固定terminal逐项核对通过。
全量原件仍在超算原目录，未修改。归档不包含全部音频、权重与软件环境，
不是无需其他输入即可重跑GPU推理的完整复现包。

验证（本目录）：`shasum -a 256 -c SHA256SUMS`。

来源root：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v18`

- 完成标记来自state/DIAGNOSTIC_COMPLETE.json；日志来自logs/。
- 其余3份来自attempts/slurm-685198/。
- Freeze和原始提交凭据另见[v18-deployment-artifacts](../v18-deployment-artifacts/README.md)。
- [当前数值结果与解释边界](../2026-09-11-job685198-verified-diagnostic.md)。

结果只针对formal40的32条诊断，不是三模型10k比较，也不是独立测试。

新增OFFLINE_ANALYSIS.json是明确标识的CPU描述性复算，不是远端原始工件。
离线工具与14项测试、3份SHA绑定snapshot源码见OFFLINE_SHA256SUMS；
全114项根据DIAGNOSTIC_COMPLETE.json内artifact_inventory核对，未改原清单。
详见[离线发现与追踪方案](../2026-09-11-job685198-offline-findings-and-trace-plan.md)。
