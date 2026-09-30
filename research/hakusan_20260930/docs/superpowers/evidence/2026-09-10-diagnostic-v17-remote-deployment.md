# v17 独立部署与真实验收记录

依据持续完成模型对比的用户目标，以及最终739项回归、真实formal40 CPU
准备和同home NFS发布探针，受控部署独立v17。不改变科学设置、600000预算、
数值容差或原1GPU/1小时时限；旧v16及更早证据保留。

- create/upload：原v4四文件、v16 freeze/失败标记/日志共七SHA保持，相关
  队列为空，新root原不存在；创建700私有目录、上传四文件，UPLOAD_RC=0。
- publish：四文件stage/tools两次SHA保持、600/single-link校验通过，
  PUBLISH_RC=0。仅移除暂存硬链接及空目录，完整文件仍在tools，旧版未改。
- audit/freeze：AUDIT_PASS、INPUTS_FROZEN，32trial/24pinned/root/协议匹配，
  AUDIT_FREEZE_RC=0。实际新freeze SHA：
  `a62ad2eaa97d4007505b584106b17812981364768170d8bc486291921fd39111`。
  已固定此值到check-only与单次提交入口，不从待验证文件反推期望SHA。

候选27文件清单SHA：
`ad163369b0cdc10626b7bb78d6dc7d1912febf78b8b212949ec5e5cf0e8ee8e9`。
诊断源码SHA：
`f45387ce78fc1d3aa902e23243f94cc2b3cb303f7579f612d8c2a2135b073b86`。
远端root：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v17`。
check-only实际返回CHECK_PASS、CHECK_ONLY_RC=0；协议/root/五目录与freeze
绑定正确，诊断源码和manifest前后SHA保持。已审核通过，接着单次提交。
原始freeze已只读下载到[v17-deployment-artifacts/input_freeze.json](v17-deployment-artifacts/input_freeze.json)，
本地SHA与上述固定值一致。尚无本版GPU结果，不得标为科研完成。

## 单次提交

唯一Job **683837**，SUBMIT_RC=0，协议formal40_batch_invariance_diag_20260903_v17。
nonce `e91ee336c8e74955ba20b3f3d5a8ceee`；
intent SHA `45e27560fe9a16e8c6a96e0b47ccf504ffb97772dfc61cc62691f63273370d22`；
response SHA `9d4c5a5dedcdce58cf9fb73c50548f02d59bafd04f7ce8004292ad24b97cae93`；
runner SHA `fd469355ed73e73878fbca8edc0590776c00083c156312c5f39f2b1deb0d34e3`。
查询、结果验证和失败取证入口已固定真实Job683837和实际freeze，不重提。
此处提交成功不代表诊断矩阵通过，仍需终态及逐工件verify-results。

原始INTENT、SBATCH_RESPONSE、SUBMISSION_RECEIPT及freeze已从远端只读下载，
四SHA通过，见[原始记录包](v17-deployment-artifacts/README.md)。
八个操作入口已固定实际身份并生成[操作脚本SHA清单](2026-09-10-diagnostic-v17-ops.sha256)。
首次查询：19:45:22 JST于spcc-a100g09启动，RUNNING；没有重新提交。

约18分35秒的只读观察：出现CHILD_EXIT_REFERENCE_COLD.json及
reference_cold/REFERENCE_COMPLETE.json、TRIAL_OUTPUTS.csv、RNG/STATE前中后
与RUNTIME记录，已越过v16的冷参考发布失败点。总作业仍RUNNING，未整体
verify-results；部分记录的存在不等同有效完整矩阵，不提取科学比较数值。

## 实际终态：TIMEOUT，不是通过

19:45:22–20:45:22 JST，Slurm TIMEOUT、Elapsed01:00:00。
协调器捕获signal15并记录失败；verify-results=2、matrix=null、
numeric_results_interpretable=false、results_verified=false、post_errors=[]。
冷参考已完成，其余矩阵未完成。本轮没有扩大1小时限制、覆盖冻结源码或重提。

19份原始文件已只读下载并逐SHA/大小核验，见
[Job683837原始归档](job-683837-v17/README.md)。
失败终态SHA aa7f03142c21a42b08014de170e0676cb39c8aa25cdbea27b16139c69707abb3；
原始日志SHA 47ce80f74713cc573ed5e32f5a2687f5e9fa19732b95d18aab4afcc3b6cc0eb0。
