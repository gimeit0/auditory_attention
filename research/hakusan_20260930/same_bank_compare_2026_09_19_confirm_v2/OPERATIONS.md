# P07conf 操作入口与计划边界

对应总计划 P05“额外确认集”+ P07“成本测量”的合并批次（设计见 [P07conf_confirmation_cost_batch.md](../checkpoint_compare_workflow_20260917/P07conf_confirmation_cost_batch.md)）。不是 P08 全量入口。没有审批文件与冻结包时不要直接运行 `sbatch run_layouts.sbatch`。

查看参数（纯本地、不会连接或提交）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  same_bank_compare_2026_09_19_confirm_v2/ship.py --help
```

## 与 P05b 包的差异

| 项 | P05b（layout_v1） | P07conf（confirm_v2） |
| --- | --- | --- |
| 布局 | 代码内固定四个名字 | `layouts/*.json` 冻结文件，SHA 固定在 `eager_compare.py`、`sequence.py` |
| 阶段 | bridge16 / cold1 / peers16 / tail17 | bridge16 / conf256 / conf32rep16 / conf32b1 |
| 基线 | 725677（旧 09/17 读取器） | 726428 bridge16（pinned v1 读取器） |
| 对照与门槛 | 代码内分支 | `sequence.py` 的 `COMPARISONS` / `GATED` 表 |
| 新增记录 | — | `PROFILE.json`（峰值显存/RSS/墙钟）、P06-4 margin 分层、P06-3 包络检查 |
| 审批文件状态 | `USER_APPROVED_P05B` | `USER_APPROVED_P07CONF` |
| 作业名 / comment | `audattn_eager_p05b` / `p05b-<nonce>` | `audattn_eager_p07conf` / `p07conf-<nonce>` |
| 远端根目录 | `eager_p05b_20260918_v1` | `eager_p07conf_20260919_v2` |

其余操作（freeze / preflight / publish / test-only / submit / release / status / collect / offline_review）语义与 P05b 相同，见 P05b 包的 [OPERATIONS.md](../same_bank_compare_2026_09_18_layout_v1/OPERATIONS.md)。

## 站点 GPU 改写的处理（用户 2026-09-19 决定）

假期内不等管理员答复：typed 提交后若 held 核验发现 `h100-20c`，由用户单独授权对同一 held 作业做唯一一次 `scontrol update ... TresPerJob=gres/gpu:nvidia_a100:1 TresPerNode=gres/gpu:nvidia_a100:1`，再由独立 `release` 重新全量核验放行。intent 记录与回读保存在证据目录。管理员询问稿见 [GRES_typed_request_inquiry.md](../docs/superpowers/evidence/p05b-production-20260918/GRES_typed_request_inquiry.md)。

## 离线复算

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  same_bank_compare_2026_09_19_confirm_v2/offline_review.py --help
```

`--baseline-root` 指向本地已收集的 726428 attempt（含 `bridge16` 子目录），其余参数同 P05b。输出增加 `envelope_exceeded_stages` 与每阶段 `cost`（`PROFILE.json` + 模型 stdout 的 `STAGE_SECONDS` 汇总）。成功状态 `P07CONF_OFFLINE_RECOMPUTED_NOT_QUALIFIED`，不自动批准全量。
