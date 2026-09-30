# v14部署门禁：真实CPU验收未通过，未部署

2026-09-10。用户批准的两项修复已经独立实现，本地645项全部通过，但实际
formal40完整指纹超过原600000工作预算，因此**没有创建远端v14目录、上传、
冻结或提交GPU作业**。不能把本地测试或模块恢复PASS解释为整体验收通过。

实际同版本CPU结果：Python3.11.5 / torch2.1.1+cu118，原24pinned与96snapshot
身份通过；严格加载61state keys、参数覆盖1.0、清单70、完整60状态张量通过。
10个缺失src模块原对象恢复成功，已有scene对象保持，无源码重执行。
scene3/model9图通过；完整指纹在work600001处拒绝，230节点/110代码对象/
33不可变默认值缓存。联合合成探针与完全独立的新进程均出现该问题。
未运行正式模型CPU forward或GPU推理，没有可解释数值。

新固定PATH可定位/usr/sbin/ldconfig，ldconfig -p只读查询成功。
8元素合成跨模块CPU Dynamo路径恢复4原对象后检查通过，postseal delta=0；
这只验证模块生命周期最小路径，不等于完整formal40验收。

四个会写远端的Mac入口（create-upload、publish、audit-freeze、submit-once）
已在文件顶部设置明确停止，实际执行均本地exit2，未启动SSH。未取得freeze
或Job，所以所有后续身份仍使用拒绝占位符，绝不能填旧Job/旧freeze。
准备好的脚本不是当前执行指令。

独立只读SSH复验：原v4 manifest/lock/evaluator/runner及v13 freeze/failure/log
七个固定SHA全通过，v14远端root不存在，两个相关队列为空。原记录保留。

候选清单20文件SHA：
`022ca5b14069a37e46f05e8e0cf23f2718ddaca17ca0cfa9fa814417e196ae35`。
当前实施及后续批准范围见[v14修复记录](2026-09-10-diagnostic-v14-runtime-import-repair.md)。
最终三模型比较仍未完成，原smoke的NLL差异未解释。

补充开销剖析：单独240秒限时的CPU profiler中止于work355867，观测777次live
校验与239784次callable anchor调用；已完成校验work197293，另一次在执行中。
这是不完整统计且附加profiler开销，不能当作完整验收或GPU耗时。后续只针对
重复检查的优化需要额外批准；本轮不提高预算、不跳过live校验、不提交。
