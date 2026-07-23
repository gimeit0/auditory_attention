"""
生成导师汇报 PPTX(中文 + 日语两版, 16:9, 嵌入 Fig 2b)。
已去掉 Fig 2e 页, 并移除仅与混淆相关的文字, 保持全篇只讲 Fig 2b。
数字均来自已核实的实验结果。

用法: python make_ppt.py   # 生成 复现汇报.pptx 和 复现汇报_ja.pptx
"""
from pptx import Presentation
from pathlib import Path
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
FIG2B = str(EXPERIMENT_DIR / "figures/fig2b_reproduction_en.png")
PRESENTATIONS = EXPERIMENT_DIR / "presentations"

COL = {"dark": RGBColor(0x00, 0x00, 0x00), "grey": RGBColor(0x55, 0x55, 0x55),
       "red": RGBColor(0xc0, 0x39, 0x2b), None: None}


def _set(run, size, font, bold=False, color=None):
    run.font.name = font                 # 拉丁字体 a:latin
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    # 同时设东亚字体 a:ea 和 a:cs, 保证日文/中文字形也用该字体
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", font)


def build(slides, font, outfile):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    BLANK = prs.slide_layouts[6]

    for spec in slides:
        kind = spec[0]
        s = prs.slides.add_slide(BLANK)
        if kind == "title":
            _, title, subs = spec
            tb = s.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.7), Inches(1.4))
            r = tb.text_frame.paragraphs[0].add_run(); r.text = title
            _set(r, 34, font, bold=True, color=COL["dark"])
            tb2 = s.shapes.add_textbox(Inches(0.8), Inches(4.1), Inches(11.7), Inches(1.8))
            for i, line in enumerate(subs):
                p = tb2.text_frame.paragraphs[0] if i == 0 else tb2.text_frame.add_paragraph()
                r = p.add_run(); r.text = line
                _set(r, 16, font, color=COL["grey"])
        elif kind == "bullets":
            _, title, bullets = spec
            tb = s.shapes.add_textbox(Inches(0.7), Inches(0.45), Inches(12), Inches(1.0))
            r = tb.text_frame.paragraphs[0].add_run(); r.text = title
            _set(r, 26, font, bold=True, color=COL["dark"])
            body = s.shapes.add_textbox(Inches(0.9), Inches(1.55), Inches(11.6), Inches(5.5))
            tf = body.text_frame; tf.word_wrap = True
            for i, item in enumerate(bullets):
                text, level = item[0], item[1]
                ckey = item[2] if len(item) > 2 else None
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.level = level; p.space_after = Pt(6)
                mark = "• " if level == 0 else ("– " if level == 1 else "· ")
                r = p.add_run(); r.text = mark + text
                _set(r, 19 - level*2, font, bold=(level == 0 and ckey is not None), color=COL[ckey])
        elif kind == "audio":
            _, title, subtitle, items = spec
            tb = s.shapes.add_textbox(Inches(0.7), Inches(0.4), Inches(12), Inches(0.8))
            r = tb.text_frame.paragraphs[0].add_run(); r.text = title
            _set(r, 25, font, bold=True, color=COL["dark"])
            sb = s.shapes.add_textbox(Inches(0.7), Inches(1.2), Inches(12), Inches(0.6))
            r = sb.text_frame.paragraphs[0].add_run(); r.text = subtitle
            _set(r, 15, font, color=COL["grey"])
            # items: list of (rows). 每个 (path, label, x_in, y_in)
            for path, label, x, y in items:
                s.shapes.add_movie(path, Inches(x), Inches(y), Inches(1.0), Inches(1.0),
                                   mime_type="audio/wav")
                lb = s.shapes.add_textbox(Inches(x - 0.5), Inches(y + 1.02), Inches(2.0), Inches(0.4))
                lb.text_frame.word_wrap = True
                p = lb.text_frame.paragraphs[0]; p.alignment = 2  # center
                r = p.add_run(); r.text = label
                _set(r, 12, font, color=COL["dark"])
        elif kind == "image":
            _, title, img, caption = spec
            tb = s.shapes.add_textbox(Inches(0.7), Inches(0.4), Inches(12), Inches(0.9))
            r = tb.text_frame.paragraphs[0].add_run(); r.text = title
            _set(r, 25, font, bold=True, color=COL["dark"])
            s.shapes.add_picture(img, Inches(0.6), Inches(1.5), height=Inches(5.4))
            cap = s.shapes.add_textbox(Inches(7.9), Inches(1.8), Inches(5.0), Inches(5.0))
            tf = cap.text_frame; tf.word_wrap = True
            for i, (text, ckey) in enumerate(caption):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.space_after = Pt(8)
                r = p.add_run(); r.text = text
                _set(r, 15, font, color=COL[ckey])
    prs.save(outfile)
    print(f"已生成: {outfile}")


