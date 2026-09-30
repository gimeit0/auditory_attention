# E0：formal40真实模型小批验收方案

日期：2026-09-23。版本：提案v1。状态：`E0_PLAN_READY_NOT_AUTHORIZED`。

本方案只定义一批工程验收，不代表已获GPU预算批准，不代表执行包就绪。超算暂停仍有效。它不启动E1的2k扫描、作者模型重评、阶段checkpoint扫描、新数据对齐或训练。

## 1. 要回答什么

验证“α及负对照是否按定义作用于真实formal40，且没有改变原有评估路径”，不是判断α是否提高Accuracy。

三个必须回答的问题：

1. 未干预模型与α=1能否复现正式作业728520的对应输出？
2. α=0是否等价独立实现的8处gain旁路，且相同scene换cue不改变输出？
3. 三个负对照、有限性、状态不变、冷重复及轻量观测是否满足工程合同？

仅formal40：checkpoint SHA `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff`。身份为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。独立说话人筛选尚未完成，不影响这项工程验证，但不能因此把旧bank称作独立测试。

## 2. 样本：96条，6个历史完整批

选择依据仅为元数据覆盖和原批边界，不查看模型表现挑样本，不做随机补选。布局提案见[E0_SAMPLE_PROPOSAL.json](E0_SAMPLE_PROPOSAL.json)。

| 原trial闭区间 | 原batch索引（0起） | 覆盖 | control数 |
| --- | ---: | --- | ---: |
| 0–15 | 0 | 1个干扰说话人 | 16 |
| 2256–2271 | 141 | 2个干扰说话人 | 16 |
| 4512–4527 | 282 | 3个干扰说话人 | 16 |
| 6752–6767 | 422 | 4个干扰说话人 | 16 |
| 8992–9007 | 562 | 8 mixed + 8 clean的历史交界批 | 0 |
| 9008–9023 | 563 | 16 clean | 0 |

合计72 mixed、24 clean、64 control。correct分支96条；shuffled/silent/distractor各64条，每轮288条预测。前4批的control恰好都是16条，后2批没有control：原批内顺序及control子批形状均可原样复现。不能把64条control任意重分批，也不能按scene_kind把交界批拆开。

这是工程覆盖集，非分层总体估计集；不承诺覆盖所有性别/SNR/标签，不能报告它的Accuracy为全bank结果。clean仍是target-only/零cue；**零cue不等于gain bypass**。生产旧predict传入的mask是None，不因clean自行新增mask。target-only+正确cue属于后续新条件，不混入本批历史桥接。

本地核查已完成：归档bank/RUN/results/logits四文件SHA一致；6批确实包含于728520的RUN.batches；样本/分支计数一致。这里是本地归档核验，不是重新核验远端checkpoint。

## 3. 固定执行协议

- 复用728520的strict加载、已知包装层解包、原生逐样本预处理和cochleagram语义；不修改冻结源文件。必须另写formal40单模型候选入口：旧evaluate_pass强制三模型，不能直接删字段冒充已支持单模型。
- 实际模型须恰好7处conv gain + attnfc，路径/类/源码/参数绑定核验；拒绝additive、residual、额外cue输出、未知布局或已有hook。
- 固定权重、eval、无梯度、FP32、eager；本批**不使用Inductor/torch.compile或AMP**。
- 目标环境与历史：Python3.11.5、torch2.1.1+cu118、CUDA11.8、cuDNN8700、A100。runtime六项：deterministic=True，cuDNN deterministic=True，benchmark=False，matmul precision=`highest`，matmul TF32=False，cuDNN TF32=False；CUBLAS_WORKSPACE_CONFIG沿历史`:4096:8`。不得沿用早期失败诊断的high/TF32=True。
- 固定seed与原scene生成规则，不跨条件更换批布局。输入scene/cue摘要须与历史一致；所有旧conditions的标签/role定义不变。
- 每个独立进程重新strict-load一次formal40，共2次，不并行占两卡；重建输入并留摘要。固定条件顺序如下，阶段间恢复模块并核验状态，不保留上阶段干预。

## 4. 实验矩阵与确切工作量

进程A、进程B各顺序执行同一10轮；每轮跑全部96条及64×3个control。

