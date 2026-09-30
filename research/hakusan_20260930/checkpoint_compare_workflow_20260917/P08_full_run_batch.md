# P08：三模型全量评估执行包与预算提案

2026-09-19。对应总计划 P08（S5）。前置全部达成：P04 S1、P05a/P05b/P07conf 四作业逐位链、P06 政策审定、P07 成本实测。**已完成：重跑 Job 728520 通过全部硬验收；见第 5 节。**

## 1. 范围（科学合同不变）

- 原冻结 10,000 trial（bank SHA `d03404f2…0091`），原序 trial_id 0..9999，batch 16，625 个完整批，无尾批。
- 三模型 formal40 / author_external / valbest33；正确 cue 全量 10,000×3；额外三种 cue 仅 2,000 条 control 子集 ×3×3；合计 **48,000 条模型—条件预测**。
- 原生预处理、eager FP32、确定性设置，与 724808 起的执行协议相同；研究身份 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。

## 2. 执行包 `same_bank_compare_2026_09_19_full_v3`

由 P07conf 的 confirm_v2 派生，科学函数与 09/17 候选 AST 相同（测试强制）。

| 阶段 | 布局 | batch | 对照 | 门槛 |
| --- | --- | ---: | --- | --- |
| full10k | 0..9999 原序（layout SHA `c6aee22c…a469`） | 16 | 无；独立复算时执行 `validate_results(full_run=True)`、10,000 行/2,000 control/48,000 预测硬校验，记录 P06-4 margin 分层与 P07 成本 | 执行/来源/有限值/状态错误即停 |
| self32 | 原 32 条 O（layout SHA `16caeca7…adcf`） | 16 | (a) vs full10k 对应 32 条：**correct cue 三模型逐位一致**（P06-1/2），7 条 control 因在全量中处于不同 control 子批，按 P06-3 包络记录；(b) vs Job 728280 bridge16：全部条件逐位一致 + 旧 canary PASS（五作业逐位链） | (a) correct 不一致或 (b) 不一致即 FAILED |

两个模型进程独立、顺序；任一门槛失败保留全部产物并终止。

### 与 P06-1 原文的对应说明

P06-1 写的是“32 条重跑与全量产物对应 trial 的 logits 逐位比较”。全量中这 32 条的 control 预测与其它 trial 的 control 共享子批，其批形状与单独重跑时不同；P06-2 已证明同伴不影响 correct 输出，P06-3 规定批形状差异记录为包络。因此本包把逐位门槛精确落在 correct cue（10,000×3 主结果所在路径），control 差异记录并对照包络（超出只记录，供人工审阅）。这是对 P06-1 的实施细化，不改变任何阈值；如你认为应另行审定，请指出。

### 工程变更

- 产物限制：单文件 64→256 MiB、总量 256→512 MiB、传输 base64 90→350 MiB、传输超时 240→1800 s；全量 logits.npz ≈146.5 MiB、results.csv+bank.csv ≈20 MB，收集一次约 240 MiB。
- 时限：`--time=03:00:00`，协调器上限 10,500 s；LIMITS.model_processes=2。
- 合成 10k 尺度 CPU 演练已并入测试：10,000 行归档构建+保存 8.0 s、独立复算 1.2 s（本地），pandas 逐批写入无明显开销。

## 3. 预算提案（待批准）

- 1 个新 Slurm 作业，1 张 A100、8 CPU、64 GiB，**时限 3 小时**；单次 held 提交；站点改写 GPU 时按 9/19 决定做唯一一次同作业修正后独立核验放行；无自动重试、不追加作业。
- 依据 P07 实测外推：scene 1,452 s + correct 1,879 s + control 1,320 s + 冷启动 50 s + 保存/重读预留 120 s + 自检进程 55 s ≈ **81 分钟**；3 小时 ≥ 2× 估计。峰值显存 5.5 GiB、RSS 1.8 GiB（10k 结果帧与 154 MB logits 常驻后估计 <4 GiB）。
- 30 分钟以上运行没有中间检查点：超时即 FAILED，产物保留，不自动重试；重提需另行审批。

## 4. 出口（P08 硬验收，均由离线复算独立执行）

