"""
HAKUSAN 等价性校验 —— 在【GPU 节点】上跑。

这是整条依赖链的闸门: 后面的作业用 --dependency=afterok 挂在它后面,
所以**任何一项不过, 必须以非零退出码结束**, 否则 afterok 会照样放行, 校验就白做了。

依次检查:
  0) 资产齐全(checkpoint / demo_stimuli / 样本表 / 干扰池 / CV clips)——早失败, 免得半夜在下游作业里才炸
  1) torch.cuda 可用 + GPU 型号
  2) checkpoint 能加载
  3) 作者 demo 复现 male->about / female->above  (端到端正确性)

全过 = 环境+权重+前向在 HAKUSAN 上等价于 Mac -> exit 0 -> 下游作业自动开跑。
任一不过 -> exit 1 -> 下游作业被 SLURM 取消(状态 DependencyNeverSatisfied)。
"""
import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import os
import pickle
import sys
from pathlib import Path

import soundfile as sf
import torch
import yaml

_orig = torch.load
def _load(*a, **k):
    k["weights_only"] = False
    return _orig(*a, **k)
torch.load = _load

from src.spatial_attn_lightning import BinauralAttentionModule
import src.audio_transforms as at

REPO = Path(__file__).resolve().parents[3]
EXP1 = REPO / "reproduction/experiment_1_gender"
EXP2 = REPO / "reproduction/experiment_2_talker_count"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
CV_CLIPS = Path(os.environ.get("CV_CLIPS", REPO / "cv_clips"))

failures = []

# ---------------------------------------------------------------- [0] 资产
print("==== [0] 资产检查 ====")
ckpt_dir = REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints"
needed = {
    "checkpoint 目录": ckpt_dir,
    "demo_stimuli":    REPO / "demo_stimuli",
    "800 词表":        REPO / "cv_800_word_label_to_int_dict.pkl",
    "样本表":          EXP1 / "data/samples_expanded.csv",
    "干扰池":          EXP2 / "data/distractor_pool.csv",
    "CV clips 目录":   CV_CLIPS,
}
for name, p in needed.items():
    ok = p.exists()
    print(f"  {'OK ' if ok else 'MISSING'}  {name:14s} {p}")
    if not ok:
        failures.append(f"缺失: {name} ({p})")

n_clips = len(list(CV_CLIPS.glob("*.mp3"))) if CV_CLIPS.exists() else 0
print(f"  CV clips 数量: {n_clips}  (期望 2819)")
if n_clips < 2819:
    failures.append(f"CV clips 只有 {n_clips} 个, 期望 2819 —— 上传可能没传完")

if failures:
    print("\n==== 结果: FAIL ❌ 资产不全, 后续检查跳过 ====")
    for f in failures:
        print("  -", f)
    sys.exit(1)

# ---------------------------------------------------------------- [1] CUDA
print("\n==== [1] CUDA 检查 ====")
print(f"  torch: {torch.__version__} | 编译 CUDA: {torch.version.cuda}")
print(f"  cuda.is_available(): {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
else:
    failures.append("没检测到 GPU —— 这个作业必须跑在 GPU 节点上(-p GPU-1 -G 1)")
print(f"  DEVICE = {DEVICE}")

# ---------------------------------------------------------------- [2] 权重
print("\n==== [2] 加载 checkpoint ====")
config = yaml.load(open(REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"),
                   Loader=yaml.FullLoader)
ckpt = sorted(ckpt_dir.glob("*.ckpt"))[0]
print(f"  checkpoint: {ckpt.name}")
model = BinauralAttentionModule.load_from_checkpoint(
    checkpoint_path=str(ckpt), config=config, strict=False).eval().to(DEVICE)
coch = model.coch_gram.to(DEVICE)
print("  加载成功。")

# ---------------------------------------------------------------- [3] demo
print("\n==== [3] demo 复现 (期望 about / above) ====")
tfm = at.AudioCompose([
    at.AudioToTensor(),
    at.CombineWithRandomDBSNR(low_snr=0, high_snr=0),
    at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
    at.DuplicateChannel(),
    at.UnsqueezeAudio(dim=0),
])
with open(REPO / "cv_800_word_label_to_int_dict.pkl", "rb") as f:
    ix2w = {v: k for k, v in pickle.load(f).items()}
sd = REPO / "demo_stimuli"
fc, _ = sf.read(sd / "female_cue.wav")
mc, _ = sf.read(sd / "male_cue.wav")
ft, _ = sf.read(sd / "female_target_above.wav")
mt, _ = sf.read(sd / "male_target_about.wav")


def dev(x):
    return x.to(DEVICE).float()


def predict(cue_wav):
    cue, _ = tfm(cue_wav, None)
    mix, _ = tfm(ft, mt)
    cue_cg, _ = coch(dev(cue), None)
    mix_cg, _ = coch(dev(mix), None)
    with torch.no_grad():
        return ix2w[model(cue_cg, mix_cg).softmax(-1).argmax(1).item()]


mp, fp = predict(mc), predict(fc)
print(f"  male cue   -> True: about | Pred: {mp}")
print(f"  female cue -> True: above | Pred: {fp}")
if mp != "about" or fp != "above":
    failures.append(f"demo 不符: male->{mp}(期望 about), female->{fp}(期望 above)")

# ---------------------------------------------------------------- 结论
if failures:
    print("\n==== 结果: FAIL ❌ 下游作业将被取消 ====")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("\n==== 结果: PASS ✅ 环境等价, 下游作业自动开跑 ====")
sys.exit(0)
