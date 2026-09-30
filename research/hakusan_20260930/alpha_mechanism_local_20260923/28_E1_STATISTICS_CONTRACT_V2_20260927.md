# E1 开发扫描统计合同（审定版 v2）

日期：2026-09-27。编号：28。文件名：`28_E1_STATISTICS_CONTRACT_V2_20260927.md`。

## 0. 状态行

- 本文是 E1 开发扫描的**统计合同 v2**：把 02 号合同草案（`02_ALPHA_CONTRACT_DRAFT.md`）与 15 号文 §5 的统计提案升级为可执行合同。
- 决定 A 至 E 已由用户于 2026-09-27 按 27 号决策稿（`27_E1_REVISION_DECISION_DRAFT_20260927.md` §9）的推荐定下：A 保留公式 `gα = 1 − α(1 − g)`；B 网格改为 {0, .5, .75, .875, 1}；C 保留 E0 与 E1 重叠的 19 条 trial，披露、在分析中标记并附排除它们的敏感性版本；D 不先做探针；E 预算维持 1 A100 / 8 CPU / 64 GiB / 180 分钟为候选上限，仍需单独批准。决定者：用户（2026-09-27，按助手推荐）；导师意见待补。
- δ 等数值的“审定”以**外部签署记录**为准。签署记录将以独立文件存放，建议路径 `docs/superpowers/evidence/e1-contract-signoff-2026MMDD/SIGNOFF.json`，内容至少含：本文的 SHA256 与字节数、签署人、签署日期、审定的 δ 数值、导师意见是否已补。**本文不自称已签署。** 本文写成后不再改动；任何修订以新编号文件另立，并在签署记录中改绑。
- 研究身份：`REUSED_VALIDATION_BANK_DEVELOPMENT_NOT_INDEPENDENT_TEST`（沿 v1 `package_ready/RELEASE.json` 的 `execution.scope`）。E1 是复用验证 bank 的开发扫描，不是独立测试；因决定 B 的动机来自 E0 试点且存在 19 条重叠，E1 进一步定性为**试点驱动的探索性开发扫描**（27 号文 §5.3），其结果不能被表述为在未接触数据上的确认性检验。
- 本文只做本地文档工作：无 SSH、无上传、无提交、无 GPU；不改任何冻结包。v1 冻结包 `release_e1_20260926_v1/package_ready`（RELEASE.json SHA `ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176`，14257 字节）保持原字节，不再是待提交候选；E1 v2 包由主流程在新目录重新冻结，其 RELEASE.json 将绑定本文 SHA（27 号文 §7 的 P9 字段）。
- 数字与 SHA 的来源：本文引用的 E0 数字来自 26 号备忘 §2 至 §4；重叠清单、簇数与簇大小由本文写作时对 `package_ready/E1_CONTRACT.json` 与 `package_ready/frozen_bank.tsv` 的实际核算得到（§4.3、§6）；§4.4 的方差由 E0 归档 `A/01_alpha_1.npz` 实际计算；文件 SHA 由本文写作时实际计算（§13）。

## 1. 研究问题与适用范围

- 固定 formal40 权重（SHA `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff`），改变推理时八处 gain 的强度 α，观察 cue 选择性如何变化。不训练、不扫描作者模型或训练阶段。
- 三个可分开的问题（27 号文 §1.1）：Q1 训练态 α=1 是否表现出 cue 选择性；Q2 cue 选择性随 α 的剂量曲线；Q3 三个负对照（均在 α=.5）能否解释 α=.5 的效应。本合同的**唯一主对比**回答 Q1；Q2 与 Q3 全部是预定次要分析，描述性报告。
- 数据：bank SHA `d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091`（10000 行）；E1 冻结的 2000 条 trial、125 个主批、125 个 control 子批（共 400 条）、13 个 clean 批（共 200 条）以 v1 `E1_CONTRACT.json`（SHA `f3fcacec3efb77962091ae58cbecde59de6b79ee503399c9ae8c0a120398b843`）为准；v2 包若重算合同文件，trial 集合、批布局与条件子批必须与 v1 完全相同（决定 C 不排除任何 trial）。

