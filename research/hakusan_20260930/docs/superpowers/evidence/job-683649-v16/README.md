# Job683649：v16 失败原始证据

2026-09-10 18:01:26–18:48:52 JST，spcc-a100g09，FAILED2:0，47分26秒。
`verify-results`返回2，`DIAGNOSTIC_FAILURE_RECORDED`、`numeric_results_interpretable=false`，
matrix=null、post_errors=[]。原始六文件均只读下载并通过`SHA256SUMS`。
PRECHECK与POSTCHECK SHA相同。没有重提作业，也没有将部分输出拼接为结果。

实际失败链为`_execute_worker_passes`→`write_reference_artifacts`→
`_write_child_artifacts`→`publish_bytes`→`_publish`→`_record_at`：
`artifact must be a mode-0600 single-link regular file`。
仅有`reference_cold/REFERENCE_INPUTS.json`，缺少参考完成标记、A2和完整矩阵。
该输入工件含两pass记录，但不能作为已验收数值/最终科研结果。

独立小文件探针（非模型、非GPU、无新作业）复现：
v16原写入函数在`/tmp`通过，在home文件系统拒绝同一错误。
保持private文件描述符打开后unlink，home上出现`.nfs`名称及nlink=2；
在unlink前关闭private描述符的控制组为nlink=1。不能简单把允许链接数改成2。
原始探针脚本SHA `e368c39121516bb90c296cc986c564441dc04670147a1a23746cd4c73334ff61`；
完整测试观察见外部修复记录。
