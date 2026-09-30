# 诊断 v8：集合类型兼容性本地修复

日期：2026-09-09。用户在 Job 680519 取证及本地复现后要求“下一步”，
本轮范围为独立本地候选的回归、修复及验证，不上传、不冻结、不提交作业。

## 固定边界

- 保留诊断 v7、Job 680519、原评估 v4 和所有先前失败证据。
- 不改训练模型、bank/checkpoint/SNR/模型角色、AMP/TF32 设置、执行矩阵或数值容差。
- 不通过清空 deque、把模型状态改成 list、跳过属性或放行所有 Collection 绕过校验。
- 新候选目录：same_bank_eval_2026_09_03_v4_numeric_diag_v8；协议和未来远端根同步提升 v8。
- 不把本地 PyTorch 2.12.1/CPU 测试当作真实 PyTorch 2.1.1/A100 实验。

## 实施顺序

1. 核对 v7 候选十一文件 SHA，完整复制到独立目录，仅调整本候选版本引用。
2. 先增加源 SHA 绑定的 deque 属性、精确 torch.Size 和属性路径错误回归，确认旧实现 RED。
3. 为必要的精确类型增加有界身份/内容记录；保留容器身份、deque.maxlen、元素递归
   与可调用子项图；拒绝未知类型/恶意子类，增加静态类型和属性路径诊断。
4. 覆盖修改内容、maxlen、容器替换、递归/工作预算、未知/恶意类型、可调用子项变化；
   使用带真实源属性的 worker 生命周期夹具覆盖签发和后续重验。
5. 重跑既有全部测试、静态检查与范围对比，记录遗漏/环境限制，生成新候选 SHA 清单。

远端日志只给通用集合错误，deque 是已复现的真实源属性兼容缺陷，但尚不能
认定它是 Job 680519 第一个或唯一触发对象；因此还需保留清晰的属性路径错误。
以上为执行前记录；以下为本轮实际完成结果。

## 完成结果

独立 v8 本地修复与回归完成；没有远端连接、上传、freeze 或提交。
复制前和最终复核时，v7 十一文件固定 SHA 均通过，原评估 v4 两个工具 SHA
不变。旧版本和 Job 680519 失败证据保留；候选目录只含十二份交付文件。

### RED → GREEN 与修复

在仅更换版本标识、未修改集合逻辑的 v8 副本中，先运行四项新回归：
源 deque 属性、torch.Size、worker 签发、未知类型属性路径。结果 1 failure、
3 errors，0.618 秒，确认旧实现不能通过；日志为 v8-collection-red.log。

修复限于 `_container_execution_identity`、新增静态错误辅助函数、deque 导入，
以及新诊断协议/根。精确 deque 记录对象身份、类型身份、maxlen、顺序及递归
元素，使用共享预算与循环引用记录；torch.Size 记录精确类型、对象身份和整数
维度。deque 子类（包括 callable 子类）及未知集合仍拒绝。Torch 的合法
ModuleList/Sequential 继续按原 callable 规则处理，没有放行所有 Collection。

未知类型错误包含有界 path 和类型名，用 type 自身的元数据描述符读取，不执行
repr、自定义元类 __getattribute__ 或元类属性。初次实现中 DiagnosticError
继承 RuntimeError，导致嵌套错误和深度预算被误写为“deque changed”；两项回归
捕获此问题，已先重抛 DiagnosticError，保留真实路径/原因。

新增测试只从 SHA 匹配的真实模型源码提取 deque 构造表达式；既有 worker 夹具
加入该属性和精确 torch.Size，覆盖签发、重复重验、修改拒绝，以及 1000 项满
窗口的预算检查。不加载完整模型，不声称该合成夹具覆盖真实模型所有属性。
Tensor 数据仍不读、不复制、不同步，注册状态版本检查未变。

### 最终完整测试（七个独立 Python 进程）

| 入口 | 通过数量 | 耗时 |
| --- | ---: | ---: |
| test_numeric_diag.py | 344 | 96.833 秒 |
| test_submit_numeric_diag.py | 66 | 12.112 秒 |
| test_loader_record.py | 6 | 0.526 秒 |
| test_real_evaluator_scope.py | 28 | 1.619 秒 |
| test_v4_manifest_json.py | 21 | 7.200 秒 |
| test_runtime_contract.py | 14 | 1.752 秒 |
| test_execution_collections.py（新增） | 26 | 1.156 秒 |
| 合计 | 505 | 专项重跑和内存退化不重复计数 |

环境：本地 Python 3.11.15、torch 2.12.1，torch.version.cuda=None。
旧的“插入 deque 后必须粘性撤销”回归未删除或改弱：支持类型不意味着允许
签发后的配置变更，该旧测试也在 344 项主回归中通过。

### 主代理有界自查

可重跑只读脚本：`2026-09-09-diagnostic-v8-local-review.py`，脚本只在进程内
替换函数做退化检查，不修改候选文件，也不访问集群。

- 整个诊断 AST 除上述两个函数、deque 导入、版本标识外与 v7 一致。
- numeric_trace.py 字节一致；提交器、runner、旧测试只允许 v7→v8 根/协议替换。
- 六种内存退化全部被捕获：恢复 v7 集合函数、去掉 deque 容量、内容、对象身份、
  去掉形状维度、使用会执行元类属性的类型读取。
- Ruff check/format、runner bash -n、两个 CLI help 及 trace 模块载入通过。
- 未新增独立子代理审查；不能沿用旧版本审查结论宣称 v8 已独立批准。

全部测试、静态、自查日志保存在
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v8-*`。

## 候选固定身份

| 文件 | SHA-256 |
| --- | --- |
| diagnose_batch_invariance.py | `6624cda3d7ea21121599f6c2c05c46c060a1e647d2256991459735ca24d49182` |
| numeric_trace.py | `fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b` |
| submit_numeric_diag.py | `cfadc25782eb8218d696c569e4df201b545d93fe0abe7c276879850bcdbb5487` |
| run_numeric_diag.sbatch | `72085b49debf2c70e730f546eb12fd62d0aa4ee64c46cfdd67d433ad4992743b` |
| README.md | `eab9385aa673cfadde4d3fa46b4be6146e803abd2b6944310cdf2434d1c9cd72` |

十二文件外部候选清单：`v8-candidate-manifest.sha256`；README 内另记十一文件。
预定协议 `formal40_batch_invariance_diag_20260903_v8`；预定远端根
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v8`。
本轮没有创建此远端根，没有新 freeze SHA 或 Job ID，不能复用 v7 freeze
`6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920`。

## 仍未完成／下一阶段

当前只修复了本地可复现的诊断工具类型兼容缺陷，不能证明 Job 680519 的首个
或全部触发对象均已消除。未进行生产 PyTorch 2.1.1+cu118/A100、真实 formal40
checkpoint 和音频的端到端验证；505 项本地通过不等同于远端成功。

下一阶段先做远端只读预检及同版本类型兼容短探针，再受控创建/发布独立 v8，
audit→freeze→核对新 SHA→check-only→单次提交。若仍失败，新的路径/类型
错误应先用于定位，不重提旧 v7，不原地改已发布文件。
Job 646900 的 NLL 差异 0.0077362060546875 仍未解释；没有 SMOKE_PASS、
没有三模型完整 10k 结果，也不能作为独立测试排名。
