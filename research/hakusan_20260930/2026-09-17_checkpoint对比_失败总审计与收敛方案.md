# checkpoint 对比：失败总审计与收敛方案

日期：2026-09-17。性质：历史证据审计和路线调整提案；**本次没有修改评估代码、上传、改动冻结协议或提交作业。**

## 1. 结论先行

用户关于“反复失败，路线可能不对”的担心有充分依据。问题不只是某一个 CUDA 报错：**原本的模型性能比较，被逐步扩展为复杂的运行时对象校验、编译器取证、观测器非干扰和原子归档系统；这些新增工程层反复阻挡了真正的比较。**

此前助手推进方式应承担的责任包括：过于依赖局部/合成测试；未足够早地跑通同环境、真实模型、真实输入的最小完整流程；把旧诊断器的所有保护接受条件长期当成不可重新审定的科研前提；对重复出现的环境和调度问题没有形成稳定、统一的实现。这不能主要归咎于用户粘贴命令或超算不稳定。

现有记录不支持“模型坏了”“训练失败了”或“所有历史指标都不可信”。训练与选定 checkpoint 已有独立证据；当前缺的是这一次 formal40 与作者 checkpoint 的完整、公平、可复算比较。

按本次可定位记录、以真实作业号去重：

- 18 个评估/诊断相关计算作业失败或超时，详细列于第 3 节。1 个是原 smoke 数值门槛失败，另 17 个没有产出可验收的数值结果。
- 这 18 个作业记载的 Elapsed 合计 **3 小时 50 分 55 秒**。这是作业墙钟时长相加，不是 GPU kernel 忙碌时间、费用，也不包含排队、CPU 探针、开发和成功作业。
- 1 个 CPU 作业 `703335` 因新增解析器误判在排队时被取消，运行 0 秒；单独记账。
- 有一次关键的真实 GPU 诊断成功：`685198`，2 小时 26 分 42 秒。它揭示了批大小数值敏感性，但不是三模型总体比较。
- 最新已保存证据：`724258` 在 A100 上运行 34 秒后失败，尚未进入正式模型加载；R 失败，C/D/E 未运行。

**建议停止给当前庞大诊断链继续逐层打补丁作为默认主线。改为：一条最小且可审计的正式评估路径，先真实小规模验收，再全量比较；深层数值取证作为有条件支线。** 这是新提案，不代表已获准改变旧合同。

## 2. 审计范围和证据等级

覆盖 same-bank 评估准备、smoke、数值诊断 v1–v19、定点追踪、G1/G2 与最新 `724258`；追溯前置 finalizer 问题。依据工作区执行台账、专题诊断记录、已下载终态和数值矩阵；本次没有重新查询远端，也没有重新计算全部历史文件哈希。

不能把以下东西相加成为“失败次数”：同一日志重复粘贴、同一作业多次 status、test-only 输出的预估编号、故意让测试失败的 RED/负例、因没有认证而未执行的远端请求。表中的 18 是**已定位清单**，不是对账户全部历史作业的穷尽式 Slurm 审计。

证据标签：

- **确认**：直接 traceback/源码，或真实同版本路径复现足以锁定该问题。
- **部分确认**：直接失败已知，但原始记录不足以确定唯一底层原因；后续探针只是支持某条解释。
- **测试/入口问题**：未进入科研推理，不能作模型数值结论。

原始完整性校验通过，只证明所核对的字节/来源关系一致；不自动证明推理有效、科学假设正确或报告可发表。

## 3. 实际失败作业清单

“v”在本表分别标明评估器、诊断器或追踪包，不能混为同一个版本序列。

