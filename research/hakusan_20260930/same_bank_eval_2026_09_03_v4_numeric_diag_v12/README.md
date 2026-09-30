# formal40 批大小数值诊断工具

状态：独立诊断 v12 本地候选；尚未正式部署、冻结或提交。远端完整模型/A100
尚未验收，不能把本地回归当作原 NLL 问题解决或模型比较完成。
下方远端命令不是当前执行指令，须经复审、同版本实际路径验证及受控部署。
诊断 v1–v11、原冻结评估 v4 和所有失败作业证据必须保留，不能原地替换。

## v12 原 runner 环境恢复与异常链记录

用户批准后，以已发布 v11 R2 十六文件为基线。原 Job682295 仅留下
frozen reference prediction failed，不能认定 GPU 根因。独立确认 v11
遗漏原 v4 runner 的三个固定 export；v12 由 child_environment 固定生成
CUBLAS_WORKSPACE_CONFIG=:4096:8、OMP_NUM_THREADS=8、
TOKENIZERS_PARALLELISM=false，不继承父进程任意值。原 runner bootstrap
已使用 coordinator_environment 在数值库导入前 exec，故不复制第二份
环境逻辑。现有精确环境校验、启动环境记录及每个 child exec 路径保持。

CLI 的补充 stderr 记录至多六层异常和每层六个帧位置，帧遍历上限128。
只写静态类型/文件 basename/函数/行号与固定原因分类；不输出底层原始消息、
args、局部变量、张量、源码行或环境。分类只是定位提示，不等同于根因结论。
保留原顶层 JSON/退出2；补充日志失败不覆盖原失败。原594项回归只变更
协议/路径版本字符串，新增启动环境和异常日志测试。

模型、bank、AMP/TF32/compile、六个运行标志、矩阵、科学阈值及工程预算不变。
详见 `../docs/superpowers/evidence/2026-09-10-diagnostic-v12-runtime-repair.md`。

## 历史：v11 注册表兼容性修复

R2：真实torch2.1.1严格加载后，扩展清单中三个普通list-held音频模块原生
training=True，未受model.eval()递归影响。新增原生注册树eval检查，保持这
三个标志不变；完整执行依赖清单、状态/参数冻结及training live指纹不删减。
禁止通过额外eval()调用修正输入行为。test_native_eval_scope.py覆盖注册树
全eval、原生列表模式保留、后续模式变动拒绝、trainable状态拒绝及冻结源码。
R1包/清单保存在snapshots/v11-ordered-registry-r1；R2使用独立清单。

Job681974的直接错误已在原v10/真实torch2.1.1/formal40 CPU重现：严格加载
61个state keys、训练参数覆盖1.0后，67个已发现模块的201个注册表均为
collections.OrderedDict，旧快照只接受精确dict而拒绝。没有可解释的数值矩阵。

v11统一原生注册表读取：仅精确dict/OrderedDict，使用未覆盖的原生items、
保留OrderedDict执行顺序，先预算和字符串键检查。应用于模块发现、静态注册
属性、参数冻结验证、状态身份和内容快照。列表内audio transform模块亦纳入。
配置/hook中的精确OrderedDict用其原生顺序；子类不走callable绕过分支。
没有将任意Mapping变成可信注册表。普通dict子类在原通用配置路径的既有
底层dict读取行为保留，不用于模块注册表。快照schema、张量字节算法未变。

新增test_ordered_registries.py覆盖注册表顺序、子类拒绝、无覆盖方法执行、
共享状态去重、scalar buffer、状态替换/原位变动、audio模块及hook重排。
原561项回归保持（仅协议/root版本递增）；详见证据文档。
有序映射原生迭代会重新hash键，因此注册表在迭代前通过底层dict.keys校验
精确字符串键；通用OrderedDict仅接受原生不可变键树，拒绝自定义hash/eq键。
新增24项回归，包含自定义键不得执行及键嵌套预算测试。
原模型、checkpoint、bank、AMP/compile/TF32/矩阵、NLL容差和600000工程work
预算均不变。CPU探针需覆盖完整快照/RNG/重复指纹，不能当作GPUworker或数值PASS。

