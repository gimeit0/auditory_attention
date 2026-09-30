# V4 numerical diagnostic execution record

## 最新验收：v14真实CPU指纹预算拒绝，未部署（2026-09-10）

645本地全PASS；实际加载/唯一原模块恢复/状态/scene3及model9图通过，但完整
执行指纹work600001触发原600000预算。独立新进程复验排除合成tracing干扰。
未改预算、模型或容差；写远端脚本已显式阻断，实际v14root不存在、队列空。
七个原v4/v13绑定SHA复验PASS，无新作业。当前统计重复校验开销，后续工程
优化若超出已批两项须另行批准。详见[v14门禁记录](2026-09-10-diagnostic-v14-remote-deployment.md)。

## 最新：v14获批修复，本地645项通过（2026-09-10）

固定PATH明确追加系统sbin；严格加载之后、签发模型图/状态之前恢复唯一
已核验且缺失的模块原对象。旧loader及封存后检测不动，645项本地全PASS，
AST范围和四项故障注入PASS；实际完整formal40 CPU检查进行中，无新提交。
详见[v14记录](2026-09-10-diagnostic-v14-runtime-import-repair.md)。
下方“待批准”及之前连接状态均为历史记录，不代表当前阶段。

## 最新：同版本最小探针复现两项工程问题（2026-09-10）

共享连接已恢复，五份Job683154核心证据SHA全部通过。实际Triton在固定PATH
下找不到ldconfig（errno2），系统绝对路径只读查询成功；跨模块CPU tracing
中，清理构造时模块会重新导入并触发sealed绑定拒绝，保留模块时通过。
未使用正式模型/GPU，不能等同原NLL根因或完整模型验证。原v4四SHA保持，
无新提交。固定PATH及封存前依赖生命周期修复方案记录完毕，等待明确批准。
见[最新诊断与修复边界](2026-09-10-job683154-compiler-path-import-diagnosis.md)。

## 最新：v13 Job683154终态失败，已整理底层证据（2026-09-10）

实际GPU运行3分14秒FAILED2:0；验收matrix=null、post_errors=[]、数值不可解释。
编译器inner_exception=FileNotFoundError，并检测到4个新增受保护模块。
最新原始freeze/failure/log三份本地SHA复验通过；PRE/POST仍待补充下载。
目前共享SSH已失效、自动认证255。没有新作业、生产修复或v14；恢复连接后
先做固定PATH的缺失工具最小检查及导入生命周期复现，不放宽原门禁。
具体事实/推断边界见[Job683154诊断记录](2026-09-10-job683154-compiler-path-import-diagnosis.md)。

以下保留此前执行过程；其中“当前”均对应当时记录时间。

## 当前：v13仅补失败元数据，实际CPU通过后独立部署（2026-09-10）

v12实际GPU失败的有界日志遗漏PyTorch.inner_exception；六种同版本8元素CPU
编译/故意失败小测试没有复现正式模块变化，不能据此豁免检查。v13只补有限
内部异常及模块delta，原拒绝/撤销/科学函数AST不变；旧612加17项共629通过。
真实torch2.1.1/formal40完整CPU准备和新增日志探针PASS；随后独立发布四文件
SHA全部通过，audit-inputs=PASS，当前freezing中；没有新的GPU结果。
详见[v13部署记录](2026-09-10-diagnostic-v13-remote-deployment.md)。

## 当前：v12 Job683076失败，已保存原始证据（2026-09-10）

作业在spcc-a100g05运行3分18秒后FAILED2:0；verify-results认证失败记录，
没有可解释矩阵。三个恢复环境值已在启动记录中确认，PRE/POST一致。
有限异常链记录BackendCompilerFailed及随后冻结模块绑定变化检查失败；
不能据此判定模型数值或具体编译根因。五份原始证据已下载并固定SHA验证。
正在只读定位，不重提、不修改已发布v12或原v4。以下是此前部署过程记录。

续记：audit/freeze/check-only已全部通过，新freeze为
6cd0407c8f48709e37fa9f0b6cdddcc6cbc5425b740b405c806c8a010eee9031。
单次Job683076提交成功，实际状态RUNNING/A100g05，自13:56:12开始；
仍等待完整产物和终态验收，不等同于诊断完成或三模型结果。

此前版本详细记录分散在逐版本证据文档。当前权威进展入口为
[v12运行配置修复](2026-09-10-diagnostic-v12-runtime-repair.md)和
[v12部署与结果](2026-09-10-diagnostic-v12-remote-deployment.md)，保留所有旧记录。

用户批准后新建v12，恢复原runner三个固定环境字面值并增加有限异常链日志。
原594回归断言不改、新增18，共612通过；六种退化检查均捕获。新清单SHA
afb0549063938ecc853c8110b4b4a211357624dfb20fc46dd9da0d1630e5a31b。
同版本正式formal40 CPU严格加载61键、完整60状态、scene3/model9、重复指纹/
RNG以及24pinned/96snapshot前后复验全部通过。探针exit0，不是GPU结果。
旧v11/v4七个SHA再次通过，独立create-upload/publish实际exit0，audit已PASS。
当前freeze生成中，没有新Job ID；完整对比试验及原NLL来源仍未解决。

## 最新实验进展：可变模块表策略原型（2026-09-08）

已实现独立进程内的本地实验原型 candidate_policy.py，真实冻结 evaluator
上 7 个断言通过（正常清理/导入不误报、模块/函数替换仍产生差异）。
没有修改 v3 或发布新生产版本。保护前缀仍为实验配置，合法冻结作用域切换、
新增依赖绑定和完整模型生命周期未覆盖，因此不可部署。
详情：`local_tests/v3_real_evaluator_probe/README.md`。

## 最新：v3 远端失败与真实 evaluator 本地定位（2026-09-08）

用户反馈 v3 audit 退出 2：production evaluator differs from verified loader。
未执行后续 freeze 或 job 提交。此前发布前自查仅证明有限夹具通过，不能
覆盖真实 evaluator 的可变模块依赖。

本轮用 SHA 匹配的真实 v4 evaluator 加载，立即重算依赖图即发现
_frozen_import_context 和 strict_load_model 图不一致，而函数 anchors 全部
一致。记录可达 sys.modules；加载器 finally 删除其临时模块使记录立即改变，
pandas 导入进一步改变模块表。此问题无需模型推理即可复现。未修改生产包。
报告：`local_tests/v3_real_evaluator_probe/README.md`。
下一步设计并测试可变导入状态与代码身份的分离校验；禁止直接放宽 graph
比较或声称 v3 已可用于正式诊断。

