"""
双耳分听(dichotic)可行性单例验证 —— 第一步,先确认"cue 放哪只耳,模型就报哪只耳的词"。

背景:模型是双通道(input_channels=2)架构。既有 diotic 管线用 DuplicateChannel 把单声道
复制成左右相同;双耳分听则是左右耳放不同语音、cue 只给目标耳,别的耳静音。

核心未知(会议上是推定,没实测过):
  单耳呈现 cue 能否起到"指定目标耳"的作用?

机制预期(读 SimpleAttentionalGain 后):gain 逐通道计算。cue 只在目标耳有能量 → 该耳按
频率选择性放行;另一只耳 cue 近似静音 → gain 被压到 floor(bias θ1),即抑制。所以理论上
应当路由到 cue 所在的耳。本脚本用实测确认。

解耦测试(用 demo 音频,男/女不同说话人不同词):
  混音固定: 左耳 = 男声 "about", 右耳 = 女声 "above"
  只用【男声 cue】,改变放哪只耳:
    - 男声 cue 放左耳  -> 位置+说话人都指向 about
    - 男声 cue 放右耳  -> 说话人=男,但位置指向右耳的 above
  若"cue 放右耳"时模型报 above => 跟随【耳朵】(双耳分听可行)
  若两种都报 about        => 只跟随【说话人】,方案需重新设计
对称起见,女声 cue 也照做一遍。

用法(repo 根目录, conda env audattn):
    python reproduction/dichotic_probe.py
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import sys
import pickle
from pathlib import Path


def _find_repo(start):
    """向上找 repo 根(含 src/ 与 cv_800_word_label_to_int_dict.pkl),不依赖脚本所在深度。"""
    for cand in [start.resolve(), *start.resolve().parents]:
        if (cand / "cv_800_word_label_to_int_dict.pkl").exists() and (cand / "src").is_dir():
            return cand
    raise SystemExit("找不到 repo 根(需含 src/ 与 cv_800_word_label_to_int_dict.pkl)")


REPO = _find_repo(Path(__file__))
sys.path.insert(0, str(REPO))

import numpy as np
import soundfile as sf
import torch
import yaml

_torch_orig_load = torch.load
def _torch_load_full(*a, **k):
    k["weights_only"] = False
    return _torch_orig_load(*a, **k)
torch.load = _torch_load_full

from src.spatial_attn_lightning import BinauralAttentionModule

DEVICE = "cpu"
RMS_LEVEL = 0.02


def rms_normalize_mono(wav, level=RMS_LEVEL):
    """单声道 demean + RMS 归一到 level(对齐 RMSNormalizeForegroundAndBackground)。"""
    wav = wav - wav.mean()
    rms = np.sqrt((wav ** 2).mean())
    if rms > 0:
        wav = wav * level / rms
    return wav


def make_dichotic(left_wav, right_wav):
    """把两条单声道波形分别放进左右声道(各自 RMS 归一),不相加。返回 [1,2,N] tensor。"""
    n = min(len(left_wav), len(right_wav))
    left = rms_normalize_mono(left_wav[:n])
    right = rms_normalize_mono(right_wav[:n])
    stereo = np.stack([left, right], axis=0)          # [2, N]
    return torch.from_numpy(stereo).unsqueeze(0).float()  # [1, 2, N]


def make_cue(cue_wav, ear, n):
    """cue放目标耳，并按两个双耳通道的全局RMS归一到0.02。"""
    cue = rms_normalize_mono(cue_wav[:n])
    stereo = np.zeros((2, n), dtype=np.float32)
    stereo[ear] = cue
    stereo = stereo - stereo.mean()
    global_rms = np.sqrt((stereo ** 2).mean())
    if global_rms > 0:
        stereo = stereo * RMS_LEVEL / global_rms
    return torch.from_numpy(stereo).unsqueeze(0).float()


def main():
    cfg = yaml.load(open(REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"),
                    Loader=yaml.FullLoader)
    ckpt = sorted((REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints").glob("*.ckpt"))[0]
    print(f"checkpoint: {ckpt.name}")
    model = BinauralAttentionModule.load_from_checkpoint(
        checkpoint_path=str(ckpt), config=cfg, strict=False).eval().to(DEVICE)
    coch = model.coch_gram.to(DEVICE)

    with open(REPO / "cv_800_word_label_to_int_dict.pkl", "rb") as f:
        word_to_ix = pickle.load(f)
    ix_to_word = {v: k for k, v in word_to_ix.items()}

    demo = REPO / "demo_stimuli"
    male_cue, _ = sf.read(demo / "male_cue.wav")
    female_cue, _ = sf.read(demo / "female_cue.wav")
    male_target, _ = sf.read(demo / "male_target_about.wav")     # "about"
    female_target, _ = sf.read(demo / "female_target_above.wav")  # "above"

    # 固定混音: 左耳=男声 about, 右耳=女声 above
    LEFT_WORD, RIGHT_WORD = "about", "above"
    mixture = make_dichotic(male_target, female_target)
    n = mixture.shape[-1]

    def predict(cue_tensor):
        cue_cg, _ = coch(cue_tensor.to(DEVICE), None)
        mix_cg, _ = coch(mixture.to(DEVICE), None)
        with torch.no_grad():
            ix = model(cue_cg, mix_cg).softmax(-1).argmax(dim=1).item()
        return ix_to_word[ix]

    print(f"\n混音: 左耳='{LEFT_WORD}'(男声)  右耳='{RIGHT_WORD}'(女声)")
    print("=" * 64)
    print(f"{'cue 说话人':>10} | {'cue 放的耳':>8} | {'位置期望':>8} | {'说话人期望':>10} | {'模型预测':>8}")
    print("-" * 64)

    cases = [
        ("男声", male_cue,   0, LEFT_WORD,  "about"),  # 位置左=about, 说话人男=about (一致)
        ("男声", male_cue,   1, RIGHT_WORD, "about"),  # 位置右=above, 说话人男=about (冲突! 关键行)
        ("女声", female_cue, 1, RIGHT_WORD, "above"),  # 位置右=above, 说话人女=above (一致)
        ("女声", female_cue, 0, LEFT_WORD,  "above"),  # 位置左=about, 说话人女=above (冲突! 关键行)
    ]
    preds = []
    for spk, cue_wav, ear, pos_exp, spk_exp in cases:
        pred = predict(make_cue(cue_wav, ear, n))
        preds.append((ear, pos_exp, spk_exp, pred))
        ear_name = "左" if ear == 0 else "右"
        flag = "  <-- 冲突行(判据)" if pos_exp != spk_exp else ""
        print(f"{spk:>10} | {ear_name:>8} | {pos_exp:>8} | {spk_exp:>10} | {pred:>8}{flag}")

    print("=" * 64)
    # 判据:两条冲突行(男cue右耳 / 女cue左耳)是否跟随"位置"
    conflict = [(pos, pred) for ear, pos, spk, pred in preds if pos != spk]  # 用变量名占位
    conflict = [(cases[1][3], preds[1][3]), (cases[3][3], preds[3][3])]
    follow_ear = sum(1 for pos, pred in conflict if pred == pos)
    print(f"\n冲突行判据: 跟随耳朵位置 {follow_ear}/2")
    if follow_ear == 2:
        print("=> 模型跟随【耳朵位置】: 单耳 cue 能路由目标耳,双耳分听方案可行,可进入批量。")
    elif follow_ear == 0:
        print("=> 模型只跟随【说话人身份】: 单耳 cue 不路由耳朵。需改 cue 喂法或重新设计。")
    else:
        print("=> 结果不一致(1/2): 需要多样本进一步确认,不能仅凭单例下结论。")


if __name__ == "__main__":
    main()
