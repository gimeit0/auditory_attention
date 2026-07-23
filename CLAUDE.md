# CLAUDE.md — 项目交接文档(给 Claude Code 的上下文)

> 这份文档是项目背景与任务说明。请在动手前完整读一遍。
> 用户主要用中文沟通;正式交付物(如给导师的报告/幻灯片)用日文。代码注释中英文皆可。

---

## 0. 一句话目标

复现论文 **Griffith, Hess & McDermott (2026, *Nature Human Behaviour*)** "Optimized feature gains explain and predict successes and failures of human selective listening" 中 **Experiment 1 的行为趋势**:用**自建的 Common Voice 评测集**,喂进**作者预训练好的 checkpoint**,看能否跑出和论文 **Fig 2a / 2b / 2d / 2e** 方向一致的趋势图。

**判据是趋势方向一致,不是数值复刻。** 这一点贯穿全程,任何输出都不要追求和论文数值相同。

代码仓库: `IanMGriff/auditory_attention`(本仓库)。论文 PDF 在项目里可参考。

---

## 1. 当前任务的边界(非常重要,别越界)

导师当前布置的任务是**验证性实验,不是训练**:

- ✅ 要做:自建 Common Voice 评测刺激 → 跑作者 checkpoint → 出图 → 和论文比趋势。
- ❌ 现阶段**不要训练模型**、**不要上超算**、**不需要作者的训练数据集**。
- 训练自己的模型、加"发达参数 α"是**后续阶段**,本任务不涉及(见第 7 节,仅作背景了解)。

**关键认知:作者训好的参数(θ)已经固化在 checkpoint 文件里,跑推理不需要作者的训练数据。** 你只负责构造"评测刺激"。模型设计上就是在没见过的语音上评测的(论文用 held-out 的 Spoken Wikipedia),所以用 Common Voice 当评测刺激能正常泛化。

---

## 2. 已完成的部分

1. **demo 跑通**:`run_demo_m1.py` 已能在 M1 上加载作者 checkpoint 做推理,输出正确(`male->about, female->above`)。该文件已打两个补丁(见第 6 节坑位)。
2. **配对脚本完成**:`build_pairs.py` 读 Common Voice `validated.tsv`,输出"配对清单"CSV。已验证四项配对逻辑均 100% 正确、target 性别平衡(男女各半)。
   - 配对规则:cue 与 target = **同一 client_id、不同录音**;distractor = **不同 client_id**;每个 target 配一个 same-sex 和一个 different-sex distractor;剔除了 gender 为空或标注不一致的说话人。
   - 该脚本**尚未**做:词级筛选(中间词限定 800 词)、切词、混音——这些依赖 forced alignment,是下一步。

---

## 3. 接下来的任务(按顺序)

### 任务 A(当前重点):Forced Alignment 词级对齐 —— 唯一的硬卡点

**为什么需要**:论文任务要求识别每条录音的"**中间词**"(target 报中间词;cue 以某词为中心)。Common Voice 只给整句录音 + 整句转写(`sentence` 列),**没有词级时间戳**。必须先做 forced alignment 切出每个词的起止时间。

**怎么做**:论文用的是 Wav2Vec2 forced alignment(引用 Pratap et al. 2024)。**作者团队仓库里没有现成可用的对齐代码**(本仓库只有 Whisper 转写脚本,用途不同)。请直接用 **torchaudio 官方 API**(环境里已装 torchaudio):
- 推荐高层封装:`torchaudio.pipelines.Wav2Vec2FABundle` / `MMS_FA`(打包了模型+tokenizer+对齐器)。
- 核心 API:`torchaudio.functional.forced_align()`。
- 官方教程(权威参考):
  - https://docs.pytorch.org/audio/stable/tutorials/ctc_forced_alignment_api_tutorial.html
  - https://docs.pytorch.org/audio/stable/tutorials/forced_alignment_for_multilingual_data_tutorial.html

**输出要求**:对每条用到的 CV 录音 + 其 `sentence`,产出每个词的起止时间(秒)。

**"中间词"定义**:论文片段是 2 秒、取 1 秒处的中点。中间词 = 跨越片段时间中点的那个词。请据此为每条录音标出中间词。

