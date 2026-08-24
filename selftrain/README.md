# Diotic self-training

这个文件夹集中保存“使用自己的 Common Voice 数据、从随机权重训练 feature-gain 模型”的全部专用内容。所有命令都应从仓库根目录运行：

```bash
cd /Users/gigi/projects/auditory_attention
```

## 文件结构

```text
selftrain/
├── README.md                 # 本说明
├── configs/
│   ├── smoke.yaml           # 1步训练/验证检查
│   └── full.yaml            # HAKUSAN正式训练
├── data/
│   └── diotic_attention.py  # 在线组合cue/target/distractor
├── scripts/
│   ├── prepare_splits.py    # 建立无说话人泄漏的数据划分
│   ├── build_anchor_catalog.py
│   ├── check_dataset.py
│   └── check_readiness.py
├── hakusan/
│   ├── upload.sh
│   ├── run_alignment.sbatch
│   └── run_training.sbatch
├── docs/
│   └── 训练模型_设计方案.md
├── full_scale_task2_2026-07-23/ # 会议任务2的正式全量实验计划与记录
├── artifacts/               # 生成的划分、对齐和锚点（Git忽略）
└── experiments/             # 自训checkpoint与日志（Git忽略）
```

`src/` 中的训练入口和音频变换是整个仓库共用的底层代码，因此没有移动进来。

任务2正式全量实验的范围、启动门槛、HAKUSAN操作步骤和记录模板见：

```text
selftrain/full_scale_task2_2026-07-23/README.md
```

## 当前状态

- 数据划分已完成，train / validation / 既有复现实验说话人重叠为0。
- 小规模锚点目录、动态数据集和随机初始化 smoke training 已通过。
- 2026-07-26两轮HAKUSAN对齐后，训练已覆盖800/800个可配对词，
  dev-only验证覆盖681/800，低于700词门槛。
- dev候选已经耗尽，因此验证候选已显式扩展为官方dev+test；两者与训练及既有
  评测说话人仍保持零重叠。正式训练前需对新增test候选完成强制对齐。

查看 readiness：

```bash
conda run -n audattn python -m selftrain.scripts.check_readiness
```

重新检查动态数据集：

```bash
conda run -n audattn python -m selftrain.scripts.check_dataset --batch-size 2
```

本地 smoke training：

```bash
conda run -n audattn python -m src.spatialtrain \
  --config selftrain/configs/smoke.yaml \
  --exp_dir selftrain/experiments \
  --gpus 0 --n_jobs 0 --precision 32-true
```

## HAKUSAN

本地上传：

```bash
bash selftrain/hakusan/upload.sh
```

HAKUSAN 上扩大锚点目录：

```bash
sbatch selftrain/hakusan/run_alignment.sbatch
```

readiness 达标后从随机权重正式训练：

```bash
sbatch selftrain/hakusan/run_training.sbatch
```

从本项目自己生成的 checkpoint 恢复中断作业：

```bash
RESUME=1 sbatch selftrain/hakusan/run_training.sbatch
```
