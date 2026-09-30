# P05b 操作入口与计划边界

对应总计划 P05 的剩余覆盖，不是 P08 全量入口。当前没有正式授权文件或冻结的发布包；不要直接运行 `sbatch run_layouts.sbatch`。

查看参数（纯本地、不会连接或提交）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  same_bank_compare_2026_09_18_layout_v1/ship.py --help
```

## 明确分开的操作

| 命令 | 前提与效果 |
| --- | --- |
| `freeze` | 只在本地创建新包；必须提供外部审批 JSON 及 SHA，范围精确匹配 P05b。不会从“继续”生成批准。 |
| `preflight` | 复用共享连接，校验账户/Python、旧输入与基线、空队列，读取调度配置及磁盘；需要人工审阅输出。 |
| `publish` | 同样先做预检；独占创建新发布目录，不覆盖旧包。 |
| `test-only` | 调度参数检查；不产生正式作业，有独占 intent。 |
| `submit` | 仅一次 held 提交，绝不自动放行。 |
| `release` | 校验实际作业身份、A100/CPU/内存/时限、保存脚本、尚未运行记账；生成 job ID 绑定契约后单次放行。资源不符时停止，无自动修复。 |
| `status` | 只读查询；提交回执缺失时按冻结的时间窗/名称读取记账，并返回 nonce 供对照。不补造回执、不自动重投。 |
| `collect` | 必须显式提供 job ID 和此前查询取得的终态 SHA；新目录下载、逐文件核验，再由独立文件收集器重验。不是数值资格通过。 |

每个远程动作均需冻结包目录与外部 release SHA。只允许使用既有共享 SSH；没有连接时先由用户在终端认证。不得把密码写进脚本或聊天。

提交、放行或上传响应不明确时，保留本地与远端 intent。不能删除 intent 后“再试一次”；先查询证据。当前状态查询用于人工恢复判断，不自动修复缺失 journal。

传输时只把已核验源码临时展开到专用临时目录，正常退出即清理。发布操作才会创建永久运行目录。网络调用上限240秒，不自动重连。合成测试不会执行这些真实网络动作。

## 统一离线科学复算入口

`offline_review.py` 已实现。它不连接超算、不加载checkpoint，只读取收集后的归档。参数必须来自真实冻结包和状态/收集记录；现在尚无新job ID，不填造执行命令中的路径或SHA。

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  same_bank_compare_2026_09_18_layout_v1/offline_review.py --help
```

- `--source`：下载并通过文件验收的四布局attempt目录。
- `--terminal-sha256`：此前独立status取得的COMPLETE/FAILED原件SHA。
- `--release-file` / `--release-sha256`：本地冻结RELEASE及外部SHA。
- `--job-id`：这次P05b实际job ID。
- `--baseline-root`：本地已收集的725677 attempt，含repeat16和batch1子目录，其receipt SHA由代码固定。
- `--status-file` / `--status-sha256`：`ship.py status`保存的RESULT.json及外部SHA，必须是终态查询。
- `--output`：不存在的新目录，不能位于输入归档/基线树内。

入口验证完整文件集合、契约与作业身份、终态/退出码/节点、四模型进程独立与顺序，逐归档从logits重算。生成7份比较JSON、合并paired_nll.csv和REPORT.json；统计包含有符号NLL差mean/std/max_abs、类别翻转和模型差值变化。32/17条上的多组对照共产生987条配对记录，不是987个独立样本。

成功状态是 `P05B_OFFLINE_RECOMPUTED_NOT_QUALIFIED`，不自动批准数值资格/10k。已失败作业只登记失败，不解释部分数值为成功。输入损坏或科学复算不一致则生成REVIEW_FAILED并停止。

## 进入真实 P05b 前仍须完成

1. 统一离线入口已实现并加入整包回归；真实四布局作业仍未运行，故尚无新科学复算结果。
2. 完成发布包冻结前的最终检查与明确预算审批：1 A100、8 CPU、64 GiB、总上限30分钟、四个顺序模型进程、一次提交、无自动修复或重试。这仍是提案。
3. 冻结后现场预检/调度 test-only；只在实际资源满足授权时放行。该批不涵盖额外确认集、成本测量或10k全量。

总计划出口不变：P05剩余覆盖及额外确认集 → P06数值政策 → P07成本 → P08全量 → P09统计 → P10交付。
