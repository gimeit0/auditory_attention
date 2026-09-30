# G2真实模型执行流程接线：本地候选与明确缺口

前置：[Job721086原生CPU R/C双轮配对已独立验收](2026-09-17-job721086-native-pair-verified.md)。
认证与该作业结果已经取回，不再以旧认证阻塞描述当前状态。

## 本轮新增

独立目录：[g2_lifetime_20260917](../prototypes/g2_lifetime_20260917/README.md)。
接入固定输入关系、保留真实HOME的scratch、原生产claim/load、冻结场景、strict-load和两轮bridge。
锁在单个child中独占持有，不改锁文件；准备失败时尚未返回的授权也会撤销。
数据保存前后复核原pass内容、summary、RNG/模型/运行设置、输入、scratch及来源。
数值差异保持NUMERIC_DIFF，不把它误报为执行失败；保存或清理失败则不返回成功。

结果归档通过受检查的调用接口衔接。这里没有假装已经完成实际大数组writer、
独立数组验收、发布清单/新freeze、coordinator、SBATCH或生产参考/观测干扰验证。
不提供CLI提交入口，也不沿用Job721086的单次CPU资源授权。

## 验证

- 19项控制流与本地OS锁测试通过；模型/capability/device部分为显式模拟对象。
- D、E两个独立冷进程分别使用实际bridge/scratch/spill/mmap与合成32条，
  各34次调用、strict-load一次，4份特征映射；两pass内容承诺不变，summary可序列化。
- 另一个E冷进程在第二轮首条注入失败；只保留第一轮2份特征映射，撤销证明、拒绝再次调用。
- 实际原证明撤销、描述符作用域关闭、HOME保持、临时目录清理均检查通过。
- 四阶段总30.208秒，单child45秒、总120秒上限；无网络操作或调度提交。

范围限制：本机torch2.12.1、合成模型，使用显式Linux-mount stub；
没有运行真实生产输入loader、`ProductionCell.run`的真实模型全链、原生Linux挂载或A100推理。
不能将19项模拟控制流测试和合成推理拼成“完整生产通过”。

## 固定证据

目录：[g2-lifetime-local-20260917T032221Z-2bz9y1zy](g2-lifetime-local-20260917T032221Z-2bz9y1zy/)。

- 回执SHA `a9e6106523c3b8d1133d2fd2dceac1a9ce1f6c4d4c3f3504cba82408c6a1df07`。
- `production_cell.py` SHA `602d90cc26ee5900ed801e45a15b4f30ebbbe3bd9edf5f9ccb65a93f8982be24`。
- 20份源快照、运行前后哈希、四份日志/进程回执和作用域声明已保存；只读复查通过。
- 前一31.904秒初验也保留；最终验收新增实际summary序列化与证明撤销检查。
- 旧scratch/输入关系证据及Job721086完整源/结果再次只读复核通过，未改写旧发布文件。

## 后续进展

同日已完成[数组归档及独立内容校验候选的本地验证](2026-09-17-g2-array-archive.md)。
原lifetime代码未修改，新增库接口支持其consume回执；实际合成bridge/mmap已验证读写，
不等于本文件ProductionCell真实模型全链已经运行。

## 下一项（尚未执行）

把已有容量受限归档/内容校验组件接入有界新生产运行器，完成新身份发布/冻结及执行来源验收。
真实32条G2矩阵仍需原计划的生产验收和GPU额度批准；之后才是三模型smoke、10k/controls和统计报告。
本轮没有新GPU提交、真实模型比较结果或完整目标完成声明。
