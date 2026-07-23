# HAKUSAN 部署清单（2026-07-13 更新版）

> 2026-07-21：部署文件已整理到 `reproduction/deployment/hakusan/`，实验脚本与数据分别位于两个实验目录。

> ⚠️ **本文件已按超算实际现状重写。** 旧版写的「建 conda 环境」**不再需要**——环境和官方仓库都已在超算上建好。
> 现在只差：**把我们自己的复现脚本 + checkpoint + 用到的 CV 音频传上去**。

---

## 一、超算现状（已完成，不用重做）

| 项 | 状态 |
|---|---|
| 登录 | `ssh s2510040@hakusan1`（校网/VPN 内）✅ 已确认可登录 |
| conda 环境 | `/home/s2510040/miniconda3/envs/attn` ✅ torch 2.1.1+cu118 / pl 2.1.1 / chcochleagram，与论文 `requirements.txt` 一致 |
| 官方仓库 | `/home/s2510040/selective_listening_repro/code/auditory_attention/` ✅ 含 `src/`、`config/`、词表 |
| 调度器 | SLURM；GPU 分区 `GPU-1`(A40) / `GPU-1A`(A100) |

> ❗**另一个环境 `auditory_attention`（py3.13 / torch 2.5.1）不要用**——torch 版本与论文不符。
> ❗**别把带 ``` 反引号的 markdown 整段粘进终端**（之前把 shell 卡死过）。只粘纯命令。

## 二、还缺什么

超算上 `find ~ -iname "*.ckpt"` 为空 → **模型权重还没上去**。另外我们自己写的复现管线（对齐/切片/混音/评分）也不在超算上。
**不用去 OSF 下载**——这些东西你 Mac 上都有（Fig 2a/2b/2e 就是用它们跑出来的），直接传，不依赖超算外网。

要传的（合计约 **900 MB**）：

| 内容 | 大小 |
|---|---|
| `attn_cue_models/`（checkpoint） | ~754 MB |
| 用到的 CV 音频子集（**不是 79GB 全量**） | ~130 MB |
| 复现脚本 + `samples_expanded.csv` + `distractor_pool.csv` + `demo_stimuli/` | 几 MB |

---

## 三、操作步骤

### 步骤 1 — 建带锚点的干扰池（**本地 Mac**，多干扰面板要用）

```
python -m reproduction.experiment_2_talker_count.scripts.build_distractor_pool --n 1200
```
约 15 分钟。产出 1200 条干扰录音（1200 个不同说话人、男女各半、与 target 说话人无重叠），
每条都以一个**表内锚点词**为中心——这样多干扰面板的**混淆率才有可比量级**
（现有 1200 条随机干扰是 Fig 2e 低估 4–5 倍的根因）。

### 步骤 2 — 上传（**本地 Mac**）

```
bash reproduction/deployment/hakusan/upload_to_hakusan.sh
```
脚本会自动算出要传哪些 clips（`make_clip_list.py`），只传这些，不传全量语料。

### 步骤 3 — GPU 等价性校验（**超算**，关键！先验证再跑全量）

```
salloc -p GPU-1 -c 8 -G 1
conda activate /home/s2510040/miniconda3/envs/attn
cd ~/selective_listening_repro/code/auditory_attention
python reproduction/deployment/hakusan/check_hakusan.py
exit
```
**期望**：`cuda.is_available(): True` + `male->about / female->above` + `PASS ✅`
通过 = 环境+权重+前向在 HAKUSAN 上等价于 Mac。**不过就别跑全量，先排查。**

或用批处理：`sbatch reproduction/deployment/hakusan/run_check.sbatch` → `squeue -u $USER` → 看 `reproduction/deployment/hakusan/logs/`。

### 步骤 4 — 复跑单干扰扫描，做交叉验证（**超算**）

编辑 `reproduction/deployment/hakusan/run_gpu.sbatch` 末尾，换成：
```
python -u -m reproduction.experiment_1_gender.scripts.snr_scan --dist_col same_dist_path --out reproduction/experiment_1_gender/results/snr_scan_results_gpu.csv
```
提交：`sbatch reproduction/deployment/hakusan/run_gpu.sbatch`

**自洽判据**：结果应复现 Mac 上的 `[26, 35, 46, 55, 63, 88]%`（±小幅抖动）。
对上了 = GPU 管线可信，可以放心跑新实验。Mac 上 6.5 小时的活，GPU 上几分钟。

> 脚本已改成**自动选设备**（`torch.cuda.is_available()`），不用再手动改 `DEVICE`。
> CV 音频路径通过 `CV_CLIPS` 环境变量读取，`run_gpu.sbatch` 里已经设好。

### 步骤 5 — 多干扰面板（待实现 `snr_scan_multi.py`）

条件：`no_distractor / one_talker / two_talker / four_talker / babble` × SNR `-9/-6/-3/0/+3`。
细节见《干扰数量面板_复现计划书.md》和《干扰数量面板_计划评审.md》。

---

## 四、拉结果回 Mac（本地运行）

```
rsync -avz s2510040@hakusan1:~/selective_listening_repro/code/auditory_attention/*.csv /Users/gigi/projects/auditory_attention/
```

## 五、常用 SLURM 命令

```
squeue -u $USER          # 看自己的作业
scancel <JOBID>          # 取消作业(占错节点务必取消)
sinfo -p GPU-1           # 看 GPU 分区空闲情况
```

---

## 六、分工

**Claude Code 全程留在 Mac 上**（它不能 SSH 上超算）：负责改代码、写作业脚本、生成命令、分析拉回来的结果。
**超算上的命令由你手动粘贴执行**，把输出贴回来给它看。

## 七、本目录文件

| 文件 | 用途 |
|---|---|
| `部署清单_HAKUSAN.md` | ⭐ 本文件 |
| `upload_to_hakusan.sh` | 一键上传（脚本 + clips 子集 + checkpoint） |
| `make_clip_list.py` | 算出要传哪些 CV clips |
| `check_hakusan.py` | GPU 等价性校验（demo about/above） |
| `run_check.sbatch` / `run_gpu.sbatch` | SLURM 作业模板 |
| ~~`environment_hakusan.yml`~~ / ~~`setup_env_hakusan.sh`~~ / ~~`chcochleagram.tar.gz`~~ | **已不需要**（环境已存在）；留作备份 |
