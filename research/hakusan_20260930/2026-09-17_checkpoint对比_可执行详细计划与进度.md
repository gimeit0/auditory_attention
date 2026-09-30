# checkpoint 对比：可执行详细计划与进度

建立日期：2026-09-17。唯一目标：完成 **formal40 与作者 checkpoint 的固定同 bank 比较**，valbest33 作为补充，交付可独立复算的结果及限制说明。

依据：[失败总审计与收敛方案](2026-09-17_checkpoint对比_失败总审计与收敛方案.md)、[已实现的小样本候选](same_bank_compare_2026_09_17_eager_v1/README.md)。用户本轮已要求制定详细计划并按计划执行。旧计划和失败证据保留为历史，不再不断复制新的“当前状态”。

## 0. 先看当前真实进度

| 问题 | 当前答案 |
| --- | --- |
| 训练是否要重做、是否重新挑 checkpoint？ | 否。原训练完成证据与三个固定 checkpoint 沿用。 |
| 新精简入口是否加载过正式 checkpoint？ | 是。Job724808严格加载formal40/author_external/valbest33，加载覆盖率均1.0。 |
| 新入口是否在真实 A100 上产生有效预测？ | 是。正式 Job728520 已完成 48,000 条预测，归档复算通过；固定配置全量重复逐位一致。跨批敏感性解释见最新勘误。 |
| 是否完成三模型 10k 比较？ | 是。10,000 条 trial、2,000 条 controls，P09 统计已完成。 |
| 本计划是否已经新提交作业？ | 历史提交和终态见各阶段台账；正式全量 Job728520 COMPLETED/0:0。当前为本地离线交付收尾，未新提交作业。 |
| 当前执行位置 | P01–P10 完成：正式全量 Job 728520、统计、勘误解释、交付文档与三张出版图均已有证据；剩余为用户最终图文核对与投稿适配（目标未定）。 |

最新解释：[数值敏感性勘误与复核](docs/superpowers/evidence/p10-delivery-20260919/NUMERIC_ERRATUM.md)。旧段落按日期保留为历史，不作为最新状态；不声称已完成全量 batch1 对照或跨批统计显著性验证。

已知最后一个旧生产作业是 `724258`，失败于 CUDA 初始化检查、无正式加载/有效数值结果。其最后保存的队列检查时间是 9/17 20:52 JST，**不能当成现在的实时队列状态**。

## 1. 不允许漂移的科学合同

| 项目 | 锁定内容 |
| --- | --- |
| 主模型 | formal40：`formal-final.ckpt`，epoch40 / step69440；SHA `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` |
| 外部参考 | author_external：`epoch=1-step=24679-v1.ckpt`；SHA `6fb23dde8455ef353a00d9bf676bf00f337961ac7c6d45f35f2c45a15cd88ed0` |
| 补充模型 | valbest33：`epoch=33-step=59024.ckpt`；SHA `853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14` |
| 数据 | 原冻结 10,000 trial：1,000 clean、9,000 mixed；固定其中 2,000 条 cue-control 子集 |
| 原 manifest | `1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5` |
| 预测总数 | 正确 cue：10,000×3=30,000；额外三种 cue：2,000×3×3=18,000；合计 **48,000 条模型—条件预测** |
| 原生预处理 | 三模型共享原始 scene/cue；模型各自使用其原生单样本预处理，差异在报告中披露 |
| 主报告 | formal40−author 的 Accuracy、NLL、成对差值与置信区间；valbest33 为次要比较，不据新结果改主模型 |
| 统计 | target_speaker 成簇配对 bootstrap，10,000 次；沿用原 v4 seed 规则：基础 20260829，模型差值按原分层偏移，不能擅自把所有调用改为同一 seed |
| 研究身份 | `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`；这是复用验证/pilot bank 的审计，不声称独立测试泛化 |

新候选为 eager FP32、autocast 关闭、矩阵乘/卷积 TF32 关闭、确定性设置开启。它是**新执行协议**，不继承旧追踪/编译取证链作为强制前提，也不声称与旧 AMP/compile 输出逐位等价。

## 2. 执行规则与权限

1. 文档、本地实现、只读核验和合成 CPU 回归可以连续推进，不要求用户每条命令再说“下一步”。
2. 旧冻结源码、模型、bank、失败证据不改；不清空旧目录，不把旧失败覆盖为 PASS。
3. 新 GPU 预算必须明确批准。用户在首次 **1 A100 / 8 CPU / 64 GiB / 最多30分钟 / 单次、不自动重试** 的预算询问后回复“开始吧”，已按该范围批准并单次提交724808。这是上限，不是完成时间承诺；不得因为尚未放行就自动重提。
4. 上述首次预算只覆盖一次 batch16 的真实32条小样本执行（含三个模型、所有既定 controls）；不自动包含冷重复、batch1、额外确认集、256条、全量10k或失败重试。后续可以一次批准一个有总上限的资格批次，不必逐组件分配作业。
5. Slurm 提交只调用一次。提交响应丢失时先按保存的 nonce/名称/时间窗口查询，不执行第二次 sbatch。SSH 断开不触发重新提交。
6. 暂扣（held）提交后核对实际请求；错误资源不放行。改变现有作业资源、取消、放行均按明确授权边界处理，不能擅自重复旧作业专用修复命令。
7. 不把任何 checkpoint 评估放到登录节点运行。登录节点只做短查询、文件校验及调度检查；真实流程交给计算节点。
8. 密码只在 SSH 提示符输入，不写代码、不写日志、不发送到聊天。
9. 出现新的工程故障：记录原始异常、所在阶段、耗时和证据；先复现与修复，再考虑新额度。禁止为了重复同一已知失败自动创建下一个诊断版本。
10. 9/18用户对P05a明确预算回复“好的”，批准一个新作业、1 A100/8CPU/64GiB、总上限30分钟，顺序repeat16/batch1，无自动重试；只允许资源完全匹配时放行。本授权不包含同作业资源修正，也不能沿用724808专用修复授权。
11. 随后用户对“修订参数、单次held提交；若GPU类型改写，仅修正同一个未运行作业，核验通过后放行，预算不变”回复“好的”。此新增授权已记录于r2独立授权文件；不修改第10条历史原件，不授权重提、取消或额外运行。

