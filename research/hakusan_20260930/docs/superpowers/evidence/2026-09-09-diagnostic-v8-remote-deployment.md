# 诊断 v8：远端部署进度

日期：2026-09-09。用户在 v8 本地修复完成后要求“下一步”。

## 最新回传与本地复现：os._Environ 映射校验不兼容

用户已重试只读取证并取得日志；此前 SSH 255 未执行远端取证，不是新作业。
本次具体错误为 `unsupported execution mapping type`，路径
`root.class[__init__].resolved[os.environ]`，类型 `os._Environ`。
primary_error 为 child exit is nonzero: 2，post_errors=[]、matrix=null；只有
四个准备/前后检查产物。READ_RC=0，EVIDENCE_RC=2，没有可验收的数值矩阵。
日志 SHA：a0c2c807b444e9c4860ba39c45ffa46ba0c17e2e4b91449324d23d7490cf75e6。

已用 SHA 匹配的模型/数据集源码衍生最小构造器，在本地重现完全相同的类型
与路径，且不需实例化模型或推理。普通映射接受、os.environ 拒绝，说明当前
直接阻塞是诊断器执行配置检查的兼容问题；不是原 smoke 数值差异的解释。
不推断唯一远端拥有者类，不宣称完整模型已经验证。没有改 v8 或新建候选。
详见 [Job 680910 映射诊断](2026-09-09-job680910-environ-diagnosis.md)。
下一步建议先独立本地修复并扩充真实源码依赖覆盖，不直接重提。

## 此前回传：Job 680910 失败，等待具体错误取证

用户运行的是 v8-status.sh，只读状态查询；所贴提交回执仍为此前相同的
Job 680910/intent_nonce，没有新的提交证据。返回 DIAGNOSTIC_FAILED、
source=terminal_marker、results_verified=false、next=verify-results。
STATUS_RC=0、ACCOUNTING_RC=0、QUERY_RC=0 仅表示查询正常。

Slurm 原始回传：

```text
JobIDRaw|State|ExitCode|Elapsed|Start|End|NodeList
680910|FAILED|2:0|00:00:48|2026-09-09T17:39:38|2026-09-09T17:40:26|spcc-a100g04
```

这证明该作业已运行并失败，但状态输出没有根因；不能据此断定又是 deque、
TF32、原 NLL 偏差或任何新错误。用户要求下一步：只准备 verify-results 与
失败标记/日志的只读取证入口，不修改候选、不建 v9、不重提或重新冻结。

## 此前操作：失败结果验证与日志读取（已回传具体错误）

在 Mac 执行：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-failure-evidence.sh
```

固定 v8 evaluator SHA、新 freeze SHA 和 Job 680910，先重验代码/清单，再
调用只读 verify-results。即使返回 2，仍继续读失败标记与日志；摘要核对
job/protocol/freeze/status，显示 primary_error、post_errors、matrix_status
和产物文件名。日志只显示最后 120 行，每行至多 2400 字符加截断提示，
原文件不变；同时输出失败标记和日志的 SHA。没有原地修复、冻结或提交。

VERIFY_RC=2 既可能表示 DIAGNOSTIC_FAILURE_RECORDED，也可能是验证本身
报错；必须结合完整 JSON/错误文本判断，不能仅凭退出码宣布验证成功。
目前还没有本次 verify-results、失败标记 SHA 或具体日志报错的实际回传。

本地校验通过：十二候选 SHA 未变，包装/远端 bash -n、测试脚本 Ruff；
摘要正例/四种身份错误、verify 返回 2 后继续取证、日志截断、四种退出码
组合、模拟 SSH 255 均通过。没有直接 SSH 或真实结果验证。
日志：2026-09-09-diagnostic-v8-failure-evidence-local-check.log。

## 此前回传：v8 已提交 Job 680910

用户实际运行 v8-submit-once.sh，十二候选 SHA 及远端 submitter/freeze SHA
通过，返回 status=SUBMITTED、job_id=680910、SUBMIT_RC=0。完整内层回执如下：

```json
{
  "diagnostic_protocol": "formal40_batch_invariance_diag_20260903_v8",
  "input_freeze_sha256": "1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c",
  "intent_nonce": "d888d95b673040b68c8580099a535320",
  "intent_record_sha256": "67f475dae73a8d32d3f7254e481922733b04ae938d4f8069c98fc49470c20028",
  "job_id": "680910",
  "response_record_sha256": "b695f0d2264fdd98df5d24822db4408776b9beaa2f3712cff72392c55055b3ea",
  "runner_sha256": "72085b49debf2c70e730f546eb12fd62d0aa4ee64c46cfdd67d433ad4992743b",
  "schema_version": 1,
  "status": "SUBMITTED"
}
```

外层 next=wait_then_status_and_verify_results。冻结 SHA 和 runner SHA 与此前
已审阅值匹配。此记录是用户回传，不是本地助手直接访问超算得到的实时状态；
还不能判定当前排队、运行或结束，也没有有效数值结果。不得重跑提交脚本。
下一项只查询固定 Job 680910，终态仍需 verify-results。

## 此前操作：只读查询 Job 680910（已回传失败状态）

在 Mac 执行，可重复查询此状态入口（不能重复提交）：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-status.sh
```

