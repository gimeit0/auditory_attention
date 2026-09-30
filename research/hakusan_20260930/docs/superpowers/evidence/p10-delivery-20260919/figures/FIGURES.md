# P10 出版图：图注、替代文本与来源

2026-09-20。三张图全部由 [p10_figures.py](../../../../../checkpoint_compare_workflow_20260917/p10_figures.py) 从 [STATISTICS.json](../../p09-statistics-20260919/STATISTICS.json)（Job 728520，P09 统计记录）确定性生成，不重新计算、不平滑、不筛选；每张图的来源 SHA、尺寸与文件 SHA 见 [MANIFEST.json](MANIFEST.json)。误差棒统一为固定执行配置下的 95% target_speaker 成簇 bootstrap 区间（10,000 次，seed 20260829 加固定分层偏移，原 v4 规则），逐项区间、未做多重比较校正。颜色用 Okabe–Ito 色盲安全色，并以标记形状/线型冗余区分，PNG 为不透明 RGB、600 dpi（180 mm 宽），PDF 为矢量并嵌入 TrueType（Type 42）字体。**投稿期刊未定**：尺寸、格式、字号为通用手稿设定，投稿前须按目标期刊官方要求核对。

## 图 1 `fig1_model_performance_by_condition`（180 × 120 mm）

**图注。** 三个 checkpoint 在冻结 10,000 条 bank 上正确 cue 条件下的表现（点估计）。(a) 各 SNR 段（mixed，每段 n = 1,800）与 clean 无 cue 条件（n = 1,000）的 top-1 准确率（800 词）；(b) 各干扰者数（每档 n = 2,250）的准确率；(c、d) 对应的交叉熵（nats）。formal40：蓝色圆点实线；作者 checkpoint：橙色方块虚线；valbest33：绿色三角点线。clean 条件与 SNR 段之间的竖线表示该条件不在 SNR 连续轴上（无干扰者、cue 置零）。准确率纵轴 0–1，交叉熵纵轴 0–5.2。本图只给点估计，成对差值及区间见图 2。

**替代文本。** 四个折线/散点面板。准确率随 SNR 升高单调上升：在 −10…−6 dB，formal40 约 0.26、作者约 0.17、valbest33 约 0.25；在 6…10 dB 三者约 0.57–0.60。clean 无 cue 条件下作者约 0.79，明显高于 formal40 约 0.64 与 valbest33 约 0.66。随干扰者数从 1 增至 4，三者准确率从约 0.48–0.51 降到约 0.32–0.37，作者始终最低。交叉熵呈相反趋势；clean 条件作者约 0.87，远低于 formal40 约 1.74。

## 图 2 `fig2_paired_differences_vs_author`（180 × 105 mm）

**图注。** 与作者 checkpoint 的逐 trial 配对差值及 95% 成簇 bootstrap 区间。(a) 准确率差（模型 − 作者，百分点）；(b) 交叉熵改善（作者 − 模型，nats）。正值有利于我们的模型。实心蓝圆：formal40 − 作者（主比较）；空心绿三角：valbest33 − 作者（补充）。行按预定分层排列：总体/mixed/clean、五个 SNR 段、干扰者数 1–4、目标性别；括号内为该层 trial 数。竖线为 0。分层区间为逐项区间，探索性解读，不据此声明模型×性别交互。

**替代文本。** 两个森林图。总体准确率差 formal40 约 +1.8 个百分点，区间 +0.2 至 +3.4 不含 0；总体交叉熵改善约 +0.03，区间 −0.09 至 +0.15 含 0。mixed 两项均为正且不含 0；clean 两项均为大幅负值（准确率约 −14 个百分点，交叉熵约 −0.87）。低 SNR 两段两项均显著为正（−10…−6 dB 准确率约 +9 个百分点，交叉熵约 +0.60），6…10 dB 交叉熵显著为负、准确率区间含 0。干扰者数各档准确率差为正，交叉熵区间多数跨 0。valbest33 − 作者在多数层比 formal40 − 作者更偏正。

## 图 3 `fig3_cue_controls`（180 × 62 mm）

**图注。** 2,000 条 cue-control 子集。(a) 四种 cue 条件下的 top-1 准确率（点估计）：correct、shuffled（另一说话人 cue）、silent（全零 cue）、distractor（指向干扰者的 cue）；(b) correct cue 相对各控制条件的逐 trial 准确率下降（百分点）及 95% 区间；(c) distractor cue 相对 correct cue 时 probe（干扰者所说词）概率的变化及 95% 区间。三模型均显著依赖 cue；distractor cue 下 probe 概率的上升点估计 formal40 约 +0.21、valbest33 约 +0.20，作者约 +0.11。这支持三者都利用 cue 且对误导 cue 敏感，但模型间依赖强度差异未做配对差中之差检验，不作因果推断。

**替代文本。** (a) correct cue 下准确率 formal40 0.42、作者 0.38、valbest33 0.42；shuffled 约 0.11–0.13；silent 约 0.23–0.25；distractor 约 0.04–0.06。(b) 三模型 correct − shuffled 约 25–31 个百分点，correct − silent 约 15–17，correct − distractor 约 32–38，区间均远离 0。(c) probe 概率变化 formal40 约 0.21、valbest33 约 0.20、作者约 0.11，author 的区间与另两者不重叠，formal40 与 valbest33 的区间重叠。

## 未在图中呈现的内容

20 个干扰数×SNR 细胞、性别分层的每模型绝对指标见 [MODEL_STRATA.md](../../p09-statistics-20260919/MODEL_STRATA.md) 与 [REPORT.md](../../p09-statistics-20260919/REPORT.md)；数值敏感性解释以 [NUMERIC_ERRATUM.md](../NUMERIC_ERRATUM.md) 为准，图中不显示条件性点估计范围（它不是置信区间）。

## 2026-09-27 更正记录

程序化核对发现并更正 3 处措辞：图 3 图注 formal40 的 probe 概率上升改为“约 +0.21”（数据 0.2069）；图 3 替代文本“区间互不重叠”改为只有 author 的区间与另两者不重叠（formal40 与 valbest33 的 95% 区间重叠）；图 1 替代文本干扰者数 4 的范围改为“约 0.32–0.37”（author 0.3231）。图件与 MANIFEST.json 未变；核对记录见 [R0_DELIVERY_VERIFICATION.md](../R0_DELIVERY_VERIFICATION.md)。
