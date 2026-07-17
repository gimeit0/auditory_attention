#!/bin/bash
# HAKUSAN 环境搭建脚本 —— 在【登录节点 hakusan1】上运行(登录节点不跑重活, 只建环境)。
# 前提: miniconda 已装在 ~/conda 且已 source(见 部署清单_HAKUSAN.md 步骤 2)。
# 用法: cd 到本 hakusan_deploy 目录后执行  bash setup_env_hakusan.sh
set -e

echo "==== [1/4] 建 conda 环境 audattn (torch 2.1.1 / CUDA 11.8) ===="
# 若 JAIST 镜像里 pytorch/nvidia 频道不可达, 这一步会报错 ->
# 改用 部署清单 里的【B 方案: pip 装 torch】或【C 方案: Singularity pytorch 容器】。
conda env create -f environment_hakusan.yml

echo "==== [2/4] 激活 ===="
source ~/conda/etc/profile.d/conda.sh
conda activate audattn

echo "==== [3/4] 装 chcochleagram (纯 python, 直接放进 site-packages) ===="
SP=$(python -c "import site; print(site.getsitepackages()[0])")
tar xzf chcochleagram.tar.gz -C "$SP"
echo "已解压到: $SP"

echo "==== [4/4] 验证 import(CPU 层面, GPU 验证在 GPU 节点做) ===="
python - <<'PY'
import torch, torchaudio, chcochleagram, num2words, soundfile, yaml, pandas, scipy
from pytorch_lightning import LightningModule
print("imports OK")
print("torch", torch.__version__, "| torchaudio", torchaudio.__version__)
print("torch 编译的 CUDA 版本:", torch.version.cuda)
PY

echo
echo "==== 完成。下一步: 在 GPU 节点验证 torch.cuda 和 demo(见 部署清单 步骤 6) ===="
