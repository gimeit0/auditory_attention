# R0 交付最终图文核对（P10）

2026-09-27。对象：本目录的 P10 交付（`P10_delivery.md`、`NUMERIC_ERRATUM.md`、`SHA256SUMS.txt`、`figures/`）及其上游 P09 统计与 P08 台账。规则来源：主计划 §14“R0_FIGURES_PRESENT / R0_DELIVERY_VERIFIED：已有图件≠最终核对完成；核验数据/图注/清单后才进入后者”。本核对只做本地只读操作与程序化比对，不改动任何既有交付文件；本文件是本目录唯一新增文件。研究身份仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`；本核对是工程交付核验，不对 α 机制或模型优劣作任何新的科学主张。

## 1. 判定

**R0_FIGURES_PRESENT 保持，R0_DELIVERY_VERIFIED 未达成。**

七类核对中六类零不一致；第 2 类（文本数字对照 STATISTICS.json）在 345 项中有 4 项不通过：1 项为事实性错误（`figures/FIGURES.md` 图 3 替代文本称三模型 probe 概率变化“区间互不重叠”，而 formal40 与 valbest33 的 95% 区间实际重叠），3 项为“约”值超出四舍五入允许范围（均在一个末位单位以内）。数据、SHA 清单、离线重算、图件确定性、作业事实与图件属性全部通过；需要修改的只是图注/正文措辞（见第 4 节），由用户决定是否修改交付文本。修改并复核后即可标 R0_DELIVERY_VERIFIED。2026-09-27 更正后复核见 §9，该复核判定 R0_DELIVERY_VERIFIED 达成。

## 2. 范围与方法

- 只读输入：`P10_delivery.md`、`NUMERIC_ERRATUM.md`、`SHA256SUMS.txt`、`figures/FIGURES.md`、`figures/MANIFEST.json`、`figures/*.png|pdf`；`../p09-statistics-20260919/{STATISTICS.json, REPORT.md, paired_strata.csv, MODEL_STRATA.md}`；`checkpoint_compare_workflow_20260917/{p09_statistics.py, p10_figures.py, numeric_sensitivity_erratum.py}`；`../p08full-production-20260919-r2/REPORT.md` 及 `frozen/collect-vvv4ed4a/collected/received/full10k/`（`results.csv`、`logits.npz` 等）、`offline-review-728520/REPORT.json`、`full-repeat-728378-vs-728520/report.json`、`held_readback_728520.log`、`correct-gpu-728520/readback.log`。
- 全部核对由 7 个 Python 脚本完成（`/opt/anaconda3/envs/audattn/bin/python -I -B`，numpy 2.4.6、pandas 3.0.3、matplotlib 3.11.0、Pillow 12.2.0、pypdf 6.14.2，另用 `pdffonts`），脚本与中间输出放在会话 scratchpad 的 `w3/` 下，不写入项目。
- 数字比对判据：文本给到小数第 k 位（含“约”值）时，要求 |文本值 − 数据值| ≤ 0.5×10^−k，即数据四舍五入到该位与文本一致；“约 a–b”型范围要求每个相关数据值四舍五入后落在 [a, b] 内。不满足但在 1×10^−k 内的记为“边界”，仍计不一致；逻辑性表述（方向、是否含 0、是否重叠、单调性、n）按数据直接判真伪。

## 3. 各项核对结果

| 项 | 内容 | 结果 | 计数 |
| --- | --- | --- | --- |
| 1 | `SHA256SUMS.txt` 23 项逐项复算 | 通过 | 23/23 |
| 1 | `figures/MANIFEST.json`：6 个图文件的 sha256 与字节数、3 条 `source_sha256`（STATISTICS.json）、3 条 `results_csv_sha256` | 通过 | 18/18 |
| 2 | 文本数字对照 STATISTICS.json（含勘误脚本输出） | **4 项不通过** | 341/345 |
| 2a | 其中 `P10_delivery.md` §1、§2（含 §2 表 5 行 n 与 30 个数值） | 1 项边界 | 91/92 |
| 2b | 其中 `figures/FIGURES.md`（总说明、三图图注与替代文本） | 1 项事实性错误、2 项边界 | 51/54 |
| 2c | 其中 `NUMERIC_ERRATUM.md`（§1 计数、§2 表 7 位小数、CI 下端） | 通过 | 32/32 |
| 2d | 其中 `MODEL_STRATA.md`（14 行×6 值、20 细胞×3 值、下降句） | 通过 | 167/167 |
| 3 | 勘误复算：`numeric_sensitivity_erratum.py` 运行至 scratchpad，输出 `OFFLINE_SENSITIVITY_AUDIT_PASS`、23 文件通过；本核对另用独立代码从 `logits.npz` 排序取 top1−top2 margin，formal40 63/10000、author_external 80/10000、valbest33 47/10000（≤0.008），29、36、23（≤0.004）；≤0.004 的 29/36/23 与 STATISTICS.json `margin_strata.by_model_condition.<model>__correct.within_envelope_le_low` 一致；≤0.008 的 63/80/47 仅与 NUMERIC_ERRATUM.md 及本核对从 `logits.npz` 的独立复算一致（STATISTICS.json 无该阈值字段，`margin_strata.edges` 为 [0.004, 0.04]）；三模型 argmax 与 `results.csv` `*_pred_label` 全部一致；总体/mixed/clean 的配对 Accuracy 差与 NLL 改善由 `results.csv` 复算，与 STATISTICS.json 在 1e−12 内一致；配对 NLL 界 0.002+0.002=0.004；单元测试 4 项 OK | 通过 | 全部一致 |
| 4 | 离线重算（§4 命令，`--output` 指向 scratchpad）：STATISTICS.json 2,138 个叶值仅 `computed_utc` 不同（交付 `2026-09-19T01:04:28.556815+00:00`，重算 `2026-09-26T16:23:02.846991+00:00`）；REPORT.md 仅第 3 行时间戳不同；paired_strata.csv sha256 完全相同 | 通过 | 差异字段 1（时间戳） |
| 5 | 图件确定性：`p10_figures.py` 支持 `--statistics` 与 `--output`，且对已存在文件抛 `FileExistsError`（不会覆盖交付图件）；在 scratchpad 重新生成后 3 个 PNG sha256 与交付版逐字节相同、像素差 0；3 个 PDF 字节数相同，仅 `/CreationDate` 不同，掩去该字段后逐字节相同 | 通过 | PNG 3/3 相同；PDF 3/3 除时间戳外相同 |
| 6 | 作业事实交叉检查（P10 正文 vs P08 台账 vs 机器记录）：728520 `COMPLETED|0:0|00:57:11|spcc-a100g02`；728378 冷重复 12 组、48,000 条逐位一致、0 翻转；六作业逐位链 724808→725677→726428→728280→728378→728520（P08 台账 §2 记载，P10 正文未直接复述，仅链接）；typed GRES 改写第 8 次，held 回读 `gres/gpu:h100-20c=1`，修正后回读 `gres/gpu:nvidia_a100=1`；728378 FAILED/1:0 验证器 CSV 分块解析缺陷；18 个失败/超时作业见失败总审计；`LOAD_REPORTS.json` 三模型 `loaded_trainable_numel_ratio` 均 1.0；`logits.npz` 12 个数组 3×(10000+2000+2000+2000)×800 float32 = 48,000 行；`RUN.json` job_id 728520/full10k/batch 16；§4 回执 SHA `21a42644fd60e73a3668fd07cfe656a49b8ca95635438fd23ef6c7b92b8881ab` 与 SHA 清单及 STATISTICS.json `source.receipt_sha256` 一致 | 通过 | 10/10；三份文档相对链接 23/23 可达 |
| 7 | 图件属性 vs 图注：MANIFEST 与 FIGURES.md 尺寸一致（180×120、180×105、180×62 mm）；PNG 均为 8-bit RGB、无 alpha，pHYs 折算 599.9988 dpi，像素 4251×2834、4251×2480、4251×1464（600 dpi 理论值 4252×2835、4252×2480、4252×1465，偏差 ≤1 px，来自 matplotlib 对 4251.97 的取整）；PDF 页面 510.24×340.16、510.24×297.64、510.24×175.75 pt，即 180.0×120.0、180.0×105.0、180.0×62.0 mm；字体 ArialMT 与 Arial-BoldMT，`pdffonts` 报 CID TrueType、已嵌入、子集化，对应 matplotlib `pdf.fonttype 42`，与“嵌入 TrueType（Type 42）字体”一致 | 通过 | 3 图×5 属性 |

对第 6 项补充：P10 §6 所述 Okabe–Ito 配色（#0072B2、#D55E00、#009E73）与形状/线型冗余（o 实线、s 虚线、^ 点线）、图 1 纵轴 0–1 与 0–5.2、图 2 分层顺序与实心/空心标记、图 3 三面板结构，均与 `p10_figures.py` 源码一致。

## 4. 不一致清单（需用户决定是否修改交付文本）

| 序号 | 位置 | 文本值 | 数据值（STATISTICS.json） | 判定 |
| --- | --- | --- | --- | --- |
| 1 | `figures/FIGURES.md` 图 3 替代文本末句：“(c) probe 概率变化 formal40 约 0.21、valbest33 约 0.20、作者约 0.11，区间互不重叠” | 区间互不重叠 | formal40 95% CI [0.1923, 0.2223]，valbest33 [0.1895, 0.2180]，二者在 [0.1923, 0.2180] 上重叠；author_external [0.1039, 0.1252] 与前两者不重叠 | 事实性错误。建议改为“作者的区间与另两者不重叠；formal40 与 valbest33 的区间重叠”或删去“互不重叠” |
| 2 | `figures/FIGURES.md` 图 3 图注：“formal40 与 valbest33 在 distractor cue 下 probe 概率的上升点估计约 +0.20” | 0.20（formal40） | formal40 0.2069（四舍五入 0.21），valbest33 0.2036（0.20） | 边界。同文件替代文本已写 formal40 约 0.21，图注与替代文本自相矛盾；建议图注改为“formal40 约 +0.21、valbest33 约 +0.20” |
| 3 | `P10_delivery.md` §1“在哪些条件差”：“formal40/valbest33 的 distractor cue probe 概率变化点估计约 +0.20” | 0.20（formal40） | formal40 0.2069 | 边界。同上，建议改为“formal40 约 +0.21、valbest33 约 +0.20” |
| 4 | `figures/FIGURES.md` 图 1 替代文本：“随干扰者数从 1 增至 4，三者准确率从约 0.48–0.51 降到约 0.33–0.37” | 0.33–0.37 | 干扰者数 4：formal40 0.3636、author_external 0.3231（四舍五入 0.32）、valbest33 0.3724 | 边界。建议改为“约 0.32–0.37” |

边界通过（在判据内，仅备查，不计不一致）：图 1 替代文本“clean 作者约 0.79”（0.7850）；图 2 替代文本“约 +1.8 个百分点”（1.7500）、“区间 +0.2”（0.1510）、“+0.15”（0.14508）；图 3 替代文本“correct − distractor 约 32–38”（单位百分点；author_external `correct_minus_distractor` 均值 0.3150，即 31.50，|32 − 31.50| = 0.50 恰在判据边界）。

措辞备注（不计不一致）：P10 §1 与图 2 替代文本称干扰数 1–4 的交叉熵“区间多数跨 0”，实际四层全部跨 0，表述偏弱但不假；图 2 替代文本“valbest33 − 作者在多数层比 formal40 − 作者更偏正”，Accuracy 12/14 层、交叉熵 14/14 层为真；图 3 图注含全角破折号，与项目当前文档风格约定不符，属格式项。

## 5. 复现命令

在工作区根目录 `/Users/gigi/发表/超算` 执行；`W3` 为任意可写的临时目录，不要指向交付目录。

```bash
W3=/path/to/tmp/w3
# 3. 勘误脚本（只读，输出 JSON）与单元测试
/opt/anaconda3/envs/audattn/bin/python -I -B checkpoint_compare_workflow_20260917/numeric_sensitivity_erratum.py > "$W3/erratum_output.json"
/opt/anaconda3/envs/audattn/bin/python -I -B checkpoint_compare_workflow_20260917/tests/test_numeric_sensitivity_erratum.py
# 4. 离线重算（P10_delivery.md §4 命令，仅改输出目录）
/opt/anaconda3/envs/audattn/bin/python -I -B checkpoint_compare_workflow_20260917/p09_statistics.py \
  --archive "$PWD/docs/superpowers/evidence/p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k" \
  --receipt-sha256 21a42644fd60e73a3668fd07cfe656a49b8ca95635438fd23ef6c7b92b8881ab \
  --output "$W3/p09-recompute"
# 5. 图件重生成（脚本拒绝覆盖已存在文件）
/opt/anaconda3/envs/audattn/bin/python -I -B checkpoint_compare_workflow_20260917/p10_figures.py \
  --statistics "$PWD/docs/superpowers/evidence/p09-statistics-20260919/STATISTICS.json" --output "$W3/figs"
# 1. SHA 清单
(cd "$PWD" && shasum -a 256 -c docs/superpowers/evidence/p10-delivery-20260919/SHA256SUMS.txt)
# 7. 图件属性
file docs/superpowers/evidence/p10-delivery-20260919/figures/*.png
pdffonts docs/superpowers/evidence/p10-delivery-20260919/figures/fig1_model_performance_by_condition.pdf
```

第 2、6、7 项的逐项比对脚本（`check1_sha.py`、`check2_numbers.py`、`check3_erratum_independent.py`、`check4_recompute_diff.py`、`check5_figdiff.py`、`check6_jobfacts_links.py`、`check7_figprops.py`）位于会话 scratchpad `w3/`，判据如第 2 节所述；其结果 JSON 同目录。

## 6. 本核对生成的关键辅助文件 sha256（均在 scratchpad，不入项目）

- 重算 `STATISTICS.json`：`f2782e5e7003adac414db06e80d238c95ea7d47efdd9df5153dee5d5e6fb3f06`（交付版 `c609fa726b30e60faca2b9a3dd648b466e3bdaa770e56f2209202a41ba3e341d`，仅 `computed_utc` 不同）；重算 `REPORT.md`：`969be54a882f2a009d61172f95a3260b268c289f01281b7262083ce17a732866`；重算 `paired_strata.csv`：`36bb3b81ead4b8b8a0a4329b5f973e50c68cfdfa3fe607981c082f7c3133c652`（与交付版相同）。
- 重生成 PNG：与交付版相同，`b1863ea65e86fbf4e85e1955f98cf3c6c1eadd8be6e16ebc12e3d922a26fcb41`、`92f14003b95b6e511a7b456dd47c2310e20ec93e466f0ddf386f2f7729ceb0ad`、`0af47adf4d8e8df3b133909303b53174da266e6523391bba840a7fc3889ed530`。
- 重生成 PDF（仅 `/CreationDate` 不同）：`77e50b080dc3eb90fc71be1fb66a1d9b333cadf6379dbdd35f3def6bec96b67f`、`131323caf07ade09d893fbc6db709d16f5e41c37fbccad63f1c17ba9769ad0c4`、`d8c1008a0b31cb2b5ee011fd477d04b73de400f94026b697084f3dc166092a20`（交付版 `f9cd013208ce0f684aafbe4f2552f636d3b90499b488a6fca94e08400d9b85f7`、`fe36b80bdaf1860454b5f1d586e0530ad8154c8c5f86105788e1a93adb0d35b9`、`93d78016b4b9636ac88d9d26ee54e1f8cf794b953d99b38d176f05a58909c38c`）。
- 勘误脚本输出 `erratum_output.json`：`b24fd99a35fdd06380e0b250b8cafe40ef3d94d5a2dc4550dcdc46662bc747c5`。

## 7. 边界

本核对不涉及 SSH、作业提交或任何远端访问；未修改 `SHA256SUMS.txt` 与任何既有交付文件。E0 为工程验收（`E0_ENDPOINT_PASS`，`scientific_alpha_result=false`），本核对的“通过”只表示交付文本、图件与冻结数据相互一致，不构成 α 机制成立的证据，也不改变复用验证集审计、非独立测试集的研究身份。

`SHA256SUMS.txt` 23 项只覆盖上游数据、统计与脚本文件；`P10_delivery.md`、`NUMERIC_ERRATUM.md`、`FIGURES.md`、`MANIFEST.json`、6 个图件、`p10_figures.py`、`numeric_sensitivity_erratum.py` 不在清单内，是否在修改措辞后扩充清单由用户决定。

## 8. 已被本核对取代的交付文本表述（待用户决定是否修改）

以下两处 `P10_delivery.md` 表述在成文时正确，现已被本核对或后续作业记录取代。本核对未修改 `P10_delivery.md`，是否改写由用户决定。

- `P10_delivery.md` §7“最终图文核对（图注数值与 REPORT.md/勘误逐项对照）由用户复核”：程序化核对已由本文件完成（第 3 节七类核对），剩余为第 4 节 4 处措辞决定。
- `P10_delivery.md` §5“站点插件改写 typed GRES 共 8 次”：2026-09-19 成文时正确（第 8 次为 Job 728520）；2026-09-26 E0 作业 746603 为第 9 次记录，见 [docs/superpowers/evidence/e0-production-20260926/REPORT.md](../e0-production-20260926/REPORT.md) §5。

## 9. 2026-09-27 更正后复核

第 4 节所列 4 处措辞已由用户于 2026-09-27 修正：`P10_delivery.md` §1（formal40 “约 +0.20”改“约 +0.21”）、§5（typed GRES 计数加时效注）、§7 改写并新增 §8 更正记录；`figures/FIGURES.md` 图 3 图注、图 3 替代文本、图 1 替代文本改写，并在文末新增更正记录。本节记录对修正后文本的完整复核。复核仍为本地只读程序化比对，不改动任何交付文件；`SHA256SUMS.txt`（23 项上游冻结清单，sha256 `c483c3b9ed60808b9b13a910b28adab8fcba2b67b9dae8fa730ea0597d2c4799`）未改。

### 9.1 判定

**R0_DELIVERY_VERIFIED 达成（2026-09-27）。** 七类核对全部通过：文本数字对照 STATISTICS.json 384 项 0 不一致（第 2 类），其余六类与首次核对相同为零不一致。本判定仍是工程交付核验：文本、图件与冻结数据相互一致，不构成 α 机制成立的证据，研究身份仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。

被复核文本的版本（sha256，字节数）：`P10_delivery.md` `d85dae243e020868dbfc5fe6dd5969aca744b138a2652d9245671c2cd9e52aa6`（9,216）；`figures/FIGURES.md` `6a963a59eb5a5a2a4c689c6b0346c9cd138048347c18d35dadce8aacfab3e26c`（5,511）；`NUMERIC_ERRATUM.md` `e5f31cc43bfeac19c01c6dc95e971043869afc69cea68493ec6f5cf689f16a56`（4,351）；`../p09-statistics-20260919/MODEL_STRATA.md` `0b4d36cc7d22b2586668172887a90eebb1619aa09a3d22cd16b236c42498fd31`（2,191）；`STATISTICS.json` `c609fa726b30e60faca2b9a3dd648b466e3bdaa770e56f2209202a41ba3e341d`（133,783）；`figures/MANIFEST.json` `556b00909b7a81895093a5506756db33109c9de216240de6c4a9ed45417986d8`（4,355）。6 个图件的 sha256 与 MANIFEST.json 一致（见第 3 节第 1 项与 `results/check1_sha.json`）。

### 9.2 脚本归档与路径改造

首次核对的 7 个脚本留在会话 scratchpad，现归档到本目录 [r0-verification-20260927/](r0-verification-20260927/)：`common.py`（公共：项目根推导、输入文件 SHA、结果写出）、`check1_sha.py`、`check2_numbers.py`（重写，见 9.3）、`check3_erratum_independent.py`、`check4_recompute_diff.py`、`check5_figdiff.py`、`check6_jobfacts_links.py`、`check7_figprops.py`，另加 `check2_sensitivity_oldtext.py`（check2 的灵敏度测试）、`make_sha256sums_delivery.py`、`run_all.sh`。所有 scratchpad 绝对路径已改为相对项目根（由脚本位置向上五级推导，或 `--root` 指定）；输出统一写入 `r0-verification-20260927/results/`（`--results` 可改）。每个结果 JSON 顶部都有 `input_sha256` 字段，记录 17 个被核对文件（`P10_delivery.md`、`FIGURES.md`、`NUMERIC_ERRATUM.md`、`MANIFEST.json`、6 个图件、`STATISTICS.json`、`REPORT.md`、`paired_strata.csv`、`MODEL_STRATA.md`、`p10_figures.py`、`p09_statistics.py`、`numeric_sensitivity_erratum.py`）的 sha256 与字节数，使结果与文本版本绑定。环境同第 2 节（numpy 2.4.6、pandas 3.0.3、matplotlib 3.11.0、Pillow 12.2.0、pypdf 6.14.2、`pdffonts`）。

`check5`、`check7` 顺带修正了两个判定口径：`check5` 比较再生成与交付的 MANIFEST 条目时排除 PDF 的 sha256（PDF 仅 `/CreationDate` 不同，其 sha 必然不同，PNG sha、字节数、尺寸、来源 sha 等仍逐项比较）；`check7` 把 matplotlib `pdf.fonttype 42` 实际写出的 `/Type0` 复合字体（子字体 `/CIDFontType2`，嵌入 `/FontFile2`）识别为 TrueType（Type 42），首次核对靠 `pdffonts` 的“CID TrueType”判读，结论不变。`check6` 新增 3 条事实（P10 §5 时效注“2026-09-26 E0 作业 746603 为第 9 次”对照 E0 台账 §5；P10 §7 指向本文件且存在；P10 §6/FIGURES.md 的配色、Type 42、600 dpi、不透明与 `p10_figures.py` 源码一致），并从 `logits.npz` 实际读取数组形状。`check7` 的图尺寸改为从 FIGURES.md 标题解析，不再手抄。

### 9.3 check2 的改造：读实际文本、绑定 SHA

首次核对的 `check2_numbers.py` 把文本中的数字手工抄成常量，重跑不能证明新文本通过。重写后的脚本直接读取当前 `P10_delivery.md`、`figures/FIGURES.md`、`NUMERIC_ERRATUM.md`、`MODEL_STRATA.md` 的文本（仅把 U+2212 负号与全角加号归一为 ASCII，逐字符替换，不改变偏移），用带上下文的正则抽取数字，按句子上下文映射到 STATISTICS.json 字段（敏感性数字映射到勘误脚本输出 `results/erratum/erratum_output.json`），判据与第 2 节相同：文本给到小数第 k 位（含“约”值）要求 |文本值 − 数据值| ≤ 0.5×10^−k；“约 a–b”要求每个相关数据值四舍五入后落在 [a, b] 内；百分点与小数按 ×100 换算；逻辑表述按数据判真伪。每个抽取器必须恰好匹配一次，否则记为 PARSE 失败项并计入不通过，改写后的句子不会静默漏检。每项输出文件、行号、匹配片段、文本值、数据值、位数、类型、通过与否、数据字段路径。

覆盖数：384 项，全部通过（`P10_delivery.md` 110、`FIGURES.md` 63、`NUMERIC_ERRATUM.md` 44、`MODEL_STRATA.md` 167；类型：精确 265、“约” 32、范围 11、布尔 76）。首次核对为 345 项（92、54、32、167），新脚本不少于它；多出的 39 项来自：P10 §8 与 FIGURES.md 更正记录中引用的数据值与新“约”值（17 项，如“数据为 0.2069”“[0.1923, 0.2223] 与 [0.1895, 0.2180] 重叠”“author 为 0.3231”）、把复合逻辑句拆成可单独判定的布尔项（如“author 的区间与另两者不重叠”与“formal40 与 valbest33 的区间重叠”各一项，“区间不含 0”“author 更好”“优于”等），以及 NUMERIC_ERRATUM.md 的百分比（0.63%/0.80%/0.47%）、ε 换算、冻结文件数、表内 n 与点估计对照 STATISTICS.json。

白名单：脚本对四份文档中全部数字记号做覆盖扫描（P10 209 个，143 个被检查项消耗；FIGURES.md 114/79；NUMERIC_ERRATUM.md 59/38；MODEL_STRATA.md 196/189），未被消耗的 129 个数字全部落入带理由的白名单规则（章节标题编号 34、作业事实 23（由第 6 类核对）、计数/枚举/常量 0 20、章节/图/面板/计划/模型编号 16、置信水平/权重常量 9、图件属性 9（由第 7 类核对）、样本量/维度 8（由第 3/6 类核对）、扰动包络常量 6、SHA 名称数字 3、加载覆盖率 1（由第 6 类核对）），无法归类的数字 0 个；白名单逐项列于 `results/check2_numbers.json` 的 `whitelist`。

四处已修正的句子均被真实解析并判定通过（相关检查 29 项，见 `results/check2_numbers.json` 的 `corrected_sentences_checks`）：P10 §1 “formal40 约 +0.21、valbest33 约 +0.20，author 约 +0.11”对 0.2069、0.2036、0.1143；FIGURES.md 图 3 图注同三值；图 3 替代文本“author 的区间与另两者不重叠，formal40 与 valbest33 的区间重叠”对 CI [0.1923, 0.2223]、[0.1895, 0.2180]、[0.1039, 0.1252]；图 1 替代文本“约 0.32–0.37”对 0.3636、0.3231、0.3724。

灵敏度测试（`check2_sensitivity_oldtext.py`，结果 `results/check2_sensitivity_oldtext.json`）：在 `results/` 下临时构造一个把这四句退回修正前措辞的项目根，对其运行同一 check2：380 项中 4 项不通过（P10 §1 formal40 约 +0.20 对 0.2069 边界；图 1 替代文本约 0.33–0.37 对 author 0.3231 边界；图 3 图注 formal40 约 +0.20 边界；图 3 替代文本 (c) 句式不同而 PARSE 失败），并有 1 个未映射数字（旧句中的 0.20）。这证明新脚本对旧文本会报错，对新文本通过并非因为检查项缺失。临时根测试后删除。

边界通过（在判据内，仅备查，与第 4 节所列相同，另加 4 位小数项）：共 11 项，如 P10 §2 表 SNR 6~10 dB Acc 差 CI 上 0.0044（0.004351）；图 1 替代文本 clean 作者约 0.79（0.7850）；图 2 替代文本约 +1.8 个百分点（1.7500）、区间 +0.2（0.1510）、+0.15（0.14508）；MODEL_STRATA.md 表 1 中 6 个 NLL 值的第 4 位差恰在 0.45～0.5 个末位单位。

### 9.4 七类核对结果（2026-09-27 重跑）

| 项 | 内容 | 结果 | 计数 |
| --- | --- | --- | --- |
| 1 | `SHA256SUMS.txt` 23 项复算；`MANIFEST.json` 6 文件 sha256 与字节数、3 条 `source_sha256`、3 条 `results_csv_sha256` | 通过 | 23/23；18/18 |
| 2 | 文本数字对照 STATISTICS.json（读实际文本） | 通过 | 384/384；白名单 129；未映射 0 |
| 3 | 勘误脚本运行至 `results/erratum/`，输出 `OFFLINE_SENSITIVITY_AUDIT_PASS`、23 文件通过（`erratum_output.json` sha256 `b24fd99a35fdd06380e0b250b8cafe40ef3d94d5a2dc4550dcdc46662bc747c5`，与首次核对相同）；单元测试 4 项 OK；独立代码从 `logits.npz`（12 个数组，共 48,000 行×800）取 margin：≤0.008 为 63/80/47，≤0.004 为 29/36/23，与 NUMERIC_ERRATUM.md（本次从文本解析）、STATISTICS.json 及勘误输出一致；argmax 与 `results.csv` 一致；总体/mixed/clean 配对 Acc 差与 NLL 改善与 STATISTICS.json 及勘误输出在 1e−12 内一致 | 通过 | 全部一致 |
| 4 | 离线重算（§4 命令，`--output` 指向 `results/p09-recompute/`）：STATISTICS.json 2,138 个叶值仅 `computed_utc` 不同（重算 `2026-09-27T07:58:52.891727+00:00`），去掉该字段后完全相同；REPORT.md 仅第 3 行时间戳不同；paired_strata.csv sha256 相同。重算 STATISTICS.json sha256 `3d14ba43f38835b69246361d0dd8d4bd42dd203889dc38bacbcb9bea2a990222`，REPORT.md `5ac67a1eb9b000ab80c1b2323e5ebb466d6682de5ef476f0cff30df483a04eb9` | 通过 | 差异字段 1（时间戳） |
| 5 | 图件重生成到 `results/figs/`（目录事先不存在，脚本拒绝覆盖）：3 个 PNG sha256 与交付版相同、像素差 0；3 个 PDF 字节数相同，仅 `/CreationDate` 不同（`D:20260927165856+09'00'`、`…165901…`、`…165906…` 对交付 `D:20260920133610+09'00'` 等），掩去后逐字节相同；再生成 PDF sha256 `ff6935895c3f7938815b24f087617d8b7d2b1762ffb19c4c6ea4ecf6b9af2422`、`10ca6fba7fda6bc414baf726230e9c82d7e5932233a6d6e5303d555187990053`、`9d38040dfef7417abb53dd15956863a65158c27427659a65f43a16758f779f2d`；MANIFEST 条目除路径与 PDF sha 外相同 | 通过 | PNG 3/3；PDF 3/3 |
| 6 | 作业事实 13 条（首次 10 条加 9.2 所述 3 条）全部一致；三份文档相对链接 26 个全部可达（首次 23 个，新增 P10 §5 E0 台账、P10 §7 与 FIGURES.md 更正记录指向本文件） | 通过 | 13/13；26/26 |
| 7 | 图件属性：FIGURES.md 标题解析尺寸 180×120、180×105、180×62 mm 与 MANIFEST 一致；PNG 8-bit RGB 无 alpha、pHYs 599.9988 dpi、像素 4251×2834、4251×2480、4251×1464（偏差 ≤1 px）；PDF 单页 510.24×340.16、510.24×297.64、510.24×175.75 pt 即 180.0×120.0、180.0×105.0、180.0×62.0 mm；字体 ArialMT 与 Arial-BoldMT 为 Type0/CIDFontType2 嵌入 FontFile2，`pdffonts` 报 CID TrueType、已嵌入、子集化；FIGURES.md 的“600 dpi”“不透明 RGB”“TrueType（Type 42）”“180 mm 宽”表述均在 | 通过 | 3 图×5 属性 |

### 9.5 交付 SHA 清单

`r0-verification-20260927/SHA256SUMS_delivery.txt`（57 项，路径相对项目根，`shasum -a 256 -c` 全部 OK；本文件 sha256 `4486286eb6a5add2405273d23f66587463b365d7fb0a31d1d6fe0d76ac30b879`，9,343 字节）覆盖：`P10_delivery.md`、`NUMERIC_ERRATUM.md`、`figures/FIGURES.md`、`SHA256SUMS.txt`、`figures/MANIFEST.json`、6 个图件、`p10_figures.py`、`p09_statistics.py`、`numeric_sensitivity_erratum.py`，以及本目录全部脚本与 `results/` 全部文件（43 个）。它不含 `R0_DELIVERY_VERIFICATION.md`（本文件引用该清单，二者不能互相包含），也不改动原 `SHA256SUMS.txt`。因 `results/` 内含时间戳（`computed_utc`、PDF `/CreationDate`），每次重跑后 `results/` 与该清单的 sha 会变，交付文本与图件的条目不变。

本目录脚本（sha256，字节数）：`common.py` `72737de2d32df34a9222f8c044c1dd2c2fe15524c37ecae5b110c0975e299633`（3,098）；`check1_sha.py` `a73e5f90fa966c79b15f8af307c80d2c2d2af03528c3713a8a500d5564ec2ed6`（3,103）；`check2_numbers.py` `36b1cc707741df83db4c97621b6ac6f5e156fb36e7281d3ca1bd5de2aefa75b1`（45,574）；`check2_sensitivity_oldtext.py` `933de7196965bcb32b712533afdc6692ff3b23bcf7ea6684f6aef427f2d15224`（3,856）；`check3_erratum_independent.py` `a18a6f09b9d2070ab7c22bceb884ea2a625eb85b10cc59b95b6018f1e47c632c`（5,301）；`check4_recompute_diff.py` `66a6723f91e2ce111c4f35719ecf66ed16d6474694ff1de9857feeef6fd0c1d2`（3,426）；`check5_figdiff.py` `0661aa4617091c141d7c536388368bf250f6addfa555cf7b16c0e31869ec5a3e`（3,578）；`check6_jobfacts_links.py` `ad3582d5803e214b3a132b79cf9914bdaf5578695074e0e80d1ce45e4cd7df55`（7,827）；`check7_figprops.py` `95985db65da3bfcd043f52b0e1f3090d08f8177a019c42d8d8f1a4388e084623`（4,874）；`make_sha256sums_delivery.py` `18e2d7f82efde26fbf1996875d7cd75e751a17e9438bd0b3502f108c99382b33`（1,523）；`run_all.sh` `0ccf7e3803fcf585ce149cc05720ca7b0751e8f0a9231a5f58a63fd8540da00e`（2,475）。结果文件见清单。

### 9.6 复现命令

在工作区根目录 `/Users/gigi/发表/超算` 执行；整套约 2 分钟，全部本地只读，不写 `figures/`。`results/p09-recompute/` 与 `results/figs/` 由上游脚本以“不存在才创建”的方式写出，重跑前须先删除 `results/`（或至少这两个子目录）。

```bash
sh docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927/run_all.sh
# 逐步等价：
D=docs/superpowers/evidence/p10-delivery-20260919/r0-verification-20260927; PY=/opt/anaconda3/envs/audattn/bin/python
mkdir -p $D/results/erratum
$PY -I -B checkpoint_compare_workflow_20260917/numeric_sensitivity_erratum.py > $D/results/erratum/erratum_output.json
$PY -I -B checkpoint_compare_workflow_20260917/tests/test_numeric_sensitivity_erratum.py
$PY -I -B checkpoint_compare_workflow_20260917/p09_statistics.py \
  --archive "$PWD/docs/superpowers/evidence/p08full-production-20260919-r2/frozen/collect-vvv4ed4a/collected/received/full10k" \
  --receipt-sha256 21a42644fd60e73a3668fd07cfe656a49b8ca95635438fd23ef6c7b92b8881ab \
  --output "$PWD/$D/results/p09-recompute"
$PY -I -B checkpoint_compare_workflow_20260917/p10_figures.py \
  --statistics "$PWD/docs/superpowers/evidence/p09-statistics-20260919/STATISTICS.json" --output "$PWD/$D/results/figs"
for c in check1_sha check2_numbers check3_erratum_independent check4_recompute_diff check5_figdiff check6_jobfacts_links check7_figprops check2_sensitivity_oldtext; do
  $PY -I -B $D/$c.py; done
$PY -I -B $D/make_sha256sums_delivery.py
shasum -a 256 -c $D/SHA256SUMS_delivery.txt
```