| 作业 / 阶段 | 已记载时长 | 直接失败及原因 | 结论边界 / 后续 |
| --- | --- | --- | --- |
| 637966 / 评估 v2 | 0:08 | `Frozen evaluation lock device changed`。把 NFS 跨节点 `st_dev/st_ino` 当成持久身份。确认。 | attempt/推理前失败；v3 改为跨调用路径、大小、SHA，进程内 FD 检查保留。[早期记录](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md) |
| 642803 / 评估 v3 | 0:38 | `No module named 'selftrain'`。冻结导入上下文退出后，真实场景函数才延迟导入。确认。 | 三模型加载已经结束，但首批场景/预测未完成。check-only 不覆盖真实调用；v4 延长导入上下文。[早期记录](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md) |
| 646900 / 评估 v4 smoke | 1:54 | batch16/1 的 `formal40_nll max_abs=0.0077362060546875`，超过旧 `1e-6`。数值现象确认，具体算子未定位。 | 这是原始科学排障起点；不是 checkpoint 损坏的证据。没有 SMOKE_PASS、没有全量比较。[早期记录](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md) |
| 670830 / 诊断 v5 | 0:13 | `noncanonical owner JSON`。外部 v4 的缩进 JSON 被错误送入诊断器 compact/canonical owner JSON 读取器。确认。 | audit 与执行使用不同读取合同；`INVALID_BOUND_INPUT_CHANGED` 标签不能证明文件真被改动。v6 分离格式边界。[修复分析](docs/superpowers/evidence/2026-09-08-diagnostic-v6-json-boundary-repair.md) |
| 671724 / 诊断 v6 | 1:10 | `frozen runtime settings are not exact`。2.1.1 中 medium 后设 allow_tf32=True，实际读回 high，代码却要求 medium。确认。 | 本机 2.12.1 fallback 曾返回假定值，未验证真实合同。v7 统一实际读回与测试。[诊断](docs/superpowers/evidence/2026-09-09-job671724-runtime-setting-diagnosis.md) |
| 680519 / 诊断 v7 | 2:05 | `unsupported execution collection type`。真实对象中 deque/torch.Size 等未被通用遍历器支持。部分确认。 | 最小源结构复现兼容问题；原日志未报具体路径，不能证明唯一首个类型。v8 增加明确类型及路径信息。[诊断](docs/superpowers/evidence/2026-09-09-job680519-collection-diagnosis.md) |
| 680910 / 诊断 v8 | 0:48 | `root.class[__init__].resolved[os.environ]; type=os._Environ` 被拒绝。确认。 | 遍历追到了 dataset 构造函数的环境映射，未到有效数值矩阵。v9 修复映射边界。[诊断](docs/superpowers/evidence/2026-09-09-job680910-environ-diagnosis.md) |
| 681974 / 诊断 v10 | 1:11 | `model state snapshot failed`。2.1.1 的参数/buffer/module 注册表为 OrderedDict，快照代码只允许精确 dict。确认。 | 同版本真实 formal40 的 201 个注册表复现；v11 统一读取规则。[诊断](docs/superpowers/evidence/2026-09-10-job681974-snapshot-diagnosis.md) |
| 682295 / 诊断 v11 | 3:35 | 仅保存 `frozen reference prediction failed`，底层异常丢失。部分确认。 | 已确认子环境漏传 CUBLAS_WORKSPACE_CONFIG、OMP_NUM_THREADS、TOKENIZERS_PARALLELISM；不能把遗漏当作该次唯一根因。v12 恢复环境并加日志。[诊断](docs/superpowers/evidence/2026-09-10-job682295-reference-failure.md) |
| 683076 / 诊断 v12 | 3:18 | `BackendCompilerFailed`，随后冻结模块绑定变化；日志未读取 `inner_exception`。部分确认。 | 恢复环境不足以通过；CPU toy 未复现真实模型导入变化。v13 补内部异常/模块差异记录。[诊断](docs/superpowers/evidence/2026-09-10-job683076-compiler-binding-failure.md) |
| 683154 / 诊断 v13 | 3:14 | 编译内部 `FileNotFoundError`，同时 src 模块新增触发保护。部分确认。 | 同环境复现固定 PATH 找不到 ldconfig；导入清理/重导入也可独立触发拒绝。但该次缺文件名未保存，不能排除别的编译问题。[诊断](docs/superpowers/evidence/2026-09-10-job683154-compiler-path-import-diagnosis.md) |
| 683523 / 诊断 v15 | 3:46 | operator 返回后模型执行指纹检查拒绝。部分确认。 | 同版本合成编译首次 forward 正常改变 counters/most_recent_backend，说明“全部可达状态必须不变”与编译生命周期冲突；真实 GPU 所有变化未枚举。v16 重做接受边界。[诊断](docs/superpowers/evidence/2026-09-10-job683523-runtime-lifecycle-diagnosis.md) |
| 683649 / 诊断 v16 | 47:26 | reference 发布时 `mode-0600 single-link regular file` 检查失败。 | 原写法在真实 home/NFS 复现 `.nfs` 与 nlink=2，关闭临时 FD 后再 unlink 可避免；原失败瞬时 nlink 没留存，属于强支持而非完整现场记录。不是 Slurm 超时。[诊断](docs/superpowers/evidence/2026-09-10-job683649-publication-diagnosis.md) |
| 683837 / 诊断 v17 | 1:00:00 | Slurm 总时限 1 小时耗尽。确认。 | 冷参考约 18 分钟完成，矩阵未完成；CPU profile 显示重复导入绑定校验显著。v18 获批增至 4 小时后完成。[分析](docs/superpowers/evidence/2026-09-10-job683837-timeout-decision.md) |
| 705468 / 定点追踪 v1 | 0:44 | `FileExistsError: reference_cold`，scratch 工厂要求独占创建，但目录已存在。 | 本机真实导入链复现库提前创建缓存父目录；后续原生 CPU 未复现相同触发点，因此不冒称 GPU 唯一创建者已证实。先创建 scratch 的修复后越过此入口。[诊断](docs/superpowers/evidence/2026-09-14-job705468-startup-fix-local.md) |
| 713897 / 定点追踪 v3 | 50:05 | reference 子进程 3000 秒超时，被监督器停止。确认。 | 不是 Slurm 2 小时到期、没有 OOM 证据；observed 未启动。又发现环境构造漏掉旧三变量，但不能证明它造成超时。[诊断](docs/superpowers/evidence/2026-09-14-job713897-reference-timeout.md) |
| 715276 / 定点追踪 v4 | 50:06 | 恢复环境后，reference 仍在 3000 秒上限终止。确认。 | batch16 返回，batch1 未返回；第40分钟栈处于绑定守卫，而非矩阵乘。单栈不代表全部时间；observed 未启动。[阶段证据](docs/superpowers/evidence/2026-09-15-job715276-result-check.md) |
| 724258 / 新 G2 R/C/D/E | 0:34 | `CUDA already initialized before CUBLAS configuration check`。确认失败窗口。 | 环境已经有 :4096:8；早期 CUDA cold 检查后、正式 runtime 配置前状态改变。没有首次初始化栈，具体触发者未知。未到 strict-load，C/D/E 未运行。[执行台账](docs/superpowers/evidence/2026-09-17-g2-production-launch.md) |