固定查询 Job 680910 和已审阅的新 freeze SHA。先核对远端 submitter/freeze
SHA，再调用一次 status；原样显示响应并核对 job_id、freeze SHA、
results_verified=false。随后显示该作业的 sacct 状态、退出码、运行时长、
起止时间和节点，两项查询错误都保留/返回。查询不会申请资源、推理、创建
提交锁或修改远端文件；终态无论完成或失败，下一项仍是 verify-results。
STATUS_RC/QUERY_RC=0 只表示查询正常，不表示诊断成功。

本地候选十二 SHA 未变，包装和远端块 bash -n、Ruff 通过；四类状态身份
测试、七类错误响应拒绝、四类查询错误码组合和模拟 SSH 255 通过。
日志：2026-09-09-diagnostic-v8-status-local-check.log。
以上仅本地模拟，没有直接 SSH、实时调度查询或 GPU/结果验证。

## 此前回传：v8 只读检查通过

用户已实际运行 2026-09-09-diagnostic-v8-check-only.sh；本地十二候选 SHA
全 OK，远端诊断器与冻结清单在检查前后均 OK。返回 schema_version=1、
CHECK_PASS，协议为 formal40_batch_invariance_diag_20260903_v8，新 freeze SHA
为 1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c，
layout.root 为预定 v8 根，五个目录与预期一致。
DIAG_V8_CHECK_ONLY=PASS、CHECK_ONLY_RC=0。

此回传仅确认输入准备检查完成，尚无 v8 提交回执/Job ID 或有效数值结果。
下一项准备固定同一 SHA 的 Mac 单次提交入口，仍保留旧 v7 和原评估 v4；
不更改已发布候选，不重新冻结，不直接调用 sbatch，不代用户执行远端提交。

## 此前操作：单次提交数值诊断（已提交，勿重跑）

只在 Mac 执行一次：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-submit-once.sh
```

脚本固定已审阅的新 freeze SHA 与 v8 submitter SHA，重验本地十二候选、
远端根/子目录和文件属性、两项固定 SHA。state/logs/attempts/submitted_runners
只要已有任一条目就停止，保留记录；仅一次调用固定 submitter。提交器自身
在 journal 锁内核对输入/队列，重跑只读检查，再检查输入/队列，持久化 intent
后最多调用一次 sbatch。直接显示完整响应，不通过管道隐藏回执，不自动重试。

范围仍为 formal40 的 32 条样本数值诊断；runner 固定为 GPU-1A、1 GPU、
8 CPU、1 小时时限、no-requeue。不是三模型 10k 正式对比或重训。
预期回传 status=SUBMITTED、新 job_id、同一 freeze SHA、SUBMIT_RC=0。
断线、失败或响应不确定时只读检查，不能重跑此脚本、清理记录或重新冻结。

本地验证通过：包装/远端 bash -n，固定 SHA 与候选清单匹配；六个空/已有证据/
读取失败场景、三种提交器模拟返回码（0/2/3）均只调用一次且参数准确，模拟
SSH 返回 2/255 均准确传播。测试脚本 Ruff 通过；原候选提交器 66 项回归通过。
日志：2026-09-09-diagnostic-v8-submit-local-check.log。候选未修改；以上没有
执行实际 SSH、超算提交或 GPU 推理，等待用户提交回执。

## 此前回传：v8 审计与冻结通过

用户实际回传相关队列为空、tools 四个固定 SHA 均 OK，随后 AUDIT_PASS、
INPUTS_FROZEN 均匹配 formal40_batch_invariance_diag_20260903_v8、32 trials、
24 pinned files；DIAG_V8_AUDIT_INPUTS=PASS、DIAG_V8_FREEZE=PASS、
AUDIT_FREEZE_RC=0。

新的冻结文件：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v8/input_freeze.json`。

