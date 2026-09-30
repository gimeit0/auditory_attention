# P07conf 批次：Job 728280 执行台账、确认集结果与成本外推

2026-09-19。对应总计划 P05“额外确认集”+ P07“测成本”合并批次；状态 `P07CONF_OFFLINE_RECOMPUTED_NOT_QUALIFIED`：数值已记录并独立复算，**不是数值资格通过，不授权全量。**

## 1. 执行台账

| 步骤 | 结果 / 证据 |
| --- | --- |
| 用户预算审批 | [AUTHORIZATION.json](AUTHORIZATION.json) SHA `f8fffa27…`；1 作业/1 A100/8 CPU/64 GiB/30 分钟/四顺序进程/单次提交/无自动重试；含“站点改写 GPU 时按 9/19 决定做唯一一次同作业修正” |
| 本地冻结 | release SHA `b3c0857c75206a9ee03e368bca83df08a3adcb851c5d6d54d0d66c119c7a375b`，[frozen/](frozen/) |
| 预检 / 发布 / test-only | 通过；`preflight-08jryr9u`、`publish-proicaq6`、`test-only-efsp1kac` |
| 单次 held 提交 | **Job 728280**，`submit-_g7kq9_z` |
| 站点改写（第 6 次） | 只读回读 ReqTRES=`gres/gpu:h100-20c=1`、TresPerNode=`gres/gpu:1`；[held_readback_728280.log](held_readback_728280.log) |
| 唯一一次 GPU 修正 | `scontrol update JobId=728280 TresPerJob/TresPerNode=gres/gpu:nvidia_a100:1` rc=0，回读 `nvidia_a100=1`；[correct-gpu-728280/](correct-gpu-728280/) |
| 独立核验后单次放行 | `release-zvk6url5`；随后 PENDING → RUNNING（spcc-a100g04，AllocTRES 1×nvidia_a100/8 CPU/64G） |
| 共享 SSH 中断 | 放行后连接的 12 小时空闲上限到期；用户在终端用既有脚本重新认证；作业不受影响 |
| 终态 | `728280|COMPLETED|0:0|00:06:12|spcc-a100g04`；COMPLETE.json SHA `e4322cf5e01c279bbc9bdbd2ca4344d4c5fde1a457466a7f5568853dda44d393`；`status-9s5f5t2q`（RESULT SHA `4f0ec7ab…`） |
| 只读收集 | `COLLECTED_NOT_QUALIFIED`，90 个文件逐项 size/SHA 校验；`collect-_wiyawt3` |
| 离线复算 | [offline-review-728280/REPORT.json](offline-review-728280/REPORT.json) SHA `ef2e08ab…`；`paired_nll.csv` 636 行，SHA `f57d9235…` |

本批 1 次 sbatch、1 次 scontrol update、1 次 scontrol release；无重提、取消或追加。四个模型进程 PID 互异、顺序执行、rc 均 0。

## 2. 门槛与数值结果

| 阶段 | 对照 | 结果 |
| --- | --- | --- |
| bridge16 | vs Job 726428 bridge16 | 三模型全部条件 logits **逐位一致**，旧 1e-6 canary PASS（724808→725677→726428→728280 四作业逐位链） |
| conf32rep16 | vs conf256 对应 32 条 | **逐位一致**，canary PASS → P06-1 在新样本、新批次同伴环境下成立 |
| conf32b1 | vs conf256 / vs conf32rep16 | **包络内**：NLL 绝对差最大 6.428e-04（包络 2e-3），logits 最大 1.314e-03（包络 4e-3）；0 翻转 → P06-3 成立 |
| 全部 | 636 条配对记录 | 0 次预测翻转；`envelope_exceeded_stages` = [] |

### P06-4 margin 分层（conf256，correct cue，top1−top2 logit margin）

| 模型 | n | 最小 margin | ≤4e-3（包络内，Accuracy 不确定性上界） | (4e-3, 4e-2] | >4e-2 |
| --- | --- | --- | --- | --- | --- |
| formal40__correct | 256 | 0.0001 | 2 (0.78%) | 7 | 247 |
| author_external__correct | 256 | 0.0042 | 0 (0.00%) | 16 | 240 |
| valbest33__correct | 256 | 0.0035 | 1 (0.39%) | 7 | 248 |

按 P06-4，256 条上 Accuracy 的数值不确定性上界约为 formal40 0.78%、author 0.00%、valbest33 0.39%。formal40 存在 margin 1e-4 量级的近平局 trial；全量报告必须按此分层给出上界，不得声称 0 翻转。

## 3. P07 成本记录（A100-PCIE-40GB，batch16 除 conf32b1）

| 阶段 | trials / control / batch | 进程墙钟 s | 输入核验 s | 三模型加载 s | scene+预测 s | 其中 forward s | 峰值显存 alloc/reserved GiB | RSS GiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bridge16 | 32 / 7 / 16 | 81.2 | 22.7 | 23.1 | 14.4 | 11.1 | 5.49 / 7.31 | 1.76 |
| conf256 | 256 / 60 / 16 | 166.3 | 14.5 | 9.1 | 124.9 | 87.7 | 5.49 / 7.31 | 1.74 |
| conf32b1 | 32 / 7 / 1 | 63.2 | 14.5 | 8.4 | 23.4 | 19.7 | 1.29 / 1.69 | 1.72 |
| conf32rep16 | 32 / 7 / 16 | 55.0 | 14.5 | 9.2 | 14.1 | 10.8 | 5.49 / 7.31 | 1.74 |

单位成本（conf256，实际分支计数）：correct 预测 62.6 ms/条（768 条）；control 预测 73.3 ms/条（540 条）；scene 生成与音频读取等非 forward 开销 145 ms/trial。首个进程冷启动（含 formal40 首次 NFS 读取 19.9 s）50.4 s，后续进程约 25.4 s。

### 全量外推（P07 第 3 条：按分支计数，不是总时长除 256）

- 10,000 trial scene 开销：1452 s
- 30,000 条 correct 预测：1879 s
- 18,000 条 control 预测：1320 s
- 冷启动 50 s + 10k 保存/独立重读/后检查预留 120 s + P06-1 内置 32 条自检进程 55 s

合计估计 **约 81 分钟**（4876 s）。建议全量作业时限取 **3 小时**（≥2× 估计），显存峰值 5.5 GiB、RSS 1.8 GiB 远低于 A100-40GB/64 GiB。该估计基于同一执行路径的实测，但 10k 的 pandas 逐批写入与 154 MB logits 保存未实测；时限是硬上限，不是完成承诺。

## 4. 进入 P08 前必须处理的两个工程点

1. **产物尺寸限制。** 现有 `inventory`/`import_attempt` 限制单文件 64 MiB、总 256 MiB、base64 传输 90 MiB；全量 logits（48,000×800 float32 ≈ 154 MB）超出单文件限制。P08 包需按模型/条件分文件保存并提高传输限制，或改用带 SHA 核验的分块传输。
2. **单进程内存与 pandas 写入。** 10k 结果帧逐批 `.loc` 写入的开销未实测；建议 P08 包在 run-full 前增加一次本地合成 10k 尺度 CPU 演练（不加载真实模型）。

## 5. 限制

- 256 条确认集是预注册的分层样本，不是 10k；研究身份 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST` 不变。
- 本批不决定主模型、主指标或统计方法；P06 政策未被修改。

## 6. 下一项

P08 全量执行包设计与预算审批：原 10k 顺序、batch16、48,000 条预测、内置 32 条逐位自检；产物分文件与传输限制调整；先合成 10k 尺度 CPU 演练，再申请一次 3 小时全量额度。