# =================== 中文内容 ===================
ZH = [
 ("title", "选择性听觉注意力模型 —— 行为趋势复现",
  ["复现论文: Griffith, Hess & McDermott (2026), Nature Human Behaviour",
   "\"Optimized feature gains explain and predict human selective listening\"",
   "汇报人: [你的名字]      日期: 2026-07"]),
 ("bullets", "本次发表的目的", [
   ("报告: 用论文(Griffith et al. 2026)作者的预训练模型, 在自建 Common Voice 评测集上,", 0),
   ("能否复现其行为趋势(Fig 2b: 准确率随信噪比、干扰说话人性别的变化)", 1),
   ("两个核心问题:", 0, "dark"),
   ("① 模型是否真能识别混音中目标说话人的中间词?", 1),
   ("② 准确率对信噪比、异性/同性干扰的依赖趋势, 是否与论文方向一致?", 1),
   ("本次定位: 不训练模型, 用作者参数做验证实验; 评的是趋势方向, 不追求数值一致", 0, "red"),
   ("本次实验成功的意义:", 0, "dark"),
   ("说明作者模型能泛化到未见过的语料(Common Voice) —— 模型稳健性/一般性的旁证", 1),
   ("确认自建评测管线正确可用 —— 成为后续扩展(其他条件、自有研究)的基础", 1),
   ("论文主要行为学结论被独立复现, 提升结论可信度(追试价值)", 1)]),
 ("bullets", "一、研究背景与复现目标", [
   ("论文: 一个带\"特征增益\"注意力机制的神经网络, 模拟人类\"鸡尾酒会\"听觉", 0),
   ("给模型一段目标说话人语音(cue) + 一段\"目标+干扰\"混音 → 报出混音中目标说话人的中间词", 1),
   ("模型据 cue 放大目标音色对应的特征、压制其余, 把目标从混音里分出来", 1),
   ("论文 Figure 2 用行为曲线展示识别成败的规律(信噪比↑越准; 异性干扰比同性易分离等)", 1),
   ("我的复现目标(验证性任务):", 0, "dark"),
   ("① 验证模型有效性: 用作者预训练模型, 在自建评测语料上确认能识别目标中间词", 1),
   ("② 复现 Fig 2b 趋势: 同性/异性干扰下, 准确率随信噪比的变化", 1),
   ("判据: 趋势方向与论文一致即成功, 不追求数值复刻(语料/说话人不同)", 1, "red")]),
 ("bullets", "一(补)、与作者做法的异同 —— 我做了什么、怎么做的", [
   ("与作者相同(直接沿用):", 0, "dark"),
   ("模型与预训练参数 / 任务定义(cue+混音→中间词) / 评测框架(SNR、同性/异性) / 评分口径", 1),
   ("与作者不同 = 我独立完成的工作:", 0, "dark"),
   ("作者的输入数据(训练/评测刺激音频)未公开 → 必须从零自建评测集", 1, "red"),
   ("① 从 Common Voice v9 筛选说话人与录音(性别均衡、说话人分离)", 1),
   ("② 用强制对齐估计每个词的时间边界(CV 没有这个信息)", 1),
   ("③ 按 800 词表 + 时间余量条件选定目标词(锚点)", 1),
   ("④ 构造 cue/目标/干扰三元组, 6档SNR混音(within-item)、RMS归一、diotic", 1),
   ("要点: 不是\"直接跑作者的数据\", 而是\"用自建评测集去验证作者的模型\"", 0, "red")]),
 ("bullets", "二、数据准备", [
   ("语料: Common Voice 9.0 英语(与论文同版本)", 0),
   ("筛选: 有性别标注、标注一致、名下≥2条录音 → 可用池 18,067人 / 971,848条", 1),
   ("目标词表: 作者公开的 800 词(字节级等同官方); 模型是 800 类分类器", 0),
   ("最终评测集: 600 个有效 target 样本", 0, "dark"),
   ("性别精确平衡: 男 300 / 女 300", 1),
   ("来自 149 个说话人、347 条录音, 覆盖 369 个不同目标词", 1),
   ("600 样本足以让 6 档信噪比每档估计稳定(二项标准误约 ±2%)", 1)]),
 ("bullets", "三、方法管线", [
   ("原始录音 → 强制对齐 → 文本规范化 → 锚点判定 → 切片+混音 → 喂模型 → 评分", 0, "dark"),
   ("1. 强制对齐(MMS_FA, 16kHz): 拿到每个词的起止时间(CV 只给整句, 无词级时间戳)", 0),
   ("2. 文本规范化: 复刻论文 convert_transcript(小写/去标点/数字转词)", 0),
   ("3. 锚点(中间词)判定: 以目标词为中心。条件=∈词表 & 词长<2s & 前后各留≥1.25s", 0),
   ("4. 切片+混音: 每样本切 2.5s@44.1kHz(内部取中间2s); within-item 6档SNR重混", 0),
   ("SNR: -9/-6/-3/0/+3/+inf dB; 按目标能量缩放干扰; +inf=无干扰; RMS归一0.02; diotic双耳同音", 1),
   ("5. 加载作者预训练 checkpoint(word_task_v10) 直接推理, 不训练、不微调", 0)]),
 ("bullets", "三(续)、三个关键工程决策 —— \"为什么这么做\"", [
   ("① 文本规范化时保留撇号", 0, "dark"),
   ("论文公开代码删撇号, 但 800 词表有 16 个带撇号缩写(can't/don't...); 删了会漏掉、对不上", 1),
   ("② 以\"目标词为中心\"切片, 而非取录音中点的词", 0, "dark"),
   ("读论文源码确认: 先选目标词、再以它为中心切片(不是先切片再看中点压到哪个词)", 1),
   ("③ 锚点优先配对(先对齐后配对)", 0, "dark"),
   ("只对齐目标候选、留有锚点的录音当 target: 627条录音产出600样本(96%), 远高于旧法22%", 1)]),
 ("bullets", "四、结果(1): 模型有效性验证", [
   ("clean 条件(纯目标、无干扰)下的中间词识别准确率:", 0),
   ("88.6%   (随机基线仅 0.1% = 1/800)", 0, "dark"),
   ("完整 600 样本的 +inf 档也得到 88.0%, 互相印证", 1),
   ("→ 模型确实能从语音中识别目标中间词, 远高于随机", 0, "red"),
   ("这是后续所有趋势实验的前提", 1, "grey")]),
 ("image", "四、结果(2): Fig 2b 复现 —— 同性 vs 异性干扰", FIG2B, [
   ("同性/异性两条线: 中间词识别准确率 vs 信噪比", "dark"),
   ("复现的趋势(与论文一致):", "red"),
   ("① 准确率随信噪比单调上升(干扰越弱越准)", "grey"),
   ("② 异性干扰整体高于同性(高9~18个百分点)", "grey"),
   ("③ +inf(无干扰)两线收敛到~88%: 无干扰时性别不起作用", "grey"),
   ("异性>同性差异稳定: 5个有干扰档误差棒全不重叠(3.4~6.8σ)", "dark"),
   ("误差棒 = ±1 SEM", "grey")]),
 ("audio", "四(补): 音频示例 —— SNR 阶梯(点击播放)",
  "同一段刺激(目标词 around)在 6 档 SNR 下的混音: 从 -9dB 到无干扰, 干扰说话人逐渐消失、目标越来越清楚",
  [("export_audio/t0000_same/mix_-9dB.wav", "-9 dB", 1.0, 2.5),
   ("export_audio/t0000_same/mix_-6dB.wav", "-6 dB", 3.0, 2.5),
   ("export_audio/t0000_same/mix_-3dB.wav", "-3 dB", 5.0, 2.5),
   ("export_audio/t0000_same/mix_+0dB.wav", "0 dB", 7.0, 2.5),
   ("export_audio/t0000_same/mix_+3dB.wav", "+3 dB", 9.0, 2.5),
   ("export_audio/t0000_same/mix_inf.wav", "+inf(无干扰)", 11.0, 2.5),
   ("export_audio/t0000_same/cue.wav", "cue(提示音)", 3.0, 5.0),
   ("export_audio/t0000_same/target_clean.wav", "纯目标(参照)", 8.0, 5.0)]),
 ("bullets", "四(补)、对本次两个问题的回答", [
   ("问题①: 模型能识别混音中目标说话人的中间词吗?", 0, "dark"),
   ("→ 能。clean 条件 88.6%(随机 0.1%); 混音下从 -9dB 的 26% 到 +inf 的 88%, 始终有效", 1),
   ("问题②: 准确率对 SNR、干扰说话人性别的依赖趋势与论文一致吗?", 0, "dark"),
   ("→ 一致。SNR↑准确率↑(单调); 异性>同性(各档误差棒不重叠); 无干扰时收敛", 1),
   ("两个问题都为肯定 → 行为趋势方向与论文一致, 复现成功", 0, "red")]),
 ("bullets", "五、关键判断与诚实说明", [
   ("严格复刻论文: 800词表、对齐思路、目标词中心切片、6档SNR、within-item、评分口径、直接用作者参数", 0),
   ("我因实际情况做的调整(不改变科学设定):", 0, "dark"),
   ("保留撇号(否则缩写词对不上词表) / 锚点优先配对(效率) / 在 M1 CPU 上运行", 1),
   ("当前范围与局限:", 0, "dark"),
   ("范围为单人语音干扰、diotic(非空间); 未做其他干扰类型、harmonicity、空间实验", 1),
   ("样本量600、CPU单次扫描约6.5h; 后续可上 hakusan GPU 扩展", 1),
   ("数值不与论文相同属预期: 语料/说话人/词都不同, 判的是趋势方向", 1, "red")]),
 ("bullets", "六、结论", [
   ("用作者公开的预训练模型, 在自建 Common Voice 评测集(600样本, 性别平衡)上:", 0),
   ("① 模型有效性确认: clean 准确率 88.6%, 远高于随机 0.1%", 0, "dark"),
   ("② Fig 2b 行为趋势成功复现(方向一致):", 0, "dark"),
   ("准确率随SNR单调上升; 异性干扰优于同性; 无干扰时收敛", 1),
   ("我们完成的是\"趋势复现\", 而非对论文科学结论真伪的再验证; 数值不追求与论文相同", 0, "red")]),
 ("bullets", "七、后续工作", [
   ("上 hakusan GPU: 推理快几十倍, 可扩大样本量、补做其他面板", 0),
   ("扩展面板: Fig 2c(普通话干扰)、Fig 2d/2e(混淆分析, 大部分可复用现有数据后处理)", 0),
   ("(可选) 其他干扰类型/空间实验: 需额外资源(AudioSet/HRTF), 超出当前范围", 0, "grey")]),
 ("bullets", "总结 (まとめ)", [
   ("目的: 用作者预训练模型 + 自建 CV 评测集, 检验能否复现 Fig 2b 行为趋势", 0),
   ("方法: 强制对齐 → 以目标词为中心切片 → 6档SNR混音 → 作者checkpoint推理(600样本, 性别平衡)", 0),
   ("结果:", 0, "dark"),
   ("① 模型有效性确认: clean 准确率 88.6% ≫ 随机 0.1%", 1),
   ("② Fig 2b 趋势复现: 信噪比↑准确率↑; 异性干扰 > 同性; 无干扰时收敛", 1),
   ("结论: 趋势方向与论文一致 → 复现成功(趋势复现, 非论文真伪验证)", 0, "red"),
   ("下一步:", 0, "dark"),
   ("① 上 hakusan GPU 大规模化(增样本, 补 Fig 2c/2d/2e 等面板)", 1),
   ("② 干扰改对称构造, 使混淆(confusion)绝对量接近论文", 1),
   ("③ (发展) 验证发达参数α等自有扩展", 1)]),
]

