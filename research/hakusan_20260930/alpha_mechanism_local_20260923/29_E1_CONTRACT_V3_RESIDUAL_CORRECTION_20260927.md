# E1 统计合同 v3：批形状残差修正

状态：LOCAL_CORRECTION_CANDIDATE_SIGNOFF_PENDING。本文件与 28 号合同组成 v3 合同；冲突处以本文件为准。28 号及其 v2 冻结包保留原字节。本轮用户授权修正，不等于统计签署、GPU 预算批准或远端提交授权。

## 1. 不改变的设计

保留现有候选公式 gα = 1 − α(1 − g)、网格 {0,.5,.75,.875,1}、三个 α=.5 负对照、2000 条样本及 19 条试点暴露。仍为探索性复用验证 bank 开发扫描。38400 条预测、400 条 control、200 条 clean、原预算候选上限不变。没有增加探针或作业。

## 2. 覆盖 28 号 §3、§5、§7 中的恒零与等价主张

main correct 使用 batch=16，control 为同主批过滤后的子批（非空大小 1–7）。α=0 的数学 cue 独立性不保证两个批形状的浮点输出相同。existing explicit_bypass==alpha_0 门只检验同条件的两种实现，不检验 correct==shuffled。

必须按 trial_id 对齐实测输出，定义 cα=I(correct,α)−I(shuffled,α)、r0=c0；主指标为 D=c1−r0，剂量指标 Dα=cα−r0。不得将 r0 置零，也不得无条件简化 D 为 c1。只有观测 r0 对每条样本全零时才能报告本次 top-1 数值恰好相等，不能外推为构造保证。

同时逐条保留 NLL(correct,α)−NLL(shuffled,α)，特别报告 α=0 的 mean、std(ddof=0)、max_abs、预测类别不一致数及其 trial_id 对齐数据。clean 两 cue 使用同批布局，其现有逐位验收门不变。

所有 bootstrap（含排除重叠的敏感性版）对完整逐 trial D/Dα 重采样；必须同步报告 c1、r0 及它们的 CI。§4.4 的旧方差估算只针对 E0 的 c1，不能当作 E1 完整 D 的已知方差或精度保证。

§7 中 D 的 CI 标签阈值暂沿旧候选 δ，但删除 D 恒等于训练态 cue 效应的解释。ALPHA_FLAT 只表示所采样点的配对差相对 α=0 残差在界限内，不等于所有 cue 效应为零，也不等于曲线处处平坦。若 r0 有任何 top-1 非零项，记录 MAIN_CROSS_BATCH_RESIDUAL_PRESENT；该轮只能给开发计算/描述性状态，不给科学候选或机制标签，须另行审阅批形状影响，不能自动加作业或放宽阈值。r0 top-1 全零也不意味着 NLL 残差全零。

## 3. 来源验收

生产 WORKER 需非空 Python/torch/CUDA/hostname/GPU 信息、正 cuDNN 版本、A100 设备标识、与归档一致的 Slurm 作业号及 8 CPU；六个 runtime 实值按冻结 eager FP32 合同严格类型和值比较。UTC 时间须可解析、带零时区偏移，process start≤pass start≤pass finish≤process finish。GPU 峰值为正整数字节、reserved≥allocated，RSS 保留单位。缺失或错误均拒绝生产验收。

CPU 合成测试仅可由包外测试驱动显式选用宽松来源校验，不能由归档字段或生产入口参数启用。合成通过不构成真实 GPU 来源核验。

## 4. 签署与后续

v3 RELEASE 同时绑定 28 号基础合同与本修正 SHA。后续 SIGNOFF 必须绑定两份文件，明确 δ 和上述解释边界；签署前仍为候选，不将旧统计状态称为已批准。本次仅实现配对算术归档及工程验收，完整 bootstrap/报告阶段仍需按合同实现和验证。不得把 E1_ARCHIVE_VERIFIED_NOT_SCIENCE_QUALIFIED 当作 E1_DEV_COMPLETE。