## 历史：v10 修复范围与验收边界

v9 的实际 2.1.1/formal40 临时 CPU 检查严格加载全部参数，但完整执行指纹
在第一个卷积块的标准 Module._call_impl 处耗尽 200000 工作量；当时仅有
121 个不同可调用节点。相同现象已用 67 个真实 PyTorch 小模块本地复现。

v10 在每个有界检查内复用精确 code object 的不可变反汇编结果，保留强
引用防止 id 重用，不跨检查保留缓存。新的不同 code object 仍计费，超大
代码在反汇编前即拒绝。所有 live 绑定、闭包、默认参数、属性、bound self、
hook、模块配置及注册张量状态仍逐次重新读取，指纹格式不改。
第一轮真实 formal40 CPU 探针仍触及工作量上限，未完成；原候选及失败证据
已保存在本地快照，不能继续使用第一轮清单验证当前源码。

R2 进一步避免重复构造固定 None/default tuple 的 anchor 表示。每次重新
读取函数/code/defaults/kwdefaults绑定；只有精确 tuple 且全部元素为精确
不可变标量时才同检查复用。可变容器、嵌套结构、子类、callable仍走原逐次
检查，不增加其原有语义覆盖。保持强引用、身份匹配、检查隔离及预算预检。

R2真实formal40已走完40/67模块，但仍耗尽200000次工程工作量；不是节点
爆炸。R3相对R2的生产改动仅一行：固定工作量上限200000→600000。明确修订
此前保持原工程上限的计划，不将此调整冒充科学数值容差不变的同一概念。
按40模块约20万估计67模块约33.5万，加有限余量；必须再实测，不由估计宣称通过。
仍保留节点10000/嵌套96/配置深度12/冷进程时限/工件1GiB上限，不能传参提高预算。
没有省略子模块或缓存live指纹；模型、bank、compile/AMP/TF32、矩阵、原
canary容差及模型角色全部不变。R1和R2十四文件清单与失败探针均保留。

R2新增24项预算回归，加原535项总计559项曾通过；R3增加固定新边界及不可
调用者覆盖的回归，完整验收结果记录在下方证据文档。67 模块结构检查
work=97817，6 个 code objects 只反汇编 6 次；去掉复用会再次失败。
缓存/不缓存的小模型指纹逐项相同；默认参数记录与原 sealer 格式相同。
去掉两种复用的三项退化均被回归捕获，旧 v9 固定文件保持不变。这里只是本地
2.12.1 的结构回归；仍须真实 2.1.1/formal40 CPU 路径及实际 GPU 诊断验收。

详见 `../docs/superpowers/evidence/2026-09-10-diagnostic-v10-budget-repair.md`。

## 历史：v9 修复范围与验收边界

Job 680910 的实际错误是 `unsupported execution mapping type`，指向
`root.class[__init__].resolved[os.environ]`、类型 `os._Environ`。
冻结数据集构造器有 `os.environ.get("CV_CLIPS", clips_dir)`；初始 6 项
本地回归复现该拒绝，包括真实数据集类图与 CPU 合成 worker 配置签发。

v9 只接受进程导入时捕获的原始 POSIX 文本环境对象及其别名，拒绝克隆、
子类和对象替换。使用精确底层 bytes 字典制作有长度分隔的进程私有密钥
摘要，不调用可覆盖的环境迭代/读取方法，不把环境名称或值写入指纹/错误。
方法、代码、默认值、编解码闭包和底层字典绑定变更仍拒绝；环境内容变化
会改变指纹并使已签发 worker 失效。上限 4096 项、4 MiB，沿用共享预算。
这是 Python 映射的同进程一致性校验，不是跨进程摘要，也不保证发现绕过
Python 映射的原生 putenv 修改。进程私有随机密钥不改变 Python/Torch RNG。