# =================== 日语内容 ===================
JA = [
 ("title", "選択的聴覚注意モデル —— 行動傾向の再現",
  ["再現対象論文: Griffith, Hess & McDermott (2026), Nature Human Behaviour",
   "\"Optimized feature gains explain and predict human selective listening\"",
   "発表者: [氏名]      日付: 2026-07"]),
 ("bullets", "本発表の目的", [
   ("本発表では、論文(Griffith et al., 2026)の著者が公開した事前学習モデルを用い、", 0),
   ("自作のCommon Voice評価セット上で、その行動的傾向(Fig 2b)を再現できるかを検証・報告する", 1),
   ("本発表で答える2つの問い:", 0, "dark"),
   ("① モデルは混合音声中の目標話者の中央単語を実際に認識できるか", 1),
   ("② 正答率のSN比および妨害話者の性別への依存傾向は、論文と方向が一致するか", 1),
   ("位置づけ: モデルの再学習は行わず、著者のパラメータをそのまま用いた検証実験。評価対象は傾向の方向であり、数値の一致は求めない", 0, "red"),
   ("本再現が成功する意義:", 0, "dark"),
   ("著者モデルが未知のコーパス(Common Voice)にも汎化することを示せる —— モデルの頑健性・一般性の傍証", 1),
   ("自作の評価パイプラインが正しく機能することを確認 —— 今後の拡張(他条件・独自研究)の基盤になる", 1),
   ("論文の主要な行動的知見が独立に再現され、知見の信頼性(追試価値)を高める", 1)]),
 ("bullets", "一、研究背景と再現目標", [
   ("論文: 「特徴ゲイン」型の注意機構をもつニューラルネットワークで、人間の「カクテルパーティー」聴取を模擬したモデル", 0),
   ("目標話者の手がかり音声(cue)と「目標+妨害」の混合音声を入力し、混合音声中の目標話者の中央単語を答えさせる", 1),
   ("cueに基づいて目標の音色に対応する特徴を増強し、それ以外を抑制することで、目標を混合音声から分離する", 1),
   ("論文Figure 2は、認識の成否を規定する要因を行動曲線で示す(SN比が高いほど正答率↑、異性妨害は同性より分離しやすい 等)", 1),
   ("本再現の目標:", 0, "dark"),
   ("① モデルの有効性検証: 著者の事前学習モデルが、自作の評価音声上で中央単語を認識できることを確認する", 1),
   ("② Fig 2bの傾向の再現: 同性/異性妨害の下での正答率のSN比依存性を再現する", 1),
   ("判定基準: 傾向の方向が論文と一致すれば成功とする。数値の完全一致は求めない(コーパスや話者が論文と異なるため)", 1, "red")]),
 ("bullets", "一(補)、著者の手法との異同 —— 私は何を・どう行ったか", [
   ("著者と同じ点(そのまま踏襲):", 0, "dark"),
   ("モデル本体と学習済みパラメータ / タスク定義(cue+混合音声→中央単語) / 評価の枠組み(SN比・同性/異性) / 採点基準", 1),
   ("著者と異なる点 = 私が独自に行った作業:", 0, "dark"),
   ("著者の入力データ(学習・評価用の刺激音声)は非公開 → 評価セットを一から自作する必要があった", 1, "red"),
   ("① Common Voice v9 から話者・録音を選別(性別均衡・話者分離)", 1),
   ("② 強制アライメントで各単語の時間境界を推定(CVには無い情報)", 1),
   ("③ 800語彙・時間余白の条件で目標単語(アンカー)を選定", 1),
   ("④ cue/目標/妨害の三つ組を構成し、6段階SN比で混合(within-item)・RMS正規化・diotic化", 1),
   ("要点: 「著者のデータをそのまま流用した」のではなく、著者のモデルを私が独自に構築した評価セットで検証した", 0, "red")]),
 ("bullets", "二、データ準備", [
   ("コーパス: Common Voice 9.0 英語版(論文と同一バージョン)", 0),
   ("選別: 性別ラベルがあり一貫し、かつ2録音以上をもつ話者 → 利用可能 18,067名 / 971,848録音", 1),
   ("目標語彙: 著者公開の800語(公式ファイルとバイト単位で一致)。モデルは800クラスの分類器", 0),
   ("最終評価セット: 有効な目標サンプル600件", 0, "dark"),
   ("性別を厳密に均衡: 男性300 / 女性300", 1),
   ("149名の話者・347録音に由来し、369種の異なる目標単語を含む", 1),
   ("600サンプルにより、6段階のSN比それぞれで推定が安定(二項標準誤差 約±2%)", 1)]),
 ("bullets", "三、手法パイプライン", [
   ("原音声 → 強制アライメント → テキスト正規化 → アンカー判定 → 切り出し・混合 → モデル入力 → 採点", 0, "dark"),
   ("1. 強制アライメント(MMS_FA, 16kHz): 各単語の時間境界を取得(CVは文単位の書き起こしのみで、単語の時刻をもたない)", 0),
   ("2. テキスト正規化: 論文のconvert_transcriptに準拠(小文字化・記号除去・数字の単語化)", 0),
   ("3. アンカー(中央単語)判定: 目標単語を中心とする。条件=語彙内 かつ 単語長<2s かつ 前後に各1.25s以上の余白", 0),
   ("4. 切り出し・混合: 各2.5s@44.1kHz(モデル内部で中央2sを使用)。within-itemで6段階のSN比に再混合", 0),
   ("SN比: -9/-6/-3/0/+3/+inf dB。目標のエネルギーに合わせて妨害を調整。+inf=妨害なし。RMS 0.02に正規化。diotic(両耳同一)", 1),
   ("5. 著者の事前学習チェックポイント(word_task_v10)でそのまま推論。再学習・微調整は行わない", 0)]),
 ("bullets", "三(続)、3つの重要な工学的判断 —— 「なぜそうしたか」", [
   ("① テキスト正規化でアポストロフィを保持する", 0, "dark"),
   ("論文の公開コードはアポストロフィを削除するが、800語彙には16個の短縮形(can't/don't 等)が含まれる。削除すると語彙照合に失敗し脱落してしまう", 1),
   ("② 「録音の中点の単語」ではなく「目標単語を中心」に切り出す", 0, "dark"),
   ("論文のソースコードで確認: まず目標単語を選び、それを中心に切り出す(先に切り出してから中点の単語を見るのではない)", 1),
   ("③ アンカー優先のペアリング(先にアライメント、後にペアリング)", 0, "dark"),
   ("目標候補のみを整列し、アンカーをもつ録音を目標に採用。627録音から600サンプル(96%)を得て、旧手法の22%を大きく上回る", 1)]),
 ("bullets", "四、結果(1): モデル有効性の検証", [
   ("clean条件(目標のみ・妨害なし)における中央単語認識の正答率:", 0),
   ("88.6%   (偶然水準は0.1% = 1/800)", 0, "dark"),
   ("600サンプルの+inf条件でも88.0%となり、相互に裏付けられる", 1),
   ("→ モデルは音声から目標の中央単語を実際に認識でき、偶然水準を大きく上回る", 0, "red"),
   ("これが以降の傾向実験の前提となる", 1, "grey")]),
 ("image", "四、結果(2): Fig 2b 再現 —— 同性 vs 異性妨害", FIG2B, [
   ("同性/異性の2本の線: 中央単語認識の正答率 vs SN比", "dark"),
   ("再現された傾向(論文と一致):", "red"),
   ("① SN比とともに正答率が単調に増加(妨害が弱いほど正答↑)", "grey"),
   ("② 異性妨害が全体的に同性より高い(9~18ポイント)", "grey"),
   ("③ +inf(妨害なし)で2本の線が約88%に収束: 妨害がなければ性別は無関係", "grey"),
   ("異性>同性の差は安定: 妨害ありの5段階すべてでエラーバーが非重複(3.4~6.8σ)", "dark"),
   ("エラーバー = ±1 SEM", "grey")]),
 ("audio", "四(補): 音声サンプル —— SN比ラダー(クリックで再生)",
  "同一刺激(目標単語「around」)の6段階SN比混合。-9dBから妨害なしへ進むと、妨害話者が徐々に消え目標が明瞭になる",
  [("export_audio/t0000_same/mix_-9dB.wav", "-9 dB", 1.0, 2.5),
   ("export_audio/t0000_same/mix_-6dB.wav", "-6 dB", 3.0, 2.5),
   ("export_audio/t0000_same/mix_-3dB.wav", "-3 dB", 5.0, 2.5),
   ("export_audio/t0000_same/mix_+0dB.wav", "0 dB", 7.0, 2.5),
   ("export_audio/t0000_same/mix_+3dB.wav", "+3 dB", 9.0, 2.5),
   ("export_audio/t0000_same/mix_inf.wav", "+inf(妨害なし)", 11.0, 2.5),
   ("export_audio/t0000_same/cue.wav", "cue(手がかり音)", 3.0, 5.0),
   ("export_audio/t0000_same/target_clean.wav", "目標のみ(参照)", 8.0, 5.0)]),
 ("bullets", "四(補)、本発表の2つの問いへの回答", [
   ("問い①: モデルは目標話者の中央単語を認識できるか?", 0, "dark"),
   ("→ 認識できる。clean条件で正答率88.6%(偶然0.1%)。混合音声下でも-9dBの26%〜+infの88%まで一貫して機能", 1),
   ("問い②: 正答率のSN比・妨害話者性別への依存傾向は論文と一致するか?", 0, "dark"),
   ("→ 一致する。SN比↑で正答率↑(単調増加)、異性妨害>同性(全SN比でエラーバー非重複)、妨害なしで収束", 1),
   ("いずれの問いも肯定 → 行動的傾向は論文と方向が一致し、再現に成功", 0, "red")]),
 ("bullets", "五、重要な判断と誠実な補足", [
   ("論文を厳密に踏襲した点: 800語彙・アライメント方針・目標単語中心の切り出し・6段階SN比・within-item・採点基準・著者パラメータの使用", 0),
   ("実情に応じて調整した点(科学的な設定は変更しない):", 0, "dark"),
   ("アポストロフィの保持(短縮形照合のため)/ アンカー優先ペアリング(効率化)/ M1 CPU上での実行", 1),
   ("現在の範囲と限界:", 0, "dark"),
   ("範囲は単一話者の音声妨害・diotic(非空間)。他の妨害種・harmonicity・空間実験は未実施", 1),
   ("サンプル数600、CPUでの1回の走査は約6.5時間。今後hakusan GPUで拡張可能", 1),
   ("数値が論文と異なるのは想定内: コーパス・話者・単語が異なるため。判定はあくまで傾向の方向", 1, "red")]),
 ("bullets", "六、結論", [
   ("著者公開の事前学習モデルを用い、自作のCommon Voice評価セット(600サンプル、性別均衡)上で:", 0),
   ("① モデルの有効性を確認: clean正答率88.6%で、偶然水準0.1%を大きく上回る", 0, "dark"),
   ("② Fig 2bの行動傾向の再現に成功(方向が一致):", 0, "dark"),
   ("正答率はSN比とともに単調に増加、異性妨害が同性より優位、妨害なしで収束", 1),
   ("本研究は「傾向の再現」であり、論文の科学的結論の真偽を再検証するものではない。数値の一致は求めない", 0, "red")]),
 ("bullets", "七、今後の課題", [
   ("hakusan GPU: 推論が数十倍に高速化し、サンプル数の増加や他パネルの追加が可能になる", 0),
   ("パネル拡張: Fig 2c(中国語妨害)、Fig 2d/2e(混同分析。大部分は既存データの後処理で対応可能)", 0),
   ("(任意) 他の妨害種・空間実験: 追加資源(AudioSet/HRTF)が必要で、現在の範囲外", 0, "grey")]),
 ("bullets", "まとめ", [
   ("目的: 著者の事前学習モデルと自作CV評価セットを用い、Fig 2bの行動傾向を再現できるかを検証した", 0),
   ("方法: 強制アライメント → 目標単語中心の切り出し → 6段階SN比で混合 → 著者チェックポイントで推論(600サンプル、性別均衡)", 0),
   ("結果:", 0, "dark"),
   ("① モデルの有効性を確認: clean正答率 88.6% ≫ 偶然水準 0.1%", 1),
   ("② Fig 2bの傾向を再現: SN比↑で正答↑、異性妨害 > 同性、妨害なしで収束", 1),
   ("結論: 傾向の方向が論文と一致 → 再現に成功(傾向の再現であり、論文の真偽検証ではない)", 0, "red"),
   ("次にやること:", 0, "dark"),
   ("① hakusan GPUで大規模化(サンプル増、Fig 2c/2d/2e など他パネルの追加)", 1),
   ("② 妨害も対称構成にし、混同(confusion)の絶対量を論文水準に近づける", 1),
   ("③ (発展) 発達パラメータαなど、独自拡張の検証へ進む", 1)]),
]

build(ZH, "PingFang SC", PRESENTATIONS / "复现汇报.pptx")
build(JA, "Meiryo", PRESENTATIONS / "复现汇报_ja.pptx")
