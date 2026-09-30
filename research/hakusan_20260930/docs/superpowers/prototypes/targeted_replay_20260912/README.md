# Job685198原始数组重放核对组件

2026-09-12：本地36项单元测试零跳过；156项真实已保存数组匹配和10个真实
归档反例通过。仅NumPy，没有导入torch、加载checkpoint、执行forward、SSH
或提交GPU作业。**不是完整真实重放或生产worker验收。**

验收：[记录与证据](../../evidence/2026-09-12-parent-replay-component-verified.md)。
源码：[parent_replay.py](parent_replay.py)，测试：[test_parent_replay.py](test_parent_replay.py)，
单次本地驱动：[validate_local.py](validate_local.py)，[固定源码SHA](SHA256SUMS)。

## 为什么需要它

参考进程与观测进程互相一致，并不能证明二者重建了原实验。新组件要求数组
同时与固定的Job685198父证据一致。它不修改原1e-6 canary容差，也不把新
精度设置、替换后的输入或重新计算的NLL当成原实验输出。

`build_contract(workspace)`复用未修改的旧离线inventory核验和计划检查，
固定父terminal、freeze、完整114文件inventory及四目标计划SHA。对A2/B2
两pass的CELL_INPUTS与BOUNDARY_DIGESTS重复记录交叉核对，正式输出按原
ndarray-hex编码验原生字节；生成381,463字节的独立合同，不写旧目录。
父工件在构建前后完整核验。固定合同SHA：

```text
95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34
```

使用时必须由可信父证据流程提供预期SHA；不能从待验证候选自行取一个SHA
就称为有可信来源。`ParentReplayGate`本身不是源码/身份认证系统，测试中
人为构造的合同也不能作为科学证据。

## 接口和完整性要求

`ParentReplayGate(wire, expected_sha, cell)`各管A2或B2一个cell。只有按原
32条完整顺序走完16→1的34批才能`finish()`；每批`accept`必须提供：

- `pass_id`、`batch_index`、原trial IDs及原六项runtime标签、对应autocast标签。
- 8项原始/前处理/模型边界和8项派生边界，共16个原生dtype数组。
- 4项**实际返回的**正式输出数组，不能只交一份被改名的边界摘要。

按原shape/dtype、逐trial SHA、存在时的逐batch SHA以及两pass全量聚合SHA
核对。支持float16/float32/int64/bool；拒绝类型转换、非有限值、隐式自定义
数组转换、错序、缺失、重复、额外数据及部分结束。任何失败后实例关闭，
不可忽略异常后继续凑出成功。没有容差近似匹配。

哈希按逻辑C顺序、每块最多1MiB；单候选batch数组最多128MiB，不拼接全32
条特征大数组。16条特征约102.4MB在该限制内。此处的预算不是GPU峰值内存
保证，也不管理调用者已有数组的总内存；逐层采集仍由既有有界归档负责。

`verify_saved_array`只验证一个已存数组或单trial。始终返回
`SAVED_ARRAY_MATCH_ONLY`和`full_replay_verified=false`，不能推进或结束
完整gate。旧归档只有少数最差样本特征，并不是完整32条输入缓存。

## 本轮实际验证与限制

真实数组匹配包括：A2/B2各两份完整32行native logits；其128行逐条核对；
两cell/两pass的scene与cue最差特征共8份（均仅trial9000）；16份完整正式
输出数组。156是核对次数，并非156个独立样本或实验。10个反例包括尾部
一个ULP改变、错误pass绑定、试图以局部归档结束完整重放。

完整34批gate仅由合成数组测试，不是已执行真实32条重放。尚未重建真实
音频/前处理输入；不声称找出逐层数值根因或得到三模型比较结果。

原工件未记录stride，本组件只能核对dtype/shape/逻辑C字节；接受逻辑内容
相同的非连续数组不代表证明原布局一致。runtime参数由调用者提供，只是
标签比较，不是独立实测或防伪证明。生产执行能力、源码/模型对象、参数、
输入防变更、RNG、hook生命周期和真实runtime检查仍需由受控worker承担。
返回值明确`production_authority=false`、`ready_for_gpu=false`。

## 复验（可选，本轮已完成，无需用户再运行）

只在Mac本地执行，会新建独立证据目录；不会覆盖旧结果或连接超算：

```bash
P=/opt/anaconda3/envs/audattn/bin/python
S="$HOME/发表/超算/docs/superpowers/prototypes"
"$P" -I -B "$S/targeted_replay_20260912/validate_local.py"
```

本轮环境Python3.11.15、NumPy2.4.6；尚未声称该新组件在超算同版本通过。
此前observer/stream/binding/archive的远端PASS不自动覆盖本组件。
