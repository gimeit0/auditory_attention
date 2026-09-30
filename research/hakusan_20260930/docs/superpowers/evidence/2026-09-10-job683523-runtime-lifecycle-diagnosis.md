# Job683523：首轮编译校验冲突与待审批边界

日期：2026-09-10。状态：实际作业失败，合成CPU对照完成，尚未修复校验合同。
这不是科研数值结果；未创建v16、未重提v15、未修改冻结代码或科学设置。

审批更新：用户已回复“好的”，批准下述修复边界。现在开始独立v16的
工程实现与负例验证；旧v15和科学输入保持冻结。只有经来源/对象/用途
验证的框架初始化可被接受，未知变动仍拒绝，不能推理后整体重新封存。
下方“尚未实施/待审批”描述的是提案时状态；实际验收另写v16记录。

## 实际GPU证据

Job683523 / diagnostic v15 / spcc-a100g09 / FAILED2:0 / 3分46秒。
verify-results=2，matrix=null，numeric_results_interpretable=false。
PRE/POST相同、post_errors=[]；五份原始工件见[job目录](job-683523-v15/README.md)。

原始异常链定位到v15 `_invoke_attested_operator`第4327行：这是operator
正常返回后的校验，而非异常分支第4322行。第4288行是scene图、model图、
完整执行指纹或导入来源记录的组合不一致检查。该日志不含具体分支差异。
因此已知是返回后校验拒绝，未知实际GPU究竟有哪些变化；没有可用科学预测
工件，不能以“函数返回”宣称推理正确。

## 同版本最小对照

固定SHA v15工具，实际hakusan1 Python3.11.5 / torch2.1.1+cu118；私有临时
缓存、1 CPU线程、120秒上限、无GPU、无科学模型/权重/音频、HOME不改。
探针是[独立脚本](2026-09-10-job683523-cpu-forward-seal-probe.py)，不属于
冻结生产候选。Toy仅对8个float32元素执行`x.sin()+1`；两种条件在独立
新进程运行，数值均与相同torch表达式精确一致。

| 合成条件 | 首次forward后的完整模型指纹 | 第二次forward相对第一次 | forward callable图 |
|---|---|---|---|
| native，无compile | 保持 | 保持 | 保持 |
| torch.compile，backend=eager | 不一致 | 保持 | 保持 |

编译条件的不一致记录都在root OptimizedModule的`dynamo_ctx`配置记录下：

- `counters`从0组/0项变为2组/4项。
- `most_recent_backend`从None变为该context闭包内的确切`compiler_fn`对象，
  使on_enter可达图新增`root.global[most_recent_backend]`；不是另一个后端。
- 第二次相同forward后，两者观察值及完整模型指纹均保持。

实际stdout存为[compiled对照](job-683523-v15/synthetic-compiled-cpu.json)与
[native对照](job-683523-v15/synthetic-native-cpu.json)。它们是本轮新CPU
观察文件，不属于GPU作业原始artifact inventory；另列checksums，不能
混入原五文件SHA256SUMS或伪装成GPU矩阵。

已直接读取远端已安装`torch/_dynamo/eval_frame.py`：OptimizeContext的
on_enter执行`most_recent_backend = compiler_fn`（该安装文件第416行），
并执行generation tagging初始化。此前还用该变量检测后端变化，因此它
并非可随意忽略的纯统计字段。另有TorchPatcher的一次性运行时修改。
这支持“冻结所有可达框架状态会拒绝正常编译初始化”，不支持“忽略任何
名叫counters或dynamo_ctx的对象”或“正式GPU只有上述两个差异”。

证据限制：合成后端为Dynamo eager，不是Inductor/A100；没有实际模型的
forward，也没有16/1 batch对照。不解释原smoke的0.0077362060546875 NLL差异。

## 建议修复范围（需明确审批，尚未实施）

把“实验输入/用户执行代码必须固定”和“框架按已知生命周期初始化”分开
验证，避免将正常首次初始化误判为篡改，但不得重新封存未知变动。

1. 先补有界、脱敏的具体组件差异记录：仅固定组件名、路径、类型、对象
   身份关系与计数，不输出环境变量值、音频或模型张量。仍按原规则拒绝。
2. 以实际2.1.1来源/对象身份和读写用途为依据逐项定义允许的框架状态转换；
   例如最近后端只能按验证过的None→当前签发compiler对象转换。统计对象
   只有证明确属观测用途才可按身份/类型/来源检查，不按任意名称豁免。
3. 用户代码、weights、参数/buffer、hook、backend替换、前处理、导入绑定、
   未识别配置变化仍拒绝；原600000预算不提高。不做首次推理后的整体重基线。
4. 增加正常冷/热两次编译、native对照，以及后端/代码/闭包/权重/hook/
   导入替换等负例；再做同版本真实准备复验。通过后才独立新版本冻结、
   单次A100诊断并验收。合成通过不能替代实际完整模型验证。
5. 原权重/数据/精度、TF32、compile使用、32条矩阵顺序与NLL容差保持；
   若数值方案仍需改变，另行按证据审批。最终仍须三模型smoke→10k对比
   →paired统计→可复现报告，不以工程测试数量代替结果。

该方案改变原校验接受边界，故本轮停在证据与方案，未自动添加豁免。
