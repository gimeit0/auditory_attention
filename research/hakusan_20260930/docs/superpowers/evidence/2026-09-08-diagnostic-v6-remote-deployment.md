# 诊断 v6 远端部署进度

## 2026-09-08：用户回传只读预检通过

来源：用户在 HAKUSAN 登录终端执行命令后回传输出，非本代理直接查询。

```text
/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/input_freeze.json: OK
/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/state/evaluation.lock: OK
V4_QUEUE=
DIAG_QUEUE=
REMOTE_DIAG_V6_PREFLIGHT=PASS
PREFLIGHT_RC=0
```

该次检查确认旧诊断 v5 根存在且非符号链接、新诊断 v6 根未占用；原评估 v4
manifest 与 lock 仍分别匹配固定 SHA：

- manifest：`1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5`
- lock：`63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710`

相关名称队列在检查时为空，不代表之后仍为空；不推断集群全部作业状态。
本地 v6 十文件候选清单再次验证通过，未改候选源码或 README。
本次记录基于已完成的[本地有界复核](2026-09-08-diagnostic-v6-prepublication-review.md)，
不是新的独立审查或 GPU 验收。

## 预检后的部署安排（历史）

1. HAKUSAN：create-once 创建新诊断 v6 根及六个子目录，权限 700。
2. Mac：验证固定候选清单，只上传四个生产文件到新根 `.upload-staging`。
3. 收到回传后，核对远端 SHA 并 create-once 发布 tools；再 audit、freeze、
   核对新 freeze SHA、check-only，最后才考虑单次作业提交。

