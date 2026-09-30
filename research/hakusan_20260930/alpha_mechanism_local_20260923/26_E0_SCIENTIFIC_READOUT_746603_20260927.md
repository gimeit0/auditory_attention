# E0 作业 746603 科学读数备忘（事后描述性读数）

日期：2026-09-27。作业：HAKUSAN 746603，formal40，96 条固定 trial，21 轮，6048 条预测。

状态行：E0 已达成 `E0_ENDPOINT_PASS`（E0_COMPLETE.json，`scientific_alpha_result=false`）。本备忘是对已归档数组的事后读数，不改变任何验收状态，不改动 E0 冻结包或 E1 冻结包。研究身份仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`：复用验证 bank 的审计，不是独立测试集。E0 是工程验收，不是 α 机制成立的证据；下文所有数字来自 96 条、单模型、单作业，无置信区间，属试点观察。

## 1. 数据来源与复现

输入（只读，SHA 由脚本实际核算）：

| 文件 | SHA256 | 大小 |
| --- | --- | ---: |
| `release_e1_20260926_v1/package_ready/frozen_bank.tsv`（10000 行，`target_label` 为 0..799 类别索引；`target_index` 是音频池索引，不使用） | `d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091` | 10803199 |
| `state/attempt/E0_COMPLETE.json` | `49b209b52611c3eae66a915d207186926c71d91c7536b7f56a8b33c114fc9d84` | 944 |
| `state/attempt/PAIR_EXECUTION.json` | `ba621556a0e8d76d11e3aa7a152730d83a4e0ea86f41f1482e4ebe629d307c32` | 1623 |
| `A/WORKER.json` / `B/WORKER.json` | `4cf6cfbc…` / `2a1bbea9…` | 2478 / 2181 |
| `A/PROVENANCE.json` / `B/PROVENANCE.json` | `f4494c19…` / `f31b9668…` | 1446 / 1446 |
| `A/STAGES.json` / `B/STAGES.json` | `b8a8b064…` / `efbe2976…` | 73903 / 66989 |
| `A/OBSERVER.json` | `d75d03cb…` | 150222 |

state 目录为 `alpha_mechanism_local_20260923/release_20260925_v2/collect-746603-SlcKgK/state/attempt/`。21 个 `NN_*.npz`（每个 928168 字节）的 SHA256 全部与各自 WORKER.json 一致；完整值见输出 JSON 的 `inputs.processes`。每个 npz 含 `correct_*`（96 条）与 `shuffled_*`/`silent_*`/`distractor_*`（各 64 条）的 ids、float32 logits[·,800] 与 float32 NLL；四个条件的 NLL 参考类别均为该 trial 的 `target_label`。两进程、所有 pass 的 trial 顺序完全一致；64 条 control 是 96 条 correct 的前 64 条。96 条中 24 clean（trial 9000..9023）、72 mixed。工程验收台账见 docs/superpowers/evidence/e0-production-20260926/REPORT.md，其 SHA256SUMS.txt（45 文件）不含本目录 readout/ 两个文件；readout 文件 SHA 记于本文 §1 与 alpha README 新增文件表。

脚本与输出：

- 脚本 `alpha_mechanism_local_20260923/e0_readout_746603.py`，SHA256 `cf27eafa1799633a272fee9e8564cc9625dbed349fc9d0481f99b9e641dc1841`（14776 字节）；只依赖 numpy / pandas / json / hashlib / argparse；不加载模型、不做推理、不做 bootstrap 或假设检验。
- 输出目录 `docs/superpowers/evidence/e0-production-20260926/readout/`：`E0_READOUT.json`（80003 字节，SHA256 `8ea0b79d70d35981fc6e769400381e03d1773c372de348e4fedb965af74a9ebb`）与 `e0_readout_table.csv`（12321 字节，SHA256 `5ec6ff77795416880b97e4d336d810e42fa2505f7de1e13ccbc96efc935be20b`，21 行 pass 加表头）。JSON 内记录输入文件 SHA、bank 行数与脚本自身 SHA。
- 测试 `alpha_mechanism_local_20260923/test_e0_readout.py`（9 项：合成 4 条 correct、2 条 control、800 类；覆盖准确率/NLL/clean-mixed 拆分、逐位比较与 A 独有 pass、预测类众数并列报告、bank SHA 不符拒绝、npz 与 WORKER.json SHA 不符拒绝、NLL 偏差只标记不掩盖、输出只写一次）。全目录 `test_*.py` 共 214 项通过（此前 205 → 213 → 214；26.351 秒为 213 项时的用时）。

2026-09-27 02:15 因脚本新增并列众数字段（most_frequent_predicted_classes），删除 readout/ 旧输出后以同一命令在同一目录重跑；当前 JSON 内 `script.sha256` 为 `cf27eafa…`，CSV 逐字节不变。

复现命令（脚本拒绝覆盖已有输出，重跑请换新的 `--out`）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/e0_readout_746603.py --out <新目录>
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py' -q
```

