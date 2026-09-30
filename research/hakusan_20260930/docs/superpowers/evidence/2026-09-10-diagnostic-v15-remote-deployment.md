# v15 受控部署与作业记录

本地665回归、实际torch2.1.1/formal40完整CPU状态/RNG/执行图复验及独立跨模块
CPU Dynamo合成复验均已通过。科学配置、权重、bank及阈值不变，旧v14与
原v4/Job683154全部证据保留。不是最终三模型对比完成。

新远端root：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v15`。
新协议：`formal40_batch_invariance_diag_20260903_v15`。
候选SHA和源码修复范围见[v15工程记录](2026-09-10-diagnostic-v15-anchor-repair.md)。

1. create/upload：原v4四SHA、v13 freeze/failure/log三SHA保持；相关队列空。
   新root原先不存在，新目录700。四文件传入独立staging。UPLOAD_RC=0。
2. publish：四文件预检和发布后SHA相同，tools下600、单硬链接。仅删除staging
   链接及空目录，同一文件数据保留tools。PUBLISH_RC=0。
3. audit/freeze：AUDIT_PASS与INPUTS_FROZEN，各32trials/24pinned，协议/root
   由单JSON验证。新freeze：
   `f3cf353561f18cc34b92a00c89bd72c1311ebe5c78c52fa0e8f97f433a8ae4aa`。
   AUDIT_FREEZE_RC=0。该值据实际输出固定到后续检查，不运行时自我推导期望值。
4. check-only：CHECK_PASS，协议/root/目录/新freeze绑定通过，工具与freeze前后
   SHA一致；CHECK_ONLY_RC=0。
5. submit-once：唯一Job **683523**，SUBMIT_RC=0。不能再次运行提交脚本。

实际提交回执：

```json
{"job_id":"683523","next":"wait_then_status_and_verify_results","receipt":{"diagnostic_protocol":"formal40_batch_invariance_diag_20260903_v15","input_freeze_sha256":"f3cf353561f18cc34b92a00c89bd72c1311ebe5c78c52fa0e8f97f433a8ae4aa","intent_nonce":"ef83a76845db4de8aefd7faffca81ef9","intent_record_sha256":"9c4f85f7f7cd8f71bea94e00222b4b29da0b662f038138681ef7665928cf3494","job_id":"683523","response_record_sha256":"a84bccfe16a44547a042b9c4cc8315bb743cbdecaa425b65c83422fb3ab1e556","runner_sha256":"d54e69d262099147ca222ef556a484eb414e5224901fadc8d5ba13b71ad1a0f9","schema_version":1,"status":"SUBMITTED"},"status":"SUBMITTED"}
```

## 实际终态与验收

Job683523在spcc-a100g09运行2026-09-10 17:05:23–17:09:09 JST，3分46秒，
Slurm FAILED2:0。verify-results返回DIAGNOSTIC_FAILURE_RECORDED、VERIFY_RC=2，
numeric_results_interpretable=false，results_verified=false，matrix=null，
post_errors=[]。本次不是成功诊断，没有完整数值工件。

五份原始文件已只读复制到[job-683523-v15](job-683523-v15/README.md)，固定
[SHA256SUMS](job-683523-v15/SHA256SUMS)逐项复验通过。失败marker SHA为
`ba4e3e471de8575c03d381a268cbde78d15f8ea3ebdb5c238f1bd670d5a8afc4`；
原始log SHA为`c4c3caf05e6009083de388faaf9e6710c66631ce14e8aef0870b761de39c928e`。
PRECHECK与POSTCHECK相同：
`2d1c301299fa553d9647305537051b101605396b23d83431bbd41c8ae42df9c0`。

异常链位于参考predict操作正常返回后的live attestation；组合条件包含
scene图、model图、完整执行指纹、导入来源记录，原日志没有具体分支差异。
不能将此失败等同NLL数值失败，亦不能宣称该数值问题解决。后续只读CPU
对照见[编译生命周期诊断](2026-09-10-job683523-runtime-lifecycle-diagnosis.md)。
新工具SHA、冻结输入和旧证据仍保留，不重提本作业。

入口均在本目录：`2026-09-10-diagnostic-v15-*.sh`。create/upload、publish、
audit/freeze、submit-once均只运行一次，不清记录后重跑。不确定状态先只读查询。
旧v14四个写入口继续硬阻断，未解除它们的门禁。