## 2. 干预与网格（决定 A、B）

### 2.1 公式（决定 A：保留）

`g = b + (1 − b)·sigmoid((mean_time(cue) − t)·s)`；`gα = 1 − α(1 − g)`，α 为固定 Python 标量，八处 gain（7 个 conv gain 与 attnfc）共享同一 α。α=1 直接调用原 forward 浮点路径；α=0 显式旁路，不计算 cue 与 gain，直接返回 mixture；0<α<1 先算原 gain 再插值，cue_mask 对应的有效 gain 严格为 1。E0 作业 746603 已按 05 号文 G0 至 G7 验收该实现（`docs/superpowers/evidence/e0-production-20260926/REPORT.md` §2），验收继续有效。

### 2.2 五个 α 点（决定 B）

正式网格 **{0, .5, .75, .875, 1}**：用 .875 替换 v1 网格 {0, .25, .5, .75, 1} 中的 .25；其余四点不变。动机：E0 试点（96 条、无区间）显示 α=.25 与 α=0 几乎重合（准确率 0/96 对 0/96，预测类别 11 对 2，平均 NLL 373.42 对 631.96），而 .75 与 1 之间没有采样点（26 号备忘 §2、§4）。保留 .5 使三个负对照维持原定义与同 α 可比性；保留 0 与 1 两个端点维持 G2 旁路门与 α=1 原路径 / 冷重复门。这是预注册前、统计合同审定前的协议修订，动机来自 E0 试点而非 E1 数据；E1 尚未运行。

### 2.3 pass 名称与 α / mode 映射表

| pass | α | mode | 作用 | 出现在 |
| --- | ---: | --- | --- | --- |
| original | 1 | native_gain（不安装干预） | 同布局原模型参考；α=1 端点门 | A main、A clean |
| explicit_bypass | 0 | bypass_module（独立旁路） | α=0 端点门（与 alpha_0 逐位比较） | A main、A clean |
| alpha_0 | 0 | alpha | 显式旁路端点 | A main、A clean |
| alpha_05 | .5 | alpha | 剂量点；三负对照的同 α 主操作 | A main、A clean |
| alpha_075 | .75 | alpha | 剂量点 | A main、A clean |
| alpha_875 | .875 | alpha | 剂量点（v2 新增，替换 v1 的 alpha_025） | A main、A clean |
| alpha_1 | 1 | alpha | 主对比的干预端点；须与 original 逐位一致 | A main、A clean、B main、B clean |
| uniform_05 | .5 | uniform | 负对照：每样本有效 gain 在非 batch 维取均值广播 | A main |
| conv_only_05 | .5 | conv_only | 负对照：只改 7 个 conv gain，attnfc 保持原 gain（α=1） | A main |
| fc_mean_preserved_05 | .5 | fc_mean_preserved | 负对照：attnfc 的干预 gain 重缩放到原 gain 均值，7 个 conv gain 用 α=.5 | A main |

mode 名沿写作时工作副本 `e1_execution.py` 的 `PASS_ALPHA_MODE`（该副本 SHA `0a5799bcf063d416a601222ff4ff087d2f294b64bcb5e507d11774abb3993221`，10052 字节，尚未冻结，不具约束力）；有约束力的映射是 v2 RELEASE.json 的 `pass_map`（P7 字段），E1 报告须核对它与本表一致，不一致即停止并报告，不得以本表替代冻结值。三个负对照沿 E0 受审定义（02 号草案第 5 条、`gain_formula_check.py`），不视为完整 lapse 模型。

### 2.4 条件、进程分工与 38400 条预测的构成

main 域四条件：correct（全部 2000 条）、shuffled / silent / distractor（各 400 条 control，按 125 个主批内原位置过滤成 control 子批）。clean 域两条件：correct_cue（新构造的独立 cue 录音）与 zero_cue（旧 clean 零 cue 语义），各 200 条，13 批（12×16 加尾批 8）。

