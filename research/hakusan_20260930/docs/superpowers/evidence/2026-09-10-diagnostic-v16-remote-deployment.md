# v16 独立部署记录（2026-09-10）

依据用户批准的精确编译生命周期方案以及698项回归、真实同版本CPU准备与
eager/Inductor合成验证，开始受控独立部署。科学配置和原数值阈值不变。

- create/upload：固定23文件候选SHA通过；原v4四文件、v15冻结/失败标记/日志
  共七文件SHA保持，两条相关队列为空，新v16目录不存在，创建私有目录并
  上传四文件至staging，`UPLOAD_RC=0`。
- publish：四文件两次远端SHA/所有者/类型校验通过，发布到tools，
  `REMOTE_DIAG_V16_TOOLS_PUBLISHED=PASS`，`PUBLISH_RC=0`。
  仅移除已核验的staging硬链接和空目录，四份完整文件仍在tools，旧版未改。
- audit/freeze：`AUDIT_PASS`、`INPUTS_FROZEN`，协议v16、32trial、24pinned均匹配；
  `AUDIT_FREEZE_RC=0`。实际新freeze SHA
  `0ee7cb2cfe50b2a1cfb6dd34f4fa43ade84f0316f3acb7c3d48ed061c8bd64fe`。
  已固定此值到只读check-only与后续入口，尚无本版本GPU结果或新的作业回执。
- check-only：协议/root/五目录/freeze匹配，`CHECK_PASS`、`CHECK_ONLY_RC=0`；
  评估器与freeze前后SHA保持。已审核，允许按既定入口单次提交。

候选清单SHA `b8dd965e688ea8d2452a14cf831985e342969927e66363377eaaff1c6582bf15`。
root `/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v16`。
所有命令入口为同目录 `2026-09-10-diagnostic-v16-*.sh`。尚未收到的freeze/job
以不可用占位符阻止误用；取得并核对真实回执后再固定。

## 单次提交回执

唯一Job **683649**，`SUBMIT_RC=0`；nonce `5c7bf1b6d7b6405da9522f7090ad81d2`。
完整[回执](2026-09-10-diagnostic-v16-submission-receipt.json)已保留。
状态、验收、失败取证入口已固定Job683649与本次freeze；不重提，等待终态
再只读verify-results。尚无有效矩阵或完整比较，提交成功不是实验通过。

## 终态及只读验收

Job683649在spcc-a100g09运行18:01:26–18:48:52 JST，47分26秒，FAILED2:0。
`verify-results`=2，`numeric_results_interpretable=false`、matrix=null、post_errors=[]。
失败发生在reference工件发布的普通0600单链接校验，不是超时终态；未重提。
六份原始文件SHA归档于[job-683649-v16](job-683649-v16/README.md)。
同home文件系统小文件重现了原writer错误；final描述符固定的控制顺序通过。
见[故障证据与下一步方案](2026-09-10-job683649-publication-diagnosis.md)。