**技术提醒(避免踩坑)**:CTC 对齐有 "peaky" 特性,词边界时间戳可能不够精确。对"定位哪个是中间词"够用;若发现切词边界毛糙,可参考教程里的 `<star>` token 技巧改善。

### 任务 B:词级筛选 + 切词

- 用对齐结果,把每条录音的"中间词"标出来。
- 筛选:中间词必须 ∈ 800 词表(`cv_800_word_label_to_int_dict.pkl`,仓库根目录)。论文还要求词长 ≥5 字符、片段 ≤2 秒,可一并照做。
- 把 `build_pairs.py` 的配对结果与这个筛选打通(脚本里留了 `--word_table` 接口)。
- 按论文:cue/target/distractor 各切成 2.5 秒(避免边界伪影),最终取中间 2 秒。

### 任务 C:混音生成评测刺激

- 对每个 target,分别与 same-sex、different-sex distractor 混音。
- **6 个 SNR**:`-9, -6, -3, 0, +3, inf`(inf = 无干扰,distractor 置零)。逐元素相加混音。
- **diotic**:单声道波形复制到左右两声道喂模型(`run_demo_m1.py` 里的 `DuplicateChannel()` 做的就是这件事)。
- cue 和 mixture 都 **RMS 归一化到 0.02**。

### 任务 D:跑 checkpoint + 出图

- 把刺激喂作者 checkpoint(用 `run_demo_m1.py` 的加载方式),收集预测。
- 评分(照论文):预测词匹配 target 句中**任一在词表内的词**即算正确;confusion = 预测词出现在 distractor 句的转写里。
- 聚合并画:
  - **Fig 2a**:prop. target word vs SNR(单语音干扰)
  - **Fig 2b**:same-sex vs different-sex distractor
  - **Fig 2d**:confusion vs SNR
  - **Fig 2e**:confusion,按 same/different-sex 分开
- (加分)**Fig 2c**:英语 vs 普通话干扰(CV 9 有中文 dev 集,可做)。

**判趋势是否复现**(方向对即成功):SNR 升高→准确率升;different-sex 准确率 > same-sex;SNR 降低→confusion 增多;same-sex 的 confusion 更高。

### 不做的(超出当前范围)

- 噪声/音乐/纹理干扰(Fig 2g/h,需 AudioSet)——defer。
- harmonicity(Fig 2f,需 STRAIGHT)——defer。
- 所有空间实验(Fig 3/4,需 HRTF/房间渲染)——**不做**,本项目走 diotic。
- 训练模型、发达参数 α——后续阶段,当前不做。

---

## 4. 评测集必须满足的结构约束(命门,不可省)

1. 词级对齐(forced alignment)已做。
2. target 中间词 ∈ 800 词表。
3. cue / target = 同一 client_id、不同录音、中间词不同。
4. distractor = 不同 client_id。
5. 每个 target 配 same-sex + different-sex 各一个单语音 distractor(靠 `gender` 字段)。
6. 6 个 SNR(-9/-6/-3/0/+3/inf)。
7. diotic(单声道复制到左右)。
8. cue 和 mixture RMS 归一化到 0.02。
9. target 性别平衡(男女各半);说话人 speaker-disjoint(评测说话人尽量与训练无重叠,用 held-out 更干净)。

---

## 5. 环境与路径信息

- **机器**:Apple Silicon Mac (M1)。
- **环境**:conda env `audattn`,Python 3.11,已装 torch 2.12 / torchaudio / pandas / chcochleagram 等。
- **本仓库**:`~/projects/auditory_attention`
- **Common Voice 9.0 英语**:`/Users/gigi/论文/计划书/cv-corpus-9.0-2022-04-27/en/`
  - `validated.tsv`(列:client_id, path, sentence, up_votes, down_votes, age, gender, accents, locale, segment)
  - `clips/`(音频 mp3;`path` 列是文件名,拼到此目录读取)
  - 数据量充足:155 万行,有性别标注 97 万,女声说话人 3788 个——性别平衡不会缺料。
