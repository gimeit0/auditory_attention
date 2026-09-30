# 2026-09-17：G2 临时目录/输入接口与认证恢复记录

最新更新：用户恢复认证后，11:14 JST取回Job721086完整工件并独立验收通过。
COMPLETED/0:0、10分26秒；R/C原生合成CPU双轮参考/观测数组逐字节相同，没有重复提交。
见[完整结果及范围](2026-09-17-job721086-native-pair-verified.md)。
认证阻塞已经解除；下面“未取回/blocked”仅为此前历史，不再描述当前作业状态。
本地scratch/输入候选的原生生产覆盖限制仍在，不因该合成CPU结果而自动通过。

## 当日较早停点与证据边界（已被上述新结果更新）

Job721086 已于9月16日单次提交。本地最后有效状态回执是9月16日15:13 JST的
RUNNING/Elapsed3:39；**这不是9月17日的实时状态**，也不能据此断言现在仍运行或已经成功。

9月17日重新检查发现 `.hakusan-control/master.sock` 不存在。
首次沙箱查询无法解析主机；获网络权限后，用 BatchMode、有界连接超时、仅查询
`hostname` 和 Job721086 accounting 的命令返回：

```text
s2510040@hakusan1: Permission denied (publickey,password,hostbased).
```

返回255发生在认证阶段，远端作业查询未执行。未获取/保存密码，未提交新作业、
未取消或重提旧作业、未上传、更改远端代码或冻结输入。
当前远端 blocker 是需要本人在终端恢复认证；不是已证明的作业计算失败。

认证恢复后，只依次进行原入口 `status` → 终态后 `collect` → 本地 `review`；
不要再执行 `submit`、`deploy`、`test-only`。成功证据不足时不进入真实 GPU 矩阵。

## 本地发现并处理的具体接口问题

新 G2 `CellBridge.run` 保留 `type(scratch) is diag._WorkerScratch`。
旧 `_WorkerScratch.check` 又要求 HOME 指向 scratch/home；此前的保留真实 HOME
实现使用 PrivateScratch 类型。因此两者直接组合会被精确类型门槛拒绝。
这是一项代码检查发现的生产集成缺口，**不是 Job721086 的已确认失败原因**。
Job721086 是合成 CPU 流程，不走这个生产 scratch 门槛。

新增独立候选：[g2_scratch_20260917](../prototypes/g2_scratch_20260917/README.md)。
旧发布包、v4/v19、四组已固定派生源和模型均不改写。

- 目录工厂仅派生 G2 的目录前缀和角色白名单。
- 原目录检查保留，缓存路径单独排除 HOME，并额外核对真实 HOME 未变。
- 复制的 bridge.run 仅替换精确 scratch 类型；反向 AST 检查要求其余函数体完整一致。
- 原 spill/mmap、Linux挂载检查、所有者/0700、独占创建、失败后保留目录、状态/输入/数值检查不删除。
- 新 binding 要求相同源模块、同进程、当前作用域的自身 scratch；禁止重入和复用失败目录。

## 本地验收

15项测试通过，0失败/错误/跳过；固定记录运行6.570秒，监督器上限45秒。
覆盖R/C/D/E及reference/observed目录、HOME保持、错误身份/环境、原源码及AST、
旧精确类型冲突复现、新精确类型接口、关闭/异常/替换/symlink/重用拒绝。

测试明确使用本地 Linux-mount stub；桥接测试停在真实推理作用域之前。
**未加载checkpoint、未初始化CUDA、没有原生Linux/GPU或完整worker验证。**
不能把15项接口测试与此前合成推理测试相加称作一次完整生产通过。

固定证据：[g2-scratch-local-20260917T015924Z-l5ehxprx](g2-scratch-local-20260917T015924Z-l5ehxprx/)。

- `RECEIPT.json` SHA：`43c8f44c6805f0ac86bdd72ecc85f725517f0564f4d06c0e54609fb6ee265a9d`。
- `scratch_binding.py` SHA：`f0d16a11c712c9c1c96de6a5906efc4ac3978d012660eb33399672a681b2e271`。
- 源码副本、前后哈希和测试stdout/stderr已保留；独立只读复查通过。
- Job721086的原30文件本地发布包与原测试/合成输出证据另行只读复核通过，未改变远端发布身份。