| 进程 | 域 | pass 数 | 每 pass 预测数 | 小计 |
| --- | --- | ---: | ---: | ---: |
| A | main | 10 | 2000 + 3×400 = 3200 | 32000 |
| A | clean | 7（original、explicit_bypass、五个 alpha_*） | 200×2 = 400 | 2800 |
| B | main | 1（只跑 alpha_1） | 3200 | 3200 |
| B | clean | 1（只跑 alpha_1） | 400 | 400 |
| VERIFY | 无预测 | 逐位比较与计数 | 0 | 0 |
| 合计 | | | | **38400**（A 34800 + B 3600；60 个数组记录） |

用 .875 替换 .25 不改变 pass 数与每 pass 预测数，预测数仍为 38400，与 v1 RELEASE.json `predictions=38400` 相同。VERIFY 的工程门（沿 `e1_execution.py` 的 `verify_arrays`）：original 与 alpha_1 逐位一致；explicit_bypass 与 alpha_0 逐位一致；A 与 B 的 alpha_1 逐位一致（冷重复）；clean 域 alpha_0 的 correct_cue 与 zero_cue 逐位一致；总数等于 38400。任一门失败即 `EXECUTION_INVALID`，不做任何统计。

## 3. 主指标 D（唯一主对比）

- 分析单位：400 条 control（`control_subset=1`），逐 trial 计算 top-1 指示 `I(condition, α) = 1[argmax logits == target_label]`。
- 定义：`D = [I(correct, α=1) − I(shuffled, α=1)] − [I(correct, α=0) − I(shuffled, α=0)]`，报告 `mean(D) × 100`，单位**百分点**。
- 构造性说明（27 号文 §4.1）：α=0 是显式旁路，同一 trial 的 correct 与 shuffled 输入只在 cue 上不同，输出逐位相同（E0 中 64/64 条 control 逐位相同，G2 门；E1 的 VERIFY 以 explicit_bypass 与 alpha_0 逐位一致把关）。因此第二个中括号对每条 trial **恒为 0**，`D ≡ I(correct, 1) − I(shuffled, 1)`，即 **α=1 处的 cue 效应**。α=0 项的角色是工程验证（cue 独立性），不是“无 cue 选择性但仍能识别”的科学对照。报告须原样写出这一等价关系，不得把 D 表述为两种可识别状态之间的比较。
- 主对比只有一个，即上式。不设第二个主对比；剂量点、NLL、分层、错误结构、clean、负对照全部为 §5 的描述性次要分析。

## 4. 等效界限 δ 与 CI 方法

### 4.1 δ

候选等效界限 **δ = 2 个百分点**（15 号文 §5 提案），不是由任何 α 结果倒推。δ 的“审定”以 §0 所述签署记录为准；签署前本文对 δ 的地位是“提案值，待签署”。δ 在本合同中的两个用途：（1）判定 `E1_CONFIRMATION_CANDIDATE` 时要求 D 的 95% CI 下界大于 +δ；（2）判定 `E1_ALPHA_FLAT_RECORDED` 时要求各 D_α 的 95% CI 全部落入 [−δ, +δ]。

### 4.2 CI 方法：target_speaker 簇配对 bootstrap

沿 v4 `locked_same_bank_eval.py::cluster_bootstrap_ci` 的构造（P09 统计已用同一实现），参数改为本合同值：

1. 簇单位：`frozen_bank.tsv` 的 `target_speaker`；缺失或空的说话人 ID 即拒绝，不默认为独立簇。
2. 重复次数 10000；随机数 `numpy.random.default_rng(20260926)`（PCG64），**seed = 20260926**；每次重复从 K 个簇中有放回抽取 K 个簇索引（`rng.integers(0, K, size=K)`）。
3. **同一重复对全部条件 / α 共同重采样**：在同一分析单位内，第 r 次重复抽出的簇集合同时用于该单位的所有统计量（D、各 D_α、配对 NLL 差、负对照比较、clean 两 cue 差），不为每个统计量各自抽样。同一分析单位内的说话人向量相同，因而与 v4 的 “same seed/draws within every identical stratum speaker vector” 政策一致。
4. 每次重复的统计量为 **trial 加权**总体值：抽中簇的逐 trial 值之和除以抽中簇的 trial 数之和（`sums[sampled].sum() / counts[sampled].sum()`）。点估计为全部 trial 的普通均值。
5. 95% CI 为 draws 的 2.5% 与 97.5% 分位数，`numpy.quantile(..., method="linear")`（percentile 法，不做 BCa 或 t 修正）。
6. 分析单位分开：control 400 条（主指标与 main 域次要分析）、clean 200 条（clean 两 cue）、以及 §6 的两个敏感性单位（386 条、195 条）。每个单位各自用 seed 20260926 初始化一次生成器；说话人向量不同，draws 自然不同。
7. 簇数少于 2 的单位或分层不给 CI，只报点估计并标 `CI_NOT_COMPUTED_FEWER_THAN_TWO_CLUSTERS`。