用户回传并已记录的 SHA-256：
`1cdb55adbeed5118b9e13f816a5ea1c096125bb447ad61a46dcab96a172c266c`。

下一项为固定此新 SHA 的只读 check-only。不得重新运行 audit-freeze、
重新生成清单或复用 v7 的 6b1f2d…75920。当前只确认准备输入成功，没有
当时的 v8 CHECK_PASS、提交回执、Job ID 或有效 GPU 数值结果；CHECK_PASS
现已回传，见顶部记录。

## 此前操作：只读 check-only（已回传通过）

在 Mac 执行：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-check-only.sh
```

脚本固定使用上述用户回传的新 freeze SHA，不从待验文件动态生成 expected。
本地重验十二文件候选，远端核对诊断器与清单的固定 SHA、常规文件、归属、
600 权限和单链接，执行只读 check-only。仅接收一个符合预期 schema、
CHECK_PASS、v8 协议、freeze SHA、根和目录列表的 JSON，随后重验两文件 SHA。
不重新冻结，不提交作业；错误时保留现场。等待真实 CHECK_PASS 回传。

本地验证：候选十二 SHA 不变，包装与远端块 bash -n，通过 12 个实际 jq/
管道场景（包括错误字段、旧版本 SHA、空/多 JSON、噪声、合法 JSON 配合
生产进程退出 2）；模拟 SSH 255 准确传递，无伪 PASS。测试脚本 Ruff 通过。
这些只是本地入口验证，没有执行真实 SSH、远端 check-only、冻结或提交。
日志：2026-09-09-diagnostic-v8-check-only-local-check.log。

## 此前回传：v8 tools 已发布

用户先在 Mac 提示符输入了两行 PASS/RC 变量赋值，这本身不代表执行操作；
随后真正运行 v8-publish.sh 的完整输出才是本条完成依据。
本地十二候选 SHA 全 OK、相关队列为空，远端 staging/tools 各四行固定 SHA
均 OK，DIAG_V8_PUBLISH_PREFLIGHT=PASS、REMOTE_DIAG_V8_TOOLS_PUBLISHED=PASS、
PUBLISH_RC=0。最终五个子目录 700，四个 tools 文件 600。

暂存四个目录入口及空 staging 目录已由发布脚本清理；四个文件数据完整保留
于 tools，不涉及原 v4 或旧 v7 数据删除。不要重跑 create-upload/publish。
当时没有 v8 input_freeze.json、check-only 或提交回执/Job ID 的完成回传；
随后审计与冻结已完成，见本文顶部最新记录。

## 此前操作：输入审计与单次冻结（已回传完成，勿重跑）

Mac 入口：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-audit-freeze.sh
```

只复制命令块；PASS/RC 是脚本结果，不需要手动赋值。脚本先核验本地候选、
远端 tools 四个固定 SHA、700 目录/600 单链接文件、精确布局与空输出目录、
相关空队列和 input_freeze.json 尚不存在。调用已固定诊断器 audit-inputs，
仅当单个 JSON 的状态/协议/根/schema/32 trials/24 pinned files 均符合预期，
且生产进程退出成功时，才执行 freeze-inputs 一次。

freeze 使用 formal40_batch_invariance_diag_20260903_v8 显式确认；工具自身
再次审计并 create-once 写新清单。脚本核对落盘文件、摘要、归属/权限/单链接，
打印新的 input_freeze.json SHA 后停止。预期 DIAG_V8_AUDIT_INPUTS=PASS、
DIAG_V8_FREEZE=PASS、AUDIT_FREEZE_RC=0。该新 SHA 需回传审阅，再准备
check-only；不以运行时重算值自动作为 trusted expected，不复用 v7 freeze。

若已有 freeze 或出现错误/断线，保留现场，只读检查后再决定，不重跑整块。
该入口准备时尚无实际完成回传；现在审计与冻结已完成，勿重跑。

本地准备验证通过：候选十二 SHA 不变，包装与远端块 bash -n，通过 16 个
实际 jq 摘要/管道场景（包括合法 audit/freeze、错误字段、空/多文档、stdout
噪声、生产进程返回 2 却输出合法 JSON），模拟 SSH 255 也准确传递并停止。
测试脚本 Ruff 通过；没有实际 SSH、生产审计、文件系统验证或冻结。
日志：2026-09-09-diagnostic-v8-audit-freeze-local-check.log。