扩展导入 SHA 绑定的完整模型类后，构造器依赖图另发现 `TorchVersion` 被当作
未知集合拒绝。v9 为精确类型记录对象、类型、原始字符串和方法绑定，限制
256 字符/128 类型成员，拒绝子类及额外实例属性；不执行重载的字符串/比较
方法，不替换 torch.__version__。此发现来自本地扩展检查，不能说是远端
Job 680910 的另一条已观察错误；也不能据此宣布所有真实 worker 属性兼容。

`test_environment_mapping.py` 包含环境、版本对象、隐私、方法篡改、预算、
worker 撤销与完整数据集/模型类的依赖图检查。真实类已导入，未实例化，
未加载正式 checkpoint、音频或做 GPU 推理。完整数据集类还作为 CPU 小模型
的 dataset 配置参与真正的签发/重验路径；其他部件仍是合成夹具。
本地依赖为 Python 3.11.15 / torch 2.12.1 CPU，不等同于集群 2.1.1+cu118。

最终八入口合计 344+66+6+28+21+14+26+30=535 项通过；恢复旧分支、遗漏
摘要/方法/私有密钥/长度分隔/版本绑定等七种内存退化均被回归捕获。
Ruff、runner bash -n、两个 CLI help、逐节点 AST 范围及旧候选 SHA 检查通过。
这是主代理本地自查，没有新增独立代理审查，也没有超算实测结论。

不修改模型、bank、AMP/TF32、运行配置顺序、矩阵、原数值阈值或模型角色。
v9 没有新的 freeze SHA/Job ID，不能复用 v8 freeze，也不能重提 Job 680910。
完整执行结果：`../docs/superpowers/evidence/2026-09-10-diagnostic-v9-environment-repair.md`。

## 历史：v8 修复范围与验收边界

诊断 v7 Job 680519 失败，stderr 为 `unsupported execution collection type`。
结果不可解释，matrix=null，PRE/POST 同 SHA。哈希一致的冻结模型源码中
`_amp_overflow_window` 是 deque；源表达式与最小模型配置指纹已重现相同错误。
torch.Size 也被旧分支拒绝。远端错误没有属性路径，不能认定 deque 是首个或
唯一触发点，不能把该错误解释为模型损坏或比较结果。

v8 仅在执行配置指纹中支持精确的 `collections.deque` 和 `torch.Size` 类型：
deque 记录对象/类型身份、maxlen、元素顺序和递归内容；torch.Size 记录对象/
类型身份与整数维度。继续使用共享工作/深度预算；拒绝 deque 子类及未知
集合，不能按类型名称冒充。未知类型错误增加有界属性路径与静态类型名，
不调用容器 repr、迭代重载或元类属性。嵌套错误保留原路径和预算原因。

不清空模型 deque，不改成 list，不跳过 `_amp_overflow_window`，不放宽数值
阈值。可调用子项不执行，但其函数图仍被记录；Tensor 只记录对象身份，
不读取、复制或同步数据，注册参数/缓冲区的版本校验仍沿用原逻辑。

新增 `test_execution_collections.py` 的 26 项覆盖：源 SHA 绑定的 deque 构造、
精确形状维度、修改内容/顺序/容量/对象、递归/预算、未知及恶意类型、可调用
子项变更、数据不读取、worker 签发与重验，以及满 1000 项窗口的预算检查。
源表达式从本地只读 `src/spatial_attn_lightning.py` 提取，SHA 必须为
`6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9`；测试
没有导入该完整模型，也没有加载真实 formal40/checkpoint/音频。

本地七个独立测试入口合计 344+66+6+28+21+14+26=505 项通过。
恢复旧分支及遗漏身份/容量/内容/维度等六种内存退化均被回归捕获。
Ruff、runner 语法、CLI、AST 范围和旧候选 SHA 检查通过；没有新增独立代理审查。

