# v18：获批的有界诊断资源调整

## 用户授权与范围

2026-09-11，助手明确询问是否同意1GPU、总时限最多4小时、单个子进程最多90分钟；
用户随后回复“好的 开始吧 我能把密码直接写入脚本吗”。本轮按该回复实施上述方案。
密码不写入脚本、不采集、不打印；只复用用户已认证的SSH共享连接。

只在独立v18目录调整版本身份和时限：Slurm 01:00:00 → 04:00:00，
子进程默认3000秒/允许上限3600秒 → 默认及允许上限5400秒。
1GPU、8CPU、不自动requeue、进程组清理、信号处理、失败即停止均保持。
总4小时上限仍可能先于某个子进程90分钟上限到达；不保证本次可以完成矩阵。

权重、bank、32trial矩阵及顺序、科学阈值、AMP/TF32/compile、600000工作量
上限和所有可变绑定检查不变。不给科学结果放宽通过条件，不缓存可变PASS。
v17及其冻结清单、Job683837全部证据保留，不重提、不复用其部分结果。

## 本轮只读起点

共享SSH已认证；远端用户s2510040、主机hakusan1；squeue当前无用户作业。
sacct复核683837=TIMEOUT、01:00:00；GPU-1A分区UP、MaxTime=UNLIMITED。
这些是当前可行性信息，不替代单次提交前的冻结/队列/身份核验。

## 起点验收状态（后续实际结果见下文）

- 尚未发布v18、冻结v18或提交新作业。
- 待完成：资源边界测试、全部旧回归、源码差异审阅、发布SHA固定。
- 待完成：独立部署、audit/freeze/check-only、最多一次提交及作业结果验证。
- 完整三模型对比尚未完成，不能用于宣称独立测试或论文结果。

## 本地验收通过

23个独立测试入口全部通过，共751项（739旧回归+12资源/源码差异测试）。
原始逐入口日志及各SHA见[v18-validation-20260910T214735389980Z/summary.json](v18-validation-20260910T214735389980Z/summary.json)。
Ruff全包通过、runner及三个部署脚本bash语法通过；候选28文件SHA复核通过。
精确差异测试证明：诊断只改2处版本字符串和2个时限数字；runner仅改版本与
SBATCH时限；submitter只改版本；numeric_trace字节相同。信号、清理、矩阵、
所有科学及可变检查函数体完全保持。旧v17候选27文件清单亦复核通过。

候选28文件清单SHA：bcd7d3e5bb776323d2b3975791962418893a3fa1746905dd3719563925f77e72。
生产四文件SHA：

- diagnose_batch_invariance.py：7ba4d1f143fd1b957639588b209600377d745bf34e1207768cdd577e3f1d5a7b
- numeric_trace.py：fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
- submit_numeric_diag.py：f29af5a28181934c0a77da7e6dd6f9cddbe8ea9e2184270fa2110e4691cd3c2f
- run_numeric_diag.sbatch：db4b7fabee2a7285d0a11fffd738584d7aa0f04ec08503b56a23b13b4cfdfb05

当前gpu-1a QoS查询MaxWall=7-00:00:00，MaxTRESPJ=cpu=26,mem=256G,node=1；
所申请4小时/8CPU/1节点未超过这些字段。仍以实际提交响应与调度验收为准。
旧v17真实CPU/NFS证据只作为未变函数体的既有工程证据，不宣称v18已重新做GPU验收。

## 部署进度

create/upload通过：原v4四SHA及v17冻结/失败标记/日志三SHA保持，队列为空，
新目录原不存在；只创建独立v18私有目录并上传四文件。
publish通过：暂存和tools四文件SHA均匹配，600权限和单链接最终检查保持。
只移除了已核验的暂存硬链接及空暂存目录，文件完整保留在tools；旧版未改。
原始操作输出及回执：