### 不应被遗漏或混计的实际结果

1. **628071：训练后的 finalizer 误判**。40 轮、step69440 和逐轮证据闭合；Lightning 恢复后的 raw total.completed=38 被误当成只完成38轮。已通过受控恢复发布。此为前置训练收尾问题，不计入上表的评估作业，也不能据此要求重新训练。[依据](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md)
2. **703335：CPU 排队取消**。控制器只接受 NumNodes=1，错误拒绝等价的 1-1；0秒、0已分配CPU。责任在新增解析器；获批替补703415成功。[依据](docs/superpowers/evidence/2026-09-13-compiled-cpu-job.md)
3. **705468、713897、715276、724258：重复 GPU 请求错配**。提交后的资源记录出现 H100/泛型，与 A100批准范围不符；held 检查拦住后在同一作业修正。不能说这些作业实际误跑了 H100，也不能说只写 typed A100 就已解决集群改写。具体改写组件尚未确定。这是同一作业内的调度问题，不另外增加4个失败作业。[首次记录](docs/superpowers/evidence/2026-09-13-job705468-held-resource-mismatch.md)、[最新记录](docs/superpowers/evidence/2026-09-17-g2-production-launch.md)
4. test-only 的 703403、704798、713298、713541 等预估编号不能当成实际提交/失败作业。

## 4. 提交前、CPU 检查和操作层失败清单

这些也消耗了大量时间，但不是额外的模型比较实验。相同类型合并，不把每次重跑/负例计一次。