| 顺序 | 条件ID | 定义/用途 |
| ---: | --- | --- |
| 1 | original | 原路径，同历史桥接 |
| 2 | alpha_1 | 8处α=1，直接原gain调用 |
| 3 | explicit_bypass | 独立最小旁路实现，不调用α适配器；保留相同模型主干 |
| 4 | alpha_0 | 8处α=0，对旁路及cue不变性 |
| 5–7 | alpha_025/05/075 | 主干中间α，有限性与重复性，不要求准确率改善 |
| 8 | uniform_05 | 每样本有效gain在非batch维取均值并广播 |
| 9 | conv_only_05 | 仅7处conv gain改α，attnfc保持原对象 |
| 10 | fc_mean_preserved_05 | 前7处正常α，attnfc有效gain缩放至其原均值 |

进程A另加一轮`alpha_05_observed`，置于其10轮之后，和同进程无观察器的alpha_05逐位比较。只收集预定8处的输入/输出摘要及有界公式误差统计，不引入递归对象图追踪。

工作量：`2×10×288 + 1×288 = 6,048`条完整模型—条件预测，21轮；其中correct为2,016条，其余controls合计4,032条。严格上限，不自动补样本/加α/增加第三模型进程。独立旁路对照包含于预算，不是另算。

mask和负对照公式单元验收使用预定首批的有限特征/gain张量，逐批处理并释放；只做gain级运算，不增加完整分类forward。它们不进入科学预测表。不得归档全部层激活。若要增加全模型mask专项forward，需先改本提案计数和预算再审。

## 5. 通过标准：先定规则，后看结果

| 门槛 | 通过要求 | 失败动作 |
| --- | --- | --- |
| G0 输入/加载/布局 | SHA、trial顺序、各分支计数、scene/cue、strict-load覆盖1.0、8处gain全部匹配；无漏权重/新参数 | 停，不解释模型行为 |
| G1 历史桥接 | A/B的original与728520相同trial/条件logits **逐位一致**；alpha_1与各自original亦逐位一致 | 停；保存差异trial/最大差/环境，不以P06包络放行 |
| G2 α=0端点 | alpha_0与独立bypass逐位一致；前4个完整control批内，相同scene的correct/shuffled/silent/distractor输出逐位一致 | 停并定位cue通路或批形状/预处理变化 |
| G3 冷重复 | A/B全部10轮各自logits逐位一致、标签完全一致；记录不同PID及重新加载证据 | 停，无自动第三次尝试 |
| G4 状态与有效性 | FP32 logits `[分支条数,800]`且有限；原始输入、参数/buffer、运行时和正式forward前后RNG不变；模块恢复、无残留hook | 停；加载初始化前后的RNG不拿来假装forward不变 |
| G5 三负对照语义 | 模块范围准确、参数身份不变；uniform逐样本不跨batch；末层均值保持定义成立；mask行identity | 停；不得把控制实现错误解释成机制效应 |
| G6 观测无干扰 | alpha_05_observed对同进程alpha_05 logits逐位一致；输入/状态不变，8处事件完整且退出移除观察器 | 停，追踪数据不能解释模型 |
| G7 归档验收 | COMPLETE、Slurm COMPLETED/0:0、6048条无重漏、文件哈希/合同关联与独立离线复算全部通过 | 归档失败不叫E0通过；保留产物，不自动重提 |

“逐位”以同dtype/shape下连续logits字节一致为准，不仅比较argmax或平均NLL。同GPU同函数计算的NLL也要求逐位；离线CPU从logits复算FP64 logsumexp与保存FP32 NLL采用预定`atol=2e-5, rtol=2e-6`，它仅是跨设备派生量复算容差，不是logits桥接容差，超出即失败待审。离线另外报告最大误差，不能只给PASS。

G5公式验收：在固定特征上由独立参考计算gain，`atol=2e-6, rtol=2e-6`；均值误差同阈值。该值是**提案容差，生产测试前审定**，不能见结果后放宽。末层有效gain均值分母绝对值≤1e-8或非有限即拒绝，不加epsilon。若真实权重在此定义下不可用，状态`E0_CONTROL_UNDEFINED`，先修改科学定义并重审，不伪装成通过。

uniform的α=1不等于原模型；conv_only的α=0和fc_mean_preserved的α=0不保证无cue。这些对照不能套用主干端点标准，本批实际只测其α=.5。同布局消除批组成混淆，但不保证跨α没有任何数值影响。中间α平坦或效果变差**不属于工程失败**，如实保留。