- [create/upload](v18-operation-create-upload-20260910T215020610531Z/receipt.json)
- [publish](v18-operation-publish-20260910T215117915668Z/receipt.json)

接着执行audit/freeze，此时尚未提交GPU作业。

实际远端Python3.11.5的SHA绑定stdlib资源探针通过：默认5400秒、上限5400秒，
3601秒按新获批范围接受，5400.000001/5401/14400/布尔/非有限/字符串等拒绝。
没有启动子进程、导入torch、读取模型或写远端文件。
见[实际探针回执](v18-operation-resource-probe-20260910T215328848489Z/receipt.json)。

audit及freeze均通过：实际返回AUDIT_PASS、INPUTS_FROZEN，32trial/24pinned，
协议和root均指向v18。[原始操作回执](v18-operation-audit-freeze-20260910T215153146785Z/receipt.json)。
新freeze SHA：bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178。
已核对并固定到check-only与submit-once入口；不从待验文件反推期望SHA。
接着只读check-only，通过后才允许单次提交。

check-only已实际通过（CHECK_PASS、CHECK_ONLY_RC=0）：协议/root/目录清单与
新freeze SHA绑定一致，源码和manifest前后SHA保持。
见[原始回执](v18-operation-check-only-20260910T215502622363Z/receipt.json)。
原始freeze已下载并逐SHA核对，存于[v18-deployment-artifacts/input_freeze.json](v18-deployment-artifacts/input_freeze.json)。
审核此门禁后，开始单次submitter调用；不会重试不确定的提交响应。

## 唯一提交：Job685198

SUBMIT_RC=0，返回SUBMITTED；调用只有一次。
见[原始提交操作输出及回执](v18-operation-submit-once-20260910T215611183581Z/receipt.json)。

- Job：685198
- 协议：formal40_batch_invariance_diag_20260903_v18
- Freeze：bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178
- Nonce：57382cfa59c44b339361aae52116413b
- INTENT SHA：4d3a48737c4a5b9eab9c7d5a80825f38818dac0acf3006b4e72a61b7bb054f6a
- RESPONSE SHA：4e4d535904b6544eb4737722d6c90a93905f34b77e3055e553d4167cc95b179d
- Runner SHA：db4b7fabee2a7285d0a11fffd738584d7aa0f04ec08503b56a23b13b4cfdfb05

status、verify-results和failure-evidence入口已固定本次真实Job与freeze。
提交成功不是诊断通过；当前仍须等待终态及完整工件verify-results验收。
不得重运行submit-once，不得在作业运行中改冻结代码/时限/输入或拼接旧结果。

## 实际运行状态（2026-09-11 06:58 JST）

status及sacct均为RUNNING；06:57:22 JST在spcc-a100g06启动。
scontrol确认TimeLimit=04:00:00、1节点/8CPU、AllocTRES含nvidia_a100=1、
Requeue=0、Restarts=0，运行时限到达时间为10:57:22 JST（并非成功完成预测）。
见[首次只读状态回执](v18-operation-status-20260910T215820762240Z/receipt.json)。
results_verified=false；完整矩阵和三模型对比均尚未完成。

原始freeze/INTENT/RESPONSE/RECEIPT已下载，四SHA逐项通过，见
[提交凭据归档](v18-deployment-artifacts/README.md)。没有保存SSH密码。

## 后续实际终态：诊断完整验收通过

09:24:04 JST完成，耗时02:26:42，COMPLETED0:0。
12:45 JST启动的独立只读verify-results返回DIAGNOSTIC_RESULTS_VERIFIED、
results_verified=true、VERIFY_RC=0，完整四cell矩阵通过工件验收。
A1/B1数值一致；A2/B2仍有批大小NLL差异，A2分类REPRODUCED。
详见[已验证结果与解释边界](2026-09-11-job685198-verified-diagnostic.md)。
这不是原三模型smoke通过，也不是最终模型对比完成；没有重新提交。