| 阶段 | 原因 | 审计判断及证据 |
| --- | --- | --- |
| 原评估 v1 audit | TSV/CSV SNR末位浮点往返：56/9000行不同，最大8.88e-16；使用了比历史合同更严的bit-exact身份判断。 | 浮点表示边界，不是场景变化；恢复已有1e-12读取容差。[早期记录](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md) |
| 首个 resume helper | Python 把 find 格式中的 `\0` 解释为 argv 内实际NUL，subprocess拒绝。 | 提交前代码错误，尚无intent/job；应测实际外部命令argv。[早期记录](2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md) |
| 诊断 v1 audit | 整个JSON递归数到25项，把layout lock算入应为24项的pinned groups。 | 清单模式理解错误，不是manifest变了。[执行记录](docs/superpowers/evidence/2026-09-03-v4-numerical-diagnostic-execution-record.md) |
| 诊断 v2 audit | 同一loader文件的记录相对路径基准不同，精确对象记录比较失败。 | 来源记录规范不一致；v3修正。[v4前置复盘](docs/superpowers/evidence/2026-09-08-diagnostic-v4-local-regression.md) |
| 诊断 v3 audit / v4本地复审 | 签发/退出冻结上下文改变sys.modules；Dynamo导入会调整torch.manual_seed，真实src导入也会改变可达图。 | 把动态导入当成静态不变量；toy selftrain fixture遗漏真实src边界。437项通过仍不够。[复审](docs/superpowers/evidence/2026-09-08-diagnostic-v5-repair-review.md) |
| 诊断 v9 本机真实结构探针 | torch2.12.1 OptimizedModule 的training存储方式与2.1.1不同。 | 本机失败不能直接外推超算；同版本小探针澄清。[记录](docs/superpowers/evidence/2026-09-10-diagnostic-v9-real-path-progress.md) |
| 诊断 v9 原生正式模型CPU准备 | 完整对象图work=200001，超过200000预算。 | 严格加载已成功；不是模型太大不能推理，是校验遍历预算不适配。[记录](docs/superpowers/evidence/2026-09-10-diagnostic-v9-real-path-progress.md) |
| 诊断 v14 原生正式模型CPU准备 | 模块恢复后完整指纹work=600001，超过600000预算；两次独立路径出现。 | 645本地测试缺乏真实规模覆盖；v14未提交GPU。[记录](docs/superpowers/evidence/2026-09-10-diagnostic-v14-remote-deployment.md) |
| 9/13 编译生命周期CPU入口 | 登录节点参考子进程60秒超时，空日志，observed未运行。 | 未知卡在哪一步；转获批CPU计算作业703415后完成，不改写旧超时。[记录](docs/superpowers/evidence/2026-09-13-compiled-cpu-verified-and-lifetime.md) |
| 追踪v2 scheduler test-only | typed/untyped GRES混合；`--gpus`组合不被现场接受。 | 提交前参数错误；仅typed `--gres` test-only通过不等于提交后的类型正确。[记录](docs/superpowers/evidence/2026-09-14-native-startup-and-gres-correction.md) |
| v19 CPU整组 / scratch补测 / 计时探针 | 总预算使末组只剩约38秒；独立50秒补测仍超时；计时探针停在expected_contract生成。 | 测试准备本身调用大量守卫，还未到待测mmap；本机18秒通过不能替代原生时长。[超时](docs/superpowers/evidence/2026-09-15-v19-native-cpu-timeout.md)、[定位](docs/superpowers/evidence/2026-09-15-v19-cpu-timing-findings.md) |
| 分阶段A2/B2/mmap原生CPU入口 | 拆分后A2仍50秒超时，B2/mmap未运行，日志为空。 | 修正测试结构未证明解决时间预算；之后718727计算节点三阶段成功。[记录](docs/superpowers/evidence/2026-09-15-staged-native-timeout.md) |
| G2原生小型CPU编译取证 | 50.150秒超时、空日志；无法确定是导入、检查、编译或执行。 | 后续720730在计算节点完成；仍不是生产模型GPU验收。[记录](docs/superpowers/evidence/2026-09-16-g2-native-backend-progress.md) |
| G2本地接口整合 | PrivateScratch与精确_WorkerScratch类型冲突；含job_id的请求SHA却要求提交前已知；归档复查复用解释器触发module already loaded。 | 真正的接口/时序缺口；局部测试通过不等于接线成功。[scratch](docs/superpowers/evidence/2026-09-17-g2-scratch-and-status.md)、[提交绑定](docs/superpowers/evidence/2026-09-17-g2-plan-binding-fix.md)、[归档](docs/superpowers/evidence/2026-09-17-g2-array-archive.md) |
| 开发测试脚本自身 | 测试参数下标、异常类型预期、本机API混用、把载荷内文件名当执行命令等。 | 应保留RED→GREEN记录，但不算实际科研实验失败；也不把负例拒绝当“又出现故障”。 |
| 终端粘贴/命令所在机器 | 括号/引号/路径/长参数断行、heredoc结束标记缩进、命令末尾多`~`、Mac上传命令在Linux执行。 | 操作入口设计不适合用户反复手工拼接。应提供短命令和明确local/remote提示，不能让用户承担所有粘贴风险。 |
| SSH / 状态理解 | Broken pipe、255、共享master消失、早期1小时后改12小时空闲退出；曾有parse error。 | 255需区分认证/传输，不代表GPU失败。SSH断开通常不取消已提交Slurm作业；历史PASS不代表当前连接可用。`squeue Invalid job id`应查sacct，不重新submit。 |

