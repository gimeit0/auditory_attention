# 两个复现实验

这里集中保存使用作者预训练 checkpoint 完成的两个定性复现实验。它们与 `selftrain/` 中的随机初始化训练是不同阶段。

## 文件结构

```text
reproduction/
├── experiment_1_gender/          # 同性/异性单干扰实验
│   ├── README.md
│   ├── scripts/
│   ├── data/
│   ├── results/
│   ├── figures/
│   ├── docs/
│   ├── presentations/
│   ├── audio_examples/
│   └── archive/                  # 被600条正式评测替代的早期44条管线
├── experiment_2_talker_count/    # 1/2/4/8名干扰说话人实验
│   ├── README.md
│   ├── scripts/
│   ├── data/
│   ├── results/
│   ├── figures/
│   ├── docs/
│   └── presentations/
├── analysis/                     # 两个实验共用的silence/有效SNR审计
├── docs/                         # 同时总结两个实验的文档
└── deployment/                   # HAKUSAN和RTX 3070部署材料
```

模型 checkpoint、800词表、`src/`、`align_words.py`、`slice_stimuli.py` 和 demo 音频由两个实验及自训练流程共用，因此继续保留在仓库根目录。

## 快速检查

所有命令从仓库根目录运行：

```bash
cd /Users/gigi/projects/auditory_attention
```

重新生成实验1三张结果图：

```bash
conda run -n audattn python -m reproduction.experiment_1_gender.scripts.plot_fig2a
conda run -n audattn python -m reproduction.experiment_1_gender.scripts.plot_fig2b
conda run -n audattn python -m reproduction.experiment_1_gender.scripts.plot_fig2e
```

检查实验脚本参数：

```bash
conda run -n audattn python -m reproduction.experiment_1_gender.scripts.snr_scan --help
conda run -n audattn python -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi --help
```

重新审计完整2.5秒与模型中央2秒之间的有效SNR差：

```bash
conda run -n audattn python reproduction/analysis/silence_snr_audit.py
```

实验1可从保存的刺激元数据精确复算；实验2最终CSV没有保存每次使用的干扰音ID，
因此该部分按已记录的性别平衡与嵌套设计重建，并在输出中明确标注，不作为原始运行ID使用。
