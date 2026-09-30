# 753729失败复盘与低α扫描v2修正

最新续接（19:07 JST）：用户继续指令后，v2原生只读导入预检通过，96快照文件/受审源码导入及前后包核验成功。未加载checkpoint、未初始化CUDA、未提交新作业。见[预检回执](release_fine_alpha_20260928_candidate_v2/source-check-v2-once/RESULT.json)。冻结提交器的并发队列规则仍待在提交前处理，不能从本次预检推断GPU执行已经验收。

最新续接（18:33 JST）：后续已按用户上传授权及对隔离检查修正的确认，成功发布v2的41个文件，哈希与远端包核验通过；旧v1和失败证据保留。未执行生产源码导入、GPU推理或提交。见[v2台账](release_fine_alpha_20260928_candidate_v2/REMOTE_PROGRESS.md)。下文范围和“未部署”均指原修正阶段时点。

日期：2026-09-28。用户指令：“开始修正”。范围：本地实现、测试、新候选打包，以及同Python环境的无GPU类型回归；不包含上传生产包、新GPU额度、提交、释放或重跑。

本轮结论：修正候选与原生CPU类型回归已通过。**453项本地测试通过；未部署v2、未提交GPU作业。** [完整交付](release_fine_alpha_20260928_candidate_v2/LOCAL_ACCEPTANCE.md)。

后续执行增量（16:53 JST）：用户另行批准v2上传和哈希/包核验。专用入口与12项上传安全测试完成；单次远端调用因队列中的754073运行中而在写入前停止，没有部署、自动重试或新GPU提交。详见[v2上传台账](release_fine_alpha_20260928_candidate_v2/REMOTE_PROGRESS.md)。下方“待批准上传”描述的是修正交付时点，现已获上传授权但尚未执行成功；原生导入和GPU权限不随之扩大。

## 1. 已确认的失败事实

- 作业753729：`FAILED / 1:0`，2026-09-28 12:27:03–14:15:24 JST，Elapsed `01:48:21`，节点spcc-a100g02。不是6小时超时。
- A产生126份npz、75,600行预测，随后在`fine_alpha_archive.run_worker → verify_provenance`报`PROVENANCE_ENVIRONMENT`。B/C未启动，没有WORKER/COMPLETE成功记录。
- [收集回执](release_fine_alpha_20260928_candidate_v1/collected-753729-_dy7mbjl/RESULT.json)及[子进程错误日志](release_fine_alpha_20260928_candidate_v1/collected-753729-_dy7mbjl/state/attempt/A/stderr.log)。147个归档文件均通过传输与落盘哈希核验；数组有限值检查通过，只是失败归档结构核查，不是生产结果验收。
- 13:26 JST本地看守因共享socket消失停止，与14:15远端失败不是同一事件；恢复连接后从sacct确认终态。没有重投。

这些部分产物保留用于诊断，不补写成功记录，不直接纳入正式54点曲线。

## 2. 根因和测试缺口

HAKUSAN PyTorch 2.1.1+cu118的`torch.__version__`实际类型为`torch.torch_version.TorchVersion`。它是字符串子类，但`type(value) is str`为假。旧`environment_record()`直接返回这个对象，旧验收要求普通str；fine worker第一次直接验收内存对象时因此拒绝。

JSON写入再读回会将该对象变成普通str。旧归档测试主要通过序列化后的手造记录，缺少真实producer → live validator以及生产worker接缝覆盖，未能捕获这次错误。环境验证又在整块计算后才执行，导致错误推迟到A块末尾。

## 3. 修正内容

1. 只在采集边界将已确认是字符串的torch版本转为普通str；None、整数、布尔、列表和任意对象仍拒绝，不通过泛化`str()`隐藏坏类型。
2. 抽出共同的严格环境和运行设置验收函数；生产验收的字段、A100/作业/CPU约束和六项数值设置不放宽。
3. fine worker在受审加载session进入后、首次forward前执行环境/运行设置验收。放在session之后是为保留既有“进入前CUDA不得初始化”的加载门槛。
4. 成功预检写`ENVIRONMENT_PRECHECK.json`，明确不是推理成功；最终WORKER按SHA绑定该文件。推理后重采环境并拒绝漂移；源文件/输入后检查及最终完整验收仍保留。失败记录新增phase。
5. 离线重读要求预检文件存在、SHA正确，且job/PID/release/环境/运行设置与WORKER一致。
6. 状态脚本改为按用户列队列再筛选作业；即使squeue失败，也只有sacct明确返回相同job的终态才允许回退，原错误保留为warning。未知状态、非终态或sacct错误仍停止；不重连/重投。

## 4. 新旧版本边界

- v1冻结包和753729全部原始证据不修改。v1包SHA仍为`b0bd8b4269b5542b65bbf6d3982b7484838f983d0c5fe7a9538551ea9a076b8f`。
- 新候选目录：`release_fine_alpha_20260928_candidate_v2/package`；新远端目标：`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v2`。
- 54点、formal40 checkpoint、数据/音频/批布局、公式、预测数219,600及预算上限均不改变。新release身份不继承v1的GPU审批或作业号。
- 旧上传、提交、修正、放行、看守脚本仍绑定v1/753729，不要用它们操作v2。后续远端发布须准备绑定v2身份的驱动并单独批准。

## 5. 本轮测试与验收

新回归先在旧代码上复现`PROVENANCE_ENVIRONMENT`和返回TorchVersion而非str的问题；修正后通过。针对性测试覆盖真实TorchVersion、内存/JSON一致性、坏类型与生产约束拒绝、首次推理前失败、环境漂移、session后检查失败、失败不写成功标记、预检文件缺失/篡改/身份错配、旧队列记录消失分支。

全目录回归、新包隔离检查和旧包保全记录以[v2本地验收](release_fine_alpha_20260928_candidate_v2/LOCAL_ACCEPTANCE.json)为准。原生CPU检查只执行哈希绑定候选中的环境函数，不写远端源码、不加载模型、不初始化CUDA；即便通过，也不等于完整生产worker或A100验收。

- 实际全目录453项，新增19项，58.061秒，全部通过；隔离包check与runner语法检查通过。
- 5个历史冻结包174个文件前后哈希一致。新release SHA：`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`。
- [原生CPU记录](release_fine_alpha_20260928_candidate_v2/native-cpu-hhstvw6w/RESULT.json)：Python 3.11.5 / torch 2.1.1+cu118，TorchVersion→str、直接内存及JSON往返验收通过；4类非法类型拒绝，CPU记录不能通过生产验收。只调用一次现有SSH，0 GPU、0提交、0远端源码文件写入。
- 包内仅5个文件变化，合同仅scope版本变化。未调整科学预测、输入、模型、α公式、预算或任何数值验收容差。

## 6. 后续门槛

1. **已完成**本地全目录回归、新包校验及原生CPU类型检查，见上方实际结果。
2. 单独批准后将v2发布至独立目录，逐文件核验并执行原生只读导入预检。
3. 再明确批准新作业预算与唯一一次held提交；资源审核后单独放行。禁止覆盖v1、续写旧attempt或自动复用旧授权。
4. 新作业仍全54点重跑；通过完整归档验收后才计算曲线。α不直接代表儿童年龄。

成本仍需留余量：v1的A块含加载、计算、后检查及失败退出共约108分钟；若粗略按75600条外推219600条，约315分钟。该估计混合固定成本且不保证线性，不是额外GPU授权，也不保证6小时一定够。
