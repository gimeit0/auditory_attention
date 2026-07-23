"""
Part 2: 验证论文 checkpoint 在我切好的片段上的有效性。

流程:
  1) 闸门: 先用仓库自带 demo_stimuli 跑 加载->推理,确认 checkpoint 正确
     (预期 male->about, female->above)。闸门不过就停,不跑后续。
  2) 对 eval_manifest.csv 的每个 trial: cue + target(clean,无 distractor,即 inf SNR)
     -> 模型预测中间词 -> 与真实中间词对比。
  3) 评分:
       - exact:   预测词 == target 锚点词
       - lenient: 预测词 ∈ target 句中所有"在 800 词表内"的词(论文宽松口径)
     打印每个 trial 的 真实 vs 预测,并汇总准确率。

clean 验证(无干扰)是最容易的情形,用来确认"模型+我的切片管线"端到端正确;
SNR/distractor 混音是 Task C/D。

用法:
    python validate_model.py
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import argparse
import pickle
from pathlib import Path

import pandas as pd
import soundfile as sf
import torch
import yaml

# checkpoint 来自作者 OSF(可信源),PyTorch>=2.6 需 weights_only=False
_torch_orig_load = torch.load
def _torch_load_full(*a, **k):
    k["weights_only"] = False
    return _torch_orig_load(*a, **k)
torch.load = _torch_load_full

from src.spatial_attn_lightning import BinauralAttentionModule
import src.audio_transforms as at
from align_words import normalize_token

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"   # 超算 GPU 节点自动切 cuda
REPO = Path(__file__).resolve().parent


def build_model():
    config_path = REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"
    config = yaml.load(open(config_path), Loader=yaml.FullLoader)
    ckpt = sorted((REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints").glob("*.ckpt"))[0]
    print(f"Using checkpoint: {ckpt.name}")
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(ckpt), config=config, strict=False).eval().to(DEVICE)
    coch = model.coch_gram.to(DEVICE)
    return model, coch


def make_transforms():
    # 与 run_demo_m1.py 完全一致(SNR=0 这里其实不混音,clean 时 background=None)
    return at.AudioCompose([
        at.AudioToTensor(),
        at.CombineWithRandomDBSNR(low_snr=0, high_snr=0),
        at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
        at.DuplicateChannel(),
        at.UnsqueezeAudio(dim=0),
    ])


def to_dev(x):
    return x.to(DEVICE).float()


def predict(model, coch, tfm, cue_wav, fg_wav, bg_wav, ix_to_word):
    """cue + 前景(+可选背景) -> 预测词。clean 时 bg_wav=None。"""
    cue, _ = tfm(cue_wav, None)
    mix, _ = tfm(fg_wav, bg_wav)
    cue_cg, _ = coch(to_dev(cue), None)
    mix_cg, _ = coch(to_dev(mix), None)
    with torch.no_grad():
        logits = model(cue_cg, mix_cg)
        pred = logits.softmax(-1).argmax(dim=1).item()
    return ix_to_word[pred]


def demo_gate(model, coch, tfm, ix_to_word):
    """闸门: demo_stimuli 必须 male->about, female->above。"""
    sd = REPO / "demo_stimuli"
    fc, _ = sf.read(sd / "female_cue.wav")
    mc, _ = sf.read(sd / "male_cue.wav")
    ft, _ = sf.read(sd / "female_target_above.wav")
    mt, _ = sf.read(sd / "male_target_about.wav")
    # 同一混音(两说话人),分别用 male/female cue
    male_pred = predict(model, coch, tfm, mc, ft, mt, ix_to_word)
    female_pred = predict(model, coch, tfm, fc, ft, mt, ix_to_word)
    print(f"[GATE] male cue   -> True: about | Pred: {male_pred}")
    print(f"[GATE] female cue -> True: above | Pred: {female_pred}")
    ok = (male_pred == "about" and female_pred == "above")
    print(f"[GATE] {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest", default="reproduction/experiment_1_gender/archive/eval_manifest.csv"
    )
    ap.add_argument(
        "--stim_dir", default="reproduction/experiment_1_gender/archive/eval_stimuli"
    )
    ap.add_argument("--word_table", default="cv_800_word_label_to_int_dict.pkl")
    args = ap.parse_args()

    with open(REPO / args.word_table, "rb") as f:
        word_to_ix = pickle.load(f)
    ix_to_word = {v: k for k, v in word_to_ix.items()}
    word_set = set(word_to_ix)

    model, coch = build_model()
    tfm = make_transforms()

    print("\n--- 闸门: demo_stimuli ---")
    if not demo_gate(model, coch, tfm, ix_to_word):
        raise SystemExit("demo 闸门未通过,停止。请先发我上面的输出。")

    print("\n--- 我的切片(clean,无 distractor) ---")
    df = pd.read_csv(args.manifest, dtype=str, keep_default_na=False)
    n = exact = lenient = 0
    for _, r in df.iterrows():
        tdir = Path(args.stim_dir) / r["trial_id"]
        cue, _ = sf.read(tdir / "cue.wav")
        tgt, _ = sf.read(tdir / "target.wav")
        pred = predict(model, coch, tfm, cue, tgt, None, ix_to_word)

        # lenient: target 句中所有表内词
        in_table = set()
        for w in r["target_sentence"].split():
            for s in normalize_token(w):
                if s in word_set:
                    in_table.add(s)
        is_exact = (pred == r["target_norm"])
        is_lenient = (pred in in_table)
        exact += is_exact
        lenient += is_lenient
        n += 1
        flag = "OK " if is_exact else ("~  " if is_lenient else "X  ")
        print(f"  {flag}{r['trial_id']} True: {r['target_norm']:14s} Pred: {pred:14s}"
              f"{'' if is_exact else '  | in-table: ' + ','.join(sorted(in_table))}")

    print(f"\n=== 汇总(clean,n={n}) ===")
    print(f"exact   (==锚点词):       {exact}/{n} = {exact/n:.1%}")
    print(f"lenient (∈句中表内词):    {lenient}/{n} = {lenient/n:.1%}")
    print("(clean 无干扰是最易情形;若 exact 明显高于随机(1/800≈0.1%)即说明 checkpoint+切片管线有效)")


if __name__ == "__main__":
    main()
