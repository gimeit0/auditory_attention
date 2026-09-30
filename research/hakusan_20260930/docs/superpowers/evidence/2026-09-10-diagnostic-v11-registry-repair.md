# v11 本地注册表兼容性修复与验收状态

2026-09-10。目标仍是formal40主模型、valbest33次模型与author_external在原
冻结10k bank上的比较；本修复没有完成该目标，没有可解释的数值矩阵。
结果仍必须标记REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。

## 直接原因和已保留证据

v10 Job681974在A100g04运行1分11秒后失败。经verify-results认证，marker为
7a86da8b924a3f021566288169ca1e39183f4ca51b7403a965a5e88e219991be，
log为63abc8deba1dd8e5ceed525a31b1846a9afcf67e21e01cfb6901ae61318b1d24。
POST/PRE相同，matrix=null，原NLL问题尚未解释。没有重提该作业或改写v10。

使用原v10固定源的临时真实formal40 CPU探针确认：torch2.1.1+cu118，
strict加载61keys、trainable numel coverage1.0、67模块，201个注册表全部
为collections.OrderedDict；原_snapshot_model_entries在line4704拒绝它。
顶层model state snapshot failed，直接cause为model state registry is invalid。
REMOTE_CPU_PROBE_RC=2，没有forward/GPU/新发布/freeze/submission。
探针文件2026-09-10-diagnostic-v10-snapshot-probe.py SHA：
2bd7de11e98369760654fb28f8a83deba123deb8ceaa6d7cef8171a73b22ef4c。

## 修复范围

独立本地same_bank_eval_2026_09_03_v4_numeric_diag_v11，不修改已发布v10。

- 精确dict/OrderedDict原生读取，统一静态注册属性、模块发现、参数冻结检查、
  状态身份指纹及状态内容快照；列表内音频模块亦进入模块/状态清单。
- OrderedDict配置/hook按原生有序语义读取，move_to_end必须改变指纹。
- 不接受任意Mapping或注册表子类，不调用可覆盖的用户迭代/查找协议。
- 本地额外发现OrderedDict.items会重新hash键；恶意键用例实际观察到2次hash。
  在原生有序迭代前先用底层dict.keys检查。注册表只接受精确str；通用有序
  配置只接受原生不可变键树（None/bool/int/float/str/bytes、tuple/frozenset递归），
  自定义键在hash/eq/repr执行前拒绝，递归受原有有界检查约束。
- 普通dict子类在原通用配置分支的底层dict读取行为保留，不用于模型注册表。
- 未改变科学模型、bank、AMP/compile/TF32设置及顺序、数值矩阵、NLL阈值、
  600000固定工程work预算、10000节点/96嵌套/时限/1GiB工件上限。
- numeric_trace.py字节不变；runner/submitter仅协议和诊断目录v10→v11。

## 本机验证（不是超算/GPU通过）

Python3.11.15，torch2.12.1 CPU。新20项初始RED：10 failures、8 errors；
初始修复后20项及旧561项PASS。主代理进一步测试恶意键hash，准确复现遗漏，
补齐键预检及4项回归。最终原561项不改断言/行为，仅root/protocol版本递增，
加24项新测试，总计585项通过：

| 入口 | 数量 | 最终用时秒 | 结果 |
| --- | ---: | ---: | --- |
| test_numeric_diag.py | 344 | 96.392 | OK |
| test_submit_numeric_diag.py | 66 | 14.954 | OK |
| test_loader_record.py | 6 | 0.557 | OK |
| test_real_evaluator_scope.py | 28 | 1.826 | OK |
| test_v4_manifest_json.py | 21 | 9.019 | OK |
| test_runtime_contract.py | 14 | 2.580 | OK |
| test_execution_collections.py | 26 | 1.409 | OK |
| test_environment_mapping.py | 30 | 3.751 | OK |
| test_execution_budget.py | 26 | 0.931 | OK |
| test_ordered_registries.py | 24 | 0.255 | OK |

Ruff check/format、runner bash -n、两个CLI --help均通过。
主代理AST复核：仅6个既有函数改变、3个新helper、OrderedDict导入；其余
科学设置/生产函数/旧测试保持。v10十四文件SHA仍匹配已发布R3清单。
4种内存故障注入中的5项回归均捕获：旧快照1、遗漏order2、危险键1、
缺失registered lookup1。普通dict模型新旧快照schema/content完全一致。
这不是独立代理审查，没有新增subagent。
复核工具2026-09-10-diagnostic-v11-local-review.py SHA：
f7a675b8ddd802808824d24a172c876bd1f195f32d1f0214c41d025658e89b5e。

## 最终候选固定值

清单：.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/
v11-candidate-manifest.sha256，共15项，SHA：
2e72c2dccda2a50980a097581b7b43da8f6502147ac97ced335b5e8fcd55ea01。

生产四文件：

```text
4143df86f71c69de37b1ae99813d6ad405dd962ec72552996571847e5694bbf9 diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b numeric_trace.py
7b21cf94186bc1ffbd342c4107bf232f455d125b5235005d121bd9cdb09ddbf2 submit_numeric_diag.py
7cd333b4c3509612faafffbdf94790d37722316e727991d9c456cde9e106df74 run_numeric_diag.sbatch
```

## 当前阻塞与下一操作