## 此前回传：v8 新根创建、staging 上传完成

用户回传创建预检 PASS，旧证据七个 SHA 一致、两类相关队列为空；新根下
tools、.upload-staging、logs、state、attempts、submitted_runners 六个目录
均为 700，REMOTE_DIAG_V8_ROOT_CREATED=PASS。本地十二候选 SHA 前后重验
OK，四个生产文件 scp 100%，DIAG_V8_UPLOAD_TO_STAGING=PASS、UPLOAD_RC=0。

当前仅创建与暂存上传完成，尚无远端 staging 的四文件 SHA 或正式 tools 发布
回传；不能再次执行 create-upload。下一项是远端严格核验后 create-once 发布，
确认四个 tools 文件后仅清理本次 staging 入口，不修改旧 v7 或原评估 v4。
仍无 v8 freeze、check-only、提交回执或 Job ID。

## 此前操作：核验并发布 tools（已回传完成，勿重跑）

已准备 `2026-09-09-diagnostic-v8-publish.sh`，仅在 Mac 执行：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-publish.sh
```

首先核验本地十二候选 SHA；远端检查 root/六子目录为本人所有、非符号链接、
700，根的条目严格符合预期，tools/logs/state/attempts/submitted_runners 均空，
相关队列为空。staging 必须恰好四个已固定 SHA 的普通文件，归属正确、单链接，
tools 四个目标必须不存在。

预检全部通过后以 `ln -T` 创建四个 tools 入口，不覆盖既有目标；设权限 600，
复验 SHA、stage/tools 同 inode、链接数为 2。全部通过才 unlink 四个已验证的
staging 入口并 rmdir 空暂存目录；原数据保留在 tools。最后复验单链接/600
并打印布局、REMOTE_DIAG_V8_TOOLS_PUBLISHED=PASS、PUBLISH_RC=0。

只清理本次已核实的暂存入口，不动 v7/v4、模型、输入或旧证据；不 freeze、
不提交。失败后保留部分现场，不删除、不覆盖、不重跑脚本，先回传输出。
本轮只是脚本准备，尚未收到远端发布或清理完成的回传。

本地验证：候选十二 SHA 重新通过，包装/远端块 bash -n 通过，脚本四个生产
SHA/目标路径与固定候选一致。源码顺序检查及四种 shell 返回码替身测试通过，
测试脚本 Ruff 通过。该验证没有真实 SSH，未模拟远端文件系统/硬链接/权限。
日志：`2026-09-09-diagnostic-v8-publish-local-check.log`。候选文件保持不变。

## 此前回传：超算只读预检通过

用户已回传 REMOTE_DIAG_V8_PREFLIGHT=PASS、PREFLIGHT_RC=0。
七个旧证据固定 SHA 全 OK、OLD_V7_AND_V4_EVIDENCE=PASS；V4_QUEUE 和
DIAG_QUEUE 为空，脚本中的新 v8 根未占用检查也通过。

同 attn Python 实际回传：

```text
TORCH_VERSION=2.1.1+cu118
RUNTIME_VALUES=[true, true, false, "high", true, true]
RUNTIME_SIX_FLAGS=PASS
COLLECTION_API_VALUES={"deque_maxlen": 1000, "shape_dimensions": [1, 2, 3], "types": ["collections.deque", "torch.Size"]}
COLLECTION_API_PROBE=PASS
PROBE_SCOPE=API_ONLY_NO_V8_EVALUATOR_NO_MODEL_NO_GPU_INFERENCE
REMOTE_DIAG_V8_PREFLIGHT=PASS
PREFLIGHT_RC=0
```

这是该次真实预检通过，不是 v8 诊断器/真实模型/GPU 运行通过。没有创建远端
v8 目录，没有上传、freeze 或新作业。下一项准备 Mac 创建新根并上传暂存区
脚本，执行前再次核对候选、旧 SHA、队列和新根未占用；暂不发布 tools。

## 此前操作：创建新根并上传 staging（已回传完成，勿重跑）

已准备 `2026-09-09-diagnostic-v8-create-upload.sh`。它在 Mac 重验 v8 十二
候选 SHA，通过 SSH 再验七个旧证据 SHA、目录归属、两类相关队列、新根
未占用；随后只创建新 v8 根及六个 700 子目录。再次核对本地候选后，scp
四个生产文件到 `.upload-staging/`；不拷贝 README/测试、不发布 tools、
不 freeze、不提交。创建及传输各需一次 SSH 认证，用户自行输入密码。

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-09-diagnostic-v8-create-upload.sh
```

