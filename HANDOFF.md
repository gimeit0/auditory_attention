# HANDOFF —— 项目交接(给新会话 / hakusan GPU 配置)

> 本文件是**当前进度快照 + 待办 + GPU 移植要点**,配合根目录 `CLAUDE.md`(原始任务背景)一起读。
> 最后更新: 2026-06-28。用户主要用中文沟通,正式交付物用日文,代码注释中英文皆可。

---

## 0. 一句话现状

论文 **Griffith, Hess & McDermott (2026, NHB)** Experiment 1 的 **Fig 2a 已成功复现**(趋势方向一致):
用作者预训练 checkpoint + 自建 Common Voice v9 评测集,中间词识别准确率随 SNR **严格单调上升**。
**Fig 2b(同性 vs 异性 distractor)的数据已备好,异性那条线的 SNR 扫描尚未跑**(因 CPU 上约 6.5h,用户决定带到 GPU/hakusan 上跑)。

---

## 1. 已完成(里程碑)

### Task A — Forced Alignment(`align_words.py`)
- 用 `torchaudio.pipelines.MMS_FA`(16kHz 字符级)对每条 CV 录音做强制对齐,得每个词的秒级起止。
- 文本规范化复刻论文 `src/get_swc_binaural_manifest_transcripts.py` 的 `convert_transcript`,
  **但保留撇号**(词表里有 16 个带撇号缩写 can't/don't/that's...,删了就匹配不上)。
- "中间词锚点候选"判定: 词 ∈ 800 词表 且 词长<2s 且 前后各≥1.25s 余量(保证能切 2.5s 片段)。

### Task B — 切片(`slice_stimuli.py` / 锚点优先扩样 `build_anchor_first.py`)
- 切片规格: **44100Hz, 2.5s = 110250 样本**(与 `demo_stimuli` 一致;模型 config `center_crop:True` 内部再取中间 2s)。
- target 以锚点中心切;cue / distractor 中心裁剪 2.5s。
- **锚点优先配对**(关键效率改进): 先对齐、后配对。旧"先随机配对后筛"产出率仅 22%;
  新流程从 627 条录音得 **600 个有效 target 样本(96%)**,性别精确 50/50(男300/女300),149 说话人、369 个不同目标词。

### 模型有效性验证(`validate_model.py`)
- demo 闸门: `demo_stimuli` 加载→推理正确(male→about, female→above),确认 checkpoint 加载无误。
- clean(无干扰)44 样本: 中间词识别 **88.6%**(exact=lenient,随机基线 0.1%)。

### Fig 2a 复现(`snr_scan.py` + `plot_fig2a.py`)
- within-item,600 样本(实际 n=599,1 条切片越界跳过),same-sex 单干扰,diotic,cue+mixture RMS 归一 0.02。
- 6 档 SNR 中间词识别准确率(exact):

  | SNR(dB) | -9 | -6 | -3 | 0 | +3 | +inf |
  |---|---|---|---|---|---|---|
  | 准确率 | 26% | 35% | 46% | 55% | 63% | 88% |

- **严格单调上升 ✓**,与论文 Fig 2a 趋势一致。inf 档 88% 与 clean 验证 88.6% 互证。
- 图: `fig2a_reproduction.png`(中文) / `fig2a_reproduction_en.png`(英文)。

---

## 2. 混音 / 评分口径(复用仓库 transforms,务必沿用)

- 混音: `CombineWithRandomDBSNR(low=high=snr)` → `RMSNormalizeForegroundAndBackground(0.02)` → `DuplicateChannel`(diotic) → `UnsqueezeAudio`。
  - foreground = target(signal),background = distractor(noise)。**SNR 越高 distractor 越弱 → 越易**。
  - **inf/clean 档: background=None**(纯 target 再归一/diotic)。
- 评分:
  - **exact** = 预测词 == target 锚点词("中间词识别准确率",主指标)。
  - **lenient** = 预测词 ∈ target 句中所有"在 800 词表内"的词(论文宽松口径,参考)。
  - (Fig 2d/e 用) **confusion** = 预测词 ∈ distractor 句的转写词 —— 见第 5 节。

---

## 3. 文件清单

### 脚本(我新建的,均带自检打印)
| 文件 | 作用 |
|---|---|
| `align_words.py` | Task A 强制对齐,输出锚点候选 JSON。**可被 import 复用**(`load_audio_16k/process_clip/normalize_token`) |
| `build_anchor_first.py` | 锚点优先扩样到 600 个 target 样本 → `samples_expanded.csv` |
| `add_diff_distractor.py` | 给 600 样本各加一个**异性** distractor 列(Fig 2b 用) |
| `slice_stimuli.py` | 把锚点切成 2.5s 片段(早期 44 样本测试集用);提供 `load_44k/slice_centered/slice_middle` |
| `validate_model.py` | demo 闸门 + clean 验证(打印 真实 vs 预测) |
| `snr_scan.py` | SNR 扫描主脚本。`--dist_col` 选同性/异性,`--out` 指定结果 csv |
| `plot_fig2a.py` | 画 Fig 2a 单线图 |

### 数据 / 结果
| 文件 | 内容 |
|---|---|
| `samples_expanded.csv` | **600 个 target 样本主表**,自带 target_center_s/label/cue/同性+异性 distractor。列见文件头 |
| `alignments.json` / `alignments_expanded.json` | 词级对齐结果(200 测试 / 扩样录音) |
| `snr_scan_results.csv` | **同性**干扰 6 档逐样本预测(599 行) |
| `snr_scan_results_diff.csv` | **异性**干扰结果 —— ⚠️ **尚未生成,待跑** |
| `fig2a_reproduction*.png` | Fig 2a 复现图 |
| `pairs_test.csv` / `eval_manifest.csv` / `eval_stimuli/` | 早期 50 pair / 44 样本测试集(已被 600 样本取代,可忽略) |

---

## 4. 立即待办(继续 Fig 2b)

1. **跑异性扫描**(Step 1 已完成: 600/600 异性 distractor 已写入 `samples_expanded.csv` 并校验异性+异人):
   ```
   caffeinate -i -s python -u snr_scan.py --dist_col diff_dist_path --out snr_scan_results_diff.csv
   ```
   - ⚠️ **CPU 约 6.5h,必须 caffeinate 防休眠**(见第 7 节坑)。GPU 上会快几十倍。
2. 输出异性 6 档准确率,和同性对比(**预期异性整体更高**)。
3. 确认趋势后画 **Fig 2b 双线对比图**(同性 vs 异性两条线)——`plot_fig2a.py` 改造成双线即可。

---

## 5. 后续面板路线图

- **Fig 2d/2e(confusion vs SNR,按 same/diff-sex 分)**: ⭐ **几乎可白嫖现有数据!**
  `samples_expanded.csv` 已存 `same_dist_sentence`/`diff_dist_sentence`,`snr_scan_results*.csv` 已存每档 `pred_<snr>`。
  confusion = 该样本预测词 ∈ distractor 句的"表内词"集合。**不需要再跑模型/对齐**,纯后处理两份结果 csv 即可出 2d/2e。
- **Fig 2c(英语 vs 普通话干扰)**: 需 CV v9 中文 dev 集 + 重做中文 distractor。中等工作量。
- **Defer(超范围)**: 2f harmonicity(STRAIGHT)、2g/h 噪声/音乐(AudioSet)、Fig 3/4 空间(HRTF)——本项目走 diotic,不做。

---

## 6. ⭐ hakusan / GPU 移植要点

目标: 把 `snr_scan.py`(和可选 `align_words.py`)从 M1 CPU 搬到 hakusan GPU,大幅提速。

**(a) 环境重建**
- 现环境: conda `audattn`,Python 3.11,**torch 2.12.1 / torchaudio 2.11.0**,另有 `chcochleagram`(耳蜗前端)、num2words、soundfile、pandas、matplotlib、scipy、pyyaml。
- 根目录有 `requirements.txt`,但注意 repo 原版库较旧(numpy1.26/scipy1.11/torch2.1),我们用的是新版+垫片;在 hakusan 上优先复刻**我们这套较新版本**,别降级到 demo 失效。
- 首次跑会下载 MMS_FA 模型(~1.2GB)到 `~/.cache/torch/hub/checkpoints/model.pt`。

**(b) 改设备 cpu→cuda**
- `snr_scan.py` / `validate_model.py` / `align_words.py` 顶部都有 `DEVICE = "cpu"`,改成 `"cuda"`。
- 模型与耳蜗前端: `model.to(DEVICE)`、`model.coch_gram.to(DEVICE)`,以及每次 `to_dev(x)` 已统一走 DEVICE,改一处常量即可。
- **务必验证**: `chcochleagram` 耳蜗前端的 FFT/complex 算子在 CUDA 上可用(M1 上当初因 MPS 不支持才退回 CPU;CUDA 一般 OK 但要实测)。

**(c) 两个必留垫片(沿用,别删)**
- `torch.load` monkeypatch 设 `weights_only=False`(checkpoint 来自作者 OSF,可信;PyTorch≥2.6 否则报错)。
- `scipy.signal.hann = scipy.signal.windows.hann`(scipy 新版删了 hann,import 前打)。

**(d) 提速优化(GPU 上建议做)**
- 当前每样本 7 次 forward(1 cue + 6 SNR 混音)。可把 **6 档 SNR 的混音 stack 成一个 batch**,
  cue cochleagram 复用、mixture 一次 batch forward 出 6 个 logits → 理论快 3–5 倍(GPU 上更多)。
- 改完**必须**用前 20 样本验证数值与现有 `snr_scan_results.csv`(同性)一致,再放全量。

**(e) 同口径对比注意**
- 若 Fig 2a(同性)在 CPU 跑、Fig 2b(异性)在 GPU 跑,严格说两条线设备不同。
  **建议**: 在 GPU 上把**同性也重跑一遍**,两条线同设备同口径,论文式对比才干净。

---

## 7. 已知坑(务必沿用现有解法)

1. **PyTorch≥2.6 加载 checkpoint**: 需 `weights_only=False`(monkeypatch,见 6c)。
2. **scipy 删 `scipy.signal.hann`**: 加垫片(见 6c)。
3. **M1 无 CUDA / MPS 不支持耳蜗前端算子**: 在 M1 上用 CPU。到 GPU 改 cuda 并实测耳蜗前端。
4. **mp3 解码**: `torchaudio.load` 需要 torchcodec(没装);用 **soundfile** 读 mp3(48kHz),再 `torchaudio.functional.resample` 到目标采样率(对齐用 16k、模型用 44.1k)。
5. **MMS 字典 `-` 是 CTC blank**: 规范化时连字符删掉(e-guitar→eguitar),否则 aligner 报 "blank index"。撇号(char 25)可正常对齐。
6. **⚠️ 长任务必须 caffeinate**: M1 上多小时 CPU 后台任务会被 macOS 维护性休眠反复挂起、零进度。
   一次 600 样本扫描原估 1h 因休眠拖到 5h+。用 `caffeinate -i -s python ...` 或对已在跑的 `caffeinate -i -s -w <PID> &`。
   (GPU/hakusan 上跑得快,基本无此问题。)

---

## 8. 关键路径

- 仓库: `~/projects/auditory_attention`
- CV v9 英语: `/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/`(`validated.tsv` + `clips/`)
- checkpoint: `attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints/epoch=1-step=24679-v1.ckpt`
- config: `config/binaural_attn/word_task_v10_main_feature_gain_config.yaml`
- 词表: `cv_800_word_label_to_int_dict.pkl`(word→标签号,与作者官方 pkl 字节一致)

---

## 9. 判趋势是否复现(方向对即成功)

- Fig 2a: SNR 升 → 准确率升 ✅(已确认)
- Fig 2b: different-sex 准确率 > same-sex(待异性扫描确认)
- Fig 2d: SNR 降 → confusion 增多
- Fig 2e: same-sex 的 confusion 更高

**判据始终是趋势方向一致,不追求数值复刻。**