## 2. 主表（correct 条件，96 条；进程 A，进程 B 相同）

| pass | top-1 准确率 | 平均 NLL（保存值） | \|logit\| 最大 | 预测类别数 / 最多类 | A==B 逐位 |
| --- | ---: | ---: | ---: | --- | --- |
| original | 41/96 = 0.4271 | 3.1477 | 78.90 | 87 / 最多 2 次（9 类并列） | 是 |
| alpha_1 | 41/96 = 0.4271 | 3.1477 | 78.90 | 87 / 最多 2 次（9 类并列） | 是 |
| explicit_bypass | 0/96 = 0.0000 | 631.9551 | 2722.09 | 2 / 697×95 | 是 |
| alpha_0 | 0/96 = 0.0000 | 631.9551 | 2722.09 | 2 / 697×95 | 是 |
| alpha_025 | 0/96 = 0.0000 | 373.4207 | 2402.75 | 11 / 697×76 | 是 |
| alpha_05 | 6/96 = 0.0625 | 46.4000 | 1360.19 | 64 / 697×12 | 是 |
| alpha_075 | 37/96 = 0.3854 | 3.3448 | 72.52 | 91 / 最多 2 次（5 类并列） | 是 |
| uniform_05 | 0/96 = 0.0000 | 631.8939 | 2721.90 | 2 / 697×95 | 是 |
| conv_only_05 | 6/96 = 0.0625 | 46.3954 | 1360.17 | 64 / 697×12 | 是 |
| fc_mean_preserved_05 | 6/96 = 0.0625 | 46.3955 | 1360.15 | 64 / 697×12 | 是 |
| alpha_05_observed（仅 A） | 6/96 = 0.0625 | 46.4000 | 1360.19 | 64 / 697×12 | A 独有；与 A 的 alpha_05 逐位一致 |

- “预测类别数 / 最多类”列：最多类出现并列时不再单列一个类号。JSON 字段 `most_frequent_predicted_classes` 列出全部并列类（升序），`most_frequent_predicted_count` 给出次数，`most_frequent_predicted_class` 只在唯一众数时给类号，否则为 null。original 与 alpha_1 的 9 类为 [257, 261, 360, 446, 560, 586, 637, 697, 700]，alpha_075 的 5 类为 [281, 360, 379, 586, 759]。
- A 与 B 十个共享 pass 的全部 12 个数组（ids/logits/NLL × 4 条件）逐位一致（tobytes 相等）；A 独有 `alpha_05_observed`。
- original 与 alpha_1 逐位一致；alpha_0 与 explicit_bypass 逐位一致（与 E0 验收结论相同，此处只是复述）。
- 类别 697 在 bank 中对应 `target_norm` 为 their。
- 由 logits 以 float64 复算 NLL 与保存的 float32 NLL 比较：21 pass × 4 条件的最大绝对误差 6.1035e-05（出现在 NLL 约 632 至 640 的 bypass / alpha_0 / uniform_05），全部处于 E0 方案第 5 节的派生量容差 `atol=2e-5, rtol=2e-6` 内；所有 logits 与 NLL 有限。