预期 `REMOTE_DIAG_V8_ROOT_CREATED=PASS`、`DIAG_V8_UPLOAD_TO_STAGING=PASS`、
`UPLOAD_RC=0`。此成功仅代表传输完成，下一项仍须远端固定 SHA 核验后发布。
若断线或失败，保留部分目录/文件，不删除、不重跑整个脚本；先回传输出
进行只读检查。当前尚未收到这一步的实际执行回传。

本地候选十二 SHA 重验通过。包装脚本及远端块 bash -n 均通过，七个证据
哈希与已通过预检脚本完全一致；四种 shell 替身测试（错误本地系统、创建
失败、scp 失败、模拟暂存成功）通过，错误码和四文件/目的路径准确传递。
验证脚本 Ruff 通过。测试不调用真实 ssh/scp，也未创建真实远端目录。
见 `2026-09-09-diagnostic-v8-upload-local-check.log`；未修改 v8 候选文件。

## 初始准备范围（历史）

本阶段准备 Mac 单文件只读远端预检，先重验本地十二文件候选 SHA；
不创建远端目录、不上传工具文件、不 freeze、不提交或重新提交作业。
尚未收到远端预检输出，不得把“脚本已准备”记为“集群已通过”。

预检对象为 HAKUSAN s2510040：原评估 v4 manifest/lock/evaluator/runner，
诊断 v7 Job 680519 的 freeze、失败终态与日志固定 SHA，相关队列为空，
预定 v8 根不存在。已有目录/文件均只读核对，不删除或覆盖。

在同一个 attn Python 中运行短进程，严格要求 torch 2.1.1+cu118，检查原配置
顺序最终读回的六项标志，以及精确 deque 的迭代/maxlen/身份和 torch.Size
维度读取、静态类型元数据。这是 API 兼容探针，不导入 v8 诊断器，不加载
checkpoint/完整模型/音频，也不申请 GPU；不能当作 v8 端到端成功或 NLL 解释。
运行标志只在这个短进程中设置，进程退出后不影响其他作业。

## 已固定身份

- 本地候选：same_bank_eval_2026_09_03_v4_numeric_diag_v8。
- 候选清单：.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-candidate-manifest.sha256。
- 预定新根：/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v8。
- 原 v4 manifest SHA：1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5。
- 原 v4 lock SHA：63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710。
- 旧 v7 freeze SHA：6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920。
- Job 680519 失败记录 SHA：2ecd6af2807d9315b4c5d1938188f0d0bf59e40fa544cee9132e7cfbffa57628。
- Job 680519 日志 SHA：92ad39871c7d20b36405bc78464a351c6842bbb5b220df99213337cd51f1dd92。

## 用户操作入口（Mac）

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence"
bash 2026-09-09-diagnostic-v8-remote-preflight.sh
```

只在 Mac 的 `(base) gigi@...` 提示符运行；脚本自身建立 SSH，密码由用户在
终端输入。完成后回传输出；即使退出 0，也仅代表当次预检通过，没有部署。
若失败，保留输出后定位，不改哈希、不删除已有根、不跳过队列检查。

通过预检后的下一项才是受控创建独立 v8 根并上传到 staging。
现在没有 v8 freeze SHA、提交回执或 Job ID；不得复用 v7 的 freeze 或提交脚本。

## 本地准备验收

本轮 v8 十二文件候选清单重验全部 OK，未更改任何候选文件。
Mac 包装脚本及其远端 Bash 块分别通过 bash -n，内嵌 Python 通过 AST/编译检查。
在本地 torch 2.12.1 上单独执行集合 API 原语通过，版本门禁正确拒绝将本地
版本当作生产 2.1.1；本地测试没有执行运行设置变更。
只用 shell 函数替身模拟 SSH 失败码 63，确认整体保留 63，不输出远端 PASS；
错误的本地操作系统也会在 SSH 前停止。实际 ssh 程序未被这些测试调用。
检查脚本自身 Ruff check/format 通过。

日志：2026-09-09-diagnostic-v8-preflight-local-check.log。
这些验证只证明本地语法与有限控制流；尚无真实超算预检输出。
