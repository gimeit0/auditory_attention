# 诊断 v7 远端部署进度

日期：2026-09-09。用户要求“开始下一步”。

## 本轮本地检查

- 再次校验 v7 十一文件候选清单，全 OK；候选未修改。
- 已阅读候选操作说明及本地修复/479 项测试记录。
- 主代理此前已完成有界 AST/四入口退化复核，不冒用旧版本独立审查结论。

## 预检命令准备（历史状态）

提供 HAKUSAN Bash 只读预检脚本 `2026-09-09-diagnostic-v7-remote-preflight.sh`：

1. 确认 Linux / s2510040，原 v4、诊断 v6 根及 state 为非符号链接目录。
2. 确认拟用诊断 v7 根未占用；若存在即停，不删除、不覆盖。
3. 检查原 v4 manifest/lock 和 v6 Job 671724 失败终态记录的固定 SHA。
4. 查询两个相关作业名，存在相关队列条目即停。
5. 在 attn Python 新进程中确认 torch 2.1.1+cu118；按原先精度/TF32 顺序
   设置并打印六项运行标志，要求 true,true,false,high,true,true。

第五项仅改变短进程内运行标志，不加载模型、读取音频或提交 GPU 作业；不
改写冻结文件。没有改成先设 high；实际顺序依旧 medium→TF32，之后验证读回。
脚本不用 heredoc，不依赖以前 shell 变量，完成后立即捕获真实退出码。

本地仅对该脚本做 bash -n 语法检查，未在本机运行 Linux 预检、未通过 SSH
执行远端命令。尚无 REMOTE_DIAG_V7_PREFLIGHT=PASS 的真实回传。

下一步须收到预检结果后再创建新根/上传。尚无 v7 远端创建、上传、发布、
audit/freeze/check、freeze SHA 或 Job ID。旧 v6 与原 v4 继续保留。

## 2026-09-09：用户回传远端预检通过

本次回传对应 `(HAKUSAN)s2510040@hakusan1`，不是本代理直接连接的结果：

```text
v4 input_freeze.json: OK
v4 state/evaluation.lock: OK
v6 state/DIAGNOSTIC_FAILED.json: OK
V4_QUEUE=
DIAG_QUEUE=
TORCH_VERSION=2.1.1+cu118
RUNTIME_VALUES=[true, true, false, "high", true, true]
RUNTIME_SIX_FLAGS=PASS
REMOTE_DIAG_V7_PREFLIGHT=PASS
PREFLIGHT_RC=0
```

此前短探针仅确认 precision 联动，本次完整确认六项配置的读回。它仍是
登录节点的独立短进程，不是 A100 推理验收，不证明旧数值差异已解决。
三个固定哈希与 v7 根未占用门禁均通过；队列为空仅表示此次查询时状态。

### 下一项准备提供：Mac 单块创建根并上传（尚未执行）

为避免在 HAKUSAN 上误用 Mac 路径，本次明确要求新开 Mac 终端执行整段。
先本地验证 v7 十一文件候选清单，再用 SSH 复查 Linux/账号、base 目录身份、
新根未占用及相关队列；create-once 创建 700 新根及六个子目录，逐一验证
权限/所有者/非符号链接。SSH 成功后，scp 只上传四个固定工具到 staging。
根已存在或任何步骤失败则停止，不删除、不覆盖、不自动重试。

可复用脚本为 `2026-09-09-diagnostic-v7-create-upload.sh`，仅完成创建及暂存上传，
不发布 tools、不执行 audit/freeze、不提交作业。本地只做语法检查，尚无
创建或上传成功回传。下一次需核对远端暂存哈希与布局后才发布。
为避免复制断行，用户在 Mac 以 bash 运行该本地脚本，而非粘贴脚本全部内容；
脚本打印并返回实际 UPLOAD_RC，失败时不继续上传，不把 printf 成功当流程成功。

## 2026-09-09：用户回传新根创建及暂存上传成功