本地 Python 3.11.15 / torch 2.12.1 CPU 与生产 2.1.1+cu118 / A100 不同，
合成 worker 的成功不能证明真实模型全部属性兼容或原数值差异已解释。
以上为 v8 当时的本地修复记录；其后已提交 Job 680910，失败见 v9 节。
不重提 Job 680519/680910。原 v4 科学文件、配置顺序、AMP/TF32、矩阵和容差均不改。
执行记录：`../docs/superpowers/evidence/2026-09-09-diagnostic-v8-collection-repair.md`。

## 历史：v7 修复范围与验收边界

诊断 v6 Job 671724 在模型加载前失败：`frozen runtime settings are not exact`。
集群 PyTorch 2.1.1+cu118 新进程探针确认，原冻结配置先设 medium，再开启
cuda.matmul.allow_tf32 后读回 high。v6 将两个相互联动的设置视为独立字段，
错误要求最后仍为 medium。

v7 不改冻结 evaluator 的任何设置或顺序，只将 worker、冷参考等价、cell、
持久 worker 验收统一到同一个不可变、类型严格的六项最终读回预期：
deterministic_algorithms=True、cudnn_deterministic=True、cudnn_benchmark=False、
float32_matmul_precision=high、cuda_matmul_allow_tf32=True、cudnn_allow_tf32=True。
禁止读取异常时代填 medium/high。实际值、期望值及读取异常会进入错误说明，
live worker 还报告 torch 版本；它不会重排、重设或“修复”任何运行标志。

v7 当时的本地 Python 3.11.15 / torch 2.12.1；六个独立测试模块合计 479 项通过。
新增 14 项覆盖固定 SHA 的真实 `_configure_runtime` 源码与显式 2.1.1 API
语义模型、worker 入口、四处严格验收、全部字段篡改拒绝，以及真实本地 getter。
本地新版 torch 在原调用顺序后读取抛错时必须拒绝，不再伪装为兼容成功。
既有 CPU 玩具模型夹具直接设置 high，明确只模拟生产最终状态，不冒充真实
冻结 setter 顺序或 A100 运行；真实顺序在独立回归中由冻结源码执行。

原评估 v4、诊断 v6 和所有旧失败证据均保留。bank/checkpoint/SNR/角色、
AMP/TF32 实际设置、执行矩阵与数值阈值均不变。这是 v7 本地修复阶段记录；
其后已部署并提交 Job 680519，失败情况见上文，不能再次提交旧作业。
证据：`../docs/superpowers/evidence/2026-09-09-diagnostic-v7-runtime-contract-repair.md`。

## 历史：v6 修复范围与验收边界

诊断 v5 Job 670830 在执行前读取外部 v4 input_freeze.json 时失败：
`noncanonical owner JSON`。原 v4 的 SHA 固定清单是 indent=2 的 JSON；
协调器错误地对它施加了诊断自身紧凑 JSON 的格式约束。audit/check-only
读取路径没有同样的格式要求；协调器测试夹具也错误地采用了紧凑格式。

v6 先用 SHA 核验过的真实 v4 序列化函数修正文件系统夹具，复现 PRE、matrix
入口及结果验证链路失败。修复仅增加固定 v4 清单专用读取入口，在解析前校验
原始字节 SHA，并按 v4 的缩进/排序/末尾换行规范核验；PRE/POST、matrix 和
成功结果验证共同使用该入口。绝不重排或回写原清单，也不重新设定可信哈希。
诊断自身的 freeze、journal、terminal 等仍使用严格紧凑 JSON 读取器。

新增 test_v4_manifest_json.py 覆盖真实 v4 格式、错误哈希、格式错配、重复键、
非有限数、符号/硬链接、读取期竞争与真实 PRE/POST、CPU 持久化矩阵结果复验。
CPU 合成矩阵不是实际 formal40/A100 实验；本地通过不能证明完整集群运行成功，
也没有解释 Job 646900 的 NLL 差异。模型、bank、SNR 和原数值容差均不变。

