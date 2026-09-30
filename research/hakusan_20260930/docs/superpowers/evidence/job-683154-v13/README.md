# Job 683154 / diagnostic v13：五份核心原始证据归档

本地已有五份从远端下载的原始文件；2026-09-10 恢复连接后补齐 PRECHECK 与
POSTCHECK，`shasum -a 256 -c SHA256SUMS` 五项全部通过。
旧 `SHA256SUMS.partial` 保留作三份文件已归档时的历史清单，不删除旧证据。

PRECHECK.json 和 POSTCHECK.json 的只读下载源为：

```text
/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v13/attempts/slurm-683154/PRECHECK.json
/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v13/attempts/slurm-683154/POSTCHECK.json
```

终态清单记录二者均为 69779 bytes、SHA
`a4e08ed5e3cce64c668484063ec735fa50579e2d4556bcb8118407b224c42611`。
两份本地副本均已核验到此 SHA。本次只下载和验证，不重提作业。
该五份归档是核心失败证据，并非所有远端工件的完整镜像。

本作业 FAILED 2:0，没有可解释数值矩阵。详见
[失败与待验证线索](../2026-09-10-job683154-compiler-path-import-diagnosis.md)。