用户在 Mac 执行本地 create-upload 脚本，候选十一文件 SHA 全 OK；回传：

```text
REMOTE_DIAG_V7_ROOT_CREATED=PASS
diagnose_batch_invariance.py 100%
numeric_trace.py 100%
submit_numeric_diag.py 100%
run_numeric_diag.sbatch 100%
DIAG_V7_UPLOAD_TO_STAGING=PASS
UPLOAD_RC=0
```

上方 Broken pipe 为预检后的旧 SSH 会话断开；脚本随后从 Mac 正常运行。
scp 曾出现一次认证失败，重试后四文件 100%、退出 0；不据此声称文件远端
SHA 已核验。当前只确认新 v7 根/布局创建与 staging 上传，尚未发布 tools。

### 下一项准备提供：核验并发布工具（尚无回传）

已编写本地 `2026-09-09-diagnostic-v7-publish.sh`。它先重验本地候选，再通过
SSH 核验远端根/布局/权限/所有者、空 tools 和输出目录、相关队列、stage
精确四文件列表。四文件 SHA、普通文件/无符号链接/单链接及目标未占用全部
通过后，使用 ln -T create-once 发布，设置 600，验证来源/目标为同一文件及
正式工具 SHA。只有四个正式文件全部通过后才 unlink 四个暂存入口并 rmdir
空 staging；正式内容仍留在 tools，最后验证单链接和 600 权限。

不存在强制覆盖、递归删除或自动重试；部分完成或任何不确定状态立即停止，
保留现场供只读检查。脚本仅发布工具，不执行 audit/freeze 或提交作业；打印
且返回实际 PUBLISH_RC。候选生产代码/清单未改，旧诊断根与冻结评估 v4 不动。
本地只做脚本语法/固定哈希检查，不冒称已在远端运行或已发布。

## 2026-09-09：用户回传远端工具发布成功

用户在 Mac 执行发布脚本并回传：本地候选十一文件 SHA 全 OK；远端
staging 四文件和 tools 四文件固定 SHA 全 OK，且：

```text
DIAG_V7_PUBLISH_PREFLIGHT=PASS
REMOTE_DIAG_V7_TOOLS_PUBLISHED=PASS
PUBLISH_RC=0
```

最终布局仅有 tools、logs、state、attempts、submitted_runners 五个 700
子目录与 tools 内四个 600 普通文件。经核验后清理的是四个暂存硬链接及
空 staging 目录，正式文件保留于 tools；旧 v6 与原评估 v4 未被发布脚本修改。
这是用户回传的部署证据，不是代理直接远端检查。尚无 v7 freeze 或 Job ID。

### 下一项准备：输入审计与单次冻结

新增 Mac 操作脚本 `2026-09-09-diagnostic-v7-audit-freeze.sh`，仍放在候选目录
之外，不改冻结候选的十一文件或哈希清单。脚本重验本地候选，通过 SSH
核验已发布根/布局/权限、四工具固定 SHA、输出目录为空和相关队列为空；
若已有 input_freeze.json 则停止，不覆盖。以 attn Python -I -B 先 audit，
通过后才执行带 v7 确认协议的单次 freeze。摘要要求恰好一份 JSON、正确
状态/协议/根、32 trials、24 pinned files；pipefail 保留 Python 失败状态。

冻结后复核落盘文件的类型/所有者/权限及摘要字段，打印新文件 SHA 后停止，
不把现场计算的 SHA 自动用作已审阅 expected 值，不运行 check-only 或提交。
本地做语法、固定哈希与摘要门禁合成测试；不声称已执行远端 audit/freeze。

本次实际本地验证：Mac 包装脚本 bash -n / zsh -n、提取的远端 Bash 脚本
bash -n 均退出 0；候选十一文件 SHA 再验全 OK，脚本四项远端哈希与候选
清单逐项相等。12 项合成门禁检查均符合预期：合法 audit/freeze 各通过，
ERROR 状态、旧协议、旧根、错误 trial 数、25 项 pinned、字符串计数、空
输出、非 JSON、多 JSON 文档均阻断；生产者输出合法 JSON 但退出 2 时，
pipefail 保留退出 2且不会抵达后续步骤。未通过 SSH 执行此新脚本。

