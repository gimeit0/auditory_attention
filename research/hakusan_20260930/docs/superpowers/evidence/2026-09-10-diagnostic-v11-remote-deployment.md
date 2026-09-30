# v11 R2部署与实际GPU诊断

2026-09-10。原v10 Job681974及原评估v4全部保留。当前没有可解释的数值
矩阵或完整三模型10k比较。此处仅记录独立32条formal40诊断。

部署前594本地回归、AST/退化复核、实际torch2.1.1/formal40 CPU完整状态/
执行图/RNG/输入前后复核通过，详见v11-registry-repair.md。没有放宽科学
阈值、更改原生模型/音频模式、bank或AMP/compile/TF32设置。

候选清单v11-r2-candidate-manifest.sha256：
1b6e6f83115f995548bf9a859c02db86ed199f3bdcc5d05dfea386e351b990a9。

```text
39ee10def3d2b90b981ee56812492b1de7266943add6a370e3ef14943f490b83 diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b numeric_trace.py
7b21cf94186bc1ffbd342c4107bf232f455d125b5235005d121bd9cdb09ddbf2 submit_numeric_diag.py
7cd333b4c3509612faafffbdf94790d37722316e727991d9c456cde9e106df74 run_numeric_diag.sbatch
```

准备Mac create-upload/publish/audit-freeze入口（由已核验v10入口只替换固定
版本/SHA，create另外绑定原v10三个失败证据SHA）；bash语法检查通过。
正式根same_bank_v4_job646900_2026-09-03_v11，已存在时停止，不重用旧根。
实际步骤结果待后续追加，不以脚本存在表示部署成功。

## 实际发布与冻结

旧v10/v4七个固定证据SHA全部OK，队列为空。create-upload=0；随后八次
stage/tools校验OK，publish=0。只删除四个已验同inode暂存链接和空staging目录；
正式tools文件保留600，五目录700，旧证据没有删除或覆盖。

audit= AUDIT_PASS、freeze=INPUTS_FROZEN，协议v11、32trials/24pinned均匹配；
AUDIT_FREEZE_RC=0。新诊断freeze SHA：
8e304d05f099a6d8ab7ab9c05a98de7ce35eab1886d0b040d6af2c6e19e559e6。
固定此新值生成check-only和submit-once入口，bash -n通过。先实际check-only，
未通过不得提交；不得重新freeze。当前还没有新Job ID。

## 单次提交 Job682295

check-only实际CHECK_PASS、协议/五目录/root/freeze绑定一致，工具和manifest
前后SHA不变，CHECK_ONLY_RC=0。之后仅调用一次固定submitter，SUBMIT_RC=0。

```json
{"job_id":"682295","next":"wait_then_status_and_verify_results","receipt":{"diagnostic_protocol":"formal40_batch_invariance_diag_20260903_v11","input_freeze_sha256":"8e304d05f099a6d8ab7ab9c05a98de7ce35eab1886d0b040d6af2c6e19e559e6","intent_nonce":"22c8bb35759c46a6a86b6c7641e86530","intent_record_sha256":"a2f09dee2cd1ff753570327241c7d604913cf62e87fd0f0122c108b3feee3804","job_id":"682295","response_record_sha256":"0ddc5f6375d7898bd2c067ff4a9d5cb6dc96ae43e28c099f2bc915f21f7480e1","runner_sha256":"7cd333b4c3509612faafffbdf94790d37722316e727991d9c456cde9e106df74","schema_version":1,"status":"SUBMITTED"},"status":"SUBMITTED"}
```

不可重跑submit-once；接下来只读status及终态verify-results。此记录不是
DIAGNOSTIC_RESULTS_VERIFIED，也不是三模型比较结果。

## 实际终态与复核

Job682295在spcc-a100g02从08:59:39运行至09:03:14（2026-09-10本地时间），
FAILED2:0/3分35秒。verify-results认证失败记录（不是数值结果认证），
VERIFY_RC=2，post_errors=[]、matrix=null、numeric_results_interpretable=false。
PRE/POST SHA相同981170e65b0d0e04c9a97d66eafe2682bf139ff2c5f4cfcc24dfbbae811e17a3。
failure marker fadf15e57a5e482f4648f692119617387a5bf03ea21ee46126227323efe3e154，
log 5dd91c497198876cbb6de84136939946412fee2b786a33f8c6cfbae829a8c287。
stderr为frozen reference prediction failed，只有4个基础工件，无完成矩阵。
未重提，最新related queue为空。源码核对发现原v4三个固定运行环境键未传入
v11子进程，底层exception cause未持久化；详细事实/推断及待审批方案见
[Job682295分析](2026-09-10-job682295-reference-failure.md)。
