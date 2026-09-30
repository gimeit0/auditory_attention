# Job683837：原始超时失败证据

v17唯一作业于2026-09-10 19:45:22–20:45:22 JST在spcc-a100g09运行。
Slurm记录TIMEOUT、Elapsed01:00:00；协调器记录收到signal15。
verify-results返回DIAGNOSTIC_FAILURE_RECORDED、VERIFY_RC=2，
numeric_results_interpretable=false、results_verified=false、matrix=null，
post_errors=[]。不能把Slurm的ExitCode0:0解释成成功。

本目录19份原始文件从远端只读下载，没有改写原始JSON/日志/CSV。
终态、日志、freeze与runner先按已核验SHA确认；15份attempt工件逐一匹配
终态inventory中的相对路径、大小、SHA与0600权限；本地文件集合完全对应。
可在本目录运行 `shasum -a 256 -c SHA256SUMS` 重验。

reference_cold完成并且子进程退出0，已越过v16的NFS发布错误。但完整A2/A1/B1/B2
矩阵没有完成，禁止复用这些部分结果作为下一次成功结果或三模型科研比较。
PRECHECK与POSTCHECK字节SHA相同，只证明这些输入检查未发现变化，不代表
完整推理/数值验收通过。

原始提交intent/response/receipt另外保存在
[部署记录包](../v17-deployment-artifacts/README.md)。
失败终态SHA：aa7f03142c21a42b08014de170e0676cb39c8aa25cdbea27b16139c69707abb3。
原始日志SHA：47ce80f74713cc573ed5e32f5a2687f5e9fa19732b95d18aab4afcc3b6cc0eb0。