### 4.3 必须报告的簇信息

报告须写出每个分析单位的实际簇数与簇大小分布（最小、中位、最大）及 numpy 版本。本文写作时按 v1 `E1_CONTRACT.json` 与 `frozen_bank.tsv` 核算的参考值：control 400 条含 **246** 个 target_speaker 簇（簇大小 1 至 9，中位 1）；clean 200 条含 **149** 个簇（簇大小 1 至 6）；全部 2000 条含 603 个簇。报告以实际重算值为准。声明限制：target_speaker 聚类只处理目标说话人共享带来的依赖；cue、distractor 与 shuffled donor 的说话人共享造成的依赖未被聚类吸收，报告不得声称已完全解决。

### 4.4 精度提示（写作时的粗估，不是结果）

E0 作业 746603 的 64 条 control 在 alpha_1 下逐 trial 差 `I(correct) − I(shuffled)` 的取值计数为 −1：1 条、0：46 条、+1：17 条，均值 0.25，样本方差（ddof=1）0.2222（由 `A/01_alpha_1.npz` 与 bank 的 `target_label` 实际计算）。若以该方差、n=400、忽略簇内相关作粗估，均值的标准误约 `sqrt(0.2222/400) = 0.0236`，即约 2.4 个百分点，95% 区间半宽约 4.6 个百分点；簇 bootstrap 通常更宽。这意味着在 400 条 control 上，任何 D_α 的 CI 落入 [−2, +2] 的等效判定都需要比设计精度更窄的区间，几乎不可达；这是设计精度的事实，记录于此供签署人参考，**不构成事后改 δ 的理由**。

## 5. 预定次要分析（全部描述性）

以下每项逐项给出点估计与 95% 簇 bootstrap CI（可算时），全部标 `DESCRIPTIVE_NO_CONFIRMATORY_CLAIM`；不做多重比较校正，也不据此作任何确认性声明；按 clean / mixed 与按 α 分开。

