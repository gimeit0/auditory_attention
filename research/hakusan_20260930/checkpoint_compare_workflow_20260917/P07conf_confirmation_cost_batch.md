# P07conf：额外确认集 + 成本测量合并批次（设计与预算提案）

2026-09-19。对应总计划 P05“额外确认集”与 P07“测成本”，按已审定 P06 第 2 节合并为一个作业。**预算已于 2026-09-19 批准并执行完毕；执行记录见第 5 节。**

## 1. 预注册的确认集（已冻结）

- 选择脚本与记录：[select_confirmation_set.py](../docs/superpowers/evidence/p05-confirmation-set-20260919/select_confirmation_set.py)、[confirmation_256.json](../docs/superpowers/evidence/p05-confirmation-set-20260919/confirmation_256.json)（SHA `d727691355aea3f7721b65ce8d64baafb13c24abd6687b18dc4d5b7fd2c1b35c`）。
- 输入只有冻结 bank 元数据（SHA `d03404f2…0091`，与 input_freeze.json 一致）；未参考任何模型输出；排除原 32 条 O。
- 规则：seed 20260919；clean 16（8f/8m）；20 个 mixed cell（干扰数 1–4 × SNR 段 5）各 12 条（6f/6m），其中 3 条 control_subset；组内按 trial_id 排序后 `default_rng(seed).choice` 无放回；组内 seeded 打乱；按固定分层顺序轮转交错。
- 结果：256 条 = clean 16 + mixed 240；control 60（23.4%，bank 为 20%）；男女各 128；184 个目标说话人；前 32 条覆盖全部 21 个分层、含 7 条 control。

## 2. 执行包 `same_bank_compare_2026_09_19_confirm_v2`

由 P05b 的 layout_v1 派生；布局改为冻结 JSON 文件并按 SHA 固定，比较逻辑由 `sequence.py` 中的 `COMPARISONS`/`GATED` 表驱动。科学推理函数（forward、evaluate_pass、save/verify_pass 等）与 09/17 候选 AST 逐一相同，由测试强制。

| 阶段 | 布局 | batch | 对照 | 门槛 |
| --- | --- | ---: | --- | --- |
| bridge16 | 原 32 条 O | 16 | vs Job 726428 bridge16（经 pinned v1 读取器） | 逐位一致，否则停止 |
| conf256 | 256 条确认集 | 16 | 无（记录 P06-4 margin 分层与 P07 成本） | — |
| conf32rep16 | conf256 前 32 条 | 16 | vs conf256 对应 trial | 逐位一致（P06-1），否则停止 |
| conf32b1 | 同 32 条 | 1 | vs conf256、vs conf32rep16 | 记录并检查 P06-3 包络；超出只记录不修复 |

四个模型进程独立顺序、各自加载 checkpoint；任一执行错误或门槛失败即停，产物全部保留。

新增 `PROFILE.json`（每进程峰值显存/常驻内存/墙钟）与模型 stdout 中逐批 `STAGE_SECONDS`；离线复算把它们汇总为 P07 成本记录。

## 3. 预算提案（待批准）

- 1 个新 Slurm 作业，1 张 A100、8 CPU、64 GiB，总上限 30 分钟，协调器上限 28 分钟。
- 参考：726428 四进程共 5 分 16 秒（bridge16 含冷启动 143 s，其余 49–64 s）。conf256 约为 32 条的 8 倍前向量，预计 3–5 分钟；全批预计 8–12 分钟。30 分钟是硬上限，不是完成承诺。
- 单次 held 提交；站点改写 GPU 类型时按用户既定决定做唯一一次同作业字段修正后独立核验放行；无自动重试、不追加作业、不含 10k 全量。

## 4. 本批的出口

1. bridge16 与 conf32rep16 逐位一致 → P06-1/2 在新样本上成立。
2. conf32b1 包络内 → P06-3 包络在新样本上成立；否则停止并调查。
3. conf256 的 margin 分层报告 → 给出 10k 全量 Accuracy 不确定性上界的第一个估计。
4. 成本记录 → 按实际分支计数外推 48,000 条预测的全量时间，据此申请一次全量额度（P07 第 3–4 条）。

## 5. 执行记录（只记实际发生的事）

- 2026-09-19 本地 Python 3.11.15 / torch 2.12.1：v2 整包 105 项（核心 72 + 控制器 33）全部通过，ruff 无告警。
- 2026-09-19 HAKUSAN 原生 Python 3.11.5 / torch 2.1.1+cu118：105/105 通过，71.149 秒，0 失败/错误/跳过；临时目录已清理，CUDA 未初始化，Slurm 作业数 0。证据：`docs/superpowers/evidence/p07conf-cpu-native-swosl8xk/`（此前一次 `p07conf-cpu-native-ebpqrokx` 为驱动脚本 115 秒 SSH 超时截断，104/105 已通过、无失败，远端确认无残留后放宽超时重跑）。
- 2026-09-19 用户批准预算（含站点改写时的唯一一次同作业修正）。冻结 release `b3c0857c…` → 预检/发布/test-only 通过 → 单次 held 提交 **Job 728280** → 第 6 次 GPU 改写，唯一一次修正后独立核验放行 → COMPLETED/0:0，6 分 12 秒，spcc-a100g04。
- 离线复算：bridge16 与 726428 逐位一致；conf32rep16 与 conf256 逐位一致（P06-1 成立）；conf32b1 包络内（NLL ≤6.43e-04，logits ≤1.31e-03，P06-3 成立）；636 条配对 0 翻转。conf256 margin 分层：formal40 2/256、author 0/256、valbest33 1/256 在包络内。
- 成本：correct 62.6 ms/预测、control 73.3 ms/预测、scene 145 ms/trial；全量外推约 81 分钟，建议 3 小时时限。完整台账与外推：[REPORT.md](../docs/superpowers/evidence/p07conf-production-20260919/REPORT.md)。
- 出口：本批全部门槛通过；P08 前需处理产物尺寸/传输限制并做合成 10k 尺度演练。
