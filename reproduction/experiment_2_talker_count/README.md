# Experiment 2：干扰说话人数

本实验复用实验1的600个 target/cue，比较1、2、4和8名干扰说话人条件。各条件采用 target-to-total-masker SNR，使相同SNR下的总干扰能量一致。

## 主要内容

- `data/distractor_pool.csv`：1,200名不同说话人的带锚点干扰池，男女各600名，与目标/cue说话人无重叠。
- `scripts/build_distractor_pool.py`：构建带锚点干扰池。
- `scripts/snr_scan_multi.py`：多话者评测基础管线。
- `scripts/plot_multi_talker.py`、`plot_multi_talker_final.py`：结果图。
- `scripts/make_ppt_groupmeeting.py`：同时汇报两个实验的英文PPT生成程序。
- `docs/`：计划评审、RTX 3070部署说明和导师汇报。

实验1的共享样本位于：

```text
reproduction/experiment_1_gender/data/samples_expanded.csv
```

## 运行

所有命令从仓库根目录运行。查看参数：

```bash
conda run -n audattn python -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi --help
```

正式评测：

```bash
conda run -n audattn python -m reproduction.experiment_2_talker_count.scripts.snr_scan_multi
```

完整的18,600行增强版结果、最终图片和中英日汇报材料已经从此前的外部结果目录复制回来，分别保存在 `results/`、`figures/` 和 `presentations/`。原外部目录仍然保留，没有删除。