## 3. 对应历史失败清单的防复发检查

详细的18个实际失败作业和CPU/传输问题保留在总审计。这里映射到执行任务，不把已知失败再跑一遍。

| 检查点 | 对应失败 | 新路径必须做到 | 证据 / 阶段 |
| --- | --- | --- | --- |
| F01 持久文件身份 | 637966；683649；v1 SNR往返 | 跨节点用路径/size/SHA；进程内保留FD检查；不要求NFS跨节点inode一致；输出独占创建；SNR沿用原读取语义 | P01/P03/P04，原文件SHA、实际NFS写入/重读 |
| F02 来源与格式边界 | v1的25/24计数；v2 loader记录；670830 JSON | 外部v4 JSON仍按外部格式读取；不强制改成新格式；原pinned groups和源码直接复用 | P01/P04，固定manifest验证 |
| F03 完整动态导入 | 642803；v3/v4；683076/683154 | frozen import context 覆盖场景创建、严格加载和整个forward，不提前退出；用真实CPU/GPU入口检验 | P04真实日志，不能用toy PASS替代 |
| F04 原生运行设置 | 671724；682295；724258 | 环境先于数值库；设置后读回；首次CUDA冷检查只在首次配置处；不把正常初始化误判为后续必须cold | P03/P04，启动阶段与实际设置记录 |
| F05 校验保护范围 | 680519/680910/681974/683523；v9/v14遍历预算 | 检查明确科学状态，不遍历os.environ/deque/编译计数器等任意对象；不扫描每算子sys.modules | P01/P04，源审查与分阶段计时 |
| F06 一次最小真实流程 | 多次本地2.12.1 PASS而原生失败 | 同一生产执行函数，真实 checkpoint/音频走到保存与独立重读；本地测试只标相应范围 | P04，没有这个结果就不做全量 |
| F07 异常与预算 | 682295/683076/683154丢异常；683837/713897/715276超时 | 完整traceback、阶段begin/end/elapsed、定时栈、Slurm时限；超时不默认延长 | P03/P04/P07，完整私有日志与耗时 |
| F08 scratch生命周期 | 705468；G2类型冲突 | 唯一scratch先于库缓存初始化；HOME不改；明确目录所有者和清理范围；不复用reference_cold | P03/P04，实际计算节点目录记录 |
| F09 实际调度资源 | 703335的1/1-1；四次GPU类型改写 | 现场调度版本/typed GRES验证；held核对ReqTRES，运行时核对AllocTRES及实际GPU；不只看脚本字符串 | P03/P04，调度原始记录 |
| F10 提交/连接/粘贴 | argv NUL、长命令破坏、SSH255、把status当submit | 本地短入口；参数数组；单次提交journal；只读status/collect与submit分开；不自动重连重试提交 | P03，命令执行测试和回执 |
| F11 真正的数值差异 | 646900；685198的16/1 DIFF | 原32条、三模型、独立冷重复、16/1、尾批、同伴重排；分别记录误差与预测翻转 | P05/P06，不临时放宽1e-6 |
| F12 科研交付 | finalizer误判、指标被所有工程PASS掩盖 | 不重新训练；48,000预测完整对应；成对统计可复算；复用验证集与原生预处理差异明确披露 | P08/P09/P10 |

## 4. 分阶段工作清单、命令和验收

状态符号：`[x]` 有证据完成；`[ ]` 尚未完成。后续未实现命令明确标“待实现”，不能复制猜测脚本名执行。

### P00 固定路线与台账

- [x] 从总审计采用新的精简主线，原诊断链仅作为有具体问题时的研究支线。
- [x] 创建本文，锁定三模型、数据、统计身份和权限边界。
- [x] 获得首次小样本预算确认并原样记录：[授权记录](docs/superpowers/evidence/eager-small-production-20260917/package/AUTHORIZATION.json)。

出口：用户目标、协议、预算边界一致；无需修改旧文件。

### P01 复核已实现本地候选

输入：[候选文件校验清单](same_bank_compare_2026_09_17_eager_v1/candidate-files.sha256)。

- [x] 重新验证候选五个文件和原 v4 evaluator/runner 的固定 SHA。
- [x] 执行候选21项CPU回归和原v4的56项回归，保存真实日志、返回码与当前环境。
- [x] 检查生产入口只允许固定32条和明确batch，不能伪装成全量完成。

已存在、可直接执行的命令（Mac）：

```bash
cd "$HOME/发表/超算/same_bank_compare_2026_09_17_eager_v1" &&
/usr/bin/shasum -a 256 -c candidate-files.sha256
```

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover \
  -s same_bank_compare_2026_09_17_eager_v1/tests -v
```

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover \
  -s same_bank_eval_2026_08_29_v4 \
  -p test_locked_same_bank_eval.py -q
```

本轮已实现[统一本地入口](checkpoint_compare_workflow_20260917/README.md)，执行上述核验及新比较工具测试并保存日志。第6节已登记本次结果；通常使用下列一条入口，无需再分别执行上面三组命令。该入口不执行SSH、上传或sbatch。

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/workflow.py local-check
```

失败处理：任一SHA不符先确认用户改动，不能重新计算SHA后直接宣布通过；测试失败先修对应新代码，不动原冻结代码。

### P02 补齐只读运行声明核验与数值比较

- [x] 实现独立核验回执文件清单、输入/模型身份、候选SHA、运行设置、加载覆盖率、环境记录和状态不变声明；调度资源仍须P04外部核对。
- [x] 实现对两个已各自重算通过的输出逐trial配对；scene及四种cue身份精确一致才比较数值。
- [x] 区分 `cold-repeat`（同batch独立进程）和 `batch-size`（16/1）；拒绝相同回执或相同进程声明冒充冷重复。
- [x] 实现输出 logits/NLL/probability 最大值、均值、分位数；预测翻转trial、top1-top2 margin；Accuracy/NLL变化与模型成对差值变化。
- [x] 单独报告旧1e-6结果表 canary，不能以本地重算容差替代；不自动写SMOKE_PASS或解锁全量。
- [x] 候选及新工具回归覆盖配置不一致、同进程冒充冷重复、cue/scene变动、损坏回执、只改指标不改logits等。

产物：[只读比较工具](checkpoint_compare_workflow_20260917/review_runs.py)、[12项新增回归](checkpoint_compare_workflow_20260917/tests/test_review_runs.py)、CLI帮助和执行日志。以上完成勾选仅代表实现与本地测试；还没有真实新GPU结果可以比较。

查看实际参数（不会运行推理）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/review_runs.py --help
```

