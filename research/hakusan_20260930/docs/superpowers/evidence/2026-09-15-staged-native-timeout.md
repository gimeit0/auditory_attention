# G1原生分阶段检查：A2仍超时，停止且未重试

2026-09-15 JST。对应用户“go on”。
结论：**认证已恢复，状态查询完成；分阶段CPU检查未通过。没有新GPU或CPU调度作业。**

## G0当前状态，不混用历史回执

- 已有SSH master PID58367，复用成功；没有重连、记录密码或写入凭据。
- 账户实时 `squeue -h -u s2510040` 查询RC0，stdout为空：查询时无排队/运行作业。
- 已保存提交回执仍指向旧Job715276；实时 `sacct` 为FAILED / 2:0 / 00:50:06 / spcc-a100g06。
- 旧COORDINATOR终态为GPU_PAIR_NOT_VERIFIED。其顶层error=null不代表成功。
- 状态输出中包含历史PENDING/HELD资源记录，均属于旧journal，不是重新提交或当前队列。

[本轮只读状态回执](gpu-control-20260914-v4/status-20260915T125652Z-6fr2zar9/receipt.json)
SHA：`30866585900167a8c6aaa03592db2a5cc9e8e76e1606b73a4106aeb628b1b433`。
全部账户队列查询通过工具直接返回，其空输出记录在会话中；未伪造另一个远端原始结果文件。
这不是对所有可能存在的目录/权重字节作完整审计；新提交仍须核对其自己的输入和attempt。

## 实际执行的一次CPU检查

执行已固定入口 `2026-09-15-staged-scratch-native-cpu.sh` 一次。
新流程顺序为A2→B2→mmap，实际只启动A2。没有自动重试或延时。

| 项目 | 结果 |
| --- | --- |
| A2子进程 | PID2627388，50.144秒，RC=-9 |
| 原因 | `TimeoutError: child deadline reached` |
| 监督器 | 50.201秒，STAGED_COMPONENT_FAILED |
| 传输 | 59.286秒，RC2，transport.error=null |
| B2和mmap | NOT_RUN，无请求/产物目录 |
| 子进程日志 | 0字节，没有完成record/result |
| 临时清理 | 监督器报告temporary_directory_removed=true |
| 远端源码后检 | 未完成；不可写成运行后完整验收PASS |

RC=-9对应监督器明确的超时停止，不能据此推断OOM。
外层 `stage transport failed` 是对非零远端返回的笼统描述；
已收到完整远端结构化失败信息，所以本例不是SSH断线。

本轮日志只能定位到“A2子进程未返回”，不能从空日志判断停在导入、初始化还是某次forward/guard。
此前旧流程的30秒栈指向完整性扫描，那是另一次执行的证据，不能冒充本次栈。
拆分A2/B2未证明可满足50秒限制；不能声称此修复已解决原生或A100超时。

按新入口范围执行的是合成测试，不加载生产checkpoint、不调用调度器、不创建远端freeze。
临时测试包/缓存按设计清理；原始模型、音频、旧发布包/失败证据未删除。
本地完整请求与远端返回保留，可复核临时执行的源和声明范围。

## 证据复查

- [失败回执](staged-scratch-native_cpu-20260915T130407Z-obg5o718/receipt.json)
  SHA：`e6595cbbaff8a298f6ee3f695e15b22bed8f4e448ea91fa0f8b74e7ff748a9e4`。
- [A2原始返回](staged-scratch-native_cpu-20260915T130407Z-obg5o718/A2/output.log)
  SHA：`32536386e0f5465343fe8ef8a04920e7af943082f115c9a57c2b988bd35008b6`。
- 请求SHA：`980b6e1bbead1a1bec794e081fd35177ba8908ebe6920478b684fbd9a603a7da`。
- [只读固定失败核验器](2026-09-15-staged-native-failure-review.py)。

核验器已运行：FAILED_CPU_EVIDENCE_VERIFIED，tests_passed=false。
核对固定receipt/四工件、165成员的原始请求包、派生supervisor、child/source绑定、外部请求SHA、
子进程/传输期限及失败状态；成功验收器对该结果明确拒绝。
现有本地来源另外复查一致。这个本地后检不代替未执行完的远端后检。

## 下一步边界：新的验证执行预算（后续已批准）

2026-09-16后续：用户已同意拟议CPU预算并要求继续。
TINY每CPU内存限制6000 MiB，实际申请据此下调至1CPU/6000MiB/10分钟/0GPU，低于批准8GiB上限。
见[新CPU批处理范围与执行记录](2026-09-16-staged-cpu-batch.md)；下方保留原决策提出时的记录。

不再次运行同一入口、不扩大登录节点50秒限制、不删除A2/样本/原断言来造PASS。
当前G1未通过，G2矩阵及正式10k均未提交。

已只读查看 `sinfo -h -o "%P|%l|%G"`：
DEF、TINY、SINGLE等分区可见，GRES显示(null)；GPU-1A显示A100。
分区列表仅说明存在CPU资源，不证明本账户有权以指定CPU/内存请求，
也不代表本次已取得调度额度；具体partition/account/QOS仍须提交前校验。

待用户决定的建议：将**同一合成分阶段生命周期检查**安排为独立CPU批处理，
拟议1CPU、8GiB、Slurm10分钟、GPU=0；总coordinator≤570秒，各阶段child≤180秒，失败即停。
这属于新的资源/期限方案，不沿用旧50秒验收条件；若后来通过，仅记录为新的CPU批处理验收。
旧单进程和本次登录节点失败均保留，不能改称已通过原时限。

获同意后先核查分区/权限与实际资源，封装计算节点身份和调度上限、本地验证，
再单次提交。现有载荷强制登录节点，不能直接拿旧入口假装在计算节点运行。
不得申请GPU或自动继而提交G2/G5。新的CPU阶段仍只是G1工程证据，不是模型科学比较。

替代方案是继续有界剖析/等价优化扫描性能；不能保证任何一种方案一次完成。
在新的执行预算/方式审定前，本轮停在取证与决策，不继续消耗相同失败路径。