1. **剂量点 α 的绝对准确率与配对差。** 对 α ∈ {0, .5, .75, .875, 1}：correct 条件 2000 条的绝对 top-1 准确率；400 条 control 上四条件各自的准确率；`D_α = mean[I(correct, α) − I(shuffled, α)] − mean[I(correct, 0) − I(shuffled, 0)]`，第二项按构造为 0，报告时标注；silent 与 distractor 的对应配对差分开报告。不做相邻 α 之间的检验，不挑峰值。
2. **绝对 NLL 与配对 NLL 差分开报告。** 绝对 NLL：每条 trial 对 `target_label` 的 NLL 均值（保存的 float32 值，另以 float64 由 logits 复算并报告最大绝对偏差）。配对 NLL 差：`NLL(correct) − NLL(shuffled)`，负数表示正确 cue 更好；α=0 处按构造恒为 0。跨 α 的绝对 NLL 图须用对数坐标或分区，并与绝对准确率并列。
3. **崩溃区描述表**（沿 26 号备忘 §2 表格式）：每个 pass、每域一行，列为 top-1 准确率、平均 NLL、|logit| 最大值、预测类别数、最多预测类别与其次数（并列时列出全部类别，沿 `e0_readout_746603.py` 的 `most_frequent_predicted_classes` 处理）；若 v2 归档含 logits 按样本 RMS（27 号文 §7 的 P10），一并列出。**预定的崩溃区分区判据**（只用于分区报告与 §7 中 Q3 可解释性的把关，不是检验）：某 pass 在某域被标为“崩溃区”，当且仅当其 correct 条件准确率低于同域 original 的 0.5 倍，或其 correct 条件 |logit| 最大值高于同域 original 的 10 倍。该判据由 E0 试点量级定下：alpha_05 对 original 的准确率比 0.0625/0.4271 ≈ 0.146、|logit| 比 1360.19/78.90 ≈ 17.2；alpha_075 的两比值为 0.3854/0.4271 ≈ 0.902 与 72.52/78.90 ≈ 0.919。判据在 E1 运行前写死于本文，不得看 E1 结果后调整。
4. **SNR / 干扰数分层。** 按 `snr_bin`（0 至 4）与 `distractor_count`（1 至 4）分层报告 correct 准确率与 control 上的配对差（每格 20 条 control，簇数不足 2 时不给 CI）。
5. **错误结构。** 对每条预测归类为：目标（命中 `target_label`）、干扰（命中任一 `distractor_k_label`）、cue 词（命中 `shuffled_cue_label` 或 `correct_cue_label`，按条件对应）、其他。`target_label` 与任一 distractor 标签相同的 trial 单列为“标签碰撞”，不计作可区分的干扰错误。
6. **clean 两 cue。** 200 条 clean 上，对每个 α 报告 correct_cue 与 zero_cue 的准确率、平均 NLL 及逐 trial 配对差；α=0 处两者按构造逐位相同（VERIFY 门）。不把旧 clean 的 correct 列名当正确 cue。
7. **三负对照与 alpha_05 的比较。** 在 400 条 control 上定义各 pass 的 cue 效应 `C_p = mean[I(correct, p) − I(shuffled, p)]`，p ∈ {alpha_05, uniform_05, conv_only_05, fc_mean_preserved_05}；报告 `C_alpha05 − C_p` 的配对差及 CI；在 2000 条 correct 上报告各负对照与 alpha_05 的 top-1 一致率与最大 |logit| 差。**可解释性把关**：若 alpha_05 在 main 域按第 3 项判据处于崩溃区，则本项只作描述性记录，标 `Q3_NOT_INTERPRETABLE_COLLAPSE`，不用于 §7 的任何标签判定；E0 试点预期即为此情形。

## 6. 敏感性版本（决定 C）：排除 E0 与 E1 重叠的 19 条 trial

- 来源：27 号文 §5.1 的本地核对（E0 `A/00_original.npz` 的 96 个 `correct_ids` 与 E1 `E1_CONTRACT.json` 的 2000 个 `labels` 键取交集）；本文写作时用同一方法重算，结果一致。
- 19 个 trial_id：**3、11、15、2257、2259、2264、4517、4518、4527、6753、6757、6758、6761、6764、9007、9008、9015、9018、9023**。
- 其中 clean 5 条（9007、9008、9015、9018、9023，均在 E1 的 200 条 clean 内）；mixed 14 条全部同时是 E0 的 control（96 条的前 64 条）与 E1 的 control（`control_subset=1`）。按 `frozen_bank.tsv`，19 条的 `target_gender` 均为 female，14 条 mixed 的 `snr_bin` 均为 0，`distractor_count` 为 1、2、3、4 的各 3、3、3、5 条。比例：19/2000 = 0.95%，14/400 = 3.5%，5/200 = 2.5%。
- 处理：19 条留在 E1 中（不改数据身份与配额）；报告在主分析与各次要分析中标记它们；另给**敏感性版本**：control 单位 400 − 14 = 386 条、clean 单位 200 − 5 = 195 条，重算 D、各 D_α、配对 NLL 差、clean 两 cue 与负对照比较，CI 方法与 §4.2 相同。敏感性版本只作报告，不替代主分析；两版结论标签见 §7 的一致性规则。
- 这些 trial 在 E0 各 pass 的读数已被查看（26 号备忘、`readout/E0_READOUT.json`），是试点暴露；v2 包须把它们写入 P8 字段。

