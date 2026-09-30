# 独立诊断 v10 远端部署

前置证据：v10 R3 本地561项通过，实际torch2.1.1/formal40 CPU完整模型
指纹337577次、重复一致及24/96来源后验通过。不是生产GPU/三模型结果。
持续三模型比较目标下，由主代理顺序执行正常部署门槛；不重提旧Job680910。

固定候选清单：v10-r3-candidate-manifest.sha256
SHA ca282426ebead30831fb87b22ce6de0f1fb93cf09c397a8cc1c75c41745bdee1
远端唯一新增根：/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v10
原v4科学根及v8已发布证据保留。v9/R1/R2不部署。

生产四文件：

- diagnose_batch_invariance.py: 2c3e07d218076abb27ba613556cfda4792ed7490821cbdbc43ad610788b637eb
- numeric_trace.py: fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b
- submit_numeric_diag.py: e123b172cf150fc4a015992fa3511e2a9a9c9109987575c405dcf0bee0aa322b
- run_numeric_diag.sbatch: 63dc1293528612afbf69c79273aa3b2f37ca41ed524cfa5f054f9f4f48d77cfa

复用既有v8部署脚本，逐项审阅差异：新路径/协议/精确SHA、旧证据改为v8、
增加清单自身SHA和用户认证共享ControlPath/BatchMode。原目录排他/属主/
权限/无符号链接/文件集合/队列空/硬链接发布后校验/不覆盖策略保留。
三个脚本bash -n通过。当前无新freeze或Job ID，执行结果随后追加。

脚本SHA：

- create-upload: f70e64ecd09a915af05afeca3b8d0d221b550e0f4a7652e0b41ba5e0b0531ffc
- publish: 6880b2ec2b2fbc1c3648f31d60181d22e77afc0e7680932acfe62bad89530e03
- audit-freeze: 47f0e725c7cfc84d53e47a73a2ecffb94da8f27ec9d6c7da9caefb8b653f7e49

## 实际创建/上传

原v4四SHA、旧v8三SHA全部匹配，相关队列为空。
REMOTE_DIAG_V10_ROOT_CREATED=PASS，六子目录均700；四文件只上传到新staging。
DIAG_V10_UPLOAD_TO_STAGING=PASS，UPLOAD_RC=0。开始逐文件远端校验/发布，
尚未freeze或提交作业。不应重跑create-upload。

## 实际发布

远端staging四SHA及发布后tools四SHA均与候选匹配，两个相关队列为空。
REMOTE_DIAG_V10_TOOLS_PUBLISHED=PASS、PUBLISH_RC=0；五目录700、四文件600、
每文件单硬链接。只移除经验证的staging链接和空staging目录，完整数据仍保留
在tools下。旧版本/原科学根未删除。接下来执行一次audit/freeeze；尚无Job。

## 实际审计/冻结

AUDIT_PASS及INPUTS_FROZEN，协议formal40_batch_invariance_diag_20260903_v10、
32条与24固定角色正确，AUDIT_FREEZE_RC=0。
新input_freeze.json SHA：
`0120364c5da694213d36b61bad4c3e7e1211b44bd1a9ae86f0559daecf59fe2e`。
已读回并固定用于下一步check-only，不能复用旧v8或R1/R2的清单。
临时CPU探针目录检查为空，明确两次R2目录不存在；原科学文件未删除或修改。
当前尚未提交，先复核CHECK_PASS与输入/目录状态。

check-only脚本SHA a9483c07bcbc7cacfd894af94e8f3273896d2b1e2302fd941d03c3434b7bba4d。
submit-once脚本SHA 809a6ff91bdfa8b7231afb10b98641bd2bbeb95278ee69a9f62d99b9f59572a3。
两者固定上述新freeze，局部/远端shell语法检查通过；check-only的JSON身份/
错误状态/重复文档/空输出/生产者失败/SSH255传播模拟全部通过，未执行真实提交。
已逐项审阅相对v8旧脚本的路径/哈希/共享连接差异；新提交器仍单次调用并
在锁内重验冻结输入与相关队列，有任何已有journal/日志/attempt则停止。

## 实际check-only与单次提交门槛

CHECK_PASS，协议v10、新freeze0120364c...、五目录和精确远端root匹配。
前后evaluator工具与清单SHA相同，CHECK_ONLY_RC=0。主代理已复核该回执。
下一操作只调用一次固定submitter，1 GPU/8 CPU/1小时上限/no-requeue，执行
原32条REFERENCE_COLD→A2→EQUIVALENCE→A1→B1→B2诊断；不改模型/精度/矩阵，
不调用训练或正式三模型10k评估。提交如不确定，只读检查，不自动重试。

## 实际唯一提交回执

SUBMIT_RC=0，Job **681974**，status=SUBMITTED。不可重跑submit-once。

```json
{"diagnostic_protocol":"formal40_batch_invariance_diag_20260903_v10","input_freeze_sha256":"0120364c5da694213d36b61bad4c3e7e1211b44bd1a9ae86f0559daecf59fe2e","intent_nonce":"bfe8891c389d42699144060276ed0ce8","intent_record_sha256":"6181882ea84a247bec10955010ec032e17ebb5bf5606c0b875040fb461c542b8","job_id":"681974","response_record_sha256":"453a35ea9791d2f703e15078889da943be15b1af6debbc22ebc152b4bdefeda8","runner_sha256":"63dc1293528612afbf69c79273aa3b2f37ca41ed524cfa5f054f9f4f48d77cfa","schema_version":1,"status":"SUBMITTED"}
```

下一步只读status与调度记录，结束后verify-results；提交成功不是运行/数值成功。

首次实际status：Job681974 RUNNING，source=squeue、results_verified=false，
STATUS_RC=0、ACCOUNTING_RC=0、QUERY_RC=0。Slurm原始记录：
681974|RUNNING|0:0|00:00:51|2026-09-10T04:46:03|Unknown|spcc-a100g04。
已进入A100节点，不代表诊断矩阵已完成；继续监控，终态后复核。

## 实际失败及复核

Job681974 FAILED 2:0，运行00:01:11，04:46:03→04:47:14，spcc-a100g04。
verify-results返回DIAGNOSTIC_FAILURE_RECORDED、VERIFY_RC=2，原因为child
exit非零2；stderr具体为`model state snapshot failed`。post_errors=[]，
matrix=null，numeric_results_interpretable=false，不能解释成数值差异结果。
PRECHECK和POSTCHECK均SHA755a950d198dcd638f167ef828766e8b0c1d742f613d79fe0d3c5c267e436d49。

失败marker SHA：7a86da8b924a3f021566288169ca1e39183f4ca51b7403a965a5e88e219991be
日志SHA：63abc8deba1dd8e5ceed525a31b1846a9afcf67e21e01cfb6901ae61318b1d24
artifact inventory SHA：75ecd48584ab4621548bac9061a35a7fe85c2c9e1fc1417aca47324ea595dab1
仅ENVIRONMENT/PRECHECK/POSTCHECK/RUNNING四工件，无有效矩阵。
本次失败证据保留，v10已发布源码不原地修补、作业不重投。下一项为快照
异常真实原因的只读复现；不能只依据总括错误就猜测模型损坏/数值问题。