## 2026-09-09：用户回传输入审计与冻结成功

用户在 Mac 执行 `2026-09-09-diagnostic-v7-audit-freeze.sh`，回传本地候选十一
文件及远端四工具 SHA 全 OK。随后两个摘要分别为 AUDIT_PASS、INPUTS_FROZEN，
均绑定 formal40_batch_invariance_diag_20260903_v7、32 trials、24 pinned files；
DIAG_V7_AUDIT_INPUTS=PASS、DIAG_V7_FREEZE=PASS、AUDIT_FREEZE_RC=0。

本次新诊断冻结清单（与原评估 v4、旧诊断 v6 清单不同）：

- 路径：`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v7/input_freeze.json`
- SHA-256：`6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920`

该 SHA 来自上述成功冻结的用户回执，现登记为下一项 check-only 的显式预期。
不再运行 create/upload/publish/freeze，不修改冻结文件。尚无 v7 CHECK_PASS、
提交回执或 Job ID；冻结成功不是数值推理验收或三模型对比完成。

### 下一项准备：固定回执 SHA 的只读 check-only

新增候选目录外的 Mac 脚本 `2026-09-09-diagnostic-v7-check-only.sh`。先重验
本地候选，再经 SSH 核验远端诊断器与清单的普通文件身份、600 权限、单链接
及各自固定 SHA；以 attn Python -I -B 调用公开 check-only，显式传入上述
用户回执 SHA。返回值必须是单一 JSON、CHECK_PASS、v7 协议、同一 freeze SHA
及预期根/五目录布局；pipefail 保留生产者失败码。随后再次校验诊断器与
清单固定 SHA，打印 CHECK_ONLY_RC 后结束；不调用 freeze、sbatch 或提交器。
本代理仅在本地准备与检查脚本，尚未执行远端 check-only。

本地检查结果：包装脚本 bash -n / zsh -n、提取的远端脚本 bash -n 均通过；
候选十一 SHA 全 OK，脚本固定的诊断器 SHA 与新回执 SHA 核对相符。10 项
合成门禁检查符合预期：合法 CHECK_PASS 通过；错误状态、旧协议、旧 freeze
SHA、旧根、错误目录布局、空输出、无效 JSON、多 JSON 均阻断；生产者输出
合法 JSON 但退出 2 时仍保留失败码，不抵达后续成功标记。这些只验证包装
脚本，不替代远端输入检查或 A100 数值诊断。

## 2026-09-09：用户回传 check-only 通过

回传摘要尾部为预期 v7 根、schema_version=1、status=CHECK_PASS，随后诊断器
及 input_freeze.json 的固定 SHA 复核均 OK，DIAG_V7_CHECK_ONLY=PASS、
CHECK_ONLY_RC=0。已提供的脚本只有单 JSON 的协议/新 freeze SHA/完整布局门禁
通过，且命令退出 0，才打印该 PASS；回传尾部本身没有再次展示完整 SHA 字段。
当前登记 v7 冻结输入检查通过，绑定已记录的
`6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920`。
仍无 v7 提交回执、Job ID 或可解释数值结果。

### 下一项准备：使用固定提交器单次提交

新增候选目录外的 Mac 脚本 `2026-09-09-diagnostic-v7-submit-once.sh`。执行此
脚本将申请正式的 32-trial formal40 数值诊断作业，而不是三模型 10k audit。
它核验本地十一候选哈希、远端目录/文件身份与模式，固定提交器 SHA
`d74c4878ccd5e9c79cd3854139009c1d2c5449df846082667ac7407ade474e86`
及上述新 freeze SHA。state/logs/attempts/submitted_runners 任意存在条目即停，
不清理旧记录。通过后仅调用一次公开 submit，带固定确认动作、原 v4 Job
646900（诊断对象，不是新 Job ID）与新 freeze SHA。