## 7. 结论标签预定义与判定规则

沿总计划 §14 的状态字典与近期执行计划 §4 的标签说明。判定只用主分析（400 条 control，§3、§4）与 §5 第 3、7 项的预定判据；敏感性版本作一致性检查。记 [L, U] 为 D 的 95% CI（百分点）。

| 标签 | 判定规则 | 备注 |
| --- | --- | --- |
| `E1_DEV_COMPLETE` | 38400 条预测全部归档、VERIFY 门通过、`offline-check` 通过、本文全部预定统计（含敏感性版本与 P1 至 P9 核对）完成 | 只表示预定计算与统计完成，与结果方向无关；其他标签只能附加在它之上 |
| `E1_CONFIRMATION_CANDIDATE` | L > +δ，且 alpha_1 在 main 域不属崩溃区，且敏感性版本的 CI 下界 > 0 | “值得进入独立确认”，不等于机制成立；须附 Q3 状态字段（`Q3_NOT_EXPLAINED` / `Q3_NOT_INTERPRETABLE_COLLAPSE`）；若 Q3 为 `Q3_UNIFORM_EXPLAINS` 则改判下一行 |
| `E1_MECHANISM_NOT_SUPPORTED` | 满足任一：（a）U < +δ 且 alpha_1 在 main 域不属崩溃区（训练态 cue 效应小于 δ）；（b）alpha_05 不属崩溃区，且 `C_alpha05 − C_uniform05` 的 95% CI 落入 [−δ, +δ]（均匀缩放可解释 α=.5 处的 cue 效应，记 `Q3_UNIFORM_EXPLAINS`） | 预定竞争解释检验支持收窄 gain 选择性主张；沿 02 号草案“均匀缩放可解释→收窄主张” |
| `E1_ALPHA_FLAT_RECORDED` | **全部**预定 α 点 α ∈ {.5, .75, .875, 1} 相对 α=0 的 D_α 的 95% CI 都落入 [−δ, +δ]（四个区间同时满足同一界限，不以 p>0.05 代替） | 因 D_α ≡ α 处的 cue 效应（α=0 项按构造为 0），本标签等价于“任何 α 下 cue 效应都与 0 等效”；α=0 端点在 E0 试点中崩溃（准确率 0/96、95/96 条预测同一类别）且 §4.4 的精度粗估显示 CI 半宽约 4.6 个百分点，使本标签在本网格下几乎不可能成立。如实保留定义，不因不可能成立而放宽 |
| `E1_INCONCLUSIVE` | 不满足以上任一标签的结果：L ≤ +δ ≤ U；或 alpha_1 在 main 域属崩溃区；或主分析与敏感性版本的 CI 相对 0 的符号不一致；或（b）项区间跨越 ±δ 边界而（a）不成立 | 混合结果不强迫三选一；报告写明是哪一条导致 |

优先级：先判 `E1_DEV_COMPLETE`（不成立则只报 `EXECUTION_INVALID` 或缺项，不给任何科学标签）；再按 `E1_CONFIRMATION_CANDIDATE`、`E1_MECHANISM_NOT_SUPPORTED`、`E1_INCONCLUSIVE` 三者互斥判一个；`E1_ALPHA_FLAT_RECORDED` 是关于剂量曲线的独立记录标签，可与 `E1_MECHANISM_NOT_SUPPORTED` 同时出现，不能与 `E1_CONFIRMATION_CANDIDATE` 同时出现（前者要求 D_1 的 CI 在 ±δ 内，后者要求 L > +δ）。任何标签都不等于“α 机制成立”；是否进入独立确认、是否改变机制假设、是否转向 E2 描述性轨迹，均在审阅开发结果后另立协议。

## 8. 禁止事项