新诊断根：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v6`。

截至本条记录，尚无 v6 目录创建或上传的回传确认；没有 v6 freeze 或 Job ID。
不覆盖旧诊断版本、原评估 v4 或 Job 670830 失败证据。不复用 v5 诊断 freeze SHA。
若创建或上传中途失败，保留现场并只读检查，不重复执行整个块、不删除重建。

## 2026-09-08 续：用户回传 v6 上传成功

用户在 Mac 执行本地十文件固定候选清单校验，全部 OK；随后将四个生产文件
上传至固定 v6 `.upload-staging`。第一次 SSH 认证返回 Permission denied，
再次输入后四文件均显示 100%，最终输出：

```text
DIAG_V6_UPLOAD=PASS
UPLOAD_RC=0
```

本次传输成功；不能由第一次认证失败推断整个上传失败。终端上方 Job 646900、
SMOKE_SUBMITTED、Broken pipe 及恢复窗口时间属于回显的历史内容，不是新提交
或本次上传失败。没有收集或记录密码。

用户未回传独立的 v6 mkdir 输出；scp 成功说明目标可用于上传，但目录类型、
权限、符号链接边界及最终远端文件 SHA 尚须发布前实查，不能据此全盘认定
目录布局已验收。此时不重复创建新根，也不重传覆盖 staging。

下一项提供 HAKUSAN 发布块：确认根和六子目录、无已冻结或执行证据、相关队列
为空、staging 恰含四个常规单链接文件、四 SHA 匹配后，以不覆盖的硬链接发布
至空 tools。再次核对正式文件 SHA 与同一文件身份，随后移除四个暂存名称和
空 staging 目录。正式 tools 文件保留，旧版本及失败证据不动。

截至此续记，仅确认上传成功；尚无 tools 发布成功、v6 audit/freeze/check 或
新作业的回传。以下四个远端 expected 值来自固定候选清单，不从当前上传文件
重新生成：

- diagnostic：`459613c3e9ca701bde52f5f4aea6d6190a032f6d869431a2860f3c86467a6dd9`
- trace：`fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b`
- submitter：`890f2c05f3982d3a53a526b3f07634ea2f811101865d83652431bd3cb94cd6b3`
- runner：`33232a2d085bb7dcdd1d11dc9cf34646bbc9042b9f868dcbabfe122bd5c05d29`

## 2026-09-08 续：用户回传正式 tools 发布成功

用户在 HAKUSAN 执行已给出的发布块，回传 staging 四文件与 tools 四文件共
八行 SHA 检查 OK，最后为：

```text
REMOTE_DIAG_V6_TOOLS_PUBLISHED=PASS
PUBLISH_RC=0
```

按照该块的完成条件，本次检查了根和子目录边界、所有者和权限、空 tools／
执行目录、无 freeze、相关队列为空及 staging 精确四文件集合。正式文件以
不覆盖的硬链接发布并复核 SHA；清理了四个暂存名称及空 `.upload-staging`，
tools 正式文件保留，单链接数复核通过。旧版本及 Job 670830 证据未列入写目标。
这补足了先前未单独回传 mkdir 输出所留下的目录验收缺口。

当前确认状态：v6 四生产文件已正式发布；还没有 v6 audit、freeze、check-only
或新作业成功的回传。原始批大小 NLL 问题仍未获得诊断结论。

下一项合并提供 audit → freeze 命令：固定 diagnostic SHA 在执行前复核，
拒绝既有 freeze；audit 退出成功且摘要字段满足 v6 协议、32 trials、24 pinned
records 后，才允许调用一次 freeze-inputs。两段采用 pipefail 和 jq 字段门禁，
只显示摘要，避免再输出完整音频清单；任何失败均停止。freeze 自身会重建并
验证 audit，再 create-once 保存新诊断清单。最后仅打印新文件 SHA 供回传核对，
不自动把它用作后续可信 expected 值，也不执行 check-only 或提交。

本地已核对 CLI help 和 Bash 语法；摘要过滤器的有效 32 条夹具通过、31 条
无效夹具被拒绝。此检查不接触集群，也不是输入审计已在集群通过。

## 2026-09-08 续：用户回传 v6 audit 与 freeze 成功

来源仍为用户的 HAKUSAN 终端回传，非本代理直接远端读取。
执行前 diagnostic 固定 SHA 检查 OK，随后：

```text
DIAG_V6_AUDIT_BEGIN
status=AUDIT_PASS
diagnostic_protocol=formal40_batch_invariance_diag_20260903_v6
trials=32
pinned_files=24
DIAG_V6_AUDIT_INPUTS=PASS
DIAG_V6_FREEZE_BEGIN
status=INPUTS_FROZEN
diagnostic_protocol=formal40_batch_invariance_diag_20260903_v6
trials=32
pinned_files=24
DIAG_V6_FREEZE=PASS
AUDIT_FREEZE_RC=0
```

上面为结构化输出的字段转录。新生成的诊断 v6 清单：

- 路径：`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v6/input_freeze.json`
- 回传 SHA-256：`c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc`
- 协议：`formal40_batch_invariance_diag_20260903_v6`

此 SHA 作为下一步显式 expected 值，来源是本次受控 freeze 的用户回传；
后续不通过现场自动计算来重新设定 expected。它不同于 v5 诊断 freeze
`739f1b…`，也不同于原评估 v4 manifest `1f6a88…`，不能混用。

下一步只运行 check-only：复核固定 diagnostic 和新清单 SHA，读取并重建当前
输入审计，与保存的 freeze 比较。已在本地核对参数契约和 Shell 语法，没有
远端执行此核验。本条记录尚无 v6 CHECK_PASS、提交回执或新 Job ID。
审计/冻结成功不代表真实 GPU 数值诊断成功，原 NLL 差异和最终三模型比较仍未完成。

## 2026-09-08 续：用户回传 v6 check-only 通过

用户回传 diagnostic 与新 freeze 的固定 SHA 检查均为 OK，随后只读核验返回：

```json
{
  "diagnostic_protocol": "formal40_batch_invariance_diag_20260903_v6",
  "input_freeze_sha256": "c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc",
  "schema_version": 1,
  "status": "CHECK_PASS"
}
```

以上为原 JSON 的关键字段摘录；原输出同时列出固定 v6 根及 tools、logs、state、
attempts、submitted_runners 五目录。末尾 DIAG_V6_CHECK_ONLY=PASS，CHECK_ONLY_RC=0。
这确认 check-only 读取并重建的审计与保存的 v6 freeze 一致，不等于 GPU 执行成功。

下一项提供固定提交器的单次 submit 命令：提交器 SHA
`890f2c05f3982d3a53a526b3f07634ea2f811101865d83652431bd3cb94cd6b3`，
expected freeze 使用上面的 c04bcc…；confirm-action 为
SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC，confirm-v4-job-id 为 646900。
646900 仅绑定原失败 smoke 证据，不是重提该旧作业。

本地主代理已复核 CLI help、固定提交器 SHA 和提交逻辑：提交器在持久锁内
检查既有回执／意图、输出目录、相关队列，重新运行完整 check-only，并在写入
耐久 INTENT 后最多调用一次 sbatch。断线、超时或 STOP_AMBIGUOUS 时保留现场，
只查 status，不自动重提、不删除 INTENT。未直接调用 runner 或协调器内部入口。

截至本条记录，尚无 v6 提交回执或 Job ID；命令由用户在 HAKUSAN 执行后再回传。
拟提交的是固定 32 条样本的 formal40 数值诊断，不是三模型 10k audit 或重新训练。

## 2026-09-08 续：用户回传 v6 Job 671724 提交成功

来源：用户在 HAKUSAN 执行固定提交块后的完整 JSON 回传，非本代理直接查询。
提交前 submitter 与 freeze 固定 SHA 检查均为 OK。外层 status=SUBMITTED，
job_id=671724，next=wait_then_status_and_verify_results，SUBMIT_RC=0。
回传 receipt 如下（仅排版，未据此推定远端回执文件本身 SHA）：

```json
{
  "diagnostic_protocol": "formal40_batch_invariance_diag_20260903_v6",
  "input_freeze_sha256": "c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc",
  "intent_nonce": "88e2cfacc8f740b7a9656a2bea4d6e6a",
  "intent_record_sha256": "30c7fdae8ae8ed92f2f25a21f3867d3e90222a195851094279d9979510bd6c01",
  "job_id": "671724",
  "response_record_sha256": "f476175f418607763d4e2bad3a9ecea55cd3fab5df31676ef905bef2148fe6dc",
  "runner_sha256": "33232a2d085bb7dcdd1d11dc9cf34646bbc9042b9f868dcbabfe122bd5c05d29",
  "schema_version": 1,
  "status": "SUBMITTED"
}
```

该输出证明本次提交器取得调度器接受回执，不证明作业当前仍在排队、正在运行、
已经完成或数值结果有效；真实状态须后续查询。671724 是新的诊断 v6 Job ID，
不同于原失败 smoke 646900 和诊断 v5 失败作业 670830。

下一项仅调用同一 submitter 的 status 并查询 sacct。状态为 PENDING/RUNNING 时
等待；终态后调用固定 diagnostic 的 verify-results，使用本次 c04bcc… freeze
及 Job 671724，再解释结果。即使 Slurm COMPLETED 也不跳过工件核验。
STATUS_RC=0 只表示状态查询成功；status 中的结果及 results_verified 字段另行判断。
不重跑 submit、不改意图／回执、不删除日志或旧版本。

截至本条记录，只有提交成功证据；尚无 Job 671724 的实时状态、完成标记或
verify-results 回传。正式三模型 10k 比较仍未开始本轮验收。

## 2026-09-09 回传：Job 671724 已失败，原因待取证

提交后的首次用户查询曾返回 PENDING、None assigned、00:00:00。
本次用户回传：

```json
{
  "input_freeze_sha256": "c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc",
  "job_id": "671724",
  "next": "verify-results",
  "results_verified": false,
  "source": "terminal_marker",
  "status": "DIAGNOSTIC_FAILED"
}
```

```text
STATUS_RC=0
JobIDRaw|State|ExitCode|Elapsed|NodeList
671724|FAILED|2:0|00:01:10|spcc-a100g03
```

以上为用户终端回传，不是本代理直接查询。2026-09-09 是此次记录／回传日期，
现有 sacct 字段不含 Start/End，故不推定实际失败时刻。
作业已获节点并运行 70 秒后退出，当前不是排队；STATUS_RC=0 是查询成功，
不是实验成功。现有输出未包含 primary_error、post_errors 或执行阶段，不能
认定重现了 v5 的 noncanonical JSON 错误，也不能推断已进入或未进入模型推理。

下一项仅取证：固定 v6 diagnostic 和 freeze SHA 核验后，用 Job 671724 执行
verify-results，收集完整失败摘要与日志 SHA，并显示日志末尾 40 行（每行最多
400 字符，完整原文件不改）。失败记录验收可能返回 DIAGNOSTIC_FAILURE_RECORDED
及退出 2；这与“数值结果通过”不同，需结合 primary_error/post_errors 判断。
若核验本身报错，也保留输出，不伪造成功或修改终态。

本次只更新状态文档和提供只读命令，不创建 v7、不修改已发布 v6、不重提作业。
尚未取得 Job 671724 的具体错误及可解释的数值结论，三模型完整比较仍未完成。

## 2026-09-09 续：失败记录验收与运行设置错误已定位

用户回传 VERIFY_RC=2、DIAGNOSTIC_FAILURE_RECORDED，primary_error 为
`child exit is nonzero: 2`，post_errors=[]。日志进一步给出
`frozen runtime settings are not exact`；terminal SHA 为
`5425b5f69dc41c782b816a608437321598793f8759aaa4c592fda0c3b7f2f999`，
inventory SHA 为 `77ce0b0dd7c03e93a4e79dd1dc2c789e8e51c6def96b211d84bead1d45fd077e`。
失败 worker 停在正式模型加载前的运行设置门禁。

本地源码与 PyTorch 2.1.1 固定标签源码对照发现：原配置设置 medium 后开启
TF32，标准 2.1.1 最终精度字段会成为 high；诊断器硬编码要求 medium。
本地 2.12.1 的 getter 则抛混用 API 异常，现有兼容分支用 medium 代填，
暴露测试版本覆盖缺口。仍待用户在集群同一 Python 执行无模型／无 GPU 计算
的短进程读回探针，不伪称已经读取失败子进程的实际字典。

完整事实、官方来源与有界后续见
[Job 671724 运行设置取证](2026-09-09-job671724-runtime-setting-diagnosis.md)。
本轮只诊断和记录，没有修改 v6、新建 v7、重提或更改科学配置。
