# Job721086：原生 CPU 双轮参考/观测配对已独立验收

2026-09-17 11:14 JST取回结果，随后完成本地独立验收。此前SSH认证阻塞已解除；
本轮只查询、下载和核验既有作业，没有重新提交、上传代码或冻结输入。

## 结论与范围

Slurm：`COMPLETED / 0:0`，`lcpcc-051`，耗时10分26秒，1CPU/6000MiB/0GPU。
终态为`NATIVE_CPU_PAIR_PASS`，本地验收为`NATIVE_CPU_PAIR_VERIFIED`。
原单次CPU额度已经使用，不再执行submit、deploy或test-only。

在HAKUSAN Python3.11.5 / torch2.1.1+cu118上，四个独立冷进程按固定顺序完成：

| 阶段 | PID | 子进程耗时 | 返回码 |
| --- | --- | --- | --- |
| R-reference | 335736 | 111.778秒 | 0 |
| R-observed | 335849 | 207.354秒 | 0 |
| C-reference | 336113 | 59.900秒 | 0 |
| C-observed | 336219 | 206.517秒 | 0 |

每个进程使用独立空缓存、32条合成样本，batch16→batch1共34次调用。
两组参考/观测配对的两轮8类边界数组及4项官方输出数组全部逐字节相同，max_abs均为0。
这里的“相同”是**同profile、同pass的参考侧与观测侧比较**，不把它改称真实模型的16/1通过。
两个观测进程各记录2次目标编译调用、2次返回、2份生成工件且实际执行标记为真。
来源、固定四阶段顺序、PID/缓存不复用、状态/RNG、提交nonce、资源/时限及工件完整性已复核。
终态记录真实HOME未改、源后验通过、临时目录已由运行器清理；保留的发布包与结果工件未删除。

明确限制：这是合成模型CPU检查，fixture中存在已披露的模型预注入，
不是生产strict-load时序验证，也没有加载formal40、作者或valbest33 checkpoint。
CPU上的TF32配置不验证A100 TF32实际数值行为；不能据此认定真实32条或10k对比通过。
`production_model_loaded`、`production_interference_validated`、`ready_for_gpu`均仍为false。
配对结果内`jobs_submitted:0`描述验收器自身不提交作业，不否认本次既有Job721086。

## 固定证据

完整目录：[collect-20260917T021406Z-j0f1qrfp](g2-bridge-batch-20260916/collect-20260917T021406Z-j0f1qrfp/)。

- [独立验收记录](g2-bridge-batch-20260916/collect-20260917T021406Z-j0f1qrfp/VERIFIED.json)
  SHA `8ba39f7711452ece900cdf25589f63f3155964705d8057dd2fa5e9eb95934623`。
- 收集回执SHA `eb8b9633a8d71c243b2f5a3f61b52dd5d9268c737571ae59677c683f30ea405a`。
- 运行终态SHA `f41b22502f66f20ccdcf41055d3e14b5966ecd2c7cb07f044f2e83e7b9fe23a5`。
- Batch release SHA `50820c6fa76f60064cdcc0dd0ae3d9f4a5de2dd64ed41d2256e5e2c1945fa227`。
- nonce `b472c5ed3130470ebc656aa87863ab0e`；原提交意图与回执保持不变。
- 当前状态查询目录：`g2-bridge-batch-20260916/status-20260917T021333Z-if2l2me5`。

验收使用本地固定校验器，不执行下载结果中携带的代码；检查运输回执与恢复字节、
原发布源/本地测试、held资源、最终accounting，再复核所有运行工件和配对数组。
`review`写入一次的VERIFIED.json已存在，不要重复执行同一写入命令。

## 下一步

进入G2新生产worker整合：新输入身份绑定、保留真实HOME的scratch、原strict-load/场景作用域、
四组设置及有界执行/归档/独立验收。scratch和输入绑定此前的本地测试仍各有范围限制，
本结果不自动补足它们的真实生产验收。随后审定真实32条GPU矩阵；原1e-6门槛、
E→C→D→R选择顺序、三模型smoke、10k/controls及最终报告的要求不变。
尚未批准新的GPU额度，尚未完成最终checkpoint对比。