1. 不看结果后加密网格、增补 α 点或改主指标；新 α 点或新对照属于新协议，须另立文件并重新冻结。
2. 不挑峰值：不在剂量点中事后选出“最好的 α”作主检验或作标题结论。
3. 不把不显著当平坦：`E1_ALPHA_FLAT_RECORDED` 只按 §7 的等效界限判定，p>0.05 或 CI 包含 0 都不是平坦。
4. 不宣布机制成立：任何标签、任何 CI 都不支持“α 机制成立 / 已证明”的表述；E0 的 `scientific_alpha_result=false` 不变。
5. 不把 400 条 control 当 2000 条控制样本；不把 96 条 E0 或 2000 条 E1 报告为 bank 准确率。
6. 不为显著性重跑、换 seed 或改 bootstrap 参数；seed 20260926 与 10000 次固定。
7. 不因 19 条重叠而排除 trial 或重抽样；敏感性版本只作报告。
8. 不把三负对照称为 lapse 模型或声称已排除 lapse。

## 9. 负结果证据的边界（引用 27 号文 §6）

E0 试点已给出的描述性观察：线性插值 `gα = 1 − α(1 − g)` 在 α ∈ {0, .25, .5} 使 formal40 的 correct 准确率为 0/96、0/96、6/96，平均 NLL 631.96、373.42、46.40，|logit| 最大 2722.09、2402.75、1360.19，预测类别收缩至 2、11、64 类；uniform_05 与 alpha_0 的 top-1 完全一致、最大 logit 差 0.64、NLL 631.89 对 631.96。E1 报告开头设“E0 试点读数与网格修订动机”一节，引用 26 号备忘与 readout/ 两个文件（`8ea0b79d…`、`5ec6ff77…`）及 27 号文。

若 E1 在 2000 条上再现 α ≤ .5 的崩溃（按 §5 第 3 项判据），允许的陈述形式为：“在 formal40 与复用验证 bank 的开发子集上，把八处有效 gain 从训练态向 1 做线性插值时，α ≤ .5 使分类器输出崩溃；因此线性 gain 插值在该区间不是一种可用于测 cue 选择性剂量效应的发达参数化。”必须附带的边界：单模型、开发身份、无独立数据；只有 logits，没有中间层激活或 gain 统计，不得说“激活推出训练分布”已被测量，不得由 uniform_05 ≈ alpha_0 或 conv_only_05 ≈ alpha_05 推断具体层或统计量的机制；不推断 α ∈ (.5, .75) 或 (.875, 1) 内的形状，不推断训练（E3）中的行为；不能说 α 机制成立或不成立。

## 10. 来源字段核对（v2 包新增的 P1 至 P9）

E1 报告在计算任何统计之前，须核对 v2 包 PROVENANCE / RUN 记录含下列字段（27 号文 §7；缺口来源为 `docs/superpowers/evidence/e0-production-20260926/REPORT.md` §4）：P1 Python、torch、CUDA、cuDNN 版本；P2 GPU 型号名与 hostname；P3 runtime 六项实际值（deterministic、cuDNN deterministic、benchmark、matmul precision、matmul TF32、cuDNN TF32）；P4 每 pass 的 `max_memory_allocated`、`max_memory_reserved` 与进程 RSS；P5 进程级与每 pass 的 UTC 起止时间；P6 sacct / scontrol 只读回读作为收集文件；P7 实际 α 网格、负对照 α、pass 名到 α 与 mode 的映射表（须与 §2.3 一致）；P8 试点暴露字段（E0 作业号 746603、§6 的 19 条清单、26 号备忘与 27 号文的 SHA）；P9 本文的 SHA256 与签署记录路径，`scientific_status` 由 `DEVELOPMENT_PROTOCOL_STATISTICS_APPROVAL_PENDING` 改为签署后的状态词。P10（logits 按样本 RMS）为可选，若归档则进入 §5 第 3 项。任一 P1 至 P9 缺失即在报告中列为缺口，`E1_DEV_COMPLETE` 不得填写。

## 11. 停止规则与预算（决定 E）