2026-09-08 本地验收：344 + 66 + 6 + 28 + 21 = 465 项测试通过；
五个入口分别在独立 Python 进程执行。Ruff check/format、runner bash -n 和
CLI help 检查通过。本地 Python 3.11.15 / torch 2.12.1；没有新独立代理审查，
没有连接集群，不能将该候选视为已发布或已完成 A100 端到端验收。
证据：`../docs/superpowers/evidence/2026-09-08-diagnostic-v6-json-boundary-repair.md`。

## v5 修复范围与验收边界

v4 独立复查发现：真实 strict_load_model 合法导入 src.spatial_attn_lightning
时，其模块绑定从未加载变为授权对象，仍被固定函数图误报。v5 的回归先在
未修复逻辑上复现失败，再限定处理为：只有固定 SHA 加载器签发的那个真实
strict_load_model 对象、那一条确定的 src 导入使用快照授权身份；不再于签发
阶段从进程搜索路径提前加载 src。在有效快照作用域内仍核对来源、声明与
模块绑定；普通函数、其他导入和 torch/yaml 依赖继续固定绑定。

专项覆盖授权 src 导入、未经授权替换、普通同名导入不获例外、缺失源声明、
封闭后新增导入，以及真实冻结 strict loader 加载临时 CPU checkpoint、封闭
模块绑定后再次推理并复验 evaluator 图。
后者使用小型夹具模型，不是真实 formal40，也不证明 A100 兼容性或原始数值
差异原因。冻结评估 v4、checkpoint、bank 和数值阈值均未修改。

## v4 修复范围与验收边界

v3 的真实 evaluator 在临时模块退出和合法导入后出现函数图误报。本候选仅对
固定 SHA 验证过的导入上下文读取器，使用进程模块注册表身份与冻结快照模块
授权检查；普通函数仍检查容器内容。冻结模块的替换、源码篡改、函数代码和
模块来源变化必须拒绝，作用域退出后回调失效。生产 worker 准备完毕后封闭
模块绑定集合。直接 import 的模块绑定和可解析属性仍纳入函数图。

本地 PyTorch 的 Dynamo 首次导入会包装 torch.manual_seed，因此必须在签发
不可变函数图前导入 Dynamo；签发之后不重新设定基线，也不放过函数替换。
新增 test_real_evaluator_scope.py 使用真实冻结 evaluator 源码和临时快照夹具，
不代表真实 checkpoint、音频或 A100 端到端验收。原始数值阈值保持不变。

## v3 修复范围

v2 实际 audit 在生产 capability 注册时失败：外层以 v4 根目录读取 evaluator，
加载器以 tools 为根目录，记录中的 relative_path 不同。v3 给加载器增加显式
allowed_root，外层传入同一个 v4 根目录；保持精确记录比较、哈希校验和路径
边界拒绝。其他调用者不传该参数时保留原先父目录基准。

新增 test_loader_record.py 覆盖真实双读取、真实 capability 注册、外层上下文
调用、错误 SHA 与越界拒绝。临时 evaluator 和科学 inventory/history 验证夹具
不等同于真实模型/GPU 端到端验收。诊断根和诊断协议提升 v3；v4 身份、32
trial 数值诊断设计、batch-size canary 阈值和模型角色不变。

## v2 修复范围

真实 v4 freeze 的五组输入共 24 项，加上 layout.evaluation_lock 共 25 项。
v1 错把布局锁纳入输入计数，并在下游要求锁属于该集合，导致 audit-inputs
在冻结前失败。v2 按冻结 v4 原始五组、仅遍历 mapping 的规则收集 24 个角色，
保留重复路径角色和顺序；布局锁另行核对固定路径、大小、SHA 与实际内容，
协调器 PRE/POST 仍绑定锁。没有把 24 改成 25，也没有放宽锁或数值门槛。
测试以带 layout 的真实结构形状为基础，并直接对照冻结 v4 源码中的遍历函数。
诊断根和诊断协议版本改为 v2；冻结 v4 身份及科学评估协议不变。