已检查现有提交器：journal lock 内执行分类、相关队列检查、完整 check-only、
输入复查，再检查队列/输出；先持久化 intent，然后最多调用一次 sbatch，
保存 response 与 receipt。包装脚本不直接调用 sbatch，不循环、不自动重试，
原样显示提交器 JSON 和真实 SUBMIT_RC。非零、断线或状态不明确时只能转只读
status，不能按失败推断“未提交”。本代理尚未执行该远端脚本或提交任何作业。

本地验证已完成：包装脚本 bash -n / zsh -n 以及提取的远端 Bash 语法检查
全部通过；固定提交器/新 freeze SHA 及唯一提交器调用核对通过。独立进程
重跑 test_submit_numeric_diag.py：66 tests、10.284s、OK，退出 0；测试使用
本地临时夹具和模拟调度器，输出中的 Job 123 不是 HAKUSAN 作业。测试后
十一文件候选 SHA 再验全 OK，没有改动候选代码或清单。

## 2026-09-09：用户回传 Job 680519 提交成功

用户执行 Mac 单次提交脚本，回传本地十一文件 SHA、远端提交器/冻结清单
固定 SHA 全 OK，完整提交回执如下；SUBMIT_RC=0。此处仅记录用户回传，
尚未查询当前调度状态，不将 SUBMITTED 解释为已运行或通过。

```json
{
  "job_id": "680519",
  "next": "wait_then_status_and_verify_results",
  "receipt": {
    "diagnostic_protocol": "formal40_batch_invariance_diag_20260903_v7",
    "input_freeze_sha256": "6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920",
    "intent_nonce": "6b435bb3f7cd42488e859b990d03933e",
    "intent_record_sha256": "9487e271c132fe51736729add365482fe5b8f52c42e1e0092b64df53ced51efb",
    "job_id": "680519",
    "response_record_sha256": "3898cd987bb4f9fdfe6db50b904faa0ec4baff90d49bc0d71259c8e0944dc842",
    "runner_sha256": "19c0d314f5ec1c8c3d93eae8a04c7c33d38b98079f1ee447cfabe95dacad0b62",
    "schema_version": 1,
    "status": "SUBMITTED"
  },
  "status": "SUBMITTED"
}
```

协议、新诊断 freeze SHA、runner SHA 与本次固定候选一致，内外 Job ID 均为
680519。原 v4 Job 646900 和旧诊断 v6 Job 671724 均不是本次新作业。
不再运行 submit-once；作业执行结果与原批大小数值差异仍待验收，三模型
完整 10k 比较尚未完成。

### 下一项：只读查询 Job 680519

新增候选目录外的 Mac 脚本 `2026-09-09-diagnostic-v7-status.sh`。通过 SSH
核对固定提交器和 v7 freeze SHA，再调用公开 status，并对回执 Job 680519
查询 sacct。保留两个查询的独立退出码及总 QUERY_RC，不隐藏非零状态；
即使 status 返回失败/不确定，也继续显示该 Job 的调度记账供核对。已确认
候选 status 实现不创建锁、写工件、推理或提交；本脚本同样不调用 submit。

该查询脚本可重复运行；QUERY_RC/STATUS_RC 为 0 只说明相应查询成功，不是
诊断数值通过。终态出现后另行使用同一 freeze SHA 和 Job ID 执行公开
verify-results；不自动修复、放宽阈值或重提。尚无此次远端状态查询回传。

查询包装脚本的 bash -n / zsh -n、提取远端脚本的 bash -n 均通过；固定 Job
680519、新 freeze SHA、提交器 SHA 核对通过，本地提交器实际哈希亦匹配。
四组退出码合成检查（0/0、2/0、0/1、2/1）均保留预期总退出码，不用末尾
打印成功覆盖查询失败。未执行远端查询，未修改候选文件。

## 2026-09-09：用户回传 Job 680519 失败终态

