"""
Group-meeting deck (English, ~15 min): reproducing selective-listening trends —
Part 1 distractor sex (done) + Part 2 number of distractors (new results).
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

PROJ = "/Users/gigi/projects/auditory_attention"
RESD = "/Users/gigi/论文/主课题/多话者复现实验 结果"
OUT = os.path.join(RESD, "group_meeting_selective_listening_FINAL_EN.pptx")

FIG2A = os.path.join(PROJ, "fig2a_reproduction_en.png")
FIG2B = os.path.join(PROJ, "fig2b_reproduction_en.png")
FIG2E = os.path.join(PROJ, "fig2e_reproduction_en.png")
FIGMT = os.path.join(RESD, "fig_multi_talker_final.png")
FIGISSN = os.path.join(RESD, "fig_issn_information_masking_final.png")

INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTE = RGBColor(0x5B, 0x5B, 0x64)
ACC = RGBColor(0x9C, 0x2E, 0x6D)      # 论文洋红
ACC2 = RGBColor(0x1F, 0x3B, 0x73)     # 深蓝
GOOD = RGBColor(0x1E, 0x7A, 0x46)
BG = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT = RGBColor(0xF3, 0xEE, 0xF2)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    r = s.shapes.add_shape(1, 0, 0, SW, SH)
    r.fill.solid(); r.fill.fore_color.rgb = BG; r.line.fill.background()
    r.shadow.inherit = False
    s.shapes._spTree.remove(r._element); s.shapes._spTree.insert(2, r._element)
    return s


def box(s, x, y, w, h, anchor=MSO_ANCHOR.TOP):
    tb = s.shapes.add_textbox(x, y, w, h); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    return tb, tf


def para(tf, txt, size, color=INK, bold=False, align=PP_ALIGN.LEFT,
         first=False, space_after=6, italic=False, bullet=False, level=0):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align; p.space_after = Pt(space_after); p.level = level
    runs = txt if isinstance(txt, list) else [(txt, color, bold)]
    for i, item in enumerate(runs):
        t, c, b = item
        r = p.add_run(); r.text = ("• " + t if (bullet and i == 0) else t)
        r.font.size = Pt(size); r.font.color.rgb = c; r.font.bold = b
        r.font.italic = italic; r.font.name = "Arial"
    return p


def bar(s, y=Inches(1.02)):
    ln = s.shapes.add_shape(1, Inches(0.7), y, Inches(2.2), Pt(3))
    ln.fill.solid(); ln.fill.fore_color.rgb = ACC; ln.line.fill.background()
    ln.shadow.inherit = False


def header(s, kicker, title):
    _, tf = box(s, Inches(0.7), Inches(0.35), Inches(12), Inches(0.9))
    para(tf, kicker.upper(), 12, ACC, bold=True, first=True, space_after=2)
    para(tf, title, 28, INK, bold=True)
    bar(s)


def pic_fit(s, path, x, y, maxw, maxh):
    from PIL import Image
    iw, ih = Image.open(path).size
    ar = iw / ih; mar = maxw / maxh
    if ar > mar:
        w = maxw; h = int(maxw / ar)
    else:
        h = maxh; w = int(maxh * ar)
    x2 = x + (maxw - w) // 2; y2 = y + (maxh - h) // 2
    s.shapes.add_picture(path, x2, y2, width=w, height=h)


def card(s, x, y, w, h, fill=LIGHT):
    c = s.shapes.add_shape(1, x, y, w, h)
    c.fill.solid(); c.fill.fore_color.rgb = fill; c.line.fill.background()
    c.shadow.inherit = False
    return c


# ============ 1. TITLE ============
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.5), SW, Inches(2.5))
band.fill.solid(); band.fill.fore_color.rgb = LIGHT; band.line.fill.background()
band.shadow.inherit = False
_, tf = box(s, Inches(0.9), Inches(2.7), Inches(11.5), Inches(2.1), MSO_ANCHOR.MIDDLE)
para(tf, "Reproducing Human Selective-Listening Trends", 34, INK, bold=True, first=True, space_after=6)
para(tf, "with a Pretrained Feature-Gain Model", 34, INK, bold=True, space_after=12)
para(tf, "A qualitative replication on a custom Common Voice evaluation set",
     18, ACC, bold=True)
_, tf = box(s, Inches(0.9), Inches(5.3), Inches(11.5), Inches(1.2))
para(tf, "Griffith, Hess & McDermott (2026, Nature Human Behaviour)", 14, MUTE, first=True, space_after=3)
para(tf, "Group meeting · Single pretrained checkpoint · 15–20 min",
     13, MUTE)

# ============ 2. THE QUESTION ============
s = slide()
header(s, "Motivation", "Can a gain-based model explain selective listening?")
_, tf = box(s, Inches(0.7), Inches(1.5), Inches(7.0), Inches(5.3))
para(tf, "The human problem", 18, ACC, bold=True, first=True, space_after=6)
para(tf, [("At a noisy party we can follow ", INK, False),
          ("one voice", INK, True),
          (" and ignore others.", INK, False)], 16, space_after=10)
para(tf, "The model (Griffith et al. 2026)", 18, ACC, bold=True, space_after=6)
para(tf, [("Applies a learned ", INK, False), ("feature gain", INK, True),
          (" that boosts features matching a cue voice and suppresses the rest.",
           INK, False)], 16, space_after=10)
para(tf, "The claim", 18, ACC, bold=True, space_after=6)
para(tf, "One optimized gain mechanism predicts BOTH successes and failures of human listening across many conditions.",
     16, space_after=10)
para(tf, "Our task", 18, ACC, bold=True, space_after=6)
para(tf, [("Feed the ", INK, False), ("authors' pretrained checkpoint", INK, True),
          (" our own Common Voice test set and check whether the ", INK, False),
          ("behavioral trends", INK, True), (" reproduce.", INK, False)], 16)
card(s, Inches(8.0), Inches(1.6), Inches(4.6), Inches(4.6))
_, tf = box(s, Inches(8.3), Inches(1.85), Inches(4.0), Inches(4.1))
para(tf, "The task, per trial", 16, ACC, bold=True, first=True, space_after=8)
para(tf, [("1.  Cue", INK, True), ("  — a sample of the target voice", MUTE, False)], 14, space_after=8)
para(tf, [("2.  Mixture", INK, True), ("  — target + distractor(s)", MUTE, False)], 14, space_after=8)
para(tf, [("3.  Report", INK, True), ("  the target's middle word", MUTE, False)], 14, space_after=8)
para(tf, "  (from an 800-word vocabulary)", 13, MUTE, italic=True, space_after=14)
para(tf, "Parameters are frozen: this tests behavior at inference, not retraining.",
     14, GOOD, bold=True)

# ============ 3. PIPELINE ============
s = slide()
header(s, "Method", "Building the evaluation set — one shared pipeline")
steps = [("Force-align", "torchaudio MMS_FA\nword-level timestamps"),
         ("Pick anchor", "in-vocab middle word\ncentered slice"),
         ("Slice 2.5 s", "model crops to 2 s\ndiotic (L = R)"),
         ("Mix @ SNR", "-9…+3 dB, +inf\nRMS-normalize 0.02"),
         ("Infer + score", "target-word accuracy\n+ distractor confusion")]
n = len(steps); gap = Inches(0.25); tot = Inches(12.0)
cw = (tot - gap * (n - 1)) // n; x = Inches(0.7); y = Inches(2.2)
for i, (t, d) in enumerate(steps):
    c = card(s, x, y, cw, Inches(1.9), LIGHT if i % 2 == 0 else RGBColor(0xEC, 0xE3, 0xEA))
    _, tf = box(s, x + Inches(0.1), y + Inches(0.15), cw - Inches(0.2), Inches(1.6), MSO_ANCHOR.MIDDLE)
    para(tf, f"{i+1}", 20, ACC, bold=True, first=True, align=PP_ALIGN.CENTER, space_after=2)
    para(tf, t, 14, INK, bold=True, align=PP_ALIGN.CENTER, space_after=4)
    para(tf, d, 11, MUTE, align=PP_ALIGN.CENTER)
    if i < n - 1:
        ar = s.shapes.add_shape(1, x + cw + Inches(0.02), y + Inches(0.85), Inches(0.2), Inches(0.2))
        ar.fill.solid(); ar.fill.fore_color.rgb = ACC; ar.line.fill.background(); ar.shadow.inherit = False
    x = x + cw + gap
_, tf = box(s, Inches(0.7), Inches(4.6), Inches(12), Inches(2.2))
para(tf, "Anchor = the paper's rule: pick the target word first, then cut a slice centered on it",
     15, INK, bold=True, first=True, space_after=10)
for t in ["Structural constraints: cue & target = same speaker / different recordings; distractor = different speaker; gender-balanced targets.",
          "Paper-compatible scoring: a prediction is correct if it matches any in-vocabulary word in the target excerpt.",
          "Model validity check: 88.6% clean-speech accuracy; +inf lands at 88.0% (chance = 0.1%)."]:
    para(tf, t, 14, MUTE, bullet=True, space_after=6)

# ============ 4. PART 1 divider ============
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.7), SW, Inches(2.1))
band.fill.solid(); band.fill.fore_color.rgb = ACC; band.line.fill.background(); band.shadow.inherit = False
_, tf = box(s, Inches(0.9), Inches(2.9), Inches(11.5), Inches(1.7), MSO_ANCHOR.MIDDLE)
para(tf, "PART 1", 16, RGBColor(0xF0, 0xC8, 0xDE), bold=True, first=True, space_after=6)
para(tf, "Distractor sex  ·  a single competing talker", 30, RGBColor(0xFF, 0xFF, 0xFF), bold=True)

# ============ 5. FIG 2a/2b ============
s = slide()
header(s, "Part 1 · Result", "Accuracy rises with SNR; different-sex is easier")
pic_fit(s, FIG2B, Inches(0.6), Inches(1.4), Inches(7.3), Inches(5.8))
_, tf = box(s, Inches(8.1), Inches(1.6), Inches(4.7), Inches(5.4))
para(tf, "What reproduces", 17, ACC, bold=True, first=True, space_after=8)
for t in ["Monotonic rise with SNR (both lines).",
          "Different-sex > same-sex at every masked SNR.",
          "Gap = +9 to +18 percentage points.",
          "Lines converge to ~88% at +inf — no distractor, sex no longer matters."]:
    para(tf, t, 14, INK, bullet=True, space_after=8)
para(tf, "within-item, N=599/597, diotic", 12, MUTE, italic=True, space_after=10)
para(tf, "= paper Fig 2a (same-sex line) + Fig 2b (both lines)", 13, GOOD, bold=True)

# ============ 6. FIG 2e + problem ============
s = slide()
header(s, "Part 1 · Result + problem", "Confusion trend reproduces — but magnitude is too low")
pic_fit(s, FIG2E, Inches(0.6), Inches(1.4), Inches(7.0), Inches(5.8))
_, tf = box(s, Inches(7.9), Inches(1.55), Inches(4.9), Inches(5.5))
para(tf, "Confusion = model reports a distractor word", 15, ACC, bold=True, first=True, space_after=8)
para(tf, "Direction correct:", 14, INK, bold=True, space_after=4)
for t in ["lower SNR → more confusion", "same-sex confuses more than different-sex"]:
    para(tf, t, 13, MUTE, bullet=True, space_after=5)
para(tf, "But 4–5x too low vs the paper", 15, RGBColor(0xB0, 0x30, 0x30), bold=True, space_after=6)
para(tf, [("Root cause: ", INK, True),
          ("distractors were picked at random, so their middle word is usually NOT in the vocabulary — the model cannot output it even if it hears it.",
           INK, False)], 14, space_after=8)
para(tf, "→ This is exactly what Part 2 fixes.", 14, GOOD, bold=True)

# ============ 7. PART 2 divider ============
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.7), SW, Inches(2.1))
band.fill.solid(); band.fill.fore_color.rgb = ACC2; band.line.fill.background(); band.shadow.inherit = False
_, tf = box(s, Inches(0.9), Inches(2.9), Inches(11.5), Inches(1.7), MSO_ANCHOR.MIDDLE)
para(tf, "PART 2  ·  NEW", 16, RGBColor(0xB9, 0xCC, 0xEA), bold=True, first=True, space_after=6)
para(tf, "Number of distractors  ·  1 / 2 / 4 talkers + babble", 30, RGBColor(0xFF, 0xFF, 0xFF), bold=True)

# ============ 8. THE QUESTION (part 2) ============
s = slide()
header(s, "Part 2 · The question", "Does talker NUMBER matter, at fixed masker energy?")
_, tf = box(s, Inches(0.7), Inches(1.55), Inches(11.9), Inches(5.3))
para(tf, "Human hearing: more competing talkers → harder, even when total masker energy is held constant.",
     18, INK, bold=True, first=True, space_after=12)
para(tf, [("That effect is ", INK, False), ("information masking", ACC, True),
          (" — being confused by other voices, not simply drowned out by energy.", INK, False)],
     16, space_after=16)
para(tf, "So the design must hold total masker energy CONSTANT while varying only the number of voices.",
     16, INK, space_after=16)
para(tf, [("Prediction under test: ", INK, True),
          ("if the feature-gain model captures information masking, accuracy should fall as talkers are added — at matched energy.",
           INK, False)], 16, space_after=10)
para(tf, "N=1 uses the same task and mixing logic as Part 1 — a built-in directional check.",
     14, GOOD, bold=True)

# ============ 9. DESIGN 1: conditions + nesting ============
s = slide()
header(s, "Part 2 · Design (1/3)", "Conditions & nested sampling")
_, tf = box(s, Inches(0.7), Inches(1.5), Inches(6.0), Inches(5.4))
para(tf, "Conditions", 17, ACC, bold=True, first=True, space_after=5)
para(tf, "no-distractor · 1 · 2 · 4 · 8-talker babble · + ISSN control", 15, INK, bold=True, space_after=6)
para(tf, "SNR: -9…+3 dB for maskers; no-distractor is a single +inf point.", 14, MUTE, space_after=14)
para(tf, "Within-item", 17, ACC, bold=True, space_after=5)
para(tf, "The SAME 600 targets are re-mixed in every condition × SNR → differences come from the condition, not the sample.",
     15, INK, space_after=14)
para(tf, "Nested sampling", 17, ACC, bold=True, space_after=5)
para(tf, "Each target draws a fixed set d1…d8; two = d1,d2; four = d1–d4; babble = d1–d8.",
     15, INK, space_after=6)
para(tf, "→ 'two-talker' is literally 'one-talker plus one more person'. Only the count changes.",
     15, INK)
card(s, Inches(7.1), Inches(1.55), Inches(5.5), Inches(5.3))
_, tf = box(s, Inches(7.4), Inches(1.8), Inches(4.9), Inches(4.8))
para(tf, "Anchored distractor pool", 16, ACC2, bold=True, first=True, space_after=8)
para(tf, "Every distractor recording also carries an in-vocab anchor word, sliced like the target.",
     14, INK, space_after=10)
for t in ["1,200 recordings / 1,200 speakers",
          "male 600 / female 600",
          "0 overlap with target speakers",
          "534 distinct anchor words"]:
    para(tf, t, 14, MUTE, bullet=True, space_after=6)
para(tf, "Now the model CAN output a distractor word → confusion becomes measurable.",
     14, GOOD, bold=True)

# ============ 10. DESIGN 2: total-masker SNR ============
s = slide()
header(s, "Part 2 · Design (2/3)", "Target-to-total-masker SNR isolates the variable")
_, tf = box(s, Inches(0.7), Inches(1.55), Inches(11.9), Inches(5.3))
para(tf, "Each distractor is RMS-aligned, then SUMMED into one total masker.",
     16, INK, bullet=True, first=True, space_after=10)
para(tf, "The whole masker is scaled so  10·log10(P_target / P_masker) = SNR;  mixture = target + masker.",
     16, INK, bullet=True, space_after=10)
para(tf, [("→ 1 / 2 / 4-talker have ", INK, False), ("identical total masker energy", ACC, True),
          (" at a given SNR.", INK, False)], 16, bullet=True, space_after=10)
para(tf, "So any accuracy difference between them CANNOT be loudness — it is 'more confusable voices'.",
     16, INK, bullet=True, space_after=10)
para(tf, "This matches the paper's core 2-/4-talker construction: equalize sources, sum, then set target-to-total-masker SNR.",
     16, GOOD, bullet=True, space_after=10)
para(tf, "The 8-talker babble remains an approximation: ours is summed online; the paper used pre-made files.",
     16, MUTE, bullet=True)

# ============ 11. DESIGN 3: safeguards ============
s = slide()
header(s, "Part 2 · Design (3/3)", "Two safeguards added before running")
card(s, Inches(0.7), Inches(1.55), Inches(6.0), Inches(5.3), LIGHT)
_, tf = box(s, Inches(1.0), Inches(1.8), Inches(5.4), Inches(4.8))
para(tf, "Gender balancing — a real confound", 16, RGBColor(0xB0, 0x30, 0x30), bold=True, first=True, space_after=8)
para(tf, "Random draws made P(≥1 same-sex distractor) climb with N: 50% → 99.6%.",
     14, INK, space_after=8)
para(tf, "Sex is a LARGE effect (Part 1) — it would masquerade as a talker-number effect.",
     14, INK, space_after=8)
para(tf, "Fix: alternate d1…d8 by sex → same-sex count exactly 0.5 / 1 / 2 / 4.",
     14, GOOD, bold=True, space_after=8)
para(tf, "Verified across all 600 targets: zero jitter, nesting intact, no self / duplicate speakers.",
     13, MUTE, space_after=0)
card(s, Inches(7.0), Inches(1.55), Inches(5.6), Inches(5.3), RGBColor(0xEC, 0xE3, 0xEA))
_, tf = box(s, Inches(7.3), Inches(1.8), Inches(5.0), Inches(4.8))
para(tf, "ISSN control condition", 16, ACC2, bold=True, first=True, space_after=8)
para(tf, "Spectrally-matched STATIONARY noise — gapless and contentless.",
     14, INK, space_after=8)
para(tf, "Separates information masking from 'glimpsing' into gaps between words.",
     14, INK, space_after=8)
para(tf, "If glimpsing drove the effect, speech (which has gaps) would be EASIER than gapless noise.",
     14, INK, space_after=8)
para(tf, "Also: 1-talker split into one_same / one_diff → free Part-1 (Fig 2a/2b) anchors.",
     13, MUTE)

# ============ 12. RESULT 1 accuracy+confusion (big fig) ============
s = slide()
header(s, "Part 2 · Result 1", "More competing talkers reduce target-word accuracy")
pic_fit(s, FIGMT, Inches(0.5), Inches(1.35), Inches(12.3), Inches(4.2))
_, tf = box(s, Inches(0.7), Inches(5.75), Inches(12), Inches(1.5))
para(tf, [("Accuracy (left): ", INK, True),
          ("monotonic in SNR; pooled one > two > four ≈ babble; +inf = 88%.   ", INK, False),
          ("Confusion (right): ", INK, True),
          ("specific distractor-word reports fall as the masker becomes more noise-like.", INK, False)],
     15, first=True, space_after=6)
para(tf, "Paper-compatible scoring · pooled one-talker sex · 95% CI clustered by 149 target speakers", 13, MUTE, italic=True)

# ============ 13. RESULT 2: ISSN information masking ============
s = slide()
header(s, "Part 2 · Result 2", "Speech maskers remain harder than matched stationary noise")
pic_fit(s, FIGISSN, Inches(0.6), Inches(1.4), Inches(7.2), Inches(5.8))
_, tf = box(s, Inches(8.0), Inches(1.6), Inches(4.7), Inches(5.4))
para(tf, "ISSN = spectrally-matched stationary noise (gapless, no words)",
     14, ACC, bold=True, first=True, space_after=10)
for t in ["Four-talker and babble accuracy is below ISSN at every tested SNR.",
          "ISSN is gapless, whereas speech contains pauses that should permit glimpsing.",
          "The remaining speech disadvantage is consistent with information masking beyond gap-listening.",
          "This is supportive evidence, not a proof: corpus and masker construction still differ from the paper."]:
    para(tf, t, 14, INK, bullet=True, space_after=9)

# ============ 14. THE FIX WORKED ============
s = slide()
header(s, "Part 2 · Result 3", "The anchored pool fixed the confusion underestimate")
card(s, Inches(0.7), Inches(1.6), Inches(3.7), Inches(2.3), LIGHT)
_, tf = box(s, Inches(0.9), Inches(1.8), Inches(3.3), Inches(1.9), MSO_ANCHOR.MIDDLE)
para(tf, "Before (random)", 15, MUTE, bold=True, first=True, align=PP_ALIGN.CENTER, space_after=4)
para(tf, "7.2%", 40, RGBColor(0xB0, 0x30, 0x30), bold=True, align=PP_ALIGN.CENTER, space_after=2)
para(tf, "same-sex confusion @ -9 dB", 12, MUTE, align=PP_ALIGN.CENTER)
ar = s.shapes.add_shape(1, Inches(4.55), Inches(2.5), Inches(0.5), Inches(0.5))
ar.fill.solid(); ar.fill.fore_color.rgb = ACC; ar.line.fill.background(); ar.shadow.inherit = False
card(s, Inches(5.2), Inches(1.6), Inches(3.7), Inches(2.3), RGBColor(0xE6, 0xF0, 0xE9))
_, tf = box(s, Inches(5.4), Inches(1.8), Inches(3.3), Inches(1.9), MSO_ANCHOR.MIDDLE)
para(tf, "After (anchored)", 15, MUTE, bold=True, first=True, align=PP_ALIGN.CENTER, space_after=4)
para(tf, "28.0%", 40, GOOD, bold=True, align=PP_ALIGN.CENTER, space_after=2)
para(tf, "same-sex confusion @ -9 dB", 12, MUTE, align=PP_ALIGN.CENTER)
card(s, Inches(9.1), Inches(1.6), Inches(3.5), Inches(2.3), LIGHT)
_, tf = box(s, Inches(9.3), Inches(1.8), Inches(3.1), Inches(1.9), MSO_ANCHOR.MIDDLE)
para(tf, "Paper", 15, MUTE, bold=True, first=True, align=PP_ALIGN.CENTER, space_after=4)
para(tf, "~41%", 40, INK, bold=True, align=PP_ALIGN.CENTER, space_after=2)
para(tf, "target for this condition", 12, MUTE, align=PP_ALIGN.CENTER)
_, tf = box(s, Inches(0.7), Inches(4.3), Inches(12), Inches(2.6))
para(tf, "From 5.7x too low to 1.5x too low — the root-cause diagnosis was correct.",
     18, INK, bold=True, first=True, space_after=12)
para(tf, [("An honest reversal: ", ACC, True),
          ("confusion is HIGHEST for a single same-sex talker and DROPS as talkers are added — opposite to our pre-registered guess, but consistent with the paper. With many voices the masker becomes noise-like, so the model emits garbage rather than a specific distractor word.",
           INK, False)], 15, space_after=10)

# ============ 15. SELF-CONSISTENCY ============
s = slide()
header(s, "Validation", "Self-consistency checks — why the pattern is credible")
_, tf = box(s, Inches(0.7), Inches(1.6), Inches(11.9), Inches(5.2))
checks = [[("no-distractor = 88.0% ", INK, True),
           ("— matches the +inf anchor from Part 1 exactly.", INK, False)],
          [("one_same / one_diff track the Part-1 single-distractor curves", INK, True),
           (", 2–6 points lower (expected: a different, anchored distractor pool).", INK, False)],
          [("N=1 reduces to the single-distractor case", INK, True),
           (" that was already reproduced — direction and shape hold.", INK, False)],
          [("Gender balancing verified across all 600 targets", INK, True),
           (": exact same-sex counts, nesting intact, no self/duplicate speakers.", INK, False)]]
for i, t in enumerate(checks):
    para(tf, t, 16, INK, bullet=True, first=(i == 0), space_after=14)
para(tf, "→ The results are internally coherent; the exact Windows run script still needs to be archived locally.",
     16, GOOD, bold=True, space_after=0)

# ============ 16. SUMMARY ============
s = slide()
header(s, "Summary", "What reproduced")
rows = [("Model validity (clean)", "88.6% vs 0.1% chance", True),
        ("Accuracy vs SNR", "monotonic rise, both experiments", True),
        ("Different-sex > same-sex", "+9 to +18 percentage points", True),
        ("More talkers → harder", "pooled one > two > four ≈ babble", True),
        ("Confusion direction", "lower SNR & same-sex → more", True),
        ("Confusion magnitude", "fixed 7.2% → 28% (paper ~41%)", True)]
y = Inches(1.55); rh = Inches(0.82)
for i, (a, b, ok) in enumerate(rows):
    c = card(s, Inches(0.7), y, Inches(11.9), rh - Inches(0.12),
             LIGHT if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF))
    dot = s.shapes.add_shape(1, Inches(0.95), y + Inches(0.16), Inches(0.34), Inches(0.34))
    dot.fill.solid(); dot.fill.fore_color.rgb = GOOD; dot.line.fill.background(); dot.shadow.inherit = False
    _, tf = box(s, Inches(1.5), y, Inches(5.6), rh - Inches(0.12), MSO_ANCHOR.MIDDLE)
    para(tf, a, 15, INK, bold=True, first=True)
    _, tf = box(s, Inches(7.1), y, Inches(5.3), rh - Inches(0.12), MSO_ANCHOR.MIDDLE)
    para(tf, b, 14, MUTE, first=True)
    y = y + rh

# ============ 17. LIMITATIONS ============
s = slide()
header(s, "Limitations", "Honest boundaries")
_, tf = box(s, Inches(0.7), Inches(1.55), Inches(11.9), Inches(5.3))
para(tf, [("Corpus mismatch (CV ≠ SWC) — the biggest one:", RGBColor(0xB0, 0x30, 0x30), True)],
     16, first=True, space_after=6)
for t in ["our stimuli are Common Voice; the paper's Experiment 1 uses held-out Spoken Wikipedia (SWC).",
          "231/347 unique target files and 703/1,200 pool files belong to the CV training split.",
          "split membership does not prove every clip was sampled during training, but held-out generalization cannot be claimed.",
          "the within-panel contrast is informative, but absolute magnitudes and generalization remain uncertain."]:
    para(tf, t, 14, MUTE, bullet=True, space_after=5, level=1)
para(tf, "Confusion vs talker number came out opposite to our stated criterion (reported, not hidden).",
     15, INK, bullet=True, space_after=8)
para(tf, "babble = 8 talkers summed online (paper uses pre-made files) — a deliberate, nesting-preserving choice.",
     15, INK, bullet=True, space_after=8)
para(tf, "One checkpoint only; the paper's feature-gain curve averages ten architectures.",
     15, INK, bullet=True, space_after=8)
para(tf, "Qualitative trend replication only; diotic and custom-stimulus conditions.",
     15, INK, bullet=True)

# ============ 18. NEXT STEPS ============
s = slide()
header(s, "Outlook", "Next steps")
_, tf = box(s, Inches(0.7), Inches(1.6), Inches(11.9), Inches(5.2))
nexts = ["Archive the exact RTX 3070 run script, environment, random seed and file hashes.",
         "Rebuild the evaluation set from held-out Spoken Wikipedia for a paper-faithful replication.",
         "Use the paper's pre-made babble and exact 2-/4-talker sex composition.",
         "Run all ten feature-gain architectures, or explicitly retain the single-checkpoint scope.",
         "Fit a mixed-effects model / speaker-cluster bootstrap and compare directly with OSF curves."]
for i, t in enumerate(nexts):
    para(tf, t, 16, INK, bullet=True, first=(i == 0), space_after=12)

# ============ 19. CLOSING ============
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.6), SW, Inches(2.3))
band.fill.solid(); band.fill.fore_color.rgb = LIGHT; band.line.fill.background(); band.shadow.inherit = False
_, tf = box(s, Inches(0.9), Inches(2.75), Inches(11.5), Inches(2.0), MSO_ANCHOR.MIDDLE)
para(tf, "A single frozen feature-gain model qualitatively reproduced", 24, INK, bold=True, first=True, space_after=8)
para(tf, "the SNR, distractor-sex and talker-number trends.", 24, ACC, bold=True)
_, tf = box(s, Inches(0.9), Inches(5.0), Inches(11.5), Inches(0.8))
para(tf, "Thank you — questions?", 18, MUTE, bold=True, first=True)

NOTES = [
    """[0:00–0:35] Today I will present a qualitative replication of the selective-listening results from Griffith, Hess and McDermott. I use one of the authors' pretrained feature-gain checkpoints, keep all model parameters frozen, and test it on a custom Common Voice evaluation set. I will first show the single-distractor validation, then focus on the new question: what happens when the number of competing talkers increases? The goal is to reproduce behavioral directions, not exact numerical values.""",
    """[0:35–1:35] The cocktail-party problem is not simply speech recognition in noise. The listener must use a cue to select one voice from a mixture. The feature-gain model turns the cue into multiplicative gains that emphasize features associated with the target talker. Each trial therefore contains a cue, a target-plus-masker mixture, and an 800-way word report. My question is whether the same frozen mechanism reproduces both successful selection and characteristic errors on speech materials that I constructed independently from the published evaluation set.""",
    """[1:35–2:45] This is the shared stimulus pipeline. Forced alignment gives word boundaries. I first choose an in-vocabulary anchor word, then extract a 2.5-second window centered on that word; the model's cochlear front end keeps the middle two seconds. All mixtures are diotic and RMS-normalized to 0.02. For the final analysis, I use the paper-compatible scoring rule: a prediction is correct if it matches any in-vocabulary word in the target excerpt. Clean-speech accuracy is about 88 percent, establishing that the checkpoint and preprocessing are functioning.""",
    """[2:45–2:55] Before the new multi-talker experiment, I briefly show the single-distractor validation. This provides an anchor for the new results and checks whether the model responds to SNR and talker similarity in the expected direction.""",
    """[2:55–4:00] With one competing talker, accuracy increases monotonically as target-to-masker SNR improves. A different-sex distractor is consistently easier than a same-sex distractor, with a gap of roughly nine to eighteen percentage points. At infinite SNR the distractor is removed, so both curves converge near 88 percent. These are the expected Figure 2a and 2b directions. I interpret this as successful qualitative validation of the inference pipeline, not a numerical reproduction, because my speech corpus and sampling procedure differ from the paper.""",
    """[4:00–4:55] The first confusion analysis also reproduced the direction: confusions increase at low SNR and are more frequent for same-sex distractors. However, the magnitude was four to five times below the paper. I traced this to stimulus construction. Random distractors often did not contain an output-vocabulary word near the center, so even a true attentional swap could not be counted. This motivated a redesigned distractor pool in which every masker contains a known in-vocabulary anchor word. The new multi-talker experiment therefore also tests whether that diagnosis was correct.""",
    """[4:55–5:05] Part two is the new result: the effect of adding one, two, four, and eight competing talkers while keeping the total masker energy controlled.""",
    """[5:05–6:00] The scientific question is whether talker number matters beyond overall masker level. If total masker energy is fixed, poorer performance with more voices cannot be explained by the masker simply becoming louder. It is consistent with information masking: more speech sources create more target-like, potentially confusable structure. The prediction is therefore lower target-word accuracy as talkers are added. The single-talker condition uses the same task and mixing logic as Part one, so its direction provides a built-in check.""",
    """[6:00–7:25] The design is within-item: the same 600 target trials are evaluated in every condition and SNR. Distractors are nested, so the two-talker condition adds a source to the one-talker set, and the four-talker condition adds sources to the two-talker set. I also built an anchored pool of 1,200 recordings from 1,200 speakers, balanced by sex and disjoint from the target speakers. Because each masker now contains a known vocabulary anchor, distractor-word confusions are measurable rather than structurally suppressed by the evaluation set.""",
    """[7:25–8:35] The key acoustic control is target-to-total-masker SNR. Individual distractors are level-aligned and summed first. The summed masker is then scaled to the requested SNR relative to the target. Therefore one, two, and four talkers have the same total masker energy at a given x-axis value. This matches the central logic of the paper's two- and four-talker construction. The eight-talker babble is less exact: I sum eight talkers online to preserve nesting, whereas the paper sampled pre-made babble recordings.""",
    """[8:35–9:40] Two safeguards address plausible confounds. First, talker sex strongly affects performance, so the number of same-sex distractors must not accidentally increase with talker count. The draw was balanced to keep the same-sex proportion controlled. Second, I added ISSN, a stationary noise shaped to match the target spectrum. ISSN is gapless and contains no linguistic content. Comparing speech maskers with ISSN helps separate a speech-specific information-masking interpretation from the simpler idea that listeners or models only exploit temporal gaps between words.""",
    """[9:40–11:25] This is the main result. The one-talker curve now correctly pools same- and different-sex trials, as in the paper's number-of-distractors analysis. All accuracy curves rise monotonically with SNR. At every tested SNR, pooled one-talker accuracy is above two-talker accuracy, and two talkers are above four. Four-talker and eight-talker babble are close, particularly at high SNR, suggesting saturation. The right panel shows a different pattern: reports of a specific distractor word decrease as more voices are added. With many voices, errors become less attributable to one identifiable masker word and more noise-like. Confidence intervals are clustered by target speaker.""",
    """[11:25–12:40] The ISSN comparison provides a complementary interpretation. Four-talker speech and eight-talker babble are harder than matched stationary noise at every tested SNR. This is notable because stationary noise is gapless, while speech contains pauses that should support glimpsing. The residual disadvantage for speech is therefore consistent with information masking beyond temporal gaps. I use the phrase 'consistent with' deliberately: this comparison supports the interpretation, but it does not prove a unique mechanism because corpus and masker construction still differ from the original experiment.""",
    """[12:40–13:35] The anchored distractor pool also fixed most of the confusion underestimate. In the same-sex, minus-nine-decibel condition, confusion increased from 7.2 percent with random distractors to 28 percent with anchored distractors, much closer to the approximately 41 percent visible in the paper. The direction across talker number reversed my initial expectation: specific-word confusions are highest for one same-sex talker and decrease with more talkers. This is not hidden; it is consistent with the idea that multi-talker maskers produce diffuse errors rather than clean swaps to one competing word.""",
    """[13:35–14:25] Several internal checks passed. The no-distractor point exactly returns to 88 percent. Same- and different-sex one-talker curves track the earlier experiment, although the new anchored pool shifts the values slightly. The qualitative shape is stable, and gender balancing and speaker exclusions were checked across all targets. These checks make the pattern credible. A remaining reproducibility task is to copy the exact Windows GPU run script and environment metadata back into the local project, because the current local multi-talker script is an older version.""",
    """[14:25–15:10] In summary, the single checkpoint reproduces six qualitative signatures: high clean accuracy, monotonic SNR effects, the different-sex advantage, decreasing accuracy with more talkers, the expected SNR and sex dependence of confusions, and recovery of much of the confusion magnitude after fixing the distractor pool. The strongest statement supported by these results is a qualitative trend replication on a custom evaluation set. It is not yet a stimulus-identical or ensemble-level reproduction of the published model panel.""",
    """[15:10–16:30] The main limitation is evaluation independence. The paper used held-out Spoken Wikipedia, whereas my target, cue and masker files come from Common Voice, the model's training corpus. Many unique files belong to the official training split, so I cannot claim cross-corpus generalization or guaranteed absence of waveform overlap. The paper also averaged ten feature-gain architectures, while I use one checkpoint. Finally, my babble is generated online rather than sampled from the paper's pre-made files. These limitations affect absolute values and the strength of the generalization claim, although the within-panel trend remains informative.""",
    """[16:30–17:25] The immediate next step is reproducibility: archive the exact GPU script, environment, seed and hashes. The scientific next step is to rebuild the evaluation set from held-out Spoken Wikipedia and match the paper's target pairing, talker-sex composition and pre-made babble. If checkpoints are available, running all ten feature-gain architectures would reproduce the published uncertainty measure. I would then fit a mixed-effects model or use speaker-cluster bootstrap and compare the condition means directly with the authors' OSF results using correlation and RMSE.""",
    """[17:25–17:45] The take-home message is that one frozen feature-gain checkpoint reproduces the main behavioral directions for SNR, distractor sex and talker number on my custom evaluation set. The next stage is to turn this successful qualitative result into a paper-faithful, fully reproducible replication. Thank you, and I welcome questions.""",
]

for index, (slide_item, note) in enumerate(zip(prs.slides, NOTES), start=1):
    slide_item.notes_slide.notes_text_frame.text = note.strip()
    if 1 < index < len(prs.slides):
        _, footer_tf = box(
            slide_item, Inches(0.7), Inches(7.18), Inches(11.9), Inches(0.2)
        )
        para(
            footer_tf,
            f"Griffith et al. (2026) · qualitative single-checkpoint replication                                      {index}/19",
            8,
            MUTE,
            first=True,
            space_after=0,
        )

prs.save(OUT)
print("saved:", OUT, "| slides:", len(prs.slides._sldIdLst))