- **词表**:`cv_800_word_label_to_int_dict.pkl`(仓库根目录)
- **checkpoint**:`attn_cue_models/word_task_v10_main_feature_gain_config/checkpoints/epoch=1-step=24679-v1.ckpt`
- **config**:`config/binaural_attn/word_task_v10_main_feature_gain_config.yaml`
- **demo 刺激**:`demo_stimuli/`
- **已有脚本**:`run_demo_m1.py`(推理 demo)、`build_pairs.py`(配对清单)

---

## 6. 已知的坑(务必沿用现有解法,别重新踩)

1. **PyTorch ≥2.6 加载 checkpoint 失败**(`weights_only` 报错):checkpoint 来自作者 OSF(可信源),需 `torch.load(..., weights_only=False)`。`run_demo_m1.py` 已用 monkeypatch 解决,沿用即可。
2. **scipy 删除了 `scipy.signal.hann`**:已加垫片 `scipy.signal.hann = scipy.signal.windows.hann`(在 import 前)。沿用。
3. **库版本比 repo 新**(numpy 2.x / scipy 1.17 / torch 2.12 vs repo 的 1.26/1.11/2.1):可能还会遇到零星 API 改名/删除的报错,优先在新版库上做兼容垫片,**不要降级到让 demo 失效**。
4. **不要把 `.cuda()` 留着**:M1 无 CUDA。用 `device = "cpu"`(MPS 对耳蜗前端算子支持不全,默认 CPU 最稳;推理只是几百条短音频,CPU 足够)。

---

## 7. 背景知识(理解模型用,当前任务不动这些)

- **任务**:听一段 cue(目标说话人的一段录音)→ 听 cue+distractor 的混音 → 报混音中目标说话人的中间词。
- **gain 机制**:每层一个 sigmoid `g = θ1 + (1-θ1)·σ(θ2·(m_cue - θ3))`,逐元素乘到 mixture 特征上。cue 里强的特征 gain→1(放行),弱的→θ1(压制)。
  - θ1/θ2/θ3 = bias/slope/threshold,是训练学到、**冻结**的参数(代码 `src/spatial_attn_architecture.py` 的 `SimpleAttentionalGain`,是 `nn.Parameter`)。
  - **gain 随 cue 动态变化**(m_cue 来自当前 cue 输入),但 θ 固定。
- **发达参数 α(后续阶段才做,当前不实现)**:导师设想在 gain 上乘一个"发达成熟度" α。
  - 正确写法:`gain = 1 - alpha*(1 - gain)`(α=1 成人,α→0 不压制=幼态)。
  - **不能写 `alpha*gain`**:gain 后面紧跟 layer normalization,均匀缩放会被归一化抵消。
  - α 必须是**外部固定的普通属性**(`self.alpha`),**不能是 `nn.Parameter`**(否则会被学回 1)。
  - 再次强调:**当前验证任务不涉及 α**,这里只为背景完整。

---

## 8. 工作方式建议

- **一次一个子任务**:任务 A→B→C→D 顺序推进,每步先在**小样本**(如 20–50 条)验证,再放大。
- 每个脚本写完后,打印**自检信息**(像 `build_pairs.py` 那样:比例、计数、分布),便于用户核对。
- 涉及改文件/跑命令前,向用户说明意图。
- 实验**设计判断**(判据、取舍、范围)由用户拍板;Claude Code 负责把管线实现、调通。

# 模型有效性已验证:用论文预训练checkpoint(word_task_v10),在44个clean样本上中间词识别准确率88.6%(exact=lenient,随机基线0.1%),失配集中在功能词/多锚点难例。管线打通:对齐→以目标词为中心切片→checkpoint推理。Task C/D(SNR/distractor/趋势图)待定,若要画趋势图需先扩数据(当前~44样本偏少)。

# Fig 2a 复现成功(2026-06)。全量 600 样本 SNR 扫描,中间词识别准确率随 SNR 严格单调上升:[-9:26%, -6:35%, -3:46%, 0:55%, +3:63%, inf:88%],与论文 Fig 2a 趋势一致。inf 档 88% 与 clean 验证 88.6% 互证。within-item 方法,same-sex distractor,diotic。结果在 snr_scan_results.csv。CPU 跑全量约 6.5h(GPU 会快几十倍,以后上 hakusan)。