以上覆盖已定位到的主要阻断原因族；不是声称枚举了每个开发断言或每次认证失败。对于早期只有聊天输出而没有完整工件的细节，维持对应证据限制。

## 5. 已经拿到什么真正有效的结果

直接读取已保存 `MATRIX_SUMMARY.json`，Job685198的实际结论如下：

| 对照 | NLL最大绝对差 | 32条预测类别是否一致 | 旧数值判据 |
| --- | ---: | --- | --- |
| AMP开，16 vs16 | 0 | 是 | PASS |
| AMP开，16 vs1 | 0.003428220748901367 | 是 | DIFF |
| AMP关，16 vs16 | 0 | 是 | PASS |
| AMP关，16 vs1 | 0.0024318695068359375 | 是 | DIFF |

输入身份、归一化输入和已记录特征一致；首个**已观测边界**差异在logits。float64离线复算NLL仍保留约0.00343/0.00243差异，因此不能只归咎于最后一步log-softmax舍入。AMP关的组仍开TF32和compile，不是完整高精度无编译对照。不能从32条类别未变推断10k或作者模型类别全部不变。

来源：[成功验收](docs/superpowers/evidence/2026-09-11-job685198-verified-diagnostic.md)、[原始矩阵](docs/superpowers/evidence/job-685198-v18/MATRIX_SUMMARY.json)、[离线分析](docs/superpowers/evidence/2026-09-11-job685198-offline-findings-and-trace-plan.md)。

已有CPU成功703415、703751、718727、720730、721086分别证明特定合成生命周期、真实模型注册准备或原生编译连接的部分环节可运行。它们有价值，但没有一个能替代三模型完整GPU小规模验收。

## 6. 系统性原因：为什么会越修越多

### 6.1 把科研可复现性与通用运行时防篡改混在一起

数据、权重、标签、代码、实际运行设置、逐trial对应和模型状态必须有依据。但是递归追踪所有可达Python对象、每个算子前后反复扫描模块表，并不是证明同bank性能差异的唯一办法。

这套做法把deque、OrderedDict、os.environ、Dynamo counters、导入缓存、FD/NFS生命周期都变成发布阻塞。v18单个诊断主文件已12,586行，原v4评估器3,622行（本次本地计数，行数本身不是质量标准）。越来越多新增工作在证明诊断器自身，而不是测量模型。

需要保留必要保护，但不能因为保护是旧版自己加的，就永久禁止重新审视其成本和适用边界。新协议中简化保护须明确说明；旧证据原样保留，不偷改旧PASS定义。

### 6.2 测试范围小于生产路径，测试数量却持续增长

本机2.12.1与超算2.1.1至少在训练状态、注册表、精度API上确有差异。mock调度器、toy模型、CPU eager backend、CPU Inductor、真实CPU strict-load、真实A100冷启动是不同覆盖层。

过去虽常写明限制，却仍用多个局部PASS组合推进一条没有完成生产整合验证的路径。最新724258在真实模型加载前即失败，说明“scratch测试+CPU编译测试+入口测试”没有覆盖组合起来的冷启动顺序。

### 6.3 把数值敏感性过早等同代码错误，并把诊断解释变成无限前置条件