control 条件（64 条，进程 A；准确率 / 平均 NLL）：

| pass | shuffled | silent | distractor |
| --- | --- | --- | --- |
| original / alpha_1 | 3/64 = 0.0469 / 6.2798 | 6/64 = 0.0938 / 9.2208 | 0/64 / 10.8213 |
| alpha_075 | 3/64 = 0.0469 / 6.1761 | 4/64 = 0.0625 / 9.5154 | 0/64 / 8.9820 |
| alpha_05 | 1/64 = 0.0156 / 52.3254 | 2/64 = 0.0312 / 41.8117 | 0/64 / 47.3116 |
| alpha_025 | 0/64 / 387.5823 | 0/64 / 333.4258 | 0/64 / 378.0066 |
| alpha_0 / explicit_bypass | 0/64 / 640.4489 | 0/64 / 640.4489 | 0/64 / 640.4489 |
| uniform_05 | 0/64 / 640.3944 | 0/64 / 640.3270 | 0/64 / 640.3831 |
| conv_only_05 | 1/64 = 0.0156 / 52.3179 | 2/64 = 0.0312 / 41.8110 | 0/64 / 47.3008 |
| fc_mean_preserved_05 | 1/64 = 0.0156 / 52.3204 | 2/64 = 0.0312 / 41.8044 | 0/64 / 47.3082 |

在 alpha_0 与 explicit_bypass 中，64 条 control 的 correct 行与 shuffled 行逐位相同（64/64），三种 control 的 NLL 因此完全相同；这是 cue 独立性的工程事实。

## 3. clean / mixed 拆分（correct 条件）

| pass | clean（24） | mixed（72） | control 64 条：correct 减 shuffled 准确率 |
| --- | ---: | ---: | ---: |
| original / alpha_1 | 16/24 = 0.6667 | 25/72 = 0.3472 | 0.2969 − 0.0469 = 0.2500 |
| alpha_075 | 15/24 = 0.6250 | 22/72 = 0.3056 | 0.2500 − 0.0469 = 0.2031 |
| alpha_05 / conv_only_05 / fc_mean_preserved_05 | 1/24 = 0.0417 | 5/72 = 0.0694 | 0.0469 − 0.0156 = 0.0312 |
| alpha_025 / alpha_0 / explicit_bypass / uniform_05 | 0/24 | 0/72 | 0.0000 |

clean 条 24 条、mixed 72 条均为工程覆盖集，不是分层总体估计；末列只是逐 trial 指示变量的均值差，不附任何区间。

## 4. 三点解读（试点观察，不是结论）

以下解读全部来自 96 条、单模型 formal40、单作业、无置信区间的试点数据。

