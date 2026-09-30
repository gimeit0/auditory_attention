# 低α扫描v2上传台账

后续版本说明：提交器的并发检查已在新[v3本地候选](../release_fine_alpha_20260928_candidate_v3/LOCAL_ACCEPTANCE.md)中修正，497项全目录回归通过；v3尚未上传或提交。本目录v2包、上传/原生预检回执均保留原样。新的发布与提交计划见[48号文](../48_FINE_ALPHA_V3_SUBMISSION_QUEUE_FIX_20260928.md)，不原地修改v2。

## 最新状态：原生只读导入预检通过，无新作业

用户在上传完成后回复“go on”，本轮只执行下一个原生只读导入门槛。2026-09-28 19:06:20–19:07:00 JST，`FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB`。见[真实预检回执](source-check-v2-once/RESULT.json)，SHA `708e668bca1a5d4d4181476e50f08d805f3124d9f4dd337ff3c704a4ee43cc76`。

- 新[固定v2预检入口](../preflight_fine_alpha_v2.py)绑定成功上传回执SHA、v2远端目录和release，不调用旧v1目标；新证据目录独占创建，不自动重试/重连。
- 13项预检本地回归通过（原6项、新7项），覆盖上传身份错配、v1/v2混用、模板变化、远端只读argv/CPU环境，以及拒绝worker/run/verify/submit模式。不是新一轮全目录回归。
- master、pre-check、source-check、post-check四步返回码均0；source-check stderr为空。
- 96个快照文件和两个原生回调的哈希/源码导入核验通过；快照manifest SHA仍为`8febb19f3c183333adfc0f7543ba7a017a3c5d4d5ae2132ffa72e701da955dcb`。已有24个pyc保留，检查使用`hash_checked_source_only`策略，不依赖这些缓存。
- 前后远端包检查及本地包复核均通过，release仍为`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`。
- `checkpoint_loaded=false`、`cuda_initialized=false`、`jobs_submitted=0`。没有真实模型forward、A100数值验收或新扫描结果；本轮不查询或改动754073。

### 下一门及已提前发现的限制

冻结包`fine_alpha_submit_once.py`仍按队列中任意`audattn`名称停止，而且先独占创建state，再检查队列。本轮仅检查代码，没有调用提交器、创建远端state或GPU审批文件。

因此不能把上传器修正等同于提交器已支持并发。若要与754073并发提交，应先修正提交器的实际冲突检查、补回归并生成新的冻结发布身份；不得原地修改当前v2冻结包或伪造空队列。另一选择是待相关作业结束后按当前包原门槛提交。无论哪条路线，新GPU预算（候选1 A100/8CPU/64GiB/最多6小时）、单次held提交和后续放行均仍待授权。

## 历史状态：上传及哈希/包核验通过，无新作业

2026-09-28 18:33:11–18:33:27 JST，单次调用完成，最终`FINE_ALPHA_V2_UPLOADED_AND_HASH_VERIFIED_NO_JOB`。见[真实回执](upload-v2-reviewed-job-once/RESULT.json)，SHA为`4d4fdce87880b88c84b1994049c6b0de4494b49ae8e188c6a51841841433facb`。

- 上传前再次只读确认754073身份、入口/工作/日志目录以及源脚本SHA匹配已审阅记录，队列快照为RUNNING。没有修改、取消或重新提交该作业。
- 41个文件已发布到`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v2/package`，逐文件落盘核验通过；远端隔离包检查返回`FINE_ALPHA_PACKAGE_CHECK_PASS`。
- 本地check、共享连接check、publish、remote-package-check四步返回码全部0；release SHA仍为`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`。
- 旧v1 RELEASE在上传前后均匹配原SHA；旧目录不在写入范围。前次停止回执SHA仍为`b03dad7d3d58998f509e8383c6defbbcc60211c758fb4dc12ae8f46d68fef7c6`，没有删改失败记录。
- 未加载checkpoint、未执行原生源码导入检查或GPU推理，新增作业0。GPU预算/提交/放行仍未授权。

下一门：申请并执行绑定v2身份的原生只读导入预检；通过后再明确新GPU预算及单次held提交。此次仅改上传阶段检查，GPU提交器的队列门槛没有改动，不能把上传通过解读为可直接并发提交。下面均为先前时点记录。

## 后续：用户确认修正上传隔离检查

用户回复“好的”后，只读回读754073，确认其为独立新种子训练目录中的数值预检。已准备仅适用于v2上传的精确作业身份/路径/脚本SHA检查，20项上传回归通过；冻结包不变。见[检查修正依据](UPLOAD_POLICY_REVIEW.md)。本轮使用新的`upload-v2-reviewed-job-once`，下方首次停止证据保持不动；尚不据此预判上传成功或授予GPU权限。

## 历史状态：上传前队列检查停止

2026-09-28 16:53:42–16:53:50 JST，用户指令“开始上传吧”仅授权将v2发布到独立目录并核验哈希/包完整性，不包含原生源码导入检查、GPU预算、提交或放行。

实际单次调用[专用上传入口](../publish_fine_alpha_v2.py)，[原始回执](upload-v2-once/RESULT.json)状态为`STOPPED_INSPECT_EVIDENCE_NO_RETRY`。

- 本地隔离包检查通过；release SHA为`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`，40个清单文件加RELEASE共41个文件。
- 现有共享SSH检查通过；没有重新认证或自动重连。
- 接收器先核验旧v1 RELEASE SHA和v2目标不存在，然后只读查询队列。
- [队列输出](upload-v2-once/publish.stdout)：`754073|audattn_numcheck_seed20260928|RUNNING`，查询返回0。
- 既有保护规则拒绝队列中名称含`audattn`的作业，抛出`QUEUE_FAILED_OR_RELATED_JOB`。这是保守的名称匹配，尚未核实754073与本扫描是否共享输入或写入目标；不据此断言存在实际资源或文件冲突。
- 根据执行顺序，异常发生在调用发布函数之前：本次没有创建v2远端目录或写入包文件，没有进入远端包检查，也没有修改v1。上传调用已发起不等于文件已发布。
- GPU作业提交数0；未加载checkpoint、未修改/取消754073、未重试上传。该队列快照不是754073的持续状态监测。

## 本地准备及复核

v2专用上传入口绑定新目录、V2 scope和上述release SHA；共享接收器保留旧CLI的V1默认值。上传相关12项本地测试通过（6项原测试和6项v2新测试），覆盖版本错配、旧目录保全、拒绝覆盖及错误回执。它们与先前453项全目录回归分开记账，不能将本次称为新的全目录回归。

冻结package、既有LOCAL_ACCEPTANCE.json和本次原始失败回执均不改写。上传失败不表示修正代码或模型推理失败，本次未执行推理。

## 下一步

先由用户决定等待754073结束，或授权进一步只读核查其与本次上传的关系；不绕过现有队列门槛。后续重新上传必须先确认远端状态，并使用新的独立尝试记录，保留`upload-v2-once`，不能直接重跑此单次入口或删除失败记录。

上传/哈希验收通过后，原生只读导入预检和新GPU预算/单次held提交仍是后续门槛。本次没有批准GPU重跑，也不继承753729的授权。
