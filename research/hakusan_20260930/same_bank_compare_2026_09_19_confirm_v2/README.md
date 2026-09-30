# P07conf 候选：额外确认集 + 成本测量合并批次

2026-09-19 由 `same_bank_compare_2026_09_18_layout_v1` 派生。状态：本地/原生各 105 项合成测试通过；**Job 728280 已真实运行并离线复算（全部门槛通过、包络内、0 翻转）**，台账见 [REPORT.md](../docs/superpowers/evidence/p07conf-production-20260919/REPORT.md)；批次设计见 [批次设计文档](../checkpoint_compare_workflow_20260917/P07conf_confirmation_cost_batch.md) 末尾的执行记录。操作说明见 [OPERATIONS.md](OPERATIONS.md)。

## 内容

- `layouts/`：四个冻结布局（bridge16 / conf256 / conf32rep16 / conf32b1）及预注册的选择记录 `confirmation_256.json`；SHA 固定于 `eager_compare.py` 与 `sequence.py`。
- `eager_compare.py`：科学函数与 09/17 候选 AST 相同（测试强制）；布局改为文件加载；新增 `PROFILE.json` 成本记录。
- `review_layouts.py`：新增 v1 基线读取（726428）、通用配对表 `PAIRS`、P06-4 `margin_strata`、P06-3 `envelope_check`。
- `sequence.py` / `sequence_worker.py`：由 `COMPARISONS` / `GATED` / `STAGE_BATCH` 表驱动；固定配置阶段不逐位一致即停止。
- `control.py` / `ship.py` / `launch_approved.py` / `run_layouts.sbatch`：与 P05b 相同的单次 held 投递与独立核验流程，名称改为 p07conf。
- `offline_review.py`：统一离线复算，增加包络超出汇总与 P07 成本汇总。
- `tests/`（72）+ `controller_tests/`（33）：合成 checkpoint/归档，不加载生产模型；基线夹具来自 v1 测试包。

## 边界

- 不是数值资格通过，不授权 10k 全量；P06 政策已审定，本包只执行其第 2 节的预注册验证。
- 旧 725677 / 726428 产物、v1 包与源码不改。
