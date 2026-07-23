import scipy.signal
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann
"""
Quick-start demo adapted for Apple Silicon (M1/M2) — CPU inference.

Differences from the README quick-start:
  - No .cuda() calls. Runs on CPU (safe for the cochleagram front-end on macOS).
    You can try MPS by setting DEVICE = "mps", but some FFT/complex ops in the
    cochleagram may be unsupported there; CPU is reliable and the demo is tiny.
  - Auto-finds the checkpoint .ckpt under attn_cue_models/ (filename can vary).
  - Clear error messages if the OSF assets aren't downloaded yet.

Run from the repo root:
    python run_demo_m1.py
"""
import pickle
from pathlib import Path

import yaml
import soundfile as sf
import torch

_torch_orig_load = torch.load
def _torch_load_full(*args, **kwargs):
    kwargs["weights_only"] = False
    return _torch_orig_load(*args, **kwargs)
torch.load = _torch_load_full

from src.spatial_attn_lightning import BinauralAttentionModule
import src.audio_transforms as at

DEVICE = "cpu"  # change to "mps" to try Apple GPU (may hit unsupported ops)
REPO = Path(__file__).resolve().parent


def _require(path: Path, hint: str) -> Path:
    if not path.exists():
        raise SystemExit(
            f"\n[Missing] {path}\n  -> {hint}\n"
            "  Download the OSF archives (attn_cue_models, demo_stimuli) from\n"
            "  https://doi.org/10.17605/OSF.IO/WJZVU and unzip them into the repo root.\n"
        )
    return path


# --- config + checkpoint -----------------------------------------------------
config_path = REPO / "config/binaural_attn/word_task_v10_main_feature_gain_config.yaml"
config = yaml.load(open(config_path, "r"), Loader=yaml.FullLoader)

ckpt_dir = _require(
    REPO / "attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints",
    "Checkpoint folder not found — unzip attn_cue_models.zip into the repo root.",
)
ckpts = sorted(ckpt_dir.glob("*.ckpt"))
if not ckpts:
    raise SystemExit(f"No .ckpt file inside {ckpt_dir}")
ckpt_path = ckpts[0]
print(f"Using checkpoint: {ckpt_path.name}")

model = BinauralAttentionModule.load_from_checkpoint(
    checkpoint_path=str(ckpt_path), config=config, strict=False
).eval().to(DEVICE)
coch_gram = model.coch_gram.to(DEVICE)

# --- audio transforms --------------------------------------------------------
SNR = 0  # dB; equal low/high pins the SNR to this value
audio_transforms = at.AudioCompose([
    at.AudioToTensor(),
    at.CombineWithRandomDBSNR(low_snr=SNR, high_snr=SNR),
    at.RMSNormalizeForegroundAndBackground(rms_level=0.02),
    at.DuplicateChannel(),
    at.UnsqueezeAudio(dim=0),
])

# --- word label dictionary ---------------------------------------------------
with open(REPO / "cv_800_word_label_to_int_dict.pkl", "rb") as f:
    word_to_ix_dict = pickle.load(f)
class_ix_to_word = {v: k for k, v in word_to_ix_dict.items()}

# --- demo stimuli ------------------------------------------------------------
outdir = _require(REPO / "demo_stimuli", "demo_stimuli folder not found — unzip demo_stimuli.zip.")
female_cue, _ = sf.read(outdir / "female_cue.wav")
male_cue, _ = sf.read(outdir / "male_cue.wav")
female_target, _ = sf.read(outdir / "female_target_above.wav")
male_target, _ = sf.read(outdir / "male_target_about.wav")
female_target_word, male_target_word = "above", "about"

# mix the two talkers, prep each cue
mixture, _ = audio_transforms(female_target, male_target)
female_cue, _ = audio_transforms(female_cue, None)
male_cue, _ = audio_transforms(male_cue, None)


def to_dev(x):
    return x.to(DEVICE).float()


female_cue_cgram, male_cue_cgram = coch_gram(to_dev(female_cue), to_dev(male_cue))
mixture_cgram, _ = coch_gram(to_dev(mixture), None)

# --- predictions -------------------------------------------------------------
with torch.no_grad():
    logits = model(male_cue_cgram, mixture_cgram)
    male_pred = logits.softmax(-1).argmax(dim=1).item()
    print(f"Male cue   -> True: {male_target_word:6s} | Predicted: {class_ix_to_word[male_pred]}")

    logits = model(female_cue_cgram, mixture_cgram)
    female_pred = logits.softmax(-1).argmax(dim=1).item()
    print(f"Female cue -> True: {female_target_word:6s} | Predicted: {class_ix_to_word[female_pred]}")

print("\nExpected: 'about' for the male cue, 'above' for the female cue (same mixture).")
