# 低α扫描v3：提交并发检查修正与交接

最新续接（22:44 JST）：用户回复“不需要我批准 我希望你直接推进到第4步”后，第5节1–4已执行：v3上传与原生预检通过；作业756262单次held提交→站点h100-20c改写→唯一一次A100修正→放行前重新并发审阅→唯一一次放行，22:44:01在spcc-a100g04运行。运行中不等于验收。见[v3远端台账](release_fine_alpha_20260928_candidate_v3/REMOTE_PROGRESS.md)。下文“未上传/未授权”指本文成文时点。

日期：2026-09-28。用户对“修正提交器的过宽并发拦截、重新冻结，再申请GPU预算”回复“haod”。本轮只完成本地修正、测试和新候选冻结，不扩大为上传、SSH查询、GPU预算、提交或放行授权。

## 1. 当前结论

**`FINE_ALPHA_LOCAL_CANDIDATE_VERIFIED_NOT_GPU_AUTHORIZED`。** 497项全目录回归通过，六个历史冻结包的214个清单文件前后哈希一致。v3已在本地生成，未上传、未执行原生检查、未获得新GPU作业号，也没有新科学结果。

- [v3交付说明](release_fine_alpha_20260928_candidate_v3/LOCAL_ACCEPTANCE.md)
- [机器可读验收](release_fine_alpha_20260928_candidate_v3/LOCAL_ACCEPTANCE.json)，SHA `b35dd562ebfcf1704b25cfa83df33bea73aa8e51b9b1a7492613b1d94dd41f9d`
- release SHA：`1644b8bd3e9eea855476f123e904707f82c9d1465f4345f43432c847893e87d7`
- 新远端目标（尚未创建）：`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v3/package`

## 2. 修正依据

v2已完成上传及原生源码导入预检，但其冻结提交器仍以“队列中任何名称含audattn”作为拒绝条件；它不判断两个任务是否相互独立，而且先创建单次使用的state目录，再发现队列冲突。

上传器的检查已在此前单独修正，不代表包内提交器同步改变。本轮保留v1/v2和全部失败/成功证据，以新版本修正提交器，不编辑已发布的v2。

## 3. 新规则及边界

新模块[并发检查](fine_alpha_submission_queue.py)采用`EXPLICIT_INDEPENDENT_JOB_REVIEW_V1`：

1. GPU审批记录必须含明确的`concurrency_review`。空队列可使用空jobs；正在排队的每一个其他作业，都须出现在已审阅记录中。
2. 审阅记录绑定作业编号、名称、账户、入口、工作目录、stdout/stderr路径、入口文件SHA以及Slurm已提交脚本的SHA，并明确确认输出独立、共享输入只读。它是审阅结论，不是靠路径自动推导的源码语义证明。
3. 实时squeue/scontrol读取必须成功；逐项匹配上述身份、检查目录重叠和符号链接、核验入口与已提交脚本。`scontrol write batch_script JOB -`仅回读到stdout，不写远端脚本文件。
4. 同一fine-alpha扫描（包括旧版本）、伪装名称但仍使用fine-alpha runner、未知作业、字段/哈希变化、目录冲突、查询失败均停止。没有通用“跳过检查”开关。
5. 不把两个作业写成账户额度，也不凭还有一个名额批准运行。`scheduler_quota_verified=false`；Slurm资源限制和单独预算审批仍适用，允许提交不保证立即获配资源。

提交器先进行只读队列核查，失败时不创建state、不调用test-only/held。初始证据写到stdout，必须由外层驱动保存；没有自动重试。通过后独占创建state，保留审批和初始检查，执行test-only，然后再次检查队列和审批身份，通过才写INTENT并调用一次`sbatch --hold`。

最终队列证据为`QUEUE_FINAL.json`，其SHA写入INTENT，进而由提交回执绑定。原有单次提交、未知响应停止、资源类型不符停止、不自动修正GRES、不自动放行等行为保留。

两次队列检查不是全局队列锁，不能排除第二次检查之后由其他入口提交新作业。因此作业仍以held提交，放行前还必须重新核查资源与并发状态。不能仅凭历史754073记录填入允许列表；下一轮需取得新的实际回读和完整审阅。

## 4. 测试与包差异

- 本轮新增23项队列/并发集成回归；针对性32项通过。
- 全目录497项通过，unittest报告64.318秒；[完整日志](release_fine_alpha_20260928_candidate_v3/regression.log)。所有调度调用均为测试替身，不是真实作业。
- 覆盖独立audattn作业通过、同扫描/路径冲突拒绝、未知/新增作业停止、元数据或源脚本/spool变化、符号链接、查询失败、缺少审批、审批中途变化、第二次核查出现冲突、严格单次held及不放行。
- [隔离包check](release_fine_alpha_20260928_candidate_v3/package-check.log)与runner语法检查通过。
- [旧包前核验](release_fine_alpha_20260928_candidate_v3/LEGACY_BEFORE.json)与[后核验](release_fine_alpha_20260928_candidate_v3/LEGACY_AFTER.json)一致，共214个清单文件，另记录各包RELEASE身份。

新包41个清单文件，加RELEASE共42个文件。相较v2，新增`fine_alpha_submission_queue.py`，修改`fine_alpha_submit_once.py`、`fine_alpha_entry.py`、`fine_alpha_contract.py`及生成的runner。执行/归档/增益/加载/输入等其他文件保持原字节。

科学合同仅scope从V2改为V3；54个α、formal40权重、E1输入与批布局、194,400条科学预测/219,600条总预测、六条件、历史桥接和精度设置不变。候选预算仍为1 A100、8CPU、64GiB、最多6小时；这是候选上限，不是本轮已获授权的GPU额度。

## 5. 下一执行批次

1. 获准后准备并执行绑定v3 release的新发布入口：独立目录上传42文件，哈希/整包核验及原生只读导入检查。v2预检不替代v3验收。
2. 只读取得当时队列、并发候选作业的元数据和源脚本/spool身份，审阅共享输入及输出范围；形成明确的并发审阅记录。若作业已结束，按实际空队列处理，不假定754073仍在运行。
3. 再申请本版本最多6 GPU小时、单次held提交。新的外层提交/回执收集入口须绑定v3并收集`QUEUE_INITIAL.json`、`QUEUE_FINAL.json`；不得复用绑定v1的旧提交脚本或伪造空队列。
4. 提交后回读资源；如发生站点typed GRES改写，保持held，单独授权同作业唯一一次修正。正式放行须另批，并重新核查并发状态；没有自动重投或扩预算。
5. 运行结束后完整归档、独立离线验收、全54点读数。工程候选通过不等于扫描完成，也不等于α已映射儿童年龄。

本轮没有创建真实GPU审批文件、连接超算或修改任何远端作业。