## 目标与已知事实

最终目标是 formal40、valbest33 和作者 checkpoint 的同 bank 对比。本包只解决
之前的数值一致性阻塞，不执行三模型完整 10k audit，也不重新训练模型。

v4 smoke Job646900 在 2026-09-01 完成两次 32-trial 推理后失败：
`formal40_nll max_abs=0.0077362060546875`。这证明批大小 canary 不一致，
并未证明模型损坏、预处理错误、AMP 或 TF32 是原因。本包不放宽原有阈值，
不修改 v4、bank、checkpoint、SNR、模型角色或科学协议，不发布 SMOKE_PASS。

所有产物仍属于 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，
不能称为独立测试成绩。作者模型最终只作为 system-level external reference，
不是任务条件完全匹配的模型排名。

本包仅加载 formal40，改变了 Job646900 三模型同时驻留的分配上下文。
即使 A2 不复现，也不能排除原始多模型驻留或编译器缓存上下文的影响。

## 文件与固定身份

十四个文件：诊断入口 `diagnose_batch_invariance.py`、追踪原语 `numeric_trace.py`、
单次提交器 `submit_numeric_diag.py`、runner `run_numeric_diag.sbatch`、九个
`test_*.py` 和本 README。远端生产 tools 只放前四个文件；测试和 README 保留本地。

固定诊断根：
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v11`

冻结 v4 根：
`/home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4`

诊断协议：`formal40_batch_invariance_diag_20260903_v11`。
v4 协议：`fullpilot4_same_bank_audit_20260829_v4_nfs_portable_identity_v1`。
训练 run：`fullpilot4_accum9_20260815_181000`，formal40 为 epoch40、global_step69440。

| 冻结对象 | SHA-256 |
| --- | --- |
| v4 evaluator | `31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4` |
| v4 runner | `b3531dce087b781a57b17e2ced9fecf570d6a7b1b56b5d32e6581b6dc1d59495` |
| v4 input_freeze.json | `1f6a881098ee298ce5ff3392cca9aa62ced0760e93b56f00355dd32d33114ce5` |
| v4 evaluation.lock | `63e6a3c031802b31928037aa246d87b7f29d18be9463bbe29739becbb1f1f710` |
| formal-final.ckpt | `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff` |

其余输入身份由上述 v4 manifest、24 项 pinned files、冻结快照源清单、选定
32 个 trial 及所用音频清单共同绑定，不能用当前工作目录文件替代。诊断 freeze
是以后在新根生成的新文件，其哈希不是上表中的 v4 manifest 哈希。

## 本地校验与测试（Mac）

先进入本 README 所在目录。下面只读验证已记录的十三个候选哈希，不是重新生成
expected 值。最终发布还须在外部验收记录核对 README 自身哈希。

```bash
sed -n '/^<!-- RELEASE_SHA256_BEGIN -->$/,/^<!-- RELEASE_SHA256_END -->$/p' README.md |
  sed '1d;$d' |
  /usr/bin/shasum -a 256 -c -