实际比较必须同时提供 `--kind`、两份输出目录和各自外部保存的 `RECEIPT.json` SHA。`batch-size` 模式左侧必须batch16、右侧batch1。得到真实目录和回执后登记完整命令，现在不填造路径或SHA。

出口：有真实输出后能用只读命令回答“同一输入、同一模型、同一设置下到底差多少”；目前没有真实新结果时，不生成伪数值报告。

### P03 计算节点投递准备（先本地，再现场只读预检）

已实现小型投递包装，没有调用旧G2发布/提交脚本。初次发布和原生test-only通过，实际暂扣查询暴露三个解析兼容性遗漏。9/18已在保留原包的前提下更新唯一控制文件，并完成同作业A100请求修复及独立核验；详见下方台账。原投递脚本绑定旧控制源码，不继续用其submit/status/release操作。

依次完成：

1. 固定执行包（源文件、候选SHA、runner、计划与预算），新目录、独占文件，不覆盖旧候选。
2. runner 在数值库导入前设置 `CUBLAS_WORKSPACE_CONFIG=:4096:8`、线程/缓存策略；使用绝对Python路径、`-I -B`，不重写HOME。
3. runner 记录实际资源；只允许批准的A100/CPU/内存/时间；完整阶段日志及每5分钟一次栈（不记录locals或凭据）。
4. 参数数组/进程返回码/错误日志/已存在attempt/信号超时都做本地测试；测试不能仅搜索源文本含某个参数。
5. 只读现场确认：当前账户队列、Slurm版本、分区、typed GPU名称、可用内存/配额、Python版本、原输入SHA、新目录不存在、旧Job状态。必要时认证，密码只在终端输入。
6. `sbatch --test-only` 检查现场接受参数；保存原始输出，不能把预估jobid当实际提交。

