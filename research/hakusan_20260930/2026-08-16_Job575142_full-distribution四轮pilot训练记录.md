# Job 575142 full-distribution 四轮 pilot 训练记录

- 实验日期：2026-08-15 至 2026-08-16
- Slurm Job ID：`575142`
- RUN_ID：`fullpilot4_accum9_20260815_181000`
- 阶段：`pilot4`
- 初始化：随机初始化
- 作业计算状态：`COMPLETED 0:0`
- 阶段审查状态：`COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW`

## 1. 实验目的

本作业是正式 40 轮 full-distribution 训练的前四轮受控 pilot，不是一个与后续 full 无关的临时模型。它的目的是在投入第 5--40 轮之前确认：

1. 正式 full 数据分布能否从随机初始化正常学习；
2. `batch_size=32` 和 `accumulate_grad_batches=9` 在四轮训练中是否持续稳定；
3. AMP overflow 门禁、checkpoint、状态记录和恢复链是否完整；
4. 模型在混合 full validation 上是否已出现明确学习趋势；
5. 是否值得进一步运行事先冻结的 10,000-scene 分层科学评估。

本作业不从 Job 551219 的单干扰 0 dB checkpoint 续训。Job 551219/565217 只提供“模型在受控条件下确实能使用 cue”的前置科学证据；Job 575142 则从随机初始化独立测试 full 分布。

## 2. 提交前门禁

提交时使用 `selftrain/hakusan/submit_training.sh`，而不是直接 `sbatch run_training.sbatch`。包装器在正式提交前完成了：

- 42 项 checkpoint、状态机、numerics PASS、cue release 和 pilot evaluator 回归测试；
- 9 项训练安全检查；
- Job 565217 的 10,000-trial cue-control 逐 trial 重算；
- Job 566556 accumulation=9 A100 numerics PASS 重新验证；
- full 配置的 pilot4 预算算术检查；
- 运行源码、配置和数据输入快照冻结；
- Slurm `--test-only` 调度检查。

前置门禁结果：

```text
Cue release      = RELEASED_FOR_FULL_DISTRIBUTION_PILOT
Cue primary      = CONFIRMATORY_PASS
Numerics PASS    = PASS (schema 3)
Training phase   = PASS
```

`--test-only` 显示的 `575141` 只是估算编号，没有真正运行。正式提交的 Job ID 为 `575142`。

## 3. 冻结配方

### 3.1 数据和场景

- 任务：800 类目标词分类；
- cue：目标说话人的 voice cue；
- 干扰者数：1--4；
- target 与合计 background 的标称 SNR：每例在 −10 至 +10 dB 之间抽样；
- `cue_free_percentage=0.1`；当前实现会同时把 cue 和 background 清零，因此这10%实际为 target-only/clean 样本；
- target gender 和 target word 做平衡抽样；
- 随机种子：`20260721`。

### 3.2 训练预算

| 项目 | 每轮 | 4 轮合计 |
|---|---:|---:|
| 在线合成训练场景 | 499,968 | 1,999,872 |
| micro-batches | 15,624 | 62,496 |
| optimizer attempts | 1,736 | 6,944 |

其他主要配置：

```text
batch_size                    = 32
accumulate_grad_batches       = 9
effective_batch_size          = 288
optimizer                     = AdamW
learning_rate                 = 5e-5
precision                     = 16-mixed
gradient_clip_norm            = 100
configured_total_epochs       = 40
pilot_fit_max_epochs          = 4
```

`499,968 = 32 × 9 × 1,736`，因此每轮没有不完整的最后一次 accumulation。

### 3.3 训练前冻结评估 bank

在模型构造和第一次 optimizer step 之前，runner 使用 seed `20260816` 生成并冻结：

```text
selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/evaluation/pilot4/frozen_bank.tsv
```

对应冻结状态：

```text
selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/state/PILOT4_BANK_FROZEN.json
```

bank 共计 10,000 个 prediction-independent 场景：

- 9,000 个 mixed 场景：4 个 distractor-count × 5 个 SNR bins × 每格 450；
- 1,000 个 clean/target-only 场景；
- 每个分层格 target gender 平衡；
- 其中 2,000 个场景预先指定为 correct/shuffled/silent/distractor cue 配对控制子集。

这保证后续不能在看到 pilot 结果后再重新选择场景或分析条件。

## 4. Slurm 运行过程

```text
JobID      = 575142
Partition  = GPU-1A
Node       = spcc-a100g05
Start      = 2026-08-15T18:13:06
End        = 2026-08-16T22:59:17
Elapsed    = 1-04:46:11
State      = COMPLETED
ExitCode   = 0:0
```

作业申请 36 小时，实际用时约 28 小时 46 分，未触发 time limit。

日志最终标记：

