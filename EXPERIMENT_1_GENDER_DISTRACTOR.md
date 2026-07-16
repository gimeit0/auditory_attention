# Experiment 1：同性与异性说话人干扰

本实验使用 Griffith、Hess 与 McDermott 的预训练选择性聆听模型，以及自建的 Common Voice v9 英语评测集，检验目标说话人与干扰说话人属于相同或不同 `gender` 标签组时，模型识别目标词的表现是否不同。

这里的任务不是判断声音属于男性还是女性，也没有重新训练模型。模型先听一段目标说话人的提示语音（cue），再从目标语音与干扰语音的混合中，从 800 个候选词里识别目标说话人的中心词。

## 实验设计

- cue 与 target 来自同一个说话人的不同录音。
- 每个 target 分别匹配一个同性、不同说话人的干扰，以及一个异性、不同说话人的干扰。
- 目标样本按 Common Voice 的 `male` / `female` 标签精确平衡，各 300 个。
- 使用 −9、−6、−3、0、+3 dB 和无干扰（+∞）六个 SNR 条件。
- 输入为 diotic：同一单声道信号复制到左右声道，不提供空间线索。
- cue 和 mixture 的 RMS 均归一化到 0.02。
- 主指标 `exact`：预测词是否等于预先选定的目标锚点词。

名义数据集包含 600 个 trial、149 个目标说话人、347 条目标录音和 369 个不同目标词。一条录音可以含多个合格锚点词，因此 trial 不是 600 个相互独立的说话人或录音。

## 数据处理过程

1. 从 Common Voice v9 英语数据中保留 `gender` 为 `male` 或 `female`、同一说话人标签一致、且至少有两条录音的说话人。
2. 使用 torchaudio `MMS_FA` 进行强制对齐，获得词级时间戳。
3. 选择属于 800 词表、时长小于 2 秒、前后各有至少 1.25 秒余量的锚点词。
4. 以锚点词为中心切出 2.5 秒 target；cue 和 distractor 取中心 2.5 秒。模型内部再中心裁剪为 2 秒。
5. 对同一批 target/cue 分别加入同性与异性单说话人干扰，扫描六档 SNR，并运行作者预训练 checkpoint。
6. 保存逐 trial 预测，计算准确率与干扰词混淆率，再生成结果图。

主要脚本：

- `align_words.py`：强制对齐与锚点判定。
- `build_anchor_first.py`：构建 600 个 target/cue/同性干扰 trial。
- `add_diff_distractor.py`：为相同 trial 添加异性干扰。
- `snr_scan.py`：混音、模型推理与逐 trial 评分。
- `plot_fig2a.py`、`plot_fig2b.py`、`plot_fig2e.py`：结果聚合与绘图。
- `validate_model.py`：作者 demo 与无干扰样本的有效性验证。

## 结果

| SNR (dB) | −9 | −6 | −3 | 0 | +3 | +∞ |
|---|---:|---:|---:|---:|---:|---:|
| 同性干扰（N=599） | 26.0% | 34.6% | 46.2% | 55.4% | 63.3% | 88.0% |
| 异性干扰（N=597） | 44.4% | 53.1% | 60.1% | 68.5% | 72.5% | 88.1% |
| 异性 − 同性 | +18.3 | +18.5 | +13.9 | +13.1 | +9.3 | +0.1 pp |

在两种干扰都成功运行的 596 个共同 trial 上，配对后的异性干扰优势依次为 18.3、18.6、13.9、13.1 和 9.2 个百分点；无干扰时两种条件完全相同，均为 88.09%。

结果支持三项定性趋势：

1. 两种干扰条件下，准确率均随 SNR 升高而单调上升。
2. 所有有限 SNR 条件下，异性干扰的准确率均高于同性干扰。
3. 没有干扰时两条曲线收敛，说明差异来自干扰条件，而不是 target/cue 本身发生变化。

混淆分析的方向也一致：−9 dB 时，模型输出干扰句中词的比例为同性 7.18%、异性 1.01%。不过该指标的绝对值被低估，因为同性干扰句中有 18.5%、异性干扰句中有 17.5%完全不含 800 词表内的词。

## 结果文件

- `samples_expanded.csv`：600 个 trial 的 target、cue、同性及异性干扰清单。
- `alignments_expanded.json`：目标录音的词级对齐与锚点信息。
- `snr_scan_results.csv`：同性干扰逐 trial 预测。
- `snr_scan_results_diff.csv`：异性干扰逐 trial 预测。
- `fig2a_reproduction.png` / `fig2a_reproduction_en.png`：同性单干扰曲线。
- `fig2b_reproduction_en.png`：同性与异性干扰准确率对比。
- `fig2e_reproduction_en.png`：干扰词混淆率。

原始 Common Voice 音频和模型 checkpoint 未包含在本提交中。

## 解释边界与已知问题

- Common Voice 的字段名是 `gender`；本实验比较的是数据集标签组及其综合声学差异，不能证明模型显式识别了生物学性别。
- “不同说话人”在每个 trial 内得到 100% 验证，但不是全数据集级的严格 speaker-disjoint：有 7 名目标说话人也在其他 trial 中作为同性干扰，5 名作为异性干扰。
- 同性条件少 1 个、异性条件少 3 个有效 trial。对应 MP3 的元数据时长略高于 2.5 秒，但解码并重采样后比所需的 110250 个采样点少 176 点，因此被安全跳过。
- 当前图中的误差棒是二项分布 SEM。由于实验是配对设计，且同一目标说话人可贡献多个 trial，正式推断应使用配对且按说话人聚类的统计模型；现有“σ”值不应当作最终显著性检验。
- 女性目标上的异性干扰优势大于男性目标，无干扰准确率也略有差异。该不对称目前尚未单独建模，应作为后续分析问题。
- 本评测使用 Common Voice，而论文原实验使用 Spoken Wikipedia；因此这里主张的是趋势复现，不是数值复刻或跨语料泛化复现。

## 复现命令

安装依赖并准备原始 Common Voice 音频、800 词表和作者 checkpoint 后：

```bash
python validate_model.py
python build_anchor_first.py --n_targets 600 --out samples_expanded.csv --seed 0
python add_diff_distractor.py --samples samples_expanded.csv --seed 0
python snr_scan.py --samples samples_expanded.csv \
  --dist_col same_dist_path --out snr_scan_results.csv
python snr_scan.py --samples samples_expanded.csv \
  --dist_col diff_dist_path --out snr_scan_results_diff.csv
python plot_fig2a.py
python plot_fig2b.py
python plot_fig2e.py
```

本仓库中的结果 CSV 可直接用于重新绘图，无需再次运行模型。