9/18在控制和资源修复后又获单独批准，已放行同一Job724808。当前可重复的只读查询如下；不要再执行`submit`或`release`，也不用已过期的held-check。

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-18-eager-small-724808-status.sh"
```

完整执行包、源SHA、授权、测试、预检、上传、提交及原始记账见[Job724808台账](docs/superpowers/evidence/eager-small-production-20260917/EXECUTION.md)。

Slurm的提交成功不等于开始运行；`--hold`用来在放行前核对请求。typed GRES的拼写必须以现场配置为准，不凭通用文档猜测。本计划参考[官方sbatch说明](https://slurm.schedmd.com/sbatch.html)和[官方GRES说明](https://slurm.schedmd.com/gres.html)，现场已有四次请求被改写的证据，因此必须检查实际记录。

出口：运行包固定、资源现场可接受、没有未查明提交、预算已批准。缺任一项不进入P04。

### P04 首次真实小规模完整运行（S1验收）

范围：首次单次授权内 batch16、原32条、三个模型及既定controls；不自动重试或顺带追加batch1。

当前：第1–6项均完成。Job724808于9/18 00:18:59以COMPLETED/0:0结束，耗时2分49秒；01:35取回37份文件并独立校验/重算通过，32条及7条controls共产生159条三模型—条件预测。详见[独立验收报告](docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/INDEPENDENT_REVIEW.json)。保留`SMALL_RUN_COMPLETE_NOT_QUALIFIED`身份，不能重提或直接跳全量。

1. 写入唯一提交intent与nonce，记录执行包SHA和批准预算。
2. 仅一次 held 提交，保存返回jobid。断线/响应不明确：仅查询，不再次提交。
3. 复核实际ReqTRES等字段；符合批准范围才按批准策略放行。出现H100/泛型错配则保留held并报告，需另行处理，不能自动同job修复。
4. 计算节点运行：原生版本/设备 → frozen输入 → strict-load formal40/author/valbest33 → 同一真实scene/cue → forward → 保存 → 独立重读/重算 → 输入postcheck。
5. 只读收集日志和回执，保存外部receipt SHA；新本地目录独占下载，离线校验。
6. 同时核对Slurm终态/ExitCode。作业COMPLETED但缺receipt、指标损坏或角色不符，也不能通过。

必须看到真实三模型输出和 `SMALL_RUN_COMPLETE_NOT_QUALIFIED`，外加独立复核记录。这个名称说明**S1走通，不表示S2已经通过**。

停止：新框架在预测前再阻断时，先评审必要性与复现；不得继续堆通用对象守卫。GPU时间到上限就结束；不默认加时。

### P05 数值资格与覆盖（S2）

前置：P04真实路径走通；资格批次总预算另行批准。

运行前固定比较集合和所有执行条件：

| 对照 | 目的 | 要求 |
| --- | --- | --- |
| 原32条，batch16，新的独立进程 | 固定执行冷重复 | 相同源码、权重、场景/顺序、软件/设备类型、seed；不是同一模型对象再次调用 |
| 原32条，batch1 | 对应原始16/1问题 | 与已验证batch16逐trial/条件比较；三模型均需测 |
| 尾批与同伴重排 | 排查batch串扰 | 事先固定17条尾批，以及同一trial在不同同伴/位置中的布局，按trial ID配对而非按行号猜测 |
| 额外确认集 | 扩大工程覆盖 | 在看新结果前按原bank分层固定clean/mixed、干扰数、SNR及controls身份；不得根据模型表现选择 |

原32条并没有覆盖全部场景组合，不能把它当作全量资格的唯一证明。候选扩展到额外固定身份后，重新冻结执行包，并复验受影响小样本路径。

输出：P02比较报告 + 覆盖表；精确输入/状态不变、重复性、batch敏感性三类结论分开。

出口：有可审阅的真实三模型数值结果；旧1e-6未过就记DIFF。没有合法新接受政策时，不因为“看起来很小”进入全量。

#### P05a：最小数值对照（2026-09-18，已复算，batch16/1保留DIFF）

S1已经独立验收；本批完成最直接的两项对照，不修改已跑通的推理源码，也不立即扩展样本。**r1调度失败保留；r2单次作业725677已COMPLETED/0:0，两个159预测产物独立复算通过。冷重复逐位一致，16/1有差异但无类别翻转，旧1e-6仍DIFF。** 详见[结果与完整统计](docs/superpowers/evidence/eager-s2a-production-20260918-r2/review-725677/RESULTS.md)，不得据此自动全量。

基线为Job724808的`batch16`产物：[原始目录](docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/archive/attempts/slurm-724808)，外部固定RECEIPT SHA `58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027`。现有候选SHA `d6f8380de33acee4dd448cd3135eab556a935e32d86598e422e3ace1d29bc3d4`，已有比较器SHA `49076fd6d9436ba2af2179cdb376836e263e72079197c0a4fa618c6f6c06fd95`；本轮复核均未变。

| 执行单元 | 范围 | 与什么比较 | 产物 |
| --- | --- | --- | --- |
| repeat16 | 新Python进程，原32条、batch16、三模型与既定controls | 已验收Job724808 batch16 | 独立冷重复报告 |
| batch1 | repeat16进程退出后，再新建Python进程，原32条、batch1、同三模型/controls | 同一新作业中的repeat16；另与Job724808比较作一致性复核 | batch16/1报告及基线交叉报告 |

已批准资源：**一个新Slurm作业，1张A100、8CPU、64GiB，总上限30分钟；顺序执行两个独立模型进程，不并行、无自动重试、无自动追加作业。** Job724808实际总耗时169秒、scene/预测阶段19.012秒，但这不保证batch1耗时；30分钟是整批硬上限，不是完成时间承诺。

执行清单（r2已完成下列执行和报告；第7项旧1e-6记录为DIFF，不改阈值）：

1. 只实现所需的两进程包装及独占投递/收集记录，复用原候选和比较器；先本地测试进程隔离、第一项失败即停止、输出不覆盖、重复提交拒绝、未知调度响应只查询等路径。已实现`qualification/{control_s2,launch_s2,ship_s2}.py`和`run_s2.sbatch`，18项包装测试与原89项回归通过。冻结包SHA为`f72fd6a1f5f72683d576dde9ebece90bb16ce66cf4c6388442ce9deb587f1839`；当前不可直接提交，因为原生test-only失败。
2. 新目录、新输出子目录，保留S1和全部旧证据；两次各自重新加载checkpoint、配置运行时、建立独立scratch/cache。记录各自PID/时间/退出码及同一jobid，不把“同一对象forward两次”冒充冷重复。
3. 用明确typed A100请求做test-only，单次held提交后核验实际ReqTRES、预算、nonce和脚本；完全符合批准范围才放行。若重现GPU类型错配，保留held并报告，不能自行改资源或再提交。
4. 计算节点核验实际AllocTRES及与S1一致的Python/Torch/CUDA/cuDNN/设备型号，随后运行repeat16。成功生成并校验完整receipt后才运行batch1；任一异常停止，不拼接残缺产物成成功。
5. 两次都成功时应各有32条、7条control子集、159条模型—条件预测；合计318条新增预测。只读下载、校验两个外部receipt SHA，并独立重算各自产物后才比较。
6. 固定输出：S1 vs repeat16的`cold-repeat`报告、repeat16 vs batch1的`batch-size`报告、S1 vs batch1的交叉报告。核对输入/权重/scene/cue/状态和软件设备身份；逐模型/条件报告logits误差分布、NLL/概率误差、预测翻转、Accuracy变化及模型间成对差值变化。
7. 旧`compare_smoke_passes`沿用数值表绝对差`1e-6`及身份一致性检查；超标记DIFF，不因为没有翻转便改写PASS。不事后扩大容差，不根据结果更换主checkpoint。

本批只完成P05中的冷重复与16/1两项，不涵盖17条尾批、同伴重排、额外确认集、256条测成本或10k全量。即使两项通过，也必须继续完成剩余覆盖和既定验收，不能写`COMPARISON_COMPLETE`。

**当前阻断及下一决策：** 新请求同时指定`--gpus=nvidia_a100:1`和`--gpus-per-node=nvidia_a100:1`，原生Slurm25.05.5返回`Invalid GRES specification (with and without type identification)`。候选科学代码未执行；远端`state`只有`DEPLOY.json`、`TEST_ONLY.json`，`attempts`为空。配置显示`JobSubmitPlugins=lua`，但未获得插件源码，不能将具体改写规则当作已确诊。S1先前仅用typed `--gres`通过test-only，实际提交却保存成H100/泛型请求，后经单独授权修正同一held作业才成功；故不能简单退回旧参数并放行。

后续选项：由集群管理员确认能保留typed A100的提交参数；或者另行批准复用S1已验证的“单次held提交、仅在错配时修正同一作业的GPU请求、独立核验后放行”流程。后者需要新的投递授权/冻结包，不能直接复用724808专用命令，也不增加作业数量或时间额度。当前未修改现有冻结包、未重试test-only、未submit/release/update/cancel。

**9/18 08:08更新：** 用户已选择并授权后一流程；新的r2投递包和26项测试完成，原科学候选和两进程启动器未变，旧r1完整保留。r2 release SHA `d534169c3f437df0d6b7434f2187a870b62ee4bc186d59886f73c1bd71f31747`。原生preflight尚未发出：本地共享SSH socket不存在，需用户通过现有连接脚本在终端认证。没有上传r2、提交作业或执行资源修正。当前执行入口、授权和恢复顺序见[r2台账](docs/superpowers/evidence/eager-s2a-production-20260918-r2/EXECUTION.md)，不盲跑旧submit/release。

**9/18 08:25更新（取代上述阻断状态）：** 用户恢复连接后，预检/部署/test-only通过；08:23:25单次提交Job725677，识别实际H100/泛型错配并只修正同一held作业的GPU字段。独立查询确认1 A100/8CPU/64G且Elapsed0，08:24:58单次release。最新squeue/scontrol/sacct均显示08:25:14 RUNNING，spcc-a100g02，实际分配与预算一致，硬结束08:55:14。后续只做status/终态collect与三份独立比较，不再次提交或放行。启动不等于数值资格通过。

**9/18 08:47更新（最新）：** 725677在08:28:44以COMPLETED/0:0结束，3分30秒。收集43文件并校验，S1/repeat16/batch1三份产物均从logits独立复算通过；保存三份数值比较及477行配对差值CSV。原比较器未改，新增离线有符号NLL统计（batch16−batch1，std ddof=0），原12项+新增6项测试通过。冷重复所有模型/条件logits逐位一致；16/1的159条预测无翻转，正确cue最大NLL差formal40=0.000682831、作者=0.000324011、valbest33=0.000713348；含controls总体最大0.001029968（valbest33/silent）。旧1e-6检查仍DIFF，P05其余覆盖和P06接受政策未完成，未授权/执行新GPU作业。完整mean/std/max_abs、模型差距变化及复算入口见[结果报告](docs/superpowers/evidence/eager-s2a-production-20260918-r2/review-725677/RESULTS.md)。

#### P05b：尾批与同伴重排覆盖（当前执行项）

P05剩余覆盖的具体布局、版本扩展要求、独立配对验收与预算提案已整理为[P05b执行设计](checkpoint_compare_workflow_20260917/P05b_remaining_coverage.md)。布局核心上一轮43项通过；新增四进程顺序/独立验收/总超时/桥接门/CSV/本地收集后，整套69项本地测试通过，见[包装证据](docs/superpowers/evidence/layout-sequence-local-20260918-v1/REPORT.md)。9/18后续原生CPU回归亦69项全部通过（28.687秒，Python3.11.5/torch2.1.1+cu118），见[原生证据](docs/superpowers/evidence/p05b-cpu-native-v2hfleb8/REPORT.md)。仅临时传入合成测试代码，已清理，未加载正式checkpoint或初始化CUDA。再后续新增发布/单次held提交/条件放行/有界传输控制器核心15项本地通过，原69项再次通过，见[控制器证据](docs/superpowers/evidence/p05b-controller-local-20260918-v1/REPORT.md)。SSH操作CLI、包冻结、原生前检/恢复查询、下载后科学复算入口及集成验证仍待完成；新增源码与变更sbatch尚未原生复测，真实A100资格仍未验证。未部署正式包或提交额外作业，预算提案未批准。

**9/18后续最新状态：** 已补齐SSH操作入口、显式审批文件绑定、发布包冻结入口、原生只读前检及提交响应丢失后的只读查询。更新整包本地/原生CPU均93项通过，原生25.863秒，[证据](docs/superpowers/evidence/p05b-cpu-native-w6ncfjx5/REPORT.md)。这取代上段“SSH入口待实现”的历史状态；本轮仅临时CPU测试，没有正式发布或Slurm提交。

- [x] 四布局及独立配对比较实现、运行包装与单次投递/传输入口。
- [x] 更新整包原生合成CPU回归；并非真实四布局模型结果。
- [x] 下载后四布局的一条离线科学复算汇总入口：`offline_review.py`，7组对照/987条配对记录；支持外部SHA、终态/节点/进程身份、逐logits复算、失败保留。新增9项测试，整包本地/原生CPU均102项通过（原生62.698秒），[证据](docs/superpowers/evidence/p05b-cpu-native-qry7yvl_/REPORT.md)。这是合成回归，没有新GPU结果。
- [x] 最终冻结检查、P05b明确预算审批（9/18 12:31）、现场预检/test-only、单次held提交Job726428；站点第5次改写typed A100为h100-20c，经用户单独授权做唯一一次同作业GPU字段修正后独立核验放行。
- [x] 真实四布局终态收集与独立复算：726428 COMPLETED/0:0，5分16秒，spcc-a100g04；四进程独立顺序、rc均0。**bridge16与725677 repeat16、cold1与725677 batch1均逐位一致；peers16的correct cue三模型32条logits逐位一致（无批内串扰）；所有跨批形状对照NLL差≤1.03e-3、logits差≤2.13e-3、987条配对0翻转、formal40−author差距变化≤4.4e-5；旧1e-6 canary跨形状均DIFF保留。** 最小top1−top2 margin 0.003，P06须按margin分层说明翻转风险。状态`P05B_OFFLINE_RECOMPUTED_NOT_QUALIFIED`，[完整台账与结果](docs/superpowers/evidence/p05b-production-20260918/REPORT.md)。
- [x] P06数值政策：9/19草案起草并经用户审定生效（五点全部同意）。
- [x] 额外确认集预注册冻结：256条（clean 16 + 20 cell×12，control 60），seed 20260919，仅用bank元数据、排除原32条；记录SHA `d7276913…b35c`。
- [x] P07conf执行包 `same_bank_compare_2026_09_19_confirm_v2`：冻结布局文件、表驱动对照/门槛、成本记录、P06-4 margin分层与P06-3包络检查；本地105项与原生105项（71.149秒）均通过，[设计与记录](checkpoint_compare_workflow_20260917/P07conf_confirmation_cost_batch.md)。
- [x] P07conf批次执行：9/19批准，Job 728280 COMPLETED/0:0（6分12秒，spcc-a100g04；站点第6次改写，唯一一次修正后放行）。bridge16与726428逐位一致；conf32rep16与conf256逐位一致；conf32b1包络内（NLL≤6.43e-04）；636条配对0翻转。conf256 margin分层：formal40 2/256在包络内（min margin 0.0001）。成本：correct 62.6 ms/预测、control 73.3 ms/预测、scene 145 ms/trial；全量外推约81分钟。[台账](docs/superpowers/evidence/p07conf-production-20260919/REPORT.md)。
- [x] P08执行包 `same_bank_compare_2026_09_19_full_v3`：full10k（0..9999原序、625批）+ self32（对全量correct逐位自检、对728280 bridge16逐位桥接）；产物限制提高到256/512 MiB、时限3小时；本地106项、原生106项（410秒，10k合成演练构建24秒/复算7秒）通过。[设计与预算提案](checkpoint_compare_workflow_20260917/P08_full_run_batch.md)。
- [x] P08首次运行：9/19批准3小时预算并确认P06-1细化；Job 728378（第7次GPU改写、唯一一次修正后放行）full10k 48,000条预测完整成功（56.8分钟），但self32.verify因10k bank.csv分块解析bug崩溃，终态FAILED/1:0。离线用修复读取器验证：全量硬校验通过、self32对全量correct逐位一致、control包络内、对728280全逐位；10k margin分层formal40 0.29%/author 0.36%/valbest33 0.23%在包络内。728378产物保留为冷重复基线，不作正式结果。
- [x] P08重跑 Job 728520（v3r2）：COMPLETED/0:0，57分11秒；离线复算全部硬验收通过；self32对728280全逐位、对全量correct逐位、control包络内；**728520与728378两次全量48,000条预测逐位一致**（P06-1全尺度）。10k margin分层：formal40 29/10000、author 36、valbest33 23在包络内。正式产物见[台账](docs/superpowers/evidence/p08full-production-20260919-r2/REPORT.md)第5节。
- [x] P09统计：`checkpoint_compare_workflow_20260917/p09_statistics.py` 只读728520产物（pinned读取器复核），沿用v4 `summarize_results(full_run=True)`（target_speaker成簇bootstrap 10,000次、seed 20260829分层偏移），加P06-4上界与P06-5误差预算；4项合成测试通过。结果：formal40 vs author 全部10k Accuracy差 +0.0175 [+0.0015, +0.0337]，mixed +0.0351 [+0.0181, +0.0517]，clean −0.1410 [−0.1803, −0.1021]；交叉熵改善全部 +0.0265 [−0.0932, +0.1451]（不显著），mixed +0.1261 [+0.0034, +0.2480]，clean −0.8699；低SNR段（−10~−2 dB）formal40显著更好、高SNR段（6~10 dB）author更好。valbest33优于formal40（Accuracy −0.0137 [−0.0236, −0.0041]），但主模型按合同不改。全部分层P06-5可忽略。[报告](docs/superpowers/evidence/p09-statistics-20260919/REPORT.md)，STATISTICS.json SHA `c609fa72…341d`。
- [x] P10交付文档：[P10_delivery.md](docs/superpowers/evidence/p10-delivery-20260919/P10_delivery.md)——中文结论（差多少/哪些条件/不确定性/不可外推）、结果包与SHA清单、一条离线重算命令、历史失败附录。**出版图已于9/20生成**（三张，[FIGURES.md](docs/superpowers/evidence/p10-delivery-20260919/figures/FIGURES.md)），待用户最终图文核对与投稿适配。
- [x] P05额外确认集的真实运行与验证（并入P07conf批次，见上）。

### P06 必要时预先审定新数值政策（S3）

**9/19 已审定生效（用户：“五点都同意 按草案审定”）：** [P06 数值接受政策（已审定）](checkpoint_compare_workflow_20260917/P06_numeric_policy_draft.md)。依据 725677/726428 结果：固定配置逐位一致无容差；无批内串扰；跨批形状扰动记录为包络（NLL 2e-3 / logits 4e-3）而非通过阈值；翻转按 margin 分层报告并给 Accuracy 不确定性上界；扰动需 < 配对 CI 半宽 1/10 才声明可忽略；旧 1e-6 永久保留为 DIFF。五个决定点全部按草案生效；P06 出口达成。用户决定假期内不等管理员答复，沿用 typed 提交+单独授权同作业修正。typed GRES 被站点改写问题的官方说明检索、现场配置查询与管理员询问稿见 [GRES_typed_request_inquiry.md](docs/superpowers/evidence/p05b-production-20260918/GRES_typed_request_inquiry.md)。

仅当排除了输入串扰、训练态、错误加载、非有限值、状态变化等实现问题，但仍存在批形状浮点敏感性时启动。

- 固定正式batch及尾批规则、运行环境、准确率/NLL/成对差值的误差预算和停止条件。
- 用独立确认运行验证，不能看完整10k结果后反推“能通过”的阈值。
- 固定设置自身不稳定先修原因；不能用一个宽阈值吞掉所有问题。
- 记录可分辨范围；若误差足以改变主要结论，增加有明确假设的对照或报告“不足以分辨”。

旧1e-6失败永久保留。新政策需用户审定，不能借“继续执行”自行更改科研判断。

### P07 测成本并冻结正式版（S4）

**9/19 已完成第1–3条（并入P07conf批次）：** 256条预注册分层集在正式路径实测；单位成本 correct 62.6 ms/预测、control 73.3 ms/预测、scene 145 ms/trial，冷启动50 s，峰值显存5.5 GiB；按分支计数外推全量约81分钟，建议一次3小时额度（第4条待批）。第5条冻结正式包前需先处理logits 154 MB超出单文件64 MiB限制的问题。[记录](docs/superpowers/evidence/p07conf-production-20260919/REPORT.md)。

在已验证执行引擎上实现同一代码路径的 `run-profile` / `run-full`；只改变已绑定的trial集合和预算，不另写一套科学推理函数。

1. 预先固定约256条预算测量集，覆盖真实controls密度、音频读取、尾批；它不是替换原10k。
2. 记录冷启动、输入验证、每模型加载、音频/特征、forward、写入、独立复核耗时与峰值GPU/主机内存。
3. 估算全量时间：冷启动/加载 + 各模型条件单位预测耗时×对应48,000预测数量 + I/O/验证开销；用实际分支计数，不简单拿总时长除256。
4. 根据测量明确安全余量，批准**一次**正式全量额度；没有有效测量不承诺几分钟/几小时完成。
5. 冻结完整执行包、数据/模型角色、数值政策、现场资源与收集/复算入口；变更后重新验证相关阶段。

### P08 正式三模型全量评估（S5）

批准后单次提交。原10k顺序不变，每条原始scene和cue由三模型共享；正确cue全量、额外cue仅原2000子集。

硬验收：

- trial ID准确、无重复/缺失/错序，场景/标签身份一致；三模型每个条件计数正确，总48,000。
- 全部strict-load、eval、有限值、状态不变、原生预处理合同成立。
- 独立重读原始输出、重算类别/NLL/概率、模型角色及checkpoint SHA一致。
- Slurm终态、返回码、结果回执一致。失败片段不得拼成完整成功，不自动重试。

输出：逐trial宽表、模型—条件长表、logits或等价可重算原始输出、完整manifest/环境/资源/运行回执。

### P09 统计和科研报告（S6）

全部从通过P08核验的文件读取，不在内存里沿用一次运行的临时结果。

1. 沿用并测试原 v4 `summarize_results(..., full_run=True)` 等统计语义；不要把small-run的“bootstrap未运行”混入正式表。
2. 主表 formal40 vs author_external；补充表 valbest33；Accuracy、NLL、paired delta及95% CI。
3. 预定分层：clean/mixed、干扰数量、SNR；controls列出正确cue收益、shuffled/silent/distractor、probe intrusion及probe概率变化。
4. 相同trial配对、target_speaker cluster bootstrap；CI来自配对差异，不是两个独立均值CI相减。
5. 数值资格结论、数据复用与预处理差异独立一节；不能为了“我训练的模型赢”换数据/配置/主指标。

### P10 可复算交付（S7）

- 完整结果包、SHA清单、唯一正式jobid与执行日志。
- 中文研究结论：差多少、在哪些条件差、不确定性多大、哪些结论不能外推。
- 主表/分层/controls表、必要的出版图；制图时再使用相应科研绘图技能。
- 一条离线重算命令，生成相同统计表；不需要重新提交GPU。
- 历史失败清单作为附录，和最终有效结果分开保存。

**任务完成定义：用户拿到可追溯、可复算的三模型比较结论及限制说明；不是拿到SUBMITTED，也不是测试数又增长。**

## 5. 统一状态词与失败分支

| 状态 | 意义 | 下一动作 |
| --- | --- | --- |
| LOCAL_CHECKS_PASS | 本机检查通过 | 继续准备原生流程，不声称真实推理通过 |
| TEST_ONLY_REJECTED_NO_JOB | 调度预检拒绝，尚无实际提交 | 保存失败请求，查明参数/站点兼容性；禁止跳过预检提交 |
| SUBMISSION_UNKNOWN | 提交响应不确定 | 只读查nonce/job；禁止重提 |
| HELD_RESOURCE_MISMATCH | 资源不在批准范围 | 不放行，报告并处理权限/集群规则 |
| PENDING / RUNNING | Slurm排队/运行 | 只读查询，不再submit |
| EXECUTION_INVALID | 执行/来源/输入/状态不合法 | 收集完整失败证据，停止数值解释 |
| SMALL_RUN_COMPLETE_NOT_QUALIFIED | 最小流程与产物重算完成 | 进入数值资格，不做总体比较声明 |
| NUMERIC_SENSITIVITY_RECORDED | 得到有效的对照数值 | 按既定政策审阅，不自动PASS |
| SMOKE_VALID | 已有明确资格政策且真实确认通过 | 测成本、冻结正式版 |
| COMPARISON_COMPLETE | 全量产物和独立复算已验收 | 完成统计/科研交付 |

## 6. 本轮执行记录（只填实际发生的事）

- 开始时核对：上一轮候选五个文件SHA全部一致；未发现已修改的候选文件。运行前后原v4 evaluator/runner与候选固定SHA一致。
- 已执行 P01/P02：统一入口创建独占证据目录，候选21项 + 原v4 56项 + 新比较工具12项，共 **89项测试通过**；两个CLI帮助检查返回0；静态检查通过。
- 环境：本机 macOS 26.1 arm64、Python 3.11.15。合成模型/checkpoint与声明用于回归，不能冒充HAKUSAN正式模型或原生GPU验证。
- 实际运行报告：[REPORT.json](docs/superpowers/evidence/eager-local-execution-20260917/20260917T135216Z-ry39bmqd/REPORT.json)。SHA：`37c978860a531143905cc2bcd967aa0a9dae4543e2b0081db74fb3e5599ea947`。各组命令、返回码、测试数、耗时、日志SHA和源码SHA均在其中。
- 原始日志：[候选21项](docs/superpowers/evidence/eager-local-execution-20260917/20260917T135216Z-ry39bmqd/candidate_tests.log)、[原v4 56项](docs/superpowers/evidence/eager-local-execution-20260917/20260917T135216Z-ry39bmqd/original_v4_tests.log)、[新工具12项](docs/superpowers/evidence/eager-local-execution-20260917/20260917T135216Z-ry39bmqd/workflow_tests.log)。
- 后续“开始吧”确认单次小样本预算；已完成现场预检、上传和test-only，23:40:37 JST单次提交Job724808，尚未放行。
- 初次提交状态：`PENDING/JobHeldUser`，Elapsed0，AllocTRES空；请求被保存为H100，故停止。原推理候选未修改。
- 本轮又复跑89项本地测试；投递14项测试通过但原生字段覆盖不足，随后据真实Job724808记录新增8项回归并验证修复提案；完整日志都在[执行台账](docs/superpowers/evidence/eager-small-production-20260917/EXECUTION.md)。不把合成调度记录或修复后的测试副本冒充远端状态。
- 9/18用户回复“好的”批准控制与资源修复，但不直接放行。35项投递/解析/修复回归通过；完整归档原包后只替换控制文件，单次更新724808的A100请求；原清单、科学代码、launcher、Slurm脚本、原预算/回执均保留。
- 9/18 00:07 JST末次独立核验：原包归档与修复绑定通过，scontrol/sacct均为1A100/8CPU/64G/30分钟，仍`JobHeldUser`、Elapsed0、未分配。无新sbatch、release、requeue或cancel。原始修复回执及SHA在[执行台账](docs/superpowers/evidence/eager-small-production-20260917/EXECUTION.md)。
- 9/18用户再次回复“好的”，批准放行同一724808；42项本地控制测试通过。00:16:04单次release返回0；独立查询确认00:16:10开始RUNNING于spcc-a100g07，实际资源符合批准范围；未新建作业。下一项是终态/产物核验，不把启动或控制测试PASS等同于科学结果通过。
- 9/18用户要求“检查”：只读查询确认00:18:59 COMPLETED/0:0，耗时2分49秒；独占下载37份文件并校验全部SHA，使用已固定验证器从保存logits重算159条预测/指标，核验三个严格加载报告、原32条身份、历史scene绑定、运行设置及真实Slurm/LAUNCH一致性。P04/S1通过，报告与原始日志保存在执行台账末节。P05/S2未开始，未新增作业，未改变容差或研究身份。
- 随后“下一步”：复核现有候选已支持batch16/1、比较器支持同一作业中不同进程身份；新增上方P05a的固定基线、两进程顺序、比较矩阵和单作业30分钟预算提案。尚未获得新GPU预算批准，因此没有上传、提交或修改远端状态；也未修改固定候选README/源码及SHA清单。
- 随后“好的”批准P05a预算。本轮实现两进程顺序包装，原89项回归和新增18项包装测试通过；完成现场预检及新根目录部署。S1、原v4、三模型及候选科学源码均未修改。
- 9/18 02:46 JST，唯一一次S2a `sbatch --test-only`返回1：带类型/不带类型GRES冲突，外层ACTION_RC=2。后续只读复核原始记录、队列、Slurm版本/配置，确认无S2a提交intent、回执、attempt或活动作业。当前状态为`TEST_ONLY_REJECTED_NO_JOB`；不是GPU运行失败，不宣称已有新结果。详见[S2a台账](docs/superpowers/evidence/eager-s2a-production-20260918/EXECUTION.md)。
- 下一轮“好的”批准预算内同作业GPU修正。r2本地26项测试通过并冻结；原生preflight在本地连接检查阶段失败，直接只读SSH检查确认socket缺失。已请求用户终端认证；此轮没有远端请求/上传/提交/更新/放行。恢复时不需再次批准同一预算，按[r2台账](docs/superpowers/evidence/eager-s2a-production-20260918-r2/EXECUTION.md)继续。
- 用户随后“ok”：共享连接恢复，08:16起按既定预算执行preflight/deploy/test-only；单次提交725677、单次GPU修正、独立核验后单次release。08:25:14已RUNNING于spcc-a100g02，实际1 A100/8CPU/64G/30分钟；数值结果未验收，不追加作业。
- 用户要求补充NLL有符号统计后“开始下一步”：只读收集并验收725677终态和43文件，完成三份比较；mean/std/max_abs覆盖各模型/条件，CSV可逐条复核。冷重复PASS、16/1旧阈值DIFF且无预测翻转；未改模型、阈值或全量资格。见P05a最新更新和结果报告。
- 9/18用户要求“检查项目判断路线是否合理”：结论为科学路线正确、但每个小作业前的工具工程开销在重新膨胀；建议脚手架冻结、P06并行起草、确认集与P07合并。随后用户“能带我跑接下来的内容吗”并明确批准P05b预算（12:31）。依次冻结→预检→发布→test-only→单次held提交726428；首次release因站点改写GPU为h100-20c被远端核验拒绝（未放行），用户单独授权后唯一一次同作业GPU修正，独立核验后12:45单次放行；排队（Resources）后于9/19前COMPLETED/0:0，5分16秒。只读收集、离线复算7组对照987条配对全部完成，0翻转，固定配置及同伴重排correct cue逐位一致。未改模型、阈值或全量资格；[台账](docs/superpowers/evidence/p05b-production-20260918/REPORT.md)。
- 9/19用户“五点都同意 按草案审定 继续下一步…能先不考虑h100吗”：P06生效；假期内不等管理员，沿用typed提交+单独授权同作业修正。随后只读下载bank元数据（SHA核验一致）、预注册256条确认集，派生v2执行包并完成本地/原生各105项合成回归；未冻结包、未发布、未提交。
- 9/19用户批准P07conf预算（含站点改写时唯一一次同作业修正）：冻结→预检→发布→test-only→单次held提交728280→第6次h100-20c改写→唯一一次修正→独立核验放行→放行后共享SSH因12小时空闲到期断开，用户终端重新认证→COMPLETED/0:0 6分12秒→只读收集90文件→离线复算4组对照636条配对全部完成、全部门槛通过、包络内、0翻转；成本记录与全量外推写入台账。未改模型、阈值或全量资格。
- 9/19用户“好的”进入P08设计：派生v3全量包（10k原序布局、self32自检、v2基线读取、full_run硬校验、限制与时限调整），本地/原生各106项通过并完成合成10k演练；写出预算提案与P06-1实施细化说明（correct逐位、control包络）。未冻结、未发布、未提交。
- 9/19用户批准P08预算（含P06-1细化）：冻结→预检→发布→test-only→单次held提交728378→第7次改写→唯一一次修正→放行→排队约50分钟→运行58分06秒后FAILED/1:0：两个模型阶段均完整成功，self32.verify因pandas分块类型推断bug崩溃。只读收集42文件；在冻结包副本上仅补读取器离线验证全部科学门槛通过并在真实bank.csv上复现/验证修复；修复包v3r2本地74+33通过。用户询问后选择用v3r2同预算重跑一次，728378作为10k逐位冷重复基线。
- 9/19用户选择用v3r2重跑：原生107项通过→冻结→预检/发布/test-only→单次held提交728520→第8次改写、唯一一次修正→放行→57分11秒COMPLETED/0:0→只读收集46文件→离线复算与全量冷重复比较全部通过。未改模型、阈值；未做统计。
- 9/19继续P09：实现p09_statistics.py与4项测试，在728520正式产物上计算（14.9秒）；输出STATISTICS.json/REPORT.md/paired_strata.csv于docs/superpowers/evidence/p09-statistics-20260919/。未改任何阈值或模型。
- 9/20用户确认第一轮勘误后要求制图：按科研绘图规范用 `p10_figures.py` 从 STATISTICS.json 生成三张图（模型分层表现、配对差值森林图、cue controls），Okabe–Ito 配色+形状冗余，PNG 600 dpi RGB / PDF Type 42；元数据检查通过；写出图注/替代文本 FIGURES.md 与 MANIFEST.json。未改任何数值。

以后继续更新本表，不为每个小步骤再创建一份互相矛盾的总计划。完成到哪个出口就写哪个出口，不把“入口测试通过”写成“checkpoint比较完成”。