## 最新复查 checkpoint（2026-09-08）

v3 主代理发布前自查完成：有界修复未发现阻塞问题，新增专项 6/6 和文件/
隔离导入 17/17 重跑通过，v3 八文件及 v2 七文件哈希匹配，静态检查通过。
这是主代理自查，不是独立复查；候选未改、未上传、未冻结、未提交。
下一步为远端新 v3 根只读预检。详见
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v3-prepublication-review.md`。

## 最新补充：v2 生产加载记录回归与本地修复启动（2026-09-08）

用户提供的远端记录确认：诊断 v2 四个工具发布并校验成功，但 audit-inputs
报 `production capability requires exact verified loader objects`，退出码 2；
该命令块未进入 freeze，也没有提交新的 GPU 诊断作业。

本地独立回归已复现同一错误：2 项中 1 项通过、1 项 ERROR（RED）。真实
加载器的记录为 `locked_same_bank_eval.py`，外层记录为
`tools/locked_same_bank_eval.py`；两份记录其余字段完全相同。夹具使用临时
最小 evaluator，不代表真实 checkpoint/GPU 端到端测试。详见
`local_tests/v2_loader_record_regression/README.md`。

用户已同意先记录再执行本地修复。计划：保持已发布 v2 七文件不变，创建
独立 v3 本地候选；统一外层与加载器的相对路径基准，保留严格记录比较和
篡改拒绝；补回归、运行全套测试。当前不授权自动远端部署、冻结或提交。
修复结果以下续记为准，不能把修复启动写成验收完成。

本轮续记：v3 本地候选已统一 allowed_root，保持 exact record/hash/path
校验。独立进程数值套件 344/344（97.381s），提交套件 66/66（10.594s），
专项 6/6（0.318s），合计 416 项。合并 discover 的模块名称冲突失败也已记录，
不声称合并运行通过。Ruff、Bash 语法与八文件候选哈希通过；v2 七文件哈希
保持不变。尚未独立复查或远端部署，仍无新的 GPU 诊断或最终比较结果。
详情：`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v3-loader-root-repair.md`。

## 当前状态（2026-09-08）

全量训练已经完成 40 轮并有恢复发布证据。后续 same-bank 评估尚未通过
smoke：v4 Job646900 在比较 batch size 16 与 1 的两轮输出时报告
`formal40_nll max_abs=0.0077362060546875`，尚无本轮三模型完整 10k audit 的
成功结果或独立测试结论。早期 Job584990 的 10k pilot 结果存在，但不是本轮
最终模型与作者 checkpoint 的比较结果。

目前实施的是已批准的独立数值诊断设计，限定 formal40、同一 32 条 smoke
trial，以及 A1/A2/B1/B2 四种重复推理组合。任务 1–4 已通过各自的本地复审；
任务 4 第五轮的独立审查限定为源码／CPU 行为，不代表真实 A100 通过。
任务 5a 已实现差异分类与正式输出无损编码；任务 5b 已从保存层基础推进到
两轮结果的完整 reference/cell 文件发布、证据重验、worst trial 选择及完成
标记最后写入。现有 Task 4 的 CPU reference／trace 两轮原始结果已直接接通。
随后任务 5c 已接通单次使用的 reference/cell worker 函数、隔离缓存和 scratch、
单模型两轮执行及保存前后输入复核；该阶段全套 226/226 通过。
任务 6a 接通固定子进程启动、独立写入环境、有界回执与超时／中断清理，
该阶段新增 25 项测试，全套 251/251 通过，隔离只读快照复测同样通过。
本次任务 6b 已把父进程回执与重新读取的两轮工件绑定，并接通持久结果的
reference/A2 等价核验、固定五进程顺序、四格汇总和只读重验。新增 24 项
测试，专项 124/124、全套 275/275 通过；精确 SHA 的隔离临时副本同样
275/275 通过（65.450 秒）。真实 GPU 矩阵仍未执行。
任务 6c 随后接通外层 owner 的提交回执等待／认证、spool 归档、持续共享锁、
全部冻结输入 PRE/POST、INT／TERM／HUP 处理和唯一终态写入内核。32 项专项
及全套 307/307 通过；真实子进程测试确认 TERM 后先回收进程再做 POST。
相同源码的独立临时副本也复测 307/307 通过（65.613 秒），不等于独立代码复审。
任务 6d 已补齐终态 attempt 文件清单、写完成标记前的工件重验，以及只读
`verify-results` 入口：重新验证 journal／归档 runner、PRE/POST、五个冷进程
的持久工件和四格矩阵，不调用 Slurm 或推理。专项 48/48、全套 323/323 通过。
任务 6e 随后接通生产执行 CLI／父子启动授权接线：冷解释器、实际 argv、
独立缓存、环境白名单，以及 Linux 父进程与提交／owner 记录的身份绑定。
新增 15 项测试；专项 38/38、全套 338/338 通过，尚未在真实 HAKUSAN 执行。
任务 7 新增 Slurm runner 本地候选，专项 18/18 与既有回归 338/338 通过。
任务 8a 已实现耐久提交记录层，专项 19/19、runner+记录层 37/37 通过。
任务 8b 随后接通固定调度器、确认式单次提交、只读状态查询和 CLI：专项
25/25、提交工具全套 62/62、数值核心回归 338/338 通过。
任务 5–8b 尚未取得新的独立审查／发布验收；完整模拟提交到五子进程的集成、
操作 README、整包发布和 A100 执行仍待完成，不能直接拿当前代码提交。
本次续作没有访问 HAKUSAN 或提交新作业。

批准设计 SHA-256（本次重新核验一致）：
`9508225bc6f1aa463423f3c50528c888a7b2450dde2f0997e6edaea8acf3ec15`。

主实验记录：
[40轮训练与same-bank评估记录](../../../2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md)。
开发账本：
[完整进度](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/progress.md)。

## 与最终模型比较的关系（2026-09-06 文档补记）

最终任务仍是同一冻结 bank 上的 `formal40`（主结果）、`valbest33`（验证集
选择的补充结果）和作者 checkpoint（外部系统参考）比较。当前诊断只限定
`formal40` 和同一 32 条 smoke trial，用来定位 batch-size 数值分歧，不是
新增训练，也不产生正式三模型排名。

当前处于“训练已完成，正式比较前的评估程序排错／验收”阶段。下一步先
完成诊断工具的受控调度、提交与发布验收，之后才能运行 A100 诊断。根据
诊断证据处理分歧并通过 smoke 后，才进入完整 10k 比较。226 项通过是此前
记录的本地代码测试，不是 226 次模型评估；GPU 根因仍未确认。

主实验记录文首现已补入面向读者的阶段总览，并把过时摘要标注为历史快照。
该次文档补记仅整理本地说明，没有改代码、访问 HAKUSAN、提交作业或同步项目镜像；
随后获授权的实现进展另见任务 6a／6b 记录，不以这段历史补记描述当前代码状态。

## Task 2–3 补记

任务 2 完成张量、状态、随机数和文件清单记录，以及有界数值比较。最终专项
23/23、全套 34/34 通过；本地不具备 CUDA，GPU 行为保留到后续集成验证。
任务 3 完成冻结输入合同、按 SHA 校验的源码加载、原始 trial 身份绑定和只读
audit/freeze/check 接口。最终专项 26/26、全套 60/60 通过，复审没有未关闭的
Critical/Important 问题。完整 RED/GREEN 过程与各次修复的 hash 均保留在开发账本。

## Task 4 本次续作（2026-09-06）

本任务负责复现冻结推理顺序和保护输入、模型及结果身份。新增 7 个测试方法，
在修改生产代码前实际运行了完整专项：69 个测试、25 个失败、0 个错误；
[RED原始日志](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-4-fix5-red.log)
及修改前快照均已保存。

修复包含：有界调用图遍历、静态属性读取、普通音频列表内子模块的完整检查、
校验记录防伪与失败后撤销、直接读取模型注册状态，以及加载完成到首次推理
之间的内容和存储身份校验。状态摘要只在加载/推理轮次边界生成；批内的冻结
运算顺序及 `1e-6` 判定阈值未改变。

最终工作目录全套测试 129/129 通过，3 个 Python 文件 AST 解析通过，包内无
`__pycache__` 或 `.pyc`。测试使用
`/opt/anaconda3/envs/audattn/bin/python -I -B`，并设置
`PYTHONNOUSERSITE=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONHASHSEED=0`。
执行目标为 `test_numeric_diag.py`；专项另加
`PredictionPathTests ReferenceEquivalenceTests`。

```text
diagnose_batch_invariance.py  099cbd6235c56c9bcde7b44dcdc90c0fc08ab44357234c6709f6a8c0763d9406
test_numeric_diag.py          8dd2a110b393a6e66a05a3203c90eaac7a34a1d016f981e65186c79be1ceb844
numeric_trace.py              b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3
```

[完整修复报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-4-report.md)
记录了中间失败、测试修正和验证范围。
[最终测试日志](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-4-fix5-full-final.log)
对应上述工作目录版本。
[待复审清单](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-4-review-findings.md)
仍明确标记为 pending。只读最终快照包含测试依赖的精确 v4 evaluator，避免
旧快照缺少参考文件而无法独立运行的问题。

这些测试证明本地诊断代码的已测行为，尚未定位真实 GPU 数值分歧；不能据此
宣布 smoke 通过、模型性能评估完成或数值根因已确认。

最终只读快照的独立临时副本也实际运行了全套测试：129/129 通过（38.515 秒），
运行后三个源码 SHA 与上表完全一致。
[快照复现日志](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-4-fix5-final-snapshot.log)。
这里的“独立临时副本”指执行目录隔离，不代表已完成独立人员或代理的代码复审。

## Task 4 独立复审结论（2026-09-06）

用户同意启用一名只读审查代理后，
`/root/task4_fix5_independent_review` 独立核对了三个源码、diff 及真实 v4
参考文件的 SHA，并从隔离副本运行专项 69/69（7.979 秒）通过。
在九项修复的审查范围内，没有证实仍存在的 Critical／Important 阻塞项，
结论为本地源码／CPU 局部通过。最后一个未返回结果的补充探针不计作证据。
真实模型的遍历规模、CUDA 非扰动性与冷启动等价仍须后续集成验证。

## Task 5a：差异分类与无损输出编码（2026-09-06）

本次完成的是任务 5 的可单独验证子阶段，不是整个任务 5 或诊断包验收：

- 区分逐位一致、有限 `DIFF` 和证据 `INVALID`。另行保留 v4-compatible
  `canary_status`，其阈值仍为 `1e-6`；小于阈值的边界差异不会消失。
- 按 trial ID 对齐两轮结果，检查原 bank 行号、模型／runtime 身份、各批次
  mutation guard，以及 before／between／after 的状态连续性。
- 固定 A2 的三种分类和首个分歧边界；若 cochleagram 一致而 logits 不同，
  只返回需要定向追踪的建议，不安装 hooks 或生成根因结论。
- 非有限位置记录最多 128 条，并在调用有限数值比较器前限制位置枚举。
- 正式输出使用固定 32 条、类型／长度／SHA 绑定的十六进制字节编码；
  保留 dtype、字节序、负零及相邻浮点值。没有用 CSV 四舍五入值做等价判定。
- 一项集成测试真实调用已有 Task 4 CPU 推理路径完成两个 pass，直接把其
  原始记录交给比较器，不重写或重签结果；该测试不是 A100 模型实验。

本次执行均使用项目 Python `-I -B` 及此前记录的三个隔离环境变量。
命令目标与原始日志：

| 阶段 | `test_numeric_diag.py` 后的目标 | 结果 | 日志（开发账本目录内） |
|---|---|---|---|
| 比较器初始 RED | `CellSemanticsTests` | 14 tests，24 个展开错误；仅缺少接口 | `task-5a-red.log` |
| 补充合同 RED | `CellSemanticsTests` | 16 tests，5 failures | `task-5a-contract-red.log` |
| 编码器 RED | `ArtifactContractTests` | 4 tests，9 个展开错误；缺少接口 | `task-5a-codec-red.log` |
| 损坏边界 RED | `CellSemanticsTests.test_non_tensor_boundary_schema_returns_invalid_instead_of_crashing` | 1 test，1 AttributeError | `task-5a-schema-red.log` |
| 最终专项 | `CellSemanticsTests ArtifactContractTests` | 22/22，3.355 秒 | `task-5a-focused-v2.log` |
| 最终全套 | 无额外目标 | 151/151，10.963 秒 | `task-5a-full-v2.log` |

中间编码器测试发现应在构造任何 NumPy 结果前校验完全部四个字段，修复后
重新验证通过；失败记录保留为 `task-5a-full-candidate-failure.log`，没有被
最终通过日志覆盖。三个 Python 文件 AST 通过，包内无 `.pyc`／`__pycache__`。
最后补测还证明非张量边界会导致 AttributeError；修复为在访问 shape 前明确
验证张量类型，使损坏记录返回 `INVALID`。此前 150 测试版本及其隔离副本
150/150（10.852 秒）的记录也保留，未用它冒充最终 151 测试版本的证据。

```text
4cb88bcdaa7dcd909c279068f5f07761609fba9674ecddeafbfd91e12fda56d6 diagnose_batch_invariance.py
5c65dd51e0970e13487c044800a0b05d9a85ad129d57d457c2c4486a838b4ed1 test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py
```

只读源码快照：`snapshots/task-5a-final/`（含真实 v4 sibling fixture）。
相对 Task 4 通过版本的 diff：`task-5a-final-review.diff`，SHA 为
`22489f8f28bc673cab58a076c0e48ad4d0a6fb0ef110efe63010427d6809d7c5`。
完整开发说明见
[Task 5a报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-5a-report.md)。

下一实现阶段是 Task 5b：NPY／JSON／CSV 的不可覆盖发布、worst-case 全局
1 GiB 预算、完整 reference/cell 工件验证、两轮 worker 入口。没有重新提交
v4 smoke，没有改动冻结 v4，也没有向项目仓库的“全量任务”镜像目录执行同步。

## Task 5b 保存层基础（2026-09-06续作）

本次是保存层基础的本地实现，不是完整任务 5b 验收：

- 从固定 attempt 目录逐级持有文件描述符，拒绝根／祖先／子目录符号链接；
  在操作中重新核验目录身份，避免路径被替换后向别处写入。
- NPY 固定使用 v1.0、C-order、非 pickle 格式，保留数值 dtype、字节序及
  负零；拒绝 object、结构体、复数等未允许类型，logits 限定 `[32,800]`。
- 先写同目录独占临时文件、fsync，再用不覆盖目标的 hard-link 发布，移除
  自己的临时名字后进行流式 SHA 校验。已有或抢先出现的目标不会被覆盖；
  同字节但不同文件身份的发布中替换也会报错，不把它当作自己的成功写入。
- 持久文件校验以路径、普通文件类型、0600 权限、size 和 SHA 为准；设备号、
  inode、mtime 只用于单次操作的竞态保护及跨节点诊断。文件必须只有一个链接。
- 通用清单校验拒绝缺失／多余文件、多出的空目录、链接与内容损坏，并在遍历
  结束再次检查文件和目录。完整 reference/cell 语义校验器仍未接上。
- worst-case 写入前计算完整三件组投影和四个 cell 已有文件合计，包含 NPY
  头部。硬上限仍是 1,073,741,824 bytes，恰好等于上限允许；单文件入口不能
  绕过整体预算。此层依赖后续协调器的独占、串行写入合同，不声称已实现分布式锁。

测试与源码快照详见
[保存层开发报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-5b-storage-report.md)。
初始 RED：40 tests、24 个展开错误（新增接口缺失）；补充 RED：24 tests、
3 failures，分别证实预算绕过、祖先 fd 异常清理遗漏、FIFO 替换可能阻塞。
修复后全套 175/175（11.544 秒）通过；只读快照的独立临时副本全套
175/175（11.669 秒）通过。三个 Python 文件 AST 通过，无包内 bytecode 缓存。
独立目录复测不等于新的独立代理／人员复审，本次没有启用审查子代理。

```text
28a0685adf658aa383e2b6d0b3b350f56bb41cac9f4c0be57447ad554c3c0f43 diagnose_batch_invariance.py
43608730aa61604d161fb5a3a7543ec93d313262d1ebae30694650ad00427bab test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py
```

只读快照 `snapshots/task-5b-storage-final/` 包含三个源码和真实 v4 参考文件。
相对 Task 5a 的 diff 为 `task-5b-storage-review.diff`，SHA：
`a2ee2b638c4864bd1a2ebcb449f84e1a239d89898d576f8708d3a03e03f07a6f`。
下一部分将把两轮推理证据接入这些基础接口：固定完整文件清单、原始输出和
commitment 无损持久化、选定 worst trial、完成标记最后发布以及 worker 串接。
没有改冻结 v4，没有访问 HAKUSAN／提交作业，也没有同步项目仓库镜像。

## Task 5b 完整子结果文件（2026-09-06再续作）

新增 `encode_pass_evidence`／`decode_pass_evidence` 保存并重验原有完整 pass
commitment，以及四个正式输出的原始字节。原始音频／cue 保存逐 trial digest，
不会从 hash 伪造张量，也不通过 CSV 舍入值还原等价结果。

`write_reference_artifacts`、`write_cell_artifacts` 与对应只读 verifier 已接上
既有保存层：固定输入、两轮 runtime／来源、三个 state/RNG 时间点、CSV；
cell 还保存边界记录、两轮完整 logits、worst-case 三件组及比较结果。reference
的完成标记不含 cell／canary／A2 数值状态。cell 则保留 PASS、有限 DIFF 和
可完整记录的 INVALID 之区别；状态／RNG 不连续时保留两侧观测，不丢失证据。

完成标记在全部载荷校验后最后写入，其内部清单排除自己；标记的 size/SHA
记录单独返回，供后续协调器绑定。只看到一个 COMPLETE 文件并不构成成功
验收，仍须对应子进程成功退出和完整重验；原子 link 之后的 I/O／竞态失败
可能留下文件，协调器不得把这种未取得成功回执的残留当作成功结果。

worst-case 按固定 trial ordinal 对齐，scene／cue cochleagram 三件组必存；
需要定向 logits 追踪时追加 logits 三件组。重验检查其原始 tensor digest、
float64 的 pass2−pass1 差值，以及有限情况下是否达到已报告的边界最大值。
canary 和 A2 分类从无损正式输出重新计算，而不是只信任状态文字。完整
cochleagram 未全部持久化，因而全量中间差值分布／分位数仍是 commitment
绑定的工作进程观测，不声称可仅凭 hash 独立重算；跨进程来源认证留给任务 6。

本次补充 RED 发现并修复了同次操作中相同内容的 marker／payload 替换、
伪造 canary 摘要以及保存的 trial 未达到报告最大差异仍被接受等问题。
最终专项 **69/69**（16.583 秒）、全套 **198/198**（24.259 秒）、只读快照
独立目录复测 **198/198**（24.581 秒）通过。AST 3/3，通过后无包内 bytecode。
这仍是本地 CPU 验证，不是新的独立代理复审或 A100 科学结果。

```text
9e3ef300bc99ac9d7f292965ebbbcc5710bbe1345421c31247a6c3b4807af6ac diagnose_batch_invariance.py
278323aa6c7470bf03cbda10dffeabb24a95bd8bde12313b8490a5e17816c6da test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py
```

只读快照 `snapshots/task-5b-child-final/`，diff `task-5b-child-review.diff` 的 SHA：
`072c5560000e97cd19bcf1986600874dc13709ea2d8c2e0b74b2bec1bd372789`。
测试初始 fixture 错误、修正后的 RED、补充失败和最终通过日志全部保留，见
[子结果开发报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-5b-child-report.md)。
下一步是生产 worker 入口、node-local scratch 和独立进程生命周期串接，再
进入任务 6 的四组合协调与身份绑定；本次没有远端操作、提交或镜像同步。

## Task 5c worker 生命周期（2026-09-06续作）

已实现 `run_reference_cold(args)` 和 `run_cell(spec,args)` 的单次使用入口：
先检查 job／隔离解释器／源码位置，再验证 attempt 和独立 scratch 环境；
随后读取 SHA 绑定的冻结输入，保持 frozen import context 到两轮结果保存
及重验结束。只调用一次冻结 runtime configurator 和 strict formal40 loader，
两轮之间不重设 seed、不重载模型。reference 固定使用原始 predictor 的
16→1，cell 严格使用 A1/A2/B1/B2 中预定的 autocast 和 batch 顺序。

每个 worker 独占 scratch 子目录，检查 UID、0700、真实目录祖先、环境路径
及缓存实际为空。Linux mount 检查拒绝网络／未知文件系统和与保护目录同设备
的 scratch；最终 Slurm 临时目录来源及启动环境 allowlist 仍由任务 7 完成。
在每轮全部输出结束之后，将已捕获的 CPU cochleagram 写入 scratch NPY，
以原始 dtype 的 copy-on-write 映射继续比较，验证原 pass commitment 不变。
这些完整中间张量不进入持久结果清单，原 1 GiB worst-case 上限未变。

诊断 freeze 与当前输入的跨节点核对仅忽略文件记录里的 device／inode／mtime
诊断字段，仍严格比较路径、mode、size、SHA、trial 身份及其余科学合同。
同一 worker 运行前后则要求其完整本地基线不变。该适配仅用于新 worker；
此前 `check-only` 的整个 audit 精确比较行为没有在本次改动中重写，后续跨节点
预飞仍须单独验证。历史 scene hash 从 SHA 绑定的 Job584990 CSV 重读，检查
完整 0..9999 trial 集合及排序后的 hash vector，不能使用随意传入的字典。

专项 **97/97**（30.771 秒）、全套 **226/226**（37.620 秒）、只读快照独立
目录复测 **226/226**（36.582 秒）通过；AST 3/3 和限定静态检查通过。
宽一点的 F401 检查仍报告上一阶段 `_cpu_artifact_array` 中已有的未使用
NumPy import，本次没有将“限定静态检查通过”写成完整 Ruff release 通过。

```text
d21d08d310da74a2e1360afd1212b376e69c96cb789f02012f87a19c54933a94 diagnose_batch_invariance.py
4f07d4c6313429797c884e3e106ea47bdb71fafbf335d33fe0e1519965f8ae0b test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py
```

只读快照 `snapshots/task-5c-worker-final/`，diff SHA：
`0cb0f4944b1da6401b621144b45ad88efa7ac765e38a2094db133bb6d7583f20`。
完整回归失败、修复及限制见
[worker 开发报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-5c-worker-report.md)。

下一步进入任务 6 的受控进程启动、reference/A2 等价门禁、四组合协调与
身份绑定。本阶段没有启动该协调器，没有访问 HAKUSAN、提交作业、修改冻结
v4 或同步项目镜像；CPU fixture 通过不代表真实 formal40/A100 数值根因已确定。

## Task 6a：接通冷启动子进程和回执边界（2026-09-06）

本次继续实现完整调度器的一个有界部分：固定绝对路径与隔离 Python 参数，
为 reference 和四个 cell 构造互不共享的可写缓存环境；每次启动独立进程组，
不继承父进程输入或锁描述符。机器回执限长 16 KiB，要求单一规范 JSON；普通
日志由 stderr 承接。返回的 PID、job、freeze、角色和 marker 路径必须与本次
启动一致，非零退出即使带有完整回执也不能接受。

超时、中断和异常会清理该子进程组；同一 launcher 不重试同一角色。这里的
`CHILD_EXIT_VERIFIED` 仅表示退出与回执边界通过，不替代重新读取结果工件、
跨进程来源核验、reference 等价检查或科学成功标记。

初始 RED 为 18 项、1 failure 与 60 个展开的 subtest errors；实现后 18/18
通过。补充测试发现缓存路径检查只覆盖了 Conda 目录，没有覆盖整个账号主
目录；先取得 25 项、1 failure 的 RED，再修复为精确账号根检查。

最终专项 **122/122**（32.648 秒），全套 **251/251**（39.240 秒），只读快照
在独立临时目录复测 **251/251**（38.404 秒）。AST 3/3 与限定 Ruff 检查通过。
新增的 25 项是本地进程与协议测试，不是 GPU 诊断或模型准确率实验。

```text
fb93d3e7abd6f1bf8010c34103a473d1a84f9b34f6678bbfaa661716bbe6aec0 diagnose_batch_invariance.py
9123c70fc03fd4b30887e020b7439f95d6f289b8fa2232b56a51b044fb9ac16e test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py
```

完整日志、只读快照、review diff 与限制见
[子进程边界开发报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-6a-cold-child-report.md)。
完整协调器及生产 child CLI 尚未开放；后续仍需接入持久回执／工件绑定、
共享锁、固定运行顺序与参考等价、输入前后校验和唯一终态。本次未访问
HAKUSAN、未提交作业、未修改冻结 v4／模型／bank／阈值，也未同步项目镜像。

## Task 6b：父进程证据绑定与四格顺序集成（2026-09-06）

本阶段测试／说明收尾于 2026-09-07（JST）；没有追加远端执行。

对应完整计划 M1 内的调度器收尾，不是新增训练或正式模型比较。

- 父进程先保存受控启动的退出回执，再按其中绑定的 marker hash 重新读取
  reference/cell 全部工件。两轮 pass 的 PID、模型实例、runtime、软件／GPU、
  缓存目录、导入来源和冻结 trial 都与父进程记录核对。
- 检查各冷进程的初始参数／buffer 内容相同、单进程两轮状态未改变；使用
  原有冻结 scene digest，不把预测变化误当作输入身份变化。
- 正式输出按无损编码逐位比较；raw/cue/correct 使用来源绑定的逐条
  shape／dtype／SHA 证据，不伪造未保存的 raw tensor，也不绕过原活体
  capability API。两轮 reference/A2 都必须等价。
- 固定执行 `REFERENCE_COLD → A2 → equivalence → A1 → B1 → B2`。有限
  `DIFF` 和 A2 未复现均继续收齐四格；等价失败保存 `INVALID_TRACE_PATH`
  证据并停止后续三格。异常不自动重跑。
- 最后一组结束后重新读取早期工件与回执并重算等价／canary／汇总。
  节点本地缓存不是持久结果输入，因此缓存清理后仍可只读复核。
- 父进程文件使用单独的固定命名空间，未扩大子进程写入权限。当前顺序组件
  不写 diagnostic terminal 或任何科学成功标记；外层 owner 尚未完成。

RED：初始 14 项测试产生 21 个展开错误（缺失接口）。首版接线被保存层的
子进程命名空间拒绝，修复为独立 owner namespace 后 14/14 通过。补充
RED 24 项中 1 项失败，发现跨进程初始模型内容尚未核对；已修复。
专项 124/124（54.540 s）、全套 275/275（64.254 s），源码 AST 3/3 和
限定静态检查通过。快照复测的执行布局问题与最终结果详见下面的开发报告。

本次使用 CPU tensor 工件与模拟父进程回执测试顺序／持久证据，未加载真实
formal40；现有 ColdChildProcessTests 另行覆盖实际子进程传输。不是 A100
或 Job646900 现象复现证据，也不是新的独立审查。

```text
ce09b24a40d20746915a3c2c5c686dae35abbdfa4c3ab7e39df810dcee48e50e diagnose_batch_invariance.py
70f6a274ba5586cebc4aff4f2e1210bc00ae5d4fbed7287fb558bf1dbbd8307d test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py（未改）
```

报告：[Task6b 开发与验证记录](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-6b-matrix-report.md)。
原设计与冻结 v4 evaluator hash 未变。没有远端连接、部署、提交、训练、
阈值调整或项目“全量任务”镜像同步。

## Task 6c：外层协调器身份、锁与失败处理（2026-09-07）

本次把固定四格流程外面的运行保护接起来，而不是更改推理计算：

- canonical intent／response／receipt 绑定相同 nonce、job、freeze 与 runner；
  仅在 receipt 尚不存在时等待，最多 120 秒。错误身份、非法响应或半截 JSON
  立即拒绝，不自动重试提交。实际 spool bytes 校验后 create-once 归档。
- 认证之后用原子创建 attempt 争取唯一 owner；旧 attempt／归档／终态不覆盖。
  使用原 v4 shared flock，持有同一 fd 直到输入复查和终态写入完成。
- 分别核验 24 个 v4 pinned record、snapshot、clip、诊断源码／runner／freeze、
  提交 journal 与归档 runner；逐文件流式计算 SHA，避免复制大 checkpoint 到内存。
  外部文件跨 invocation 使用 canonical path、regular-file type、size、SHA；
  v4 目录自身的 PRE/POST 仍严格比较目录身份与内容指纹。
- 主推理错误与后续输入／目录复验错误分别保留；有限 DIFF 不会自动失败。
  INT／TERM／HUP 进入失败处理，现有 launcher 先结束并回收活动子进程组，
  再尝试 POST。终态发布失败不写第二个矛盾终态；不可捕获终止保留 incomplete。
- 阻止禁用科学标记、目录替换与重复终态。terminal 提交临界段无活动子进程，
  临时忽略上述三种信号以免 link/fsync 被打断后错误写入相反终态。

先运行缺失 API 的 RED（19 tests / 29 expanded errors），再接文件 adapter。
一轮 7 个错误来自测试 fixture 没有更新临时 v4 root，修正 fixture 后通过；
补充 RED 找出未验证矩阵返回值、attempt 替换、源码记录错误新增 path 三个
问题，均已修复。最终专项 32/32（0.404 s）、全套 307/307（62.424 s）通过。
这些是本地文件／CPU／子进程测试，不是 GPU 数值矩阵；隔离复测见完整报告。

```text
13f2a6d24f96444792dc8efc5ee734e377c21dfe64fe5b11805dae607b8c762c diagnose_batch_invariance.py
8d19d8d42e4986eb5a5cc7f175c6a2ca24a8889ea675efc2bfed39350e81fb89 test_numeric_diag.py
b71b2411a202fa68130f685122a2fc0177d9ff5d13bae1e280c88da53fe644e3 numeric_trace.py（未改）
```

[Task6c 开发与验证报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-6c-owner-report.md)
记录了当前边界：owner 仍是私有组件，生产 CLI 保持关闭，最终终态清单／
只读 verifier 和真实父子启动授权尚未完成。不能将这些局部测试算作 Task 6
整体或 M1 发布通过。没有访问 HAKUSAN、提交作业或同步项目镜像。

## Task 6d：完整结果重验与只读出口（2026-09-08）

新增 attempt 全文件／目录清单，绑定 mode、size、SHA 和相对路径；缺失、
额外条目、链接及坏文件均不能解释为完整结果。`DIAGNOSTIC_COMPLETE.json`
写入前重新验证实际工件、矩阵与输入，不能只相信内存中的完成字样。

公开 `verify-results` 只读接口通过归档 runner 验证提交身份，不要求作业
结束后已被清除的 Slurm spool 或 node-local cache。已完成结果重新核对
owner ENVIRONMENT／RUNNING／PRECHECK／POSTCHECK、子进程 PID 与环境、
冻结 trial／snapshot／历史 scene hash、双 pass 等价和四格数值汇总。
有限 DIFF 仍可成为完整诊断证据，不修改原 `1e-6`。

同一次执行的 v4 PRE/POST 指纹必须完全相同；跨节点结果读取先验证记录
自身的树 hash，再仅将 device/inode 降为诊断字段，其余目录信息和全内容
hash 仍须匹配。当前所有绑定输入也前后重验。定向 trace 建议绑定已验证
的 native-logits worst trial，并且只定位到 model forward，不推断具体 kernel。

返回状态明确区分 `INCOMPLETE_NO_TERMINAL`、`DIAGNOSTIC_FAILURE_RECORDED`
和 `DIAGNOSTIC_RESULTS_VERIFIED`；前两者命令行非零，不代表数值验收。
缺少 terminal 不推断 Slurm 已结束，仍须另查 scheduler；失败记录验证
不宣称其部分矩阵可解释，也不会修复、补写或重新提交。

RED 包括缺失验证器／清单、伪造 owner 环境未被拒绝、只读 CLI 缺失，以及
没有实际矩阵却可写完成标记。组合测试数据曾有 trial schema／clip use／
freeze SHA 的不兼容，已修正测试 fixture，未放宽生产输入校验。

最终专项 48/48（29.306 秒），全套 323/323（92.472 秒）；AST 3/3、Ruff
F821/F822/F823/F811 通过，无新增 bytecode。相同 SHA 的只读隔离副本
再次通过 323/323（92.085 秒）；这是隔离复测，不是新增独立代码审查。
精确源码快照和原始日志见
[Task 6d 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-6d-verifier-report.md)。

还不是可运行的完整诊断包：生产执行入口、runner、提交器与发布验收尚未
完成。没有访问 HAKUSAN、提交 GPU 作业、修改冻结 v4 或同步项目镜像。

## v2 本地修复与只读复查（2026-09-08）

远端确认 manifest 固定 SHA 未变、25 总记录／24 五组记录之后，用户授权修复。
新建本地 same_bank_eval_2026_09_03_v4_numeric_diag_v2，v1 全部七文件保持发布
哈希。收集规则对齐冻结 v4 原遍历函数；24项角色不包含布局锁，锁另行验证
实际内容并独立纳入 owner PRE/POST。诊断根／诊断协议切换 v2，冻结 v4 身份、
数值阈值、科学协议不变。

RED：5 tests／18 failures + 1 error。新添原 v4 walker 行为对照后，共新增6项
回归；核心344/344、提交66/66通过。用户此前授权的同一只读审查代理复查Ready，
独立33/33通过。边界、测试及最终校验见
[v2 修复报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v2-manifest-scope-repair.md)
及 [v2 七文件清单](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v2-release-manifest.sha256)。
尚未上传v2、运行真实v2审计、冻结或提交。下一步新根只读预检／部署，不覆盖v1。

## Task 10 阻塞：真实 v4 freeze 计数范围不一致（2026-09-08）

用户报告 audit-inputs 返回 DiagnosticError：v4 manifest must bind exactly
24 pinned files，AUDIT_FREEZE_RC=2。日志未到 FREEZE_BEGIN；本次流程未执行
freeze，也未提交作业。已发布诊断工具须保留，不原地覆盖。

本地源代码核对：冻结 v4 verify_frozen_manifest 仅遍历 inputs、historical_evidence、
completion、models、checkpoint_selection 五组；诊断器 _collect_pinned_records
却递归整个 manifest，把 layout.evaluation_lock 也纳入。用五组 24 条加 layout
锁的结构夹具执行当前真实收集函数得到 25，复现计数范围缺陷。待用户对远端
固定哈希清单进行只读计数确认，不应将此错误解释为训练文件缺失。

此前合成 fixture 未覆盖带 layout 的真实冻结结构；独立发布复审亦未发现。
暂停后续 freeze/check/submit，Task 9 发布就绪结论不足以跨过该真实数据门槛。
下一步需确认真实结构后，对新候选补回归和有界修复；不能把 24 简单改成 25。

## Task 10：远端工具发布成功，待输入审计／冻结（2026-09-08）

用户终端记录确认：REMOTE_ROOT_CREATED=PASS、CREATE_RC=0；Mac 七文件
发布清单全通过，四个生产工具上传成功，UPLOAD_RC=0。之后 staging 与 tools
四项 SHA 均为 OK，REMOTE_TOOLS_PUBLISHED=PASS、PUBLISH_RC=0。
最终目录仅含 state/logs/attempts/submitted_runners/tools 及四个工具，
.upload-staging 已移除；发布流程仅 unlink 已核验的 staging 名称，tools 保留。
这些为用户提供的远端证据，不是助手直接 SSH 观测。尚无 input_freeze.json
成功生成或真实诊断提交证据。下一步 audit-inputs → create-once freeze，
之后人工审阅 freeze 与固定哈希，不能跳过 check-only／零写入关卡。

## Task 10：远端只读预检通过，待创建与上传（2026-09-08）

用户粘贴的 HAKUSAN 输出：V4_QUEUE 和 DIAG_QUEUE 均为空，
REMOTE_DIAGNOSTIC_PREFLIGHT=PASS、PREFLIGHT_RC=0。
该预检验证固定诊断根未使用／非符号链接、base 类型及两类队列为空。
来源为用户终端记录，不是助手直接连接集群。当前尚无新根创建、上传、
freeze 或诊断作业提交的成功证据。下一步创建私有目录后上传四个已审工具，
必须再次核验 staging 哈希并以不可覆盖方式发布。

## Task 9：独立发布复审 Ready（2026-09-08）

用户明确批准一个只读审查子代理。审查者完成有界独立检查，回报 Ready、无阻塞
问题，独立 4 项集成／调用面测试通过。README 仅更新复审状态，六个代码／测试
文件保持不变。主代理再次跑核心 338/338（94.603s）、提交／集成 66/66
（10.470s）通过；七文件发布清单、命令语法及静态检查通过。
[正式独立审查记录](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9-independent-release-review.md)
和 [最终发布哈希](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9-release-manifest.sha256)
是 Task 10 的输入。Task 9 关闭，但本轮没有远端检查、上传或提交。

## Task 9c：操作说明与候选校验（2026-09-08）

七文件包已具备 README：明确操作边界、冻结身份、部署流程和短命令，
区分诊断结果与最终三模型比较。六项内嵌哈希和八段命令的 Bash 语法通过；
README 最终编辑后核心 338/338（93.418s）、提交／集成 66/66（10.444s）通过，
Ruff／format、AST 5/5、runner 语法和隔离加载通过。
七文件候选哈希见
[Task 9c 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9c-operator-release-report.md)。
本轮仅主代理自检，独立发布复审仍待完成。Task 9 尚未关闭，未上传或提交。

## Task 9b：完整本地模拟链路（2026-09-08）

新增两个集成和两个安全调用面测试。模拟调度器接实际提交记录、runner bootstrap、
协调器、五个真实本地 CPU 子进程和实际结果验证器；合成有限 DIFF 可完成，错误
PID 安全停止，执行后重复提交被拒绝。提交套件 66/66（10.683s）、数值核心
338/338（93.534s），Ruff／format、AST 5/5 和 Bash 语法通过。
测试数据、GPU 元数据和外部 check-only 响应均为替身；不是实际 A100 测试。
仅修改测试文件，没有改动生产工具、冻结 v4 或数值阈值，没有远端操作。
详细边界和候选 hash 见
[Task 9b 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9b-integration-report.md)。
剩余操作 README、最终七文件哈希及发布复审，尚不能部署。

## Task 9a：完整静态／格式子关卡（2026-09-08）

初始 Ruff 293 项失败已修正，五个 Python 文件的完整检查与格式检查通过。
更新格式化后 numeric_trace 的固定长度／SHA；数值核心 338/338、提交工具
62/62 回归通过，AST 5/5 和 Bash 语法通过。没有新增集成测试或实际调度器调用。
当前候选哈希与边界见
[Task 9a 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-9a-style-report.md)。
整包五子进程模拟链路、安全测试、README 和发布复审仍待完成，不能部署。

## Task 8b：单次提交与只读状态查询接线（2026-09-08）

接通固定路径 SchedulerGateway、输入 freeze／源码初检、独立 check-only
完整审计、审计前后队列检查、先写意图再调用一次 sbatch、严格回执处理。
status 只读区分排队／运行、记账延迟、诊断终态标记和缺失终态的作业结束；
终态观察始终返回 results_verified=false，数值工件必须另行 verify-results。

专项 25/25（0.523 秒）、提交工具全套 62/62（1.178 秒）、数值核心回归
338/338（93.352 秒）通过。修正了查询中 freeze／终态变化导致混合状态报告
的问题。模拟覆盖真实 gateway 的 subprocess 边界、durable intent、实际
runner bootstrap 对回执发布前意图的接受、单次调用与 v4 fixture 零写入。
完整五子进程及结果验证器的端到端集成仍在 Task 9；没有实际 Slurm 调用。

CLI 已接通，但仍不是可部署版本。下一步 README、整包集成／安全／格式／
hash 与发布复审。M1 未完成，未远端操作或更改模型／数据／阈值。详见
[Task 8b 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-8b-gateway-report.md)。

## Task 8a：耐久提交记录层（2026-09-08）

新增 stdlib-only 的 SubmissionJournal／CommandOutcome／固定合同和 argv。
以非阻塞排他锁保护不可覆盖的 INTENT、原始响应和 SHA 绑定回执；只接受
零退出码、空 stderr 和严格数字 Job ID。超时／信号／异常输出／回执写失败
均保留不确定状态，禁止自动重投。回执已通过既有协调器的实际读取校验。

专项 19/19、runner+记录层 37/37 通过，包含真实本地 flock 竞争、fsync／
短写／磁盘写失败模拟及 readonly journal classification。既有数值核心
回归另跑 338/338（92.431 秒）通过。journal classification 不是 Slurm
status：调度器、完整输入预检、队列查询与正式 CLI 尚待 Task 8b。当前 CLI
明确拒绝执行，不会提交。日志及 hash 见
[Task 8a 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-8a-journal-report.md)。

未进行远端操作、修改冻结文件或数值阈值，未同步项目镜像。M1 尚未完成。

## Task 7：Slurm runner 本地实现候选（2026-09-08）

新增固定 GPU-1A／1 GPU／8 CPU／1 小时／no-requeue 的运行脚本及测试。
启动时验证 freeze、四份生产文件、实际 spool runner 与 INTENT，拒绝已有
attempt／归档／终态；创建独占节点本地缓存，记录环境指纹，再 exec 既有
协调器。回执等待及 create-once 归档仍由协调器负责，runner 不发布终态。

专项 18/18（0.365 秒）、既有回归 338/338（94.715 秒）通过；Bash 语法、
AST、选定 Ruff 检查通过。测试覆盖失败路径、缓存 mkdir 写入范围及模拟的
exec 边界，不代表 Linux／A100 正向验收。完整 fake-Slurm 提交集成待 Task 8
提交器实现后补齐。源码与日志见
[Task 7 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-7-runner-report.md)。

下一步 Task 8 耐久提交器及只读 status，再做整包验收。M1 尚未完成；未上传、
登录、提交作业、修改冻结 v4／阈值，亦未同步项目镜像。

## Task 6e：生产执行入口与父子身份接线（2026-09-08）

将 `run-coordinator`、`_child-reference`、`_child-cell` 接到已有 owner／
worker 实现。执行仍只接受固定 job／freeze／nonce／spool 参数，无任意输出
root 或 CPU 执行绕过入口；coordinator 实际 argv 必须与约定 runner 命令一致。

coordinator 验证隔离的生产 Python、完整环境白名单、node-local 私有缓存
目录、0700／owner、初始空目录与无旧子目录。运行中的缓存身份／环境检查
纳入 owner 输入 PRE/POST，使变化成为失败记录，而非忽略后继续解释结果。

child 在创建缓存或导入数值库前，读取 Linux proc 的父 PID、UID、start time、
解释器与 argv，绑定 owner ENVIRONMENT／RUNNING、冻结代码和提交 journal／
归档 runner。PID 重用、进程换父、错误命令或已有终态均拒绝；不另取共享锁。
这些是同一可信 Unix 账号中的完整性检查，不是对同 UID 恶意进程的安全沙箱。

错误出口改用纯 stdlib canonical JSON，不因拒绝启动而先加载 numeric_trace。
数值库／模型的实际加载仍留在通过身份与 scratch 校验后的既有 worker 路径。

专项 38/38（1.350 秒）、全套 338/338（92.502 秒）、AST 3/3、选定 Ruff
检查通过。相同源码的只读隔离副本复测亦为 338/338（95.370 秒）；这不是
独立代码审查。Linux proc 行为用临时 fixture 覆盖，CLI 冷启动拒绝用真实隔离
Python 子进程覆盖；不声称已经在 Linux GPU 节点完成正向执行验收。
原始日志、源码 hash、快照及剩余边界见
[Task 6e 报告](../../../.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-6e-entry-report.md)。

下一项为 Task 7 薄 Slurm runner、Task 8 耐久提交器，随后做整包验收。M1
尚未完成。没有超算登录、提交、改动 v4 或放宽阈值，也未同步项目镜像。

## Task 1

Completed local package skeleton and read-only file primitives. The staging
workspace is non-Git; no commit was created. Checkpoint:

```text
f07e6e948d47688ef6bcca0787b51c1843d0e4a507b2e52958f4b7c68aa44f60  numeric_trace.py
d8bf6d5ffbf06d00da6fb963385c404514d8b4613fcb59a8af55de1ac0f706a8  test_numeric_diag.py
```

The isolated focused class and whole current test file each passed (8 tests).
Full RED/GREEN transcript and self-review:
`/Users/gigi/发表/超算/.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/task-1-report.md`.