用户执行只读 status 脚本，提交器和新诊断 freeze SHA 均 OK，状态返回：

```json
{"input_freeze_sha256":"6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920","job_id":"680519","next":"verify-results","results_verified":false,"source":"terminal_marker","status":"DIAGNOSTIC_FAILED"}
```

Slurm 记账回传为：

```text
JobIDRaw|State|ExitCode|Elapsed|Start|End|NodeList
680519|FAILED|2:0|00:02:05|2026-09-09T15:14:06|2026-09-09T15:16:11|spcc-a100g04
```

STATUS_RC=0、ACCOUNTING_RC=0、QUERY_RC=0 仅表示查询成功。当前只知道失败
终态，尚无具体 primary_error、post_errors 或日志错误行；不能断言是旧
运行标志问题再次发生，也不能从运行时间推断已通过哪个模型/数值阶段。
不重提、不修改代码、不开新版本，先核验失败证据。

### 下一项：公开 verify-results 与失败日志取证

新增候选目录外 Mac 脚本 `2026-09-09-diagnostic-v7-failure-evidence.sh`。
核对固定诊断器与 v7 freeze SHA 后，以 Job 680519 调用公开 verify-results；
保留原始 JSON 和 VERIFY_RC，失败时仍继续读取失败 marker 的阶段/工件清单
摘要、marker SHA 及作业日志 SHA/末尾 120 行。仅显示时将超 2400 字符单行
截断并明确标注 DISPLAY_TRUNCATED，不修改原日志，必要时再定向读取。

失败记录经过验证通常返回 DIAGNOSTIC_FAILURE_RECORDED、VERIFY_RC=2，
numeric_results_interpretable=false；这不是可解释数值结果通过。脚本分别
打印 READ_RC 与 EVIDENCE_RC，并保留非零验证退出码；没有修复/删除/重提。
本代理未连接远端执行此取证，当前尚未收到失败根因回传。

本地检查：包装脚本 bash -n / zsh -n、提取远端脚本的 bash -n 均通过；
固定 Job/freeze/诊断器 SHA 与公开 verify-results 参数核对通过。四组验证/
读取退出码组合均保留预期总退出码。实际诊断器 SHA 未变；重跑失败 marker
不可被解释为数值成功、只读 CLI 对失败/未完成返回非零两项回归，2 tests、
0.174s、OK。该本地夹具验证不提供 Job 680519 的实际失败原因。

## 2026-09-09：失败证据回传及本地集合类型复现

用户回传 DIAGNOSTIC_FAILURE_RECORDED，VERIFY_RC=2；父进程 execution 错误
为 child exit is nonzero: 2，子进程日志实际错误为 unsupported execution
collection type。post_errors=[]、锁已获得、matrix=null，仅 ENVIRONMENT /
PRECHECK / POSTCHECK / RUNNING 四份工件。PRECHECK 和 POSTCHECK 同 SHA，
均为 2187e9dafc18b33430c2af50640fb9e9a08d2478bc9161fbf6bfc024ea3e496c。
失败 terminal SHA 为 2ecd6af2807d9315b4c5d1938188f0d0bf59e40fa544cee9132e7cfbffa57628，
日志 SHA 为 92ad39871c7d20b36405bc78464a351c6842bbb5b220df99213337cd51f1dd92。
没有通过验收的参考/cell 数值结果，不把本次报错等同于 v6 运行设置错误。

本地定位到集合身份函数拒绝未显式支持的 Collection。哈希与冻结快照相同
的模型源文件第 37 行构造 _amp_overflow_window=deque；仅提取该构造表达式
并在最小 torch 模块上执行 v7 配置指纹，即重现同一错误。torch.Size 也被
该分支拒绝，远端无路径信息，不能确认首个/唯一触发对象。候选十一 SHA
未变，无远端写入、无 v8 创建或重提。详细证据与本地复现边界见
[集合类型诊断](2026-09-09-job680519-collection-diagnosis.md)。
