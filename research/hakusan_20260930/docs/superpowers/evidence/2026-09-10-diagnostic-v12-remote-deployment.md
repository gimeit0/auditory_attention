# v12部署与A100数值诊断

2026-09-10。用户批准恢复原runner三个固定环境值/有限异常链日志。以612项
本地回归、六项退化测试及实际torch2.1.1/formal40完整CPU检查为部署前证据。
科学模型、精度设置、矩阵和阈值不变；原评估v4、诊断v1–v11和失败证据保留。

候选manifest SHA：afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b。

```text
b5cf658961739a9f9b1ae3532554ce35f28dd43d927af43534dea70928c213a4 diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b numeric_trace.py
27322b33cb694e4a6cf43d9b20576c8096bc7f2ec99d0860cf9bf2bbba080c42 submit_numeric_diag.py
9b188d8c8b1a7395c2155b9f79d93ba5ba7dff3cf5a7d89588747db640c520a4 run_numeric_diag.sbatch
```

独立remote root：same_bank_v4_job646900_2026-09-03_v12。只读确认尚不存在。
create/publish/audit入口已做bash-n及固定SHA复核。正式执行结果见后续追加；
脚本存在不证明已经上传/冻结/提交，更不证明最终三模型比较完成。

## 实际发布

旧v11/v4七个绑定SHA全通过，相关队列为空。create/upload=0；八次stage/tools
哈希验证通过，publish=0。四份同inode暂存链接和空暂存目录已移除，数据仍完整
保留在tools，文件600/目录700。旧版本及证据未删除、未覆盖。

现在执行audit/freezing，尚没有新freeze回执或Job ID；不得重跑create/publish。

## 实际freeze与提交前验证

audit返回AUDIT_PASS，freeze返回INPUTS_FROZEN，协议v12、32条trial、24个绑定
记录一致；AUDIT_FREEZE_RC=0。新freeze SHA为：
6cd0407c8f48709e37fa9f0b6cdddcc6cbc5425b740b405c806c8a010eee9031。
已据实际回执固定check-only/submit/status/verify脚本的预期SHA，不从现存文件
自动推断预期值；Job仍待真实提交回执，未填写或推测。

check-only实际返回CHECK_PASS，协议v12/五目录/root/新freeze均准确绑定，源码
和freeze前后SHA匹配，CHECK_ONLY_RC=0。现在按既定资源及单次submitter入口
提交一次；不直接sbatch、不重试。若提交响应不确定，必须先查持久状态。

## 单次提交Job683076

实际submitter只调用一次，SUBMIT_RC=0，收到以下回执。随后只读status/终态
verify，不再调用提交入口。该回执不是数值验收或最终比较结果。

```json
{"job_id":"683076","next":"wait_then_status_and_verify_results","receipt":{"diagnostic_protocol":"formal40_batch_invariance_diag_20260903_v12","input_freeze_sha256":"6cd0407c8f48709e37fa9f0b6cdddcc6cbc5425b740b405c806c8a010eee9031","intent_nonce":"3b198890c95b46c0a3de537a79251de2","intent_record_sha256":"5fc1e3f6ecd3a23fce6047544a0bf1c101f4dd3ae25d0a966e3c71172aed4adb","job_id":"683076","response_record_sha256":"76ace3559e86325a5574e341503e353f6da2a751c1ba0819453959b2d5cd1f33","runner_sha256":"9b188d8c8b1a7395c2155b9f79d93ba5ba7dff3cf5a7d89588747db640c520a4","schema_version":1,"status":"SUBMITTED"},"status":"SUBMITTED"}
```

## 实际终态与新增定位证据

Job683076在spcc-a100g05于13:56:12–13:59:30运行3分18秒，FAILED2:0。
实际启动记录包含CUBLAS_WORKSPACE_CONFIG=:4096:8、OMP_NUM_THREADS=8、
TOKENIZERS_PARALLELISM=false，启动记录SHA为
ee98f50f7c125fd36ed857ec29b8d507f965e92075b16e6fefaf212624b1d36b。

verify-results实际返回DIAGNOSTIC_FAILURE_RECORDED/exit2、matrix=null、
post_errors=[]、numeric_results_interpretable=false；工件仅ENVIRONMENT/
PRECHECK/POSTCHECK/RUNNING。PRE与POST均为
7552a71579d524f51fa13f9b501190bd90f321c73d55266d53d9929738d98f16。

failure SHA 31aa3df3ef605cef5c75a3afe260e54f14dfb34570ed107ebcfa38c0287de4f6；
log SHA 8ad5ea84a944317e3bbdeef3e1ca41f63f0d66526a472ddf8a6f8070dad71649；
inventory SHA a0c2f36696b07ebb38aa55b50a94d2448166e813667d6d8cf69ef2afafb49b90。

本次有限异常链首次提供具体路径：最外层reference prediction failed，下一层
verify_runtime_bindings第3054行（源码对应sealed frozen module bindings changed），
再下一层torch._dynamo.exc.BackendCompilerFailed，其末端帧为Inductor
TritonFuture.result→future.result。不是已证实的模型/NLL结论，也不能据此
断言编译器根因、哪一个模块变化，或确定两者因果先后以外的具体关联。

官方v2.1.1与远端实际exc.py均把底层异常放在inner_exception属性，当前日志
只遍历标准cause/context，所以没有记录该内部异常。尚不关闭compile、不取消
模块绑定检查、不重提v12。只读访问原compute scratch被SSH host-key校验拒绝，
没有关闭host-key校验或自动接受新密钥。

五份原始证据已下载至[job-683076-v12](job-683076-v12/)，固定SHA256SUMS全部
通过。详细后续诊断以另行记录为准；完整三模型比较尚未完成。