1. **把有效 gain 从训练态向 1 插值时，输出 \|logit\| 量级增大、预测类别收缩、准确率与 NLL 整体崩溃；这提示激活可能偏离训练分布，但本读数未测量中间层激活。**** 公式 `gα = 1 − α(1 − g)`：α=1 保留训练得到的 g，α=0 把八处 gain 全部置 1。从 α=1 到 0，correct 的 \|logit\| 最大值由 78.90 变为 72.52（α=.75）、1360.19（α=.5）、2402.75（α=.25）、2722.09（α=0），准确率由 41/96 变为 37/96、6/96、0/96、0/96，平均 NLL 由 3.15 变为 3.34、46.40、373.42、631.96。预测类别在 α≤.25 时收缩到 11 个乃至 2 个，α=0 时 95/96 条都预测类别 697。与 cue 选择性丧失相比，这些数字更符合整个分类器输出崩溃的描述（correct 与三种 control 的 NLL 632 对 640，准确率均 0）。α=.75 在此 96 条上尚保持接近原模型的量级（与 original 的 top-1 一致率 54/96，最大 logit 差 18.65）。
2. **E1 冻结网格 {0, .25, .5, .75, 1} 中，0、.25、.5 三点在本试点里处于崩溃区，且主指标 D 的 α=0 端点会退化。** 15 号计划定义 `D=[I(correct,1)−I(shuffled,1)]−[I(correct,0)−I(shuffled,0)]`。本试点里 α=0 的 correct 与 shuffled 输出逐位相同，第二个中括号对每条 trial 恒为 0，而且 α=0 端点本身准确率为 0、几乎只输出一个类别；第二个中括号恒为 0 是 α=0 显式旁路的构造性质（15 号计划 §5 已指出“α=0 差为零首先是工程 cue 独立性”），不是 E0 的新发现；本试点补充的描述性观察是 α=0 端点准确率为 0、几乎只输出一个类别，因此 D 按定义将呈现为 α=1 的 cue 效应减去一个恒零项，而不是“有 cue 选择性”对“无 cue 选择性但仍能识别”的比较。NLL 上要区分两种量：α=0 端点的绝对平均 NLL 约 632 nat，任何跨 α 的绝对 NLL 曲线都会被这个量级主导；但 15 号计划的配对差 NLL(correct) − NLL(shuffled) 在 α=0 旁路下按构造恒为 0，不受该量级影响。讨论 E1 是否调整时须先指明所指的是哪一个量。在本试点的 96 条上，.75 与 1 是仅有的同时满足两个条件的点：correct 准确率高于 shuffled（配对 64 条：0.2500、0.2969 对 0.0469）且 \|logit\| 最大值与 original 同阶（72.52、78.90 对 78.90）；α=.5 的 correct 亦高于 shuffled（0.0469 对 0.0156），但 \|logit\| 最大值已达 1360 量级。这是事后描述性划分，不是预注册判据。
3. **conv_only 与 fc_mean_preserved 在 α=0.5 与主操作预测类别相同、汇总指标接近；在七处卷积 gain 已改变的背景下，两种末层处理带来的额外变化较小。这支持后续调查卷积层 gain，但不足以完成机制归因或排除层间交互。** alpha_05、conv_only_05、fc_mean_preserved_05 的 top-1 完全相同（6/96，且 96/96 条预测类别一致），平均 NLL 46.4000 / 46.3954 / 46.3955，两两最大 logit 差 0.22 / 0.10 / 0.22（相对于约 1360 的 logit 量级）。conv_only 保持 attnfc 原 gain、fc_mean_preserved 把 attnfc 的干预 gain 重缩放到原 gain 均值，两者与全八处 α=.5 几乎相同，表明在此 96 条上，attnfc 处 α=.5 的两种处理相对全八处 α=.5 只带来不超过 0.23 的 logit 变化（相对量级约 1360）；三者不是数值上不可区分，只是差异很小。它支持后续调查卷积层 gain 的作用，但不能完成层级归因，也不能排除卷积层与末层之间的交互。另一方面 uniform_05（逐样本均值广播）与 alpha_0 的 top-1 完全一致、最大 logit 差 0.64、NLL 631.89 对 631.96，即在 α=.5 把 gain 的空间/通道结构抹平后输出与完全去除 gain 几乎相同；这一现象目前没有 gain 统计量可解释（OBSERVER.json 只记录八处输入/输出摘要，不记录 gain 均值），只能记录，不作机制解释。

## 5. 对 E1 的影响与可选处置

