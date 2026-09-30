# P08full 候选：三模型全量评估执行包

2026-09-19 由 `same_bank_compare_2026_09_19_confirm_v2` 派生。**状态：v3r2 已完成正式全量 Job 728520 并通过全部硬验收（[台账](../docs/superpowers/evidence/p08full-production-20260919-r2/REPORT.md)）；首次运行 728378 因读取器缺陷 FAILED，其产物作为全量冷重复基线（48,000 条逐位一致）。**设计、预算提案与执行记录见 [P08_full_run_batch.md](../checkpoint_compare_workflow_20260917/P08_full_run_batch.md)；操作与 P07conf 相同（[OPERATIONS.md](../same_bank_compare_2026_09_19_confirm_v2/OPERATIONS.md)），名称改为 p08full，审批状态字段 `USER_APPROVED_P08FULL`，远端根目录 `eager_p08full_20260919_v3`，作业名 `audattn_eager_p08full`。

## 内容

- `layouts/full10k.json`：0..9999 原序、625 个 16 批；`layouts/self32.json`：原 32 条 O。SHA 固定于 `eager_compare.py` 与 `sequence.py`。
- `sequence.py`：`STAGES=("full10k","self32")`；`GATED` 对 728280 bridge16 全逐位；`CORRECT_GATED` 对全量 correct cue 逐位、control 记录包络；时限 3 小时；产物限制 256 MiB/512 MiB。
- `review_layouts.py`：v2 基线读取（728280）；full10k 归档读取时执行 `validate_results(full_run=True)` 与 10,000/2,000/48,000 硬校验。
- `control.py` / `ship.py`：`--time=03:00:00`、传输限制与超时放宽（collect 1800 s）。
- `tests/`（73）+ `controller_tests/`（33）：含合成 10k 尺度归档（按进程缓存一次）与离线复算演练。

## 边界

- 只执行 P08；不做 P09 统计、不改主模型/指标/数据；不授权重提。