- trial ID 0..9999 无重复/缺失/错序；三模型每条件计数正确，总 48,000；scene/cue 身份与 Job584990 历史绑定一致。
- strict-load 覆盖率 1.0、eval、有限值、状态不变、运行时设置不变。
- self32 两项门槛通过；旧 1e-6 canary 在 bridge 上 PASS。
- Slurm COMPLETED/0:0、节点与环境一致；产物逐文件 SHA 校验。

通过后状态为 `P08FULL_OFFLINE_RECOMPUTED_NOT_QUALIFIED` → P09 统计（配对 bootstrap、分层、controls、P06-4 上界与 P06-5 误差预算）→ P10 交付。

## 5. 执行记录（只记实际发生的事）

- 2026-09-19 本地 Python 3.11.15 / torch 2.12.1：v3 整包 106 项（核心 73 + 控制器 33）通过，ruff 无告警；合成 10k 归档构建+保存 8.0 s、独立复算 1.2 s。
- 2026-09-19 HAKUSAN 原生 Python 3.11.5 / torch 2.1.1+cu118：106/106 通过，410.2 s，0 失败/错误/跳过；合成 10k 归档构建 24.0 s、独立复算 7.2 s；临时目录已清理，CUDA 未初始化，Slurm 作业数 0。证据 `docs/superpowers/evidence/p08full-cpu-native-hlps64rp/`。
- 2026-09-19 用户批准预算并确认 P06-1 细化。冻结 release `8072c182…3940` → 预检/发布/test-only → 单次 held 提交 **Job 728378** → 第 7 次 GPU 改写，唯一一次修正后放行 → 排队约 50 分钟 → RUNNING（spcc-a100g02）。
- **728378 终态 FAILED/1:0，58 分 06 秒。** full10k 模型阶段完整成功（48,000 条预测、保存/独立重读/后检查、in-job 验证 rc=0，process 3,408 s、forward 3,008 s、显存 5.5 GiB、RSS 2.3 GiB）；self32 模型成功；**self32.verify 崩溃**：10k `bank.csv` 的 `snr_bin_low` 等列（clean 行为空、mixed 行为数值）被 pandas 2.1.3 分块推断成 str/float 混合，与 32 行表 `assert_frame_equal` 失败（“-10.0 != -10.0”）。此前所有对照 ≤256 行单块解析未暴露；合成夹具列数不足未覆盖。不是模型或数值问题。
- 只读收集 FAILED 产物（42 文件）。在冻结包副本上仅打读取器补丁（`low_memory=False`、bank 按规范文本比较，执行器不变）离线验证：全量硬校验通过（10,000/2,000/48,000）；self32 对全量 **correct cue 三模型逐位一致**，control 在包络内（NLL ≤1.41e-3、logits ≤2.63e-3）、0 翻转；self32 对 728280 bridge16 **全逐位、canary PASS**（五作业逐位链）。10k margin 分层：formal40 29/10000（0.29%）、author 36（0.36%）、valbest33 23（0.23%）在包络内。真实 bank.csv 上直接复现并验证修复。证据：`docs/superpowers/evidence/p08full-production-20260919/offline-verify-728378-reader-fix/`。
- 修复包 v3r2（同目录、远端根 `eager_p08full_20260919_v3r2`）：读取器修复；合成夹具加宽到 60+ 列并与 v2 夹具对齐；新增 `full-repeat` 对照（728378 的 r1 全量作为基线，48,000 条逐位比较）；本地 74+33 项通过。
- 用户选择“用修复包 v3r2 重跑一次（同预算）”，作为单独重提授权记录于 `p08full-production-20260919-r2/AUTHORIZATION.json`。728378 全量产物保留为冷重复基线，不作为正式 P08 结果。
- **重跑 Job 728520：COMPLETED/0:0，57 分 11 秒，spcc-a100g02（第 8 次 GPU 改写，唯一一次修正后放行）。** 离线复算：48,000 条预测硬校验通过；self32 对 728280 全逐位 + canary PASS；对全量 correct 逐位、control 包络内；**728520 与 728378 两次全量 48,000 条预测逐位一致**。P08 验收完成，状态 `P08FULL_OFFLINE_RECOMPUTED_NOT_QUALIFIED`。台账：[REPORT.md](../docs/superpowers/evidence/p08full-production-20260919-r2/REPORT.md)。