```

```bash
P=/opt/anaconda3/envs/audattn/bin/python
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
"$P" -I -B test_numeric_diag.py
"$P" -I -B test_submit_numeric_diag.py
"$P" -I -B test_loader_record.py
"$P" -I -B test_real_evaluator_scope.py
"$P" -I -B test_v4_manifest_json.py
"$P" -I -B test_runtime_contract.py
"$P" -I -B test_execution_collections.py
"$P" -I -B test_environment_mapping.py
"$P" -I -B test_execution_budget.py
/bin/bash -n run_numeric_diag.sbatch
ruff check --no-cache .
ruff format --check --no-cache .
```

各命令必须退出 0。模拟集成启动五个真实本地进程，但使用合成 CPU 张量、GPU
元数据和调度器响应；实际验证了传输、持久记录和验收链路，不代表 A100 结果。
九个测试入口必须分别使用独立 Python 进程；合并 discover 会因现有模拟集成
重新加载诊断模块而触发 `_numeric_trace_verified` 名称占用保护。
新专项还依赖本机 `/Users/gigi/projects/auditory_attention` 的指定源文件及
现有音频/Lightning 等导入依赖；逐个核对源码 SHA，不跳过缺失或哈希不符。
导入完整类可能初始化依赖的临时缓存，但不调用类构造器或加载模型权重。

## 发布流程：仅在 Task 9 发布复审通过后

1. 在 Mac 核对外部验收记录中的 README 哈希及上面的十三个文件哈希。
2. 只使用固定的新诊断根；若已存在，停止并只读检查，不能删除、覆盖或自动重试。
3. 在新根 staging 上传四个生产文件，逐一核对本 README 的预期哈希；拒绝符号链接。
4. 以 create-once 操作发布到 tools，核对最终文件身份后才清理本次 staging。
   不能覆盖既有 tools，也不能修改或清理 v4 与失败作业证据。
5. audit → freeze → 人工核对新 freeze 哈希 → check-only → 单次提交。

这是受控部署流程，不是授权执行。实际创建／上传命令由 Task 10 根据远端只读
检查结果给出，不能靠重复运行整个部署块恢复。

## 远端命令契约（HAKUSAN；现在不要运行）

以下命令仅用于发布批准后已创建、已核验的根。使用短变量和数组，避免把参数
中间的换行当成新命令。不要把中文说明或提示符复制进终端。

```bash
R="$HOME/audattn_external_eval_diag"
R="$R/same_bank_v4_job646900_2026-09-03_v11"
P="$HOME/miniconda3/envs/attn/bin/python"
D="$R/tools/diagnose_batch_invariance.py"
S="$R/tools/submit_numeric_diag.py"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED=0
"$P" -I -B "$D" audit-inputs
```

audit 通过后，只 freeze 一次。失败时保留现场，不重新创建根或复用 v4 的 freeze。

```bash
A=(freeze-inputs --confirm-protocol)
A+=(formal40_batch_invariance_diag_20260903_v11)
"$P" -I -B "$D" "${A[@]}"
```

从已审阅的 freeze 输出／外部记录输入新诊断 freeze SHA，不能自动对当前文件
计算哈希后把它当作可信 expected 值。check-only 通过后才考虑提交。

```bash
read -r -p 'Reviewed diagnostic freeze SHA-256: ' F
A=(check-only --expected-input-freeze-sha256 "$F")
"$P" -I -B "$D" "${A[@]}"
```

下列提交器先验证输入、队列和持久记录，然后最多调用一次 sbatch。不要直接
调用 runner、协调器或内部 `_child-*` 入口。

```bash
A=(submit --confirm-action)
A+=(SUBMIT_V4_FORMAL40_NUMERIC_DIAGNOSTIC)
A+=(--confirm-v4-job-id 646900)
A+=(--expected-input-freeze-sha256 "$F")
"$P" -I -B "$S" "${A[@]}"
```

输出不确定、断线、超时、已有 INTENT／执行证据时，只查 status，绝不自动重提。
确认 sbatch 成功后，作业由调度器负责，不依赖 SSH 或 tmux 连接；tmux 只用于
观察。交互式 srun 不是这里的提交方式。

```bash
"$P" -I -B "$S" status
```

status 只报告调度／记录状态，不证明数值结果有效。Slurm COMPLETED 也不等于
通过。作业结束后，从已核对回执输入诊断 Job ID，并运行真正的只读结果验证：

```bash
read -r -p 'Diagnostic job ID from reviewed receipt: ' J
A=(verify-results --expected-input-freeze-sha256 "$F")
A+=(--job-id "$J")
"$P" -I -B "$D" "${A[@]}"
```

## 执行矩阵与产物

依次运行五个独立进程：reference_cold → A2 → A1 → B1 → B2。
参考走冻结 predict_batch；各 cell 为相同 32 个 trial 的两次推理。

| cell | autocast | 两次 batch size |
| --- | --- | --- |
| A2 | 开启 | 16、1 |
| A1 | 开启 | 16、16 |
| B1 | 关闭 | 16、16 |
| B2 | 关闭 | 16、1 |

每个子进程使用独立 scratch／缓存，父进程绑定 PID、参数、输入哈希、完成记录
及持久文件。正式产物在 attempts/slurm-JOB 下，含 reference_cold、cells、
输入／环境记录、边界与输出证据、比较摘要及工件清单；state 存终态记录，
submitted_runners 保存实际 runner，logs 保存作业日志。schema_version 为 1，
每份结果同时绑定协议、Job ID、freeze SHA、trial／源身份及大小／哈希清单。
序列化数组和受控工件有全局 1 GiB 最坏情况预算，不能改成无限 dump；日志和
scratch 不是可用这一预算替代管理的正式数值工件。

## 如何解释结果

- DIFF：身份和数值有效，但超过固定一致性判据；这是诊断发现，不自动判实验失败。
- INVALID：非有限值、来源／结构／追踪等有效性失败；不得解释成可比较模型结果。
- DIAGNOSTIC_COMPLETE：协调器完成证据链；仍须 verify-results 重新核验文件及比较。
- DIAGNOSTIC_RESULTS_VERIFIED：只读结果验证通过，才进入人工数值原因分析。
- DIAGNOSTIC_FAILURE_RECORDED：失败证据可核对，不代表数值结果可解释。
- Slurm 已结束但缺少终态：未完整结束，需要调查；不得补写成功标记。
- ACCOUNTING_PENDING／STOP_AMBIGUOUS：等待再次只读查询或调查，不自动重试。

诊断不会自动修复 v4、放宽阈值、发布 smoke 成功、提交新评估或推导三模型排名。
之后须审阅 A2 复现、冷参考等价和边界差异，再决定有证据支持的修复与新的 smoke，
最后才是完整 10k 对比。

## 十三文件候选哈希

下面是机器可读取的固定值。README 自身哈希只记录在外部报告，避免自哈希循环。

<!-- RELEASE_SHA256_BEGIN -->
5e25caf8ccc53559a916f4813d783141ae371ef228426861c9439f605b171736  diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b  numeric_trace.py
e123b172cf150fc4a015992fa3511e2a9a9c9109987575c405dcf0bee0aa322b  submit_numeric_diag.py
63dc1293528612afbf69c79273aa3b2f37ca41ed524cfa5f054f9f4f48d77cfa  run_numeric_diag.sbatch
19407f26a9d329ddec4b29b2587833c317f24c361194603dae91fa82205b905f  test_numeric_diag.py
4fcbe4a6307a9fb70f8bf35f11d5099246b89180eba415282d186bfccc7b055b  test_submit_numeric_diag.py
4af79705c62f3f9951ba5f99bd100270913d4997edca7a1ccc3b2120e39cd2b5  test_loader_record.py
e478b24126141cbc6b54c89ffc44f74321c1493bbc0572aefd428598357b82d9  test_real_evaluator_scope.py
418b875c356286ca470c263fa91abbb270d2eff6a4bef691a57a8b25a625565f  test_v4_manifest_json.py
29000c14ddfcf9024bcacddec4c89c2cc0060584c9161527c1621dbc887c5834  test_runtime_contract.py
1e163e72ac414401b02060fa10729926b6271db78d7bf605e12f8fe22b916617  test_execution_collections.py
56364b0c0afb5faa24492b8144e3d43115caefa4f87de7ce3c1e55e46a8ff08b  test_environment_mapping.py
88f79d3eef1a65d558cda930bea7d8f083fa04e2dd140322a827e1cf67d9e33d  test_execution_budget.py
<!-- RELEASE_SHA256_END -->