## 6. 预算提案：单作业、单卡、30分钟上限

| 资源 | 提案 |
| --- | --- |
| GPU | 1×A100-40GB，1作业，最多0.5 GPU小时 |
| CPU / 主存 | 8 CPU / 64 GiB |
| Slurm时限 | 00:30:00；协调器1500秒硬期限，余量用于结束和失败归档 |
| 进程/加载 | 2个顺序模型进程，各strict-load一次；不并行、不编译 |
| 产物 | 总归档≤128 MiB，不保存全层激活；6048×800×4的原始logits约18.46 MiB |
| 内存监测 | 记录max allocated/reserved/RSS；每阶段同步后allocated峰值>16 GiB或RSS>24 GiB即停止下一阶段并标资源超限；非瞬时硬内存隔离 |
| 失败 | OOM、超时、输入变化、端点失败即结束并保留可得产物；不得悄悄改batch1或重试 |

估算依据[P07实测](../docs/superpowers/evidence/p07conf-production-20260919/REPORT.md)：correct约0.0626秒、control约0.0733秒、scene约0.145秒/trial。故forward约`2016×.0626 + 4032×.0733 = 421.7秒`；保守按21轮均重建96条scene估算约292.3秒；两个进程启动/加载预留100秒、状态摘要/保存/观测/离线检查预留180秒，总约994秒，即**16.6分钟**。申请30分钟硬上限，不保证线性、不承诺必定完成；新公式、哈希同步或NFS慢可能增加开销，超时也不自动续批。

授权用语建议（目前未获批准）：完成执行包本地验收后，单独批准“E0提案v1：1作业、1 A100、8CPU、64GiB、30分钟、6048条预测、两次加载、单次held提交、无自动重试”。站点改写typed GRES时，**另行授权同一held作业唯一一次修正**，独立回读正确后才放行。未获此授权不得沿用旧作业授权。

## 7. 提交前必须补齐的实现，不允许跳过

1. 把本布局提案物化为96个有序ID、6批和条件索引；冻结layout/源码/合同SHA。已有本地合成contract不得改scope后直接冒充生产RUN。
2. 新建单模型生产适配，strict加载/预处理与原科学代码逐项核对；源、checkpoint、配置、bank、音频来源/输入摘要、runtime、8路径、α/mode、job/PID、加载报告进入RUN。
3. 实现独立bypass、历史子集提取器、上述门槛和失败归档；观察器只做定点、有界数据采集。
4. 本地合成回归覆盖完整6048条产物、错序/错mode/少行/归档损坏/超时分支、NLL复算、模块恢复和预算计数；禁止只凭目前30项单测称执行包就绪。
5. 本地代码审阅后再请用户批准恢复连接与部署；只读确认远端文件和环境，新独立目录上传、哈希、test-only。若需要额外远端CPU测试预算另列，不隐含在本轮文档授权中。
6. 审批具体GPU批次→单次held提交→资源核验→单次放行→只读status/collect→独立验收。共享SSH过期由用户终端重连，无自动重连。

## 8. 出口与执行台账

`E0_PLAN_READY_NOT_AUTHORIZED` → `E0_PACKAGE_LOCAL_PASS` → `E0_REMOTE_PREFLIGHT_PASS` → `E0_HELD` → `E0_RUNNING` → `E0_COLLECTED_NOT_VERIFIED` → `E0_ENDPOINT_PASS`。

任一阶段失败进入具体`E0_*_FAIL`或`E0_CONTROL_UNDEFINED`；保存证据并停在当前阶段。即使E0通过，也只允许编制E1预算，不自动执行2k扫描，不把机制结论写成已证实。

2026-09-23实际记录：本地四文件SHA与历史批匹配/计数核查通过；方案SHA `8d562e56ec4980b45fb1aa4e338b01dfcc026587f6ab7703009b1b2ab1a11aef`（指JSON样本提案，不是整个执行release）。检查命令：

```bash
/opt/anaconda3/envs/audattn/bin/python -B alpha_mechanism_local_20260923/check_e0_proposal.py
```

输出`E0_LOCAL_PROPOSAL_CHECK_PASS`，96/24/72/64、288×21=6048。未连接远端、未加载checkpoint、作业提交数0。下一步为第7节的**本地执行包实现与验收**，不是现在提交GPU。