PyTorch 2.1.1官方明确说明：batch计算与单条/切片计算不保证逐位相同；TF32会降低部分计算的有效精度。因此不存在通用的“1e-5一定正常、1e-2一定bug”分界。类别翻转也可能发生在很小的分类margin附近，既不能直接判bug，也不能直接判无害。[官方数值说明](https://raw.githubusercontent.com/pytorch/pytorch/v2.1.1/docs/source/notes/numerical_accuracy.rst)

这不意味着本项目差异可以不管。正确的问题是：输入/状态是否正确、固定方案是否可重复、数值变化是否实质改变报告指标。需要量化，而不是追求任何batch/后端/精度下同一个比特。

确定性设置也不承诺跨版本/平台结果相同。[官方可复现说明](https://raw.githubusercontent.com/pytorch/pytorch/v2.1.1/docs/source/notes/randomness.rst)

### 6.4 保护检查成为性能瓶颈，早期却缺少阶段计时

Job715276的单次栈落在模块绑定校验；后续合成profile中，batch16→batch1使完整身份检查45→675次、模块扫描3060→45900次。不能把合成比例全部外推真实模型，但足以证明守卫放大问题真实存在。[测量](docs/superpowers/evidence/2026-09-15-guard-overhead-findings.md)

出现47分钟发布失败、1小时超时、两次50分钟超时以后，仍继续为合成测试的50秒上限创建更多包装层，收益已经偏离最终目标。合理资源边界需要实测吞吐，不应反复用短探针封装长生命周期。

### 6.5 重复缺陷没有收敛成单一实现

- 三个运行环境变量在v11漏过，新的追踪启动器又漏一次。
- A100实际资源错配在四个作业重复出现，后续反复添加按Job专用恢复器。
- 导入/封存生命周期问题从早期selftrain延迟导入，延伸到sys.modules、compile初始化，再到CUDA初始化窗口。

这表明需要统一入口、配置和真实记录回放，而非每次复制一套控制器并重新建立不同的身份链。

### 6.6 日志和状态文档过多，但关键进展信号不足

早期只留下“child exit2”，后来漏inner_exception、缺文件名、空超时日志；某些终态error=null而嵌套失败。与此同时，大量SHA/PASS和长篇追加的“当前状态”容易使用户误以为已经进入正式比较。

应只保留一个简短最新状态表；历史记录单列。首先报告“是否加载真实模型、是否产生有效预测、是否完成三模型比较”，再报告测试数。失败证据验收成功必须明确叫“失败证据有效”，不能缩写成任务PASS。

## 7. 新的完整解决方案（提案，尚未执行）

### 7.1 路线选择

不建议默认继续修补724258后重跑四格编译取证矩阵。也不建议直接把旧1e-6改成宽阈值然后跑10k。

推荐：**基于已有v4的科学逻辑建立一个新的精简评估版本，复用严格加载、共享原始场景、模型原生前处理、controls和配对统计；不继承整个v18/v19运行时对象图认证/观测器链。** 每一项移除或替换的保护在差异说明中列明，新版本不冒称旧诊断器等价。

与9月15日计划的实质区别：旧计划已经写过“比较主线、追踪支线”，但后续G2仍继承原守卫、编译取证、bridge、scratch精确类型和多层签发关系，因此实际开发仍被诊断框架牵制。本提案不仅换里程碑名称，而是**重新划定运行保护边界，并取消“四格编译取证和旧追踪链整体验收”作为正式比较一律必须满足的前置条件**。如果不批准这项实质调整，就只能继续旧合同，不能假称已经完成简化。

第一候选数值配置建议为无compile、无autocast、TF32矩阵乘与卷积均关闭的FP32路径，开启适用的确定性设置，固定batch计划及尾批规则。这是为了减少编译/精度变量，不是保证消除所有浮点差异。仍必须实测三模型适用性、性能和敏感性；不得按谁准确率更高来挑设置。

如果模型构造器自动包装compile，需审阅并显式禁用/取出正确底层模型，验证参数、buffer、架构、原生forward及前处理关系；不能全局monkeypatch torch.compile，也不能从state_dict键名“看起来一样”推定等价。已冻结的旧代码和权重不改。

R/C/D/E与逐层追踪保留为解释旧差异的支线：只有新候选依然有不可接受的不稳定，或论文结论确实需要解释某个机制时，才提交针对性控制实验。无需先证明所有编译内部对象完全不变，才能开始性能比较。

### 7.2 哪些检查保留，哪些不进入全量热路径

| 必须保留 | 从正式每batch热路径移出 / 不作为默认门槛 |
| --- | --- |
| 固定数据/三checkpoint/标签/科学配置/源码哈希；新唯一attempt；不覆盖旧证据 | 全Python可达对象图反复递归封存、每算子扫描整个sys.modules |
| 严格加载；eval；无训练/梯度更新；真实dtype/device/运行设置读回 | 为deque、os.environ、Dynamo计数器等建立通用“所有对象静止”假设 |
| 原始scene/cue/trial身份精确配对；有限值、输出维度、NLL语义检查 | 10k中逐层hook、大张量追踪、编译器生成代码取证 |
| 模型参数/buffer在适当阶段前后检查；小规模阶段加强输入不变性检查 | 把正常框架初始化也当作科学模型改变；用缓存PASS假装进行了新检查 |
| 实际资源核对、预算/超时、完整异常链、终态/输出内容独立重读 | 针对每个job再造一整套恢复/归档/签发框架 |

边界调整不是“所有保护都删掉”。新威胁模型是可信单用户科研执行下的防误用、防混源和可追溯性；不额外承诺同进程恶意代码任意修改下仍安全。如果用户/机构确实需要后者，应把它作为独立安全工程项目预算和验收。

### 7.3 分阶段计划和硬退出条件

| 阶段 | 工作 / 产物 | 通过条件；失败怎么处理 |
| --- | --- | --- |
| S0 定案与基线 | 批准路线调整；一份简短协议，锁定三模型、10k、controls、统计角色及旧失败；整理唯一状态表。 | 不重新训练、选checkpoint或采样bank；确认没有未查明的提交；新额度单独确认。 |
| S1 最小真实完整流程 | 单一入口：环境先于数值库导入 → 安全scratch → 固定源码导入 → strict-load → 真实场景 → forward → 保存输出 → 独立重读。先覆盖formal40与作者，再补valbest33。 | 同版本计算节点真实小样本走到底；测试用这个生产入口，只改变样本列表。仅toy/AST/CPU准备通过不能进入全量。 |
| S2 数值资格与三模型smoke | 原32条故障样本做回归；另预先固定覆盖clean、mixed、SNR、干扰数及controls的工程确认集。测固定batch冷重复、16/1、尾批、batch同伴重排、所有cue分支。 | 输入/状态有效、固定方案可重复；量化logits/NLL/probability分布、预测翻转与margin。未过旧1e-6仍记旧判据不通过，不临时调阈值。 |
| S3 预先审定新的接受政策（仅必要时） | 若只剩批形状浮点敏感性，明确新固定batch政策、数值/指标误差预算、确认样本和失败条件；在新的确认运行前锁定。 | 不依据全量模型排名反推标准。若输入串扰、训练态、状态变化、NaN、样本错配或固定设置重复不稳定，停止修实现。 |
| S4 测成本并冻结正式版本 | 在相同已验代码上用预先固定的中等规模样本实测，例如256条；区分加载、预处理、推理、I/O、验证耗时及显存/内存。 | 预算由实测与冷启动开销估算并获批；保护开销不可再次主导运行。更改代码/设置后复验受影响smoke。 |
| S5 全量执行 | 同一10k正确cue ×3模型；同一2000控制子集 ×3额外cue ×3模型。合计48000模型-条件预测。 | 完整覆盖、无重复/缺失/错序、身份一致、状态有效、独立重算输出与终态一致。失败片段不拼作完整成功。 |
| S6 统计与科研报告 | 主比较formal40−author；valbest33补充。Accuracy、NLL、成对差值与95%CI；SNR/干扰数及预定controls分层。 | 沿用已审定target_speaker cluster bootstrap、10000次、固定seed与配对抽样；从逐trial重算，不拿两个独立均值CI相减。 |
| S7 交付 | 逐trial表、主表、分层/controls表、图、环境/配置/来源清单、短复算命令、限制与失败附录。 | 本地结果包完整验证；可回答模型差多少、在哪些条件差、结论多大不确定性。不要求自己的模型获胜。 |

S1–S2可以在同一获批的小规模计算作业内按关卡顺序执行，前项失败即停止后项；不需要为了每个微小组件都单独申请一次GPU。最早应获得的是**真实两模型有效预测**，而不是新的数百项合成PASS。不得未经授权合并为无限时长或自动追加作业。

S4样本的256是预算测量提议，不是既有已冻结科学样本；实施前固定身份和覆盖，不能看结果后挑选。最终总体估计始终来自完整原10k。

### 7.4 数值验收具体如何落地

把三个问题分开，不再用一个笼统“完全一样”覆盖一切：

1. **输入和实现正确性**：trial、标签、scene/cue、模型角色必须精确对应；eval状态、原生前处理、strict-load、有限值和输出语义必须成立。固定一条样本更换同batch同伴用于排查跨样本依赖；不能仅看batch总平均。
2. **固定执行方案重复性**：在固定软件/设备类型/seed/batch顺序下，独立冷进程重复；保存精确差异，不预先声称跨硬件逐位一致。若自身固定方案都不稳定，先查原因。
3. **改变batch的数值敏感性**：保存误差分位数、最大值、类别翻转、top1-top2 margin，以及accuracy/NLL和成对差值的变化；科学重要性由预先确定的误差预算判断，不由一个通用绝对常数判断。

在**同一个完整已验证样本集合上**，若两个模型改变batch后分别有比例q₁、q₂的类别变化，则该集合上accuracy差值的变化绝对值至多q₁+q₂；NLL差值变化可由两模型逐条NLL变化绝对值的均值之和界定。小确认集的这个界不能无条件外推全部10k，必须明确样本覆盖/推断限制。

如果剩余误差已大到可能改变主要结论，就增加一个有明确假设的精度/执行对照，或在报告中保留“不足以分辨”；不能挑选更好看的结果。新的数值容差须在独立确认运行之前定稿，旧1e-6失败永久保留原义。

### 7.5 对最新724258的处理

旧作业不重排，不复用其一次额度。为了防新入口重复该错误，启动日志必须记录关键导入前后CUDA状态，CUBLAS配置由进程外环境在任何数值导入前设定。需要时在受控小型生产启动探针中保存第一次CUDA初始化的调用栈，不能依据“没有分配张量”推断CUDA未初始化。

目前只知道早期cold检查与后续准备检查之间状态改变。先审计预导入、场景导入和实际设备查询顺序；不把“环境变量已经正确”与“CUDA必须到很晚都未初始化”混为一个条件，也不能直接删检查强行通过。新入口应有一项真实计算节点冷启动验收，而不是再仅测hermetic-test分支。

这个故障可以局部研究，但不应成为保留整个旧认证框架的理由。

### 7.6 调度、日志和停止规则

- 统一一个提交/状态/下载入口。实际sbatch仅一次；回执不确定时先查询原nonce/job，绝不盲重提。
- 把已保存的四次GPU错配记录纳入同一资源验证器；held阶段核对实际ReqTRES，运行时核对AllocTRES和设备。若需同作业修正，预先写明严格范围并取得授权；持续改写则向集群管理员确认规范，不每次临时造恢复脚本。
- 一次认证用于短提交/查询；计算生命周期交给Slurm。密码不写脚本、不进聊天；网络断开只影响查询，不能触发新提交。
- 每个关键阶段写begin/end/elapsed和进度；完整异常类型、消息、cause/context及编译内部异常落私有日志，不记录凭据/locals/完整环境。超时保存栈和当前阶段；不等50分钟只剩“child exit2”。
- 结果明确区分：EXECUTION_INVALID、NUMERIC_SENSITIVITY_RECORDED、SMOKE_VALID、COMPARISON_COMPLETE。工程执行失败不作数值结论；敏感性观察也不自动标成执行错误。
- 同一个已知失败没有新证据/针对性回归，禁止再提交。首次最小生产流程若又被新增校验框架阻断，先做设计复核，不自动新建下一诊断版本。
- 吞吐不足先依据计时处理，不能默认加时。任何新GPU额度由用户明确确认；本方案不预授权自动重试或全量运行。

## 8. 科研结论的边界和最终交付

正式角色不变：formal40主结果、author_external外部系统参考、valbest33验证选择的补充。原生前处理不同必须披露；这不是仅权重不同的严格单因素实验。

本bank已经用于验证/pilot选择。最终报告必须标注：

`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`

它可以回答“这三个固定系统在这一冻结bank上的表现差异”，不能单凭此次CI宣称独立测试集泛化或作者训练数据与测试speaker绝无重叠。若论文需要独立泛化结论，需要另行规划未参与选择的数据；这是额外研究任务，不能把旧bank改名解决。

交付至少包含：

1. 对应48000条模型-条件预测的完整记录、trial/scene/cue/label身份，以及可复算logits或等价原始输出。
2. formal40对author主表、valbest33补充表、paired CI和预定分层/controls结果。
3. 数值资格报告、固定配置、实际吞吐/资源、程序/环境/权重/数据清单和唯一正式作业台账。
4. 从结果文件重新生成表图的入口；失败历史单独附录，不掩盖旧DIFF或把部分结果拼成成功。

**当前建议的下一动作是审定这条精简主线，然后实现和验收一个真实模型的最小完整流程；不是立即再提交724258的补丁版。**

本次审计只形成此文档。旧发布、冻结数据/模型、运行源码、历史作业和主计划均未改动；路线调整、数值合同和计算预算仍需在实施前明确确认。