新的临时真实formal40 CPU状态探针准备完成：
2026-09-10-diagnostic-v11-remote-cpu-probe.py，SHA
74b86c2d272e8b7d0be126adb9abfd5a8c11a47fe0f5e8006f96de4fc6ab964d。
使用固定base probe，240秒/1CPU线程、临时目录、原v4锁只读共享锁、源哈希检查，
不改HOME，不forward、不部署/freeze/提交，不伪造生产CUDA worker capability。
新增模型完整字节快照及注册张量覆盖、scene/model图、materialized完整指纹、
重复状态/RNG/图/模块身份检查和退出后96源/24pinned再验。
本地清单和生成的远端代码编译检查PASS。

第一次--run停在本地共享socket检查：master.sock已消失（目录仍700），
没有传输候选。BatchMode直接SSH亦255 Permission denied，无免密替代。
该次初稿清单SHA1d6e321...、diag3f1dc770...从未传至远端；现由上述最终
键预检候选替代。当前v11无新freeze或Job ID，未创建正式远端v11目录。
已请用户仅在Mac运行连接脚本重新认证；密码不进入聊天。

恢复连接后由代理运行：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-10-diagnostic-v11-remote-cpu-probe.py --run
```

必须看实际CPU结果后才决定独立部署/新32条GPU诊断，不能重复提交旧v10。

## 连接恢复后的实际CPU结果与R2修订（2026-09-10）

用户恢复master42507后，原候选实际运行：24pinned/96来源通过，strict加载
完成但在扩展inventory的全项eval断言处停止，REMOTE_CPU_PROBE_RC=2。
第二个只记录状态的临时探针确认：70inventory entries、69unique modules、
66个PyTorch注册树模块。仅三个额外音频对象training=True，均不在注册树中：
AudioToTensor、BinauralCombineWithRandomDBSNRPerExample、BinauralRMSNormalizePerExample。
三者均无parameter/buffer；没有修改标志或forward、部署、freeze、GPU提交。

固定SHA源码证据：原strict_load_model只调用model.eval()、model.parameters()
冻结，AudioCompose.transforms是普通list，不是注册子模块容器。三个原生
transform的forward及其直接helper均不读取training；旧v10音频指纹本就记录
真实布尔training而不强求False。因而把扩展“执行依赖清单”同时当成
model.eval()递归树，是v11新增检查范围不一致，不是权重或原推理模式变化。

R2工程修订：原注册模块树仍必须全部eval（直接原生注册表遍历，不调用可
替换modules/named_modules）；扩展音频依赖保留原生标志，不执行eval修复、
不跳过指纹/状态/参数冻结检查。所有70条身份及training仍逐次纳入live指纹，
任何注册模块training=True或后续音频标志变化均拒绝。无科学运行设置改变。
原R1十五文件及清单已完整保存在snapshots/v11-ordered-registry-r1，原v10
远端证据不动。下一项先RED→GREEN和原585项回归，再重新做真实CPU快照流程。

### R2本地验收（2026-09-10）

新增9项初始RED，1failure/10errors（含subtests）；修复后9/9通过。
十一独立测试入口完整594/594通过：environment30、budget26、collections26、
loader6、native_eval9、numeric344、ordered24、scope28、runtime14、submit66、
manifest21。旧585项测试文件逐字不改，runner/submitter/trace字节不改。
Ruff check/format、runner bash -n通过。AST确认R2仅新增一个bounded注册树
helper，prepare_formal40_worker只替换一个eval guard，其余顶层/函数AST一致。
skip-eval、强制audio模式、旧全清单eval三种内存退化均被新回归捕获。
主代理复核，不冒充独立review或GPU验证。

R2十六文件清单v11-r2-candidate-manifest.sha256 SHA：
1b6e6f83115f995548bf9a859c02db86ed199f3bdcc5d05dfea386e351b990a9。
新diag SHA39ee10def3d2b90b981ee56812492b1de7266943add6a370e3ef14943f490b83。
review SHA40bef31b367c48a7926f8fa175d342f26d4f65b98bad73efd3a067a157126f98。
R1training探针SHA3dbfc35f7d5f37d7e018cfe2bead50791805d70b51a46cbd6a90384271248098。
R2真实CPU探针SHAc16221564a7983a8684371ccdf0a8e60bc273073e57dbe7a1504fbebb1baf951，
固定同一base，仅将eval范围替换成生产R2helper、保留完整state/RNG/图验证。
已通过master42507实际启动，待真实结果；无正式部署/freeze/GPU提交。

### R2真实CPU通过

同一实际torch2.1.1+cu118、固定原formal40、单CPU线程：24pinned/96snapshot
通过；strict61keys/coverage1.0；70inventory entries中210个OrderedDict注册表。
快照60独立张量，覆盖原生注册状态60个；scene3/model9 callable图通过。
完整materialized执行指纹work381317、230nodes、110code/4literal-default缓存，
未触600000预算。重复seal、60状态快照、RNG、模块身份及退出后输入验证通过。
FORMAL40_CPU_STATE_SEAL_PROBE_PASS，REMOTE_CPU_PROBE_RC=0。
没有forward，production_worker_verified=false、gpu_numerics_verified=false。
可以进入独立v11受控部署，仍不得称原NLL数值问题已解决。