- 预算：1 A100、8 CPU、64 GiB、180 分钟为候选上限（v1 RELEASE.json `budget`：`wall_minutes=180`、`worker_deadline_seconds=9000`、`coordinator_deadline_seconds=9900`）；27 号文 §8.2 对 n=5 网格的机械外推为总时长 54.3 至 71.5 分钟（A 进程 34800 条按 0.1118 秒/条约 3890 秒），E1 三进程与新 clean 路径未实测，外推不是运行保证。**任何 GPU 批次单独批准**，单次 held 提交，不自动重试、不自动拆批或续跑。
- 停止规则（沿 15 号文 §4 与 27 号文 §8、主计划 §13）：超时、输入变化、加载失败、端点或冷重复逐位不一致、计数不等于 38400，均保存失败档案并停止，标 `EXECUTION_INVALID`，不解释数值；typed GRES 改写先保持 held，只在该作业单独授权后唯一一次修正；失败不自动重提。
- 统计层面的停止规则（主计划 §5）：若效应仅来自幅度、普遍识别恶化、α 大段平坦或只在接近 0 时突变，记录单参数机制不足并停止加密搜索；是否转向 cue 可靠性假设另立新协议与预算。

## 12. 与旧文档的关系；签署

- 02 号合同草案与 15 号文 §5 为**历史文本**，保留不改；本文生效后，15 号文 §5 的“待审定”由 §0 所述签署记录关闭，`E1_INPUTS_FROZEN`（15 号文 §6 第 3 条）在签署后方可填写。
- 15 号文 §3 的“正式α集合固定为{0,.25,.5,.75,1}”为历史文本；决定 B 的记录见 15 号文文末的 2026-09-27 修订段与本文 §2.2。
- 本文写成后不再改动。签署记录（`SIGNOFF.json`）须写入本文的 SHA256 与字节数；若日后需要修改任何条款，另立新编号合同并重新签署，v2 包的 P9 字段随之改绑。

## 13. 依据文件与写作时核算的 SHA256

| 文件 | SHA256 | 字节 |
| --- | --- | ---: |
| `02_ALPHA_CONTRACT_DRAFT.md` | `c84fb3275926b225087f4434f91575c2f37f14fe64f676430c5af2227c88e00e` | 4246 |
| `15_E1_DEVELOPMENT_PLAN_20260926.md`（本文写作时、修订段追加前） | `51df6c9dc1130a3d0dd00951ec0eeb6591a89f99731b2a5cbd8a4fbd280797e2` | 9021 |
| `26_E0_SCIENTIFIC_READOUT_746603_20260927.md` | `10f33a654f79647152f4f40936703d02c3a3c0028f119d0700cb00a1016d383d` | 16301 |
| `27_E1_REVISION_DECISION_DRAFT_20260927.md` | `bc90afd78cebb4968a1e92bb6dab486a4d19cbd8782e9b7408d8925d45cd5811` | 33423 |
| `release_e1_20260926_v1/package_ready/RELEASE.json` | `ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176` | 14257 |
| `release_e1_20260926_v1/package_ready/E1_CONTRACT.json` | `f3fcacec3efb77962091ae58cbecde59de6b79ee503399c9ae8c0a120398b843` | 67948 |
| `release_e1_20260926_v1/package_ready/frozen_bank.tsv` | `d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091` | 10803199 |
| `docs/superpowers/evidence/e0-production-20260926/REPORT.md` | `2f463621243b0687940897cb28fb6ab91bf2d9d7b7aa549280833bc7941bc58a` | 21690 |
| `docs/superpowers/evidence/e0-production-20260926/readout/E0_READOUT.json` | `8ea0b79d70d35981fc6e769400381e03d1773c372de348e4fedb965af74a9ebb` | 80003 |
| `docs/superpowers/evidence/e0-production-20260926/readout/e0_readout_table.csv` | `5ec6ff77795416880b97e4d336d810e42fa2505f7de1e13ccbc96efc935be20b` | 12321 |

其他依据（未逐一列 SHA）：`2026-09-20_选择性听取发达机制_主课题总计划.md` §5 与 §14；`2026-09-23_主课题_近期执行计划.md` §4 与 §7；`checkpoint_compare_workflow_20260917/p09_statistics.py` 与 `same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py` 的 `cluster_bootstrap_ci`（bootstrap 构造的来源实现）。本文的 SHA256 与字节数由主流程在写成后计算并写入 v2 RELEASE.json 的 P9 字段与签署记录；本文内不含自身 SHA。
