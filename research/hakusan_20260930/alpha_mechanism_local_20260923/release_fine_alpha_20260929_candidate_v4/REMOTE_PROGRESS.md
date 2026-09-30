# 低α扫描v4远端台账

日期：2026-09-29。计划与本地准备见[51号文](../51_FINE_ALPHA_V4_GAP_FILL_PLAN_20260929.md)。用户对“1张A100、8CPU、64GiB、最多4小时、单次held提交”回复“可以 提交吧 跟到结束”。

## 当前状态：757288已完成，收集、验收、对接点比对与合并读数全部通过

- **运行**：作业757288于08:57:13 JST以 **COMPLETED / 0:0** 结束，用时02:57:14。看守只读查询36次，无报警。
- **收集**：240个文件哈希核验通过；离线验收 `FINE_ALPHA_ARTIFACTS_VERIFIED`，122,400条预测。
- **对接点**：0.50与0.75的12组数组与756262**逐位相同**（`V4_ANCHORS_BITWISE_EQUAL_756262`）。
- **读数**：与756262合并的0–1完整曲线见[52号读数](../52_FINE_ALPHA_COMBINED_READOUT_20260929.md)，结果目录为 `readout-combined-756262-757288-eq581r9c/`。

| 步骤 | JST | 结果 | 回执SHA前缀 |
|---|---|---|---|
| 上传42个文件并做远端包检查 | 05:52 | `FINE_ALPHA_V4_UPLOADED_AND_HASH_VERIFIED_NO_JOB` | `2a47ff0f` |
| 原生只读预检 | 05:53 | `FINE_ALPHA_NATIVE_SOURCE_CHECK_PASS_NO_GPU_JOB` | `ca984a04` |
| 提交前只读并发抓取 | 05:58 | 只有757211，审阅通过（`queue-review-l3t31nc6`） | — |
| 单次held提交 | 05:59:04–12 | 作业757288；站点把GPU改写为h100-20c，记为 `RESOURCE_MISMATCH` | `845f38a3` |
| 唯一一次GRES修正 | 05:59:18–24 | 修正为A100，作业仍held | `d3feb7d8` |
| 放行前只读并发抓取 | 05:59:3x | 只有757211和作业自身（`queue-review-4jtv88ua`） | — |
| 唯一一次放行 | 05:59:40–48 | `FINE_ALPHA_RELEASED_READBACK_VERIFIED`，放行1次 | `36892093` |

各步授权文件：`GPU_HELD_AUTHORIZATION_1.json`（`ceba0325`）、`GRES_CORRECTION_AUTHORIZATION_1.json`（`d745f046`）、`RELEASE_AUTHORIZATION_1.json`（`adc1433e`）。

## 要点

- **提交**：冻结提交器的两次队列核查都是 `CONCURRENT_JOBS_REVIEWED_DISJOINT`，只有757211。回读确认时限04:00:00、8 CPU、64G、GPU-1A；站点的GPU类型改写与v1、v3相同。
- **修正**：修正后为 `gres/gpu:nvidia_a100=1`、`TresPerNode=gres/gpu:nvidia_a100:1`，作业仍为JobHeldUser，Priority 0。
- **放行**：放行授权携带放行前新抓取的并发审阅，远端用冻结的 `inspect_queue` 实时复核通过后才放行。即时回读为PENDING、Reason=None、Priority 16473；约10秒后开始RUNNING。
- **看守**：启动前发现v4看守从v3复制来的“接近时限”报警阈值仍是5小时40分钟，已改为3小时40分钟（4小时时限前20分钟），并同步修改测试。

## 下一步

无待执行的远端操作。科学上的后续选项见52号文。