仅自动清理测试自身建立的临时目录；失败/运行证据目录、历史作业、数据与checkpoint均保留。

## 下一步顺序

1. 恢复认证后取回Job721086终态、完整工件，独立复核原生R/C双轮配对。
2. 新scratch候选接入新生产worker时，验证真实来源/新执行身份、实际spill和数值推理端点，
   不复用旧发布身份，不将本地mount stub引入生产。
3. 按主计划G2的预定矩阵与接受规则做真实32条数值设置决策，再走三模型smoke、10k/controls及报告。

最终checkpoint对比仍未完成，当前没有新的真实模型数值结果。

## 同日继续：新输入关系候选已本地验证，认证仍未恢复

再次检查共享socket仍不存在；同一有界、只读的Job721086查询继续在认证阶段
返回 `Permission denied (publickey,password,hostbased)` /255，未取回新的作业状态。
当前没有已确认仍存活的进程/作业句柄，因此不把本轮称为运行中的“等待”。
上一轮为接口实现及测试进展；本轮为下述输入绑定实现及测试进展。目标未完成。

新增独立[输入关系与原生产loader连接候选](../prototypes/g2_inputs_20260917/README.md)：

- 各profile使用自己的固定protocol/root/代码SHA和新freeze，旧v18仅作为数据依据。
- 完整比较32条身份、顺序、bank行、135份clip及96份snapshot记录、模型/标签/v4合同。
- 只有新执行身份、另行校验的四份代码记录及跨次文件系统inode/device/mtime允许不同；
  内容SHA、大小、权限、用途等不删除。进程内仍调用原完整重验。
- `WorkerInputs`保留原生产冷进程claim、输入加载与重验，另核对新root下物理代码和freeze。
  外层发布/调度授权、锁、scratch、真实场景、模型执行与归档仍未由本组件提供。

16项本地测试通过，0失败/错误/跳过，1.262秒；监督器上限30秒。
测试的新freeze身份及两个未来启动文件为明确合成fixture，**没有执行真实生产loader**，
没有创建远端freeze或加载模型。AST检查只证明原loader调用未删，不等于生产集成通过。

固定证据：[g2-inputs-local-20260917T020953Z-h62a3opl](g2-inputs-local-20260917T020953Z-h62a3opl/)。

- 回执SHA：`56acc1d761c0aa012b8b264a6d032e02a55212c1ef9bf4bbbcd3de402c715645`。
- `input_binding.py` SHA：`6a99559df859bb88cdf730d7dcd1bf72caf2f2f04800ae69781da23e64103896`。
- 源码副本、前后哈希、完整日志及独立只读复查通过；上一轮scratch证据也再次复查通过。

目前不能在缺少Job721086原生结果的情况下判断应修正哪条编译路径，或发布新的真实GPU矩阵。
下一项仍是恢复认证、只读获取该作业终态并收集验收，不能以继续堆叠合成测试代替这项证据。

## 11:11 JST：连续第三轮确认认证阻塞

共享socket仍不存在；现有证据目录没有新增状态回执或收集结果。
已获网络权限的同一有界免密只读查询再次返回255及
`Permission denied (publickey,password,hostbased)`，远端查询仍未执行。
前两轮分别完成scratch接口与输入绑定的本地工作；本轮没有新的计算结果，
不能标为已确认运行中的等待，也不能根据昨天的RUNNING推断今天的终态。

连续三轮遇到同一缺少有效SSH认证的阻塞。独立于远端结果的上述两项本地工作已完成；
下一步必须取得已提交作业的原生证据，才能决定发布或针对失败修正。
将持续目标标记为 **blocked（等待本人恢复认证）**，不是complete。
没有取消、暂停、重提或更改Job721086；该作业在超算上的实际终态仍未知。

解除条件：本人在Mac终端运行既有连接脚本并完成交互认证，共享连接可用。
恢复后继续原721086的status、终态collect、独立review；不从submit重新开始。