```text
FORMAL TRAINING PILOT4 COMPLETE:
RUN_ID=fullpilot4_accum9_20260815_181000
```

日志检查未显示 `Traceback`、`ERROR:`、`FloatingPointError` 或 `Non-finite` 终止。

## 5. 学习趋势

用户已从作业日志归档全部四个完整 epoch summary：

| 完成轮次 | train loss | train accuracy | validation loss | validation accuracy | AMP overflow |
|---|---:|---:|---:|---:|---:|
| epoch 0（第1轮） | 6.38 | 1.06% | 5.84 | 2.98% | 0 |
| epoch 1（第2轮） | 5.34 | 7.73% | 4.83 | 13.50% | 2 |
| epoch 2（第3轮） | 4.34 | 19.80% | 4.16 | 21.80% | 0 |
| epoch 3（第4轮） | 3.63 | 31.00% | 3.75 | 27.90% | 1 |

四轮中 train/validation loss 逐轮下降，train/validation accuracy 逐轮上升。从第一轮到第四轮：

- train loss 从 6.38 降到 3.63；
- train accuracy 从 1.06% 升到 31.00%；
- validation loss 从 5.84 降到 3.75；
- validation accuracy 从 2.98% 升到 27.90%。

800 类随机 top-1 只有 `1/800 = 0.125%`，第四轮 aggregate validation accuracy 27.9% 约为随机水平的 223.2 倍。这是 full 配方在四轮内持续学习的强描述性证据。

之前在 epoch 3 完成前 81% 处看到的 `val_acc=0.218` 是 Lightning 保留的上一次 validation 值；本次已用最终 `AMP epoch summary: epoch=3` 确认第四轮真实最终值为 `val_acc=0.279`。

上述 validation 仍是内置 aggregate validation，混合了 1--4 名干扰者、不同 SNR 和 10% clean/target-only 样本。它可以证明学习趋势，不能单独作为后续 36 轮的科学 GO 标准。

## 6. AMP 和 optimizer 完整性

`PILOT4_COMPLETE.json` 记录：

```text
expected optimizer attempts     = 6,944
global_step                     = 6,944
successful optimizer steps      = 6,941
AMP overflows                   = 3
```

数量关系一致：

```text
6,941 successful updates + 3 AMP skips = 6,944 attempts
```

AMP overflow 率为：

```text
3 / 6,944 = 0.0432%
```

这三次 overflow 均被 AMP/GradScaler 正常处理，没有超过累计上限 64，也没有触发非有限值或连续/窗口 overflow 安全中止。就已提供的证据而言，该 pilot 的数值稳定性通过。

第四轮单轮数值记录为：

```text
epoch_attempts          = 1,736
epoch_successful_steps  = 1,735
epoch_overflows         = 1
window_overflows        = 0/1000
final GradScaler scale  = 32,768
final grad_norm         = 16.20
```

## 7. 最终 checkpoint 与阶段状态

最终 checkpoint：

```text
selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/full/checkpoints/pilot4-final.ckpt
```

Checkpoint SHA-256：

```text
c61af82c1ce32071616a81f992bcf25edfb06476e6c3a87542103cf3eb2a28ba
```

结构化状态：

```text
selftrain/experiments/runs/fullpilot4_accum9_20260815_181000/state/PILOT4_COMPLETE.json
```

关键字段：

```text
schema_version                 = 1
status                         = COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW
run_phase                      = pilot4
completed_epochs               = 4
last_completed_epoch_index     = 3
checkpoint_epoch               = 4
global_step                    = 6,944
expected_final_global_step     = 6,944
effective_batch_size           = 288
```

实际 checkpoint 的 basename、SHA、epoch 和 global step 与阶段计划完全一致，因此它可作为后续冻结评估的 pilot-final 输入。

## 8. 本次已经成功的部分

现在可以确认：

- Slurm 作业成功完成；
- 四轮预算和 6,944 attempts 全部走完；
- 模型在内置 aggregate validation 上出现强学习趋势；
- AMP 数值门禁未触发中止；
- 随机初始化路径正常；
- 最终 checkpoint 已按计划固化并绑定 SHA；
- `PILOT4_COMPLETE.json` 已生成；
- 训练前的冻结评估 bank/state 已建立。

## 9. 尚未完成的科学审查

`COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW` 不是失败，也不是 `GO`。它表示：训练计算已经通过，但后续 full continuation 仍被独立科学门禁锁定。

下一步必须使用事先冻结的 10,000-scene bank，对：

1. `stage-0.ckpt`；
2. `pilot4-final.ckpt`

做完全相同场景的配对评估，并分开报告：

- overall 和 mixed-only accuracy/cross-entropy 改善；
- clean/target-only 准确率；
- 1/2/3/4 名干扰者分层；
- 5 个 SNR bins 分层；
- correct/shuffled/silent/distractor cue 配对差异；
- target-speaker cluster bootstrap 95% CI。

