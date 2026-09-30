# v2上传隔离检查修正

日期：2026-09-28。用户在获知旧上传器按`audattn`名称过宽拦截后回复“好的”。本轮范围仍是独立目录上传、文件哈希与包检查，不授权GPU提交、取消/修改754073或自动重试。

## 已核查事实

只读`scontrol show job -o 754073`返回：

- `JobName=audattn_numcheck_seed20260928`，`JobState=RUNNING`，`RunTime=04:45:18`，`NodeList=spcc-a100g09`。
- `WorkDir=/home/s2510040/selective_listening_repro/code/auditory_attention_seed20260928`。
- `Command`为该目录下`selftrain/hakusan/run_numerics_preflight.sbatch`。
- `StdOut/StdErr`为该目录下`selftrain/hakusan/logs/audattn_numcheck_seed20260928_754073.log`。
- [既有提交记录](../../docs/superpowers/evidence/retrain-formal40-newseed-20260928/submit_preflight_console.log)记录源脚本和已提交spool的相同SHA：`a6a4a6413fb98759f214ed7c16f9d431cfb37bb55818527d79bca24fea040011`。新上传器会在上传前再次核验实时元数据和源脚本哈希，不能只凭旧记录放行。

该作业是换种子训练的数值预检，不是本次低α扫描。上传只创建不存在的`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v2`；不写入754073的工作目录、脚本、日志或训练文件。这里确认的是上传目标隔离，不是完整运行时写入审计，也不是账户最大并发作业数的核验。

## 修正边界

- 共享接收器默认V1行为保持原样。仅V2入口显式提供已审阅作业754073的身份；不提供泛用跳过检查的开关。
- 队列查询失败、未知作业、元数据缺失/重复、编号/名称/账户/目录/日志/入口不符、路径重叠、脚本哈希变化或符号链接都停止。
- 队列为空可继续。已审阅作业仍存在时，需要实时回读并通过上述核验，而不是按名称或“还有名额”放行。
- 新目录独占创建、拒绝覆盖、V1 RELEASE前后检查、41文件哈希和远端隔离包检查仍保留。没有修改冻结包或GPU提交器。
- 前次`upload-v2-once`全部证据保留；新调用只使用`upload-v2-reviewed-job-once`，目录已存在即停止。先检查前次确实仅到队列拒绝阶段，再发起本次人工确认后的新尝试；不自动重试。

## 本地验证

`test_fine_alpha_upload*.py`共20项通过，包含新增8项队列/身份/路径/脚本哈希负例。首次回归发现账户字段的前缀匹配未拒绝多余后缀，已改为完整格式匹配；重新执行20项全部通过。不是全目录回归。

冻结v2隔离`check`仍返回`FINE_ALPHA_PACKAGE_CHECK_PASS`，release SHA仍为`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`。实际上传结果另见本轮回执，不由本文预判成功。
