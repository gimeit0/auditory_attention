# checkpoint 对比执行入口

P05b最新：四布局、四进程顺序运行/独立验收、总超时/桥接门、CSV和本地收集已实现，69项本地测试通过，见[新候选说明](../same_bank_compare_2026_09_18_layout_v1/README.md)及[最新证据](../docs/superpowers/evidence/layout-sequence-local-20260918-v1/REPORT.md)。尚缺原生验证、远程发布/单次投递/SSH传输控制器，未提交新作业；不要复用下方历史作业投递脚本。

按[详细计划与进度](../2026-09-17_checkpoint对比_可执行详细计划与进度.md)推进；历史原因见[失败总审计](../2026-09-17_checkpoint对比_失败总审计与收敛方案.md)。

本地`workflow.py`与`review_runs.py`仅包含检查和只读结果比较。Job724808于9/18 00:18:59以COMPLETED/0:0结束，耗时2分49秒（spcc-a100g07，实际1 A100/8CPU/64GiB）。三正式模型、原32条及7条controls的159条预测已独立重算通过，P04/S1完成；数值资格和全量比较仍未完成。没有自动重连、自动重试；不用旧诊断提交脚本。

最新状态和只读查询命令见[Job724808台账](../docs/superpowers/evidence/eager-small-production-20260917/EXECUTION.md)。原`ship_small.py`绑定旧控制源码，不再用于此修复后的作业；不要重新submit或release。已放行阶段使用`2026-09-18-eager-small-724808-status.sh`，不再用held-check。

9/18新增S2a（原32条batch16冷重复，再独立进程batch1）：预算已批准，原89项回归与新增18项包装测试通过，新包已部署；**调度test-only因typed/untyped GRES冲突失败，尚未提交新作业**。原包不改，不能直接执行submit或重用S1专用修复命令。已保存[完整台账](../docs/superpowers/evidence/eager-s2a-production-20260918/EXECUTION.md)，当前没有新的数值对照结果。

9/18 08:47最新：**Job725677已COMPLETED/0:0，3分30秒；两次产物各159预测已独立重算通过。冷重复逐位一致，16/1无类别翻转，但旧1e-6检查仍DIFF。** 各模型/条件的有符号NLL mean/std/max_abs、三份比较和逐样本CSV已保存：[结果报告与离线复算](../docs/superpowers/evidence/eager-s2a-production-20260918-r2/review-725677/RESULTS.md)。只新增离线补充器`review_s2_results.py`，原比较器和科学源码未改。后续不再submit、correct-gpu或release；全量与数值资格仍未完成。

当前作业只读查询：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/qualification_r2/ship_s2.py status
```

如需再次只读检查这次阻断（不会sbatch、更新或取消作业；要求现有SSH共享连接）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/qualification/inspect_scheduler.py
```

## 本地检查（Mac）

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/workflow.py local-check
```

固定候选与原v4源码SHA核验后，依次运行候选21项、原v4 56项、新工具12项测试及两个CLI帮助检查。每次生成新的本地证据目录，保存原始日志、测试数、返回码、耗时及文件SHA；不覆盖之前的报告。每组命令最多120秒，出现失败就停止后续组。

已执行记录：[89项测试通过的报告](../docs/superpowers/evidence/eager-local-execution-20260917/20260917T135216Z-ry39bmqd/REPORT.json)。范围是本机CPU与合成模型，不是正式checkpoint/A100资格。

## 两次真实运行的只读比较

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  checkpoint_compare_workflow_20260917/review_runs.py --help
```

实际比较需要以下参数，必须来自已收集的真实运行：

| 参数 | 内容 |
| --- | --- |
| `--kind` | `cold-repeat` 或 `batch-size` |
| `--left` / `--right` | 两次独立运行的输出目录 |
| `--left-receipt-sha256` / `--right-receipt-sha256` | 分别在收集时外部保存的RECEIPT.json SHA；不是任意重新生成的清单 |

`cold-repeat`要求同batch且运行声明属于不同进程；`batch-size`要求左16、右1。工具先各自核验文件清单和logits重算，再检查来源、配置、bank、scene、所有cue身份匹配。运行声明仍需与独立Slurm记录交叉核对，哈希本身不能证明记录真实。

输出JSON包含logits/指标差异、预测翻转、类别margin、模型差值的变化及旧1e-6 canary结果。`NUMERIC_SENSITIVITY_RECORDED`表示已记录差异，**不是SMOKE_PASS**。不写入或修改输入目录，不批准全量，不计算全量bootstrap。

S1真实基线：[S1验收报告](../docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/INDEPENDENT_REVIEW.json)，[输出目录](../docs/superpowers/evidence/eager-small-production-20260917/collect-724808-8lr7w3yd/archive/attempts/slurm-724808)。外部固定回执SHA为`58f1fc6953c4732955efcadcbf7adbf543738936672639d929d0ef5359f00027`。现已有Job725677独立batch16/batch1对照，见上方结果；后续剩余覆盖、资格、全量和统计仍按计划及预算授权推进。
