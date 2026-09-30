# 按信噪比拆分的 10 张图：准确率与交叉熵

2026-09-29，按导师要求把 P10 图 1 的面板 a（准确率）和面板 c（交叉熵）按信噪比段拆开：5 个信噪比段 × 2 个指标 = 10 张图。原冻结图件（[../p10-delivery-20260919/figures/](../p10-delivery-20260919/figures/)）未改动。

## 读图方式

- 每张图只含一个信噪比段的 mixed 场景，正确 cue 条件，作业 728520 的全量结果。
- 横轴是干扰者人数 1 到 4；每个点 450 条样本。原图 1 的每个信噪比点，就是这里 4 个点合并后的结果。
- 三条线：蓝色实线圆点 formal40（epoch 40），橙色虚线方块作者 checkpoint，绿色点线三角 valbest33（epoch 33）。颜色与标记和原图一致。
- clean 条件没有信噪比和干扰者，不在这 10 张图里，仍以原图 1 为准。
- 纵轴在 5 张图间统一：准确率 0 到 1，交叉熵 0 到 6，可以直接跨图比较高低。

## 误差棒

- 点估计从逐条结果表重算，120 个值（20 格 × 3 模型 × 2 指标）与冻结的 P09 统计记录逐一完全一致，脚本不一致即拒绝出图。
- 误差棒是本次新增的描述性 95% 区间：在每格内按目标说话人成簇 bootstrap，10,000 次，百分位法。它不是冻结 P09 记录的一部分，也不是两模型之间的配对检验。两条线的区间是否重叠不能当作显著性判断，模型间差异的正式区间见原图 2。
- 每格含 271 到 284 位目标说话人；准确率区间半宽 2.6 到 5.6 个百分点，交叉熵 0.21 到 0.38 nats。

## 文件

| 信噪比段 | 准确率 | 交叉熵 |
| --- | --- | --- |
| −10 到 −6 dB | [snr0_accuracy.png](snr0_accuracy.png) / .pdf | [snr0_cross_entropy.png](snr0_cross_entropy.png) / .pdf |
| −6 到 −2 dB | [snr1_accuracy.png](snr1_accuracy.png) / .pdf | [snr1_cross_entropy.png](snr1_cross_entropy.png) / .pdf |
| −2 到 2 dB | [snr2_accuracy.png](snr2_accuracy.png) / .pdf | [snr2_cross_entropy.png](snr2_cross_entropy.png) / .pdf |
| 2 到 6 dB | [snr3_accuracy.png](snr3_accuracy.png) / .pdf | [snr3_cross_entropy.png](snr3_cross_entropy.png) / .pdf |
| 6 到 10 dB | [snr4_accuracy.png](snr4_accuracy.png) / .pdf | [snr4_cross_entropy.png](snr4_cross_entropy.png) / .pdf |

- 每张图 88 × 76 mm，PNG 600 dpi 不透明 RGB，PDF 矢量嵌字；逐文件 SHA 见 [MANIFEST.json](MANIFEST.json)。
- 数值表 [cell_metrics_with_ci.csv](cell_metrics_with_ci.csv)：每格每模型每指标的点估计、区间、说话人数与 bootstrap 种子。
- [overview_all_10.png](overview_all_10.png) 是 10 张图的缩略拼版，只供浏览（SHA `c4b1788a…`）。
- 生成脚本 [p10_snr_split_figures.py](../../../../checkpoint_compare_workflow_20260917/p10_snr_split_figures.py)，复用 p10_figures.py 的配色与导出；输入绑定 results.csv `c705f29e…` 与 STATISTICS.json `c609fa72…`；拒绝覆盖已有输出。

```bash
cd "$HOME/发表/超算" && /opt/anaconda3/envs/audattn/bin/python -I -B checkpoint_compare_workflow_20260917/p10_snr_split_figures.py --output "$PWD/<新的空目录>"
```

## 图中可以看到的（描述性）

formal40 减作者 checkpoint 的准确率差，按干扰者 1、2、3、4 人：

| 信噪比段 | 准确率差（百分点） | 交叉熵的方向 |
| --- | --- | --- |
| −10 到 −6 dB | +10.9、+7.6、+8.9、+8.2 | 四档都是 formal40 更低（更好） |
| −6 到 −2 dB | +0.9、+12.4、+7.6、+9.3 | 四档都是 formal40 更低 |
| −2 到 2 dB | +3.3、+1.1、+3.6、+0.4 | 两者接近 |
| 2 到 6 dB | +0.9、+0.7、+5.3、0.0 | 两者接近，作者略低 |
| 6 到 10 dB | −4.4、−6.0、−2.7、+2.2 | 四档都是作者更低（更好） |

- 原图 1 里“低信噪比时我们的模型更好、高信噪比时作者模型更好”的格局，在每一种干扰者人数下都成立，不是某一档干扰者数单独造成的。
- 低信噪比段，干扰者越多三个模型的准确率都越低、交叉熵越高；高信噪比段随干扰者人数的变化很小，6 到 10 dB 时 4 人甚至略高于 3 人，每格只有 450 条，这类小起伏在区间范围内。
- 这些都是逐格描述，未做多重比较校正，研究身份仍是复用验证集的审计，不是独立测试。