GPU evaluator 只生成 `PILOT4_EVAL.json` 和逐 trial CSV，不会自动生成 `PILOT4_GO.json`。只有当冻结评估结论为 GO，并且人工 review 和 release checker 均通过后，才可以从上述 `pilot4-final.ckpt` 继续第 5--40 轮。

## 10. 结论

Job 575142 的四轮 full-distribution pilot **训练计算阶段成功**。作业以 `COMPLETED 0:0` 结束，完成全部 1,999,872 个在线合成训练场景和 6,944 次 optimizer attempts，并安全处理三次 AMP overflow。最终 checkpoint 与预期 step/哈希一致，学习曲线在前三个完整轮次中明显改善。

但该记录不将“训练完成”误写为“已放行 40 轮”。当前正确结论仍是：

```text
COMPUTATION_COMPLETE_PENDING_SCIENTIFIC_REVIEW
```

下一步是提交 `run_full_pilot_eval.sbatch` 运行冻结配对评估，而不是直接继续 36 轮。

## 11. 2026-08-17 冻结评估进度更新

后续冻结评估 Job 584990 已在 `spcc-a100g02` 完成：

```text
State                         = COMPLETED
ExitCode                      = 0:0
Elapsed                       = 00:24:17
engineering_status            = PASS
decision                      = GO
result rows                   = 10,000
all preregistered gates       = true
```

在同一批训练前冻结的场景上：

- overall accuracy：0.24% → 28.22%；
- mixed-only accuracy：0.267% → 24.867%；
- clean accuracy：0.00% → 58.40%；
- cue-control correct/shuffled/silent accuracy：23.65% / 11.05% / 17.00%；
- correct 相对最强 control 的优势为 +6.65 个百分点，高于预注册 +5 个百分点门禁。

7 项预注册门禁全部通过。完整分层、CI、哈希和科学边界另见：

`2026-08-17_Job584990_full-pilot冻结10k科学评估记录.md`

这将训练阶段从“等待科学评估”推进为“冻结 evaluator 已 GO”，但仍需要完成人工 review 并由 `pilot_release.py` 原子生成、二次验证 `PILOT4_GO.json`，才能正式提交第 5--40 轮。

## 12. 2026-08-17 正式 pilot release 完成

用户已审阅 Job 584990 的 overall、mixed、clean、cue、SNR、干扰者数和 gender 分层，并明确批准继续 full。

`pilot_release create` 从冻结逐 trial 结果独立重算门禁并生成 `state/PILOT4_GO.json`，随后 `pilot_release validate` 二次验证通过。

```text
schema_version                 = 2
status                         = GO
approved_at UTC                = 2026-08-17T00:44:08.784369+00:00
pilot_global_step              = 6,944
pilot checkpoint SHA256        = c61af82c1ce32071616a81f992bcf25edfb06476e6c3a87542103cf3eb2a28ba
review record SHA256           = 82ebbb1533b4a632a1212d7e4c81dbf19b8145c8217218a36b2ca5fa4b2c5562
cue-control release SHA256     = 06f0f91ce292ffa49db1eee71618fa01d4c8fabbecf0129295e8ffefa89547a3
pilot completion SHA256        = ac6b1e12d99899f926abe7ac8a3e313b9e90e13cde91b1c8b3d8011b9470f64c
```

这表示已正式获准从同一 `RUN_ID` 的 `pilot4-final.ckpt` / global step 6,944 继续 full phase。截至本次更新，full continuation 尚未提交或启动。

## 13. 2026-08-20 full continuation 中期更新

首次 full continuation 已作为 Slurm Job `587802` 提交，并从 `pilot4-final.ckpt` / global step 6,944 正常恢复。截至用户归档的完整日志，已完成 `epoch 4--12`，即总计 13/40 轮。

当前最新完整轮次为：

```text
epoch                       = 12（总第13轮）
train_loss / train_acc      = 1.77 / 64.3%
val_loss / val_acc          = 2.93 / 41.1%
total optimizer attempts    = 22,568
successful updates          = 22,558
AMP overflows               = 10 (0.0443%)
```

从 pilot 末轮到 epoch 12，validation accuracy 从 27.9% 提高到 41.1%，validation loss 从 3.75 降到 2.93，说明模型在 full 分布上仍在有效学习。与此同时，epoch 12 的 train--validation accuracy gap 已扩大到 23.2 个百分点，需要继续监控泛化差距。Job 的最终 Slurm 状态尚未归档，因此不能写成第一分段或 40 轮已经完成。

完整逐轮表、AMP 账本、训练量和发表边界另见：

`2026-08-20_Job587802_full训练第一分段_epoch4至12中期记录.md`