E1 冻结包 `release_e1_20260926_v1/package_ready`（RELEASE.json 的 `scientific_status` 为 `DEVELOPMENT_PROTOCOL_STATISTICS_APPROVAL_PENDING`，统计合同未审定；25 号计划记录的 release SHA `ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176`，已按 package_ready/RELEASE.json 文件哈希核算：该值为 RELEASE.json 自身的 SHA256，其 files 表 26 项的 SHA256 与字节数均与磁盘一致）按本试点预期会把 38400 条预测中相当一部分花在崩溃区，且主对比 α=1 对 α=0 按定义将呈现第 4 节第 2 点描述的退化形式。试点暴露须先披露：E0 的 96 条 trial 中有 19 条（其中 5 条 clean）也在 E1 冻结的 2000 条内（按 E1_CONTRACT.json 的 trial 列表核对）。任何基于 E0 的修订都是试点驱动的探索性修订，后续 E1 结果不能被表述为在完全未接触数据上的确认性检验。可选处置有四种，均需用户与导师决定；本备忘不做决定，不改 E1 包，不提交任何作业：

1. **按冻结网格照跑并如实记录。** 优点是完全遵守 15 号计划“不得看结果后加密网格或挑峰值”的规则，E0 试点与 E1 数据的关系简单；代价是五点中三点预计给出接近 0 的准确率与数百 nat 的 NLL，D 的 α=0 端点退化，结果宜同时报告“gain 去除导致的输出崩溃”这一描述性解读，并与 cue 效应消失的解释并列讨论。
2a. **在统计合同审定前只调整网格。** 干预公式 `gα = 1 − α(1 − g)` 不变，改变采样位置，例如把网格移向 α∈[.75,1]。这是同一干预的采样修订，E0 已验收的端点与负对照定义继续有效；需在文档写明动机来自 E0 的 96 条试点而非 E1 数据，记录上述 19 条重叠，并说明与“不得看结果后加密网格”规则的关系：E1 尚未运行、统计合同尚未审定，属预注册前的协议修订。
2b. **更换插值公式。** 例如每层均值保持的插值。这改变干预本身，是新的实验假设：端点桥接、α=0 语义、三个负对照的定义与 G5 公式检查都要重新验收，不能沿用 E0 的 PASS。另外“保持 gain 均值”不能直接称为“保持激活尺度”，二者是否等价需要测量中间层激活才能说明。
3. **先做更小的 CPU/GPU 探针。** 例如在同一 96 条上补 α∈{.6,.7,.8,.9}，或试验其他插值公式变体（其是否保持激活尺度需测量），确认 .5 与 .75 之间的转变位置（探索性目的，不是预注册判据）后再冻结 E1 网格。这需要单独申请预算与授权，且探针结果仍是试点身份，不能作为 E1 的科学结果。

无论选哪一种，E1 的研究身份仍是复用验证 bank 的开发扫描，不是独立测试；任何“机制”表述都要等独立数据与审定的统计合同。

## 6. 不能推出的结论

- 不能说 α 机制成立、已证明或不成立；E0 只验证干预按定义作用于真实模型且不破坏原评估路径。
- 不能把 41/96 = 0.4271 报告为 formal40 的 bank 准确率；96 条是按原批边界选的工程覆盖集，不是分层样本。
- 不能对任何两条曲线之间的差异做显著性陈述；control 条件命中数为 0 至 6，一条 trial 的变化就是 1/64 ≈ 1.6 个百分点，没有置信区间。
- 不能由 uniform_05 ≈ alpha_0 或 conv_only_05 ≈ alpha_05 推断具体哪一层、哪一种 gain 统计量引起崩溃；本读数只有 logits，没有 gain 张量统计。
- 不能把“激活推出训练分布”理解为已测量的分布位移；本备忘只观察到 logit 量级增大与预测类别收缩，未测量中间层激活。同理，不能把“保持 gain 均值”等同于“保持激活尺度”。
- 不能推断 α 在训练（E3）中的行为，也不能推断 α∈(.5,.75) 或 (.75,1) 内的形状；试点没有这些点。
- 不能由此预测 E1 在 2000 条上的数值；E1 的批组成、clean 新条件与统计合同都不同于 E0。
- 不能把本备忘视为对 E1 网格的决定或修改；决定权在用户与导师。
