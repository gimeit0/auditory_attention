# R1 anchor 声源隔离核查 — 2026-09-22

状态：`R1_ANCHOR_SCOPE_REVIEWED`。这是 R1 的一个已完成子项，不是 R1 全部完成、独立测试成立或 E0 完成。

## 实际执行与证据

本地 15 项测试通过（原 inventory 8 项及新增 anchor 7 项）。dry-run 后执行一次获准的远端读取：复用现有 SSH master，90 秒远端上限、110 秒本地上限；只读两份 anchor 和 frozen_bank.tsv，读取前绑定 SHA；不上传源码、不读取 checkpoint、不加载模型、不写远端文件、不提交作业。首次沙箱内 socket 检查被权限拒绝，获准后检查成功，未自动重连。

- [执行回执](remote-readonly-ejwnsbgb/RECEIPT.json)：returncode=0，`ANCHOR_SCOPE_COLLECTED`。
- [完整聚合结果](remote-readonly-ejwnsbgb/stdout.json)：重新计算 SHA 为 `0d7549dbb4d601716de2921c704a883e298be1437b79cc67001c6506ed66f7ba`，与回执一致。
- 实际 stdin 载荷 SHA：`0fc5c4e13ee751486cc1b8d80c50ee3ed487b99787519fa840558e6359ba2606`。
- [入口](run_anchor_scope.py)、[统计实现](anchor_scope.py)、[合成测试](test_anchor_scope.py)。入口拼接原 remote_inventory 的只读帮助函数；不会运行旧 metadata main。

## 已确认结果

| 对象 | anchor/场景行数 | 唯一录音路径 | 唯一说话人 |
| --- | ---: | ---: | ---: |
| train anchors | 91,476 | 36,842 | 7,712 |
| validation anchors | 4,342 | 2,364 | 1,201 |
| frozen bank | 10,000 | 按角色详见 JSON | target 795；全角色817（前次本地 bank 核查） |

训练与验证的说话人、录音路径、(说话人,录音路径) 对交集均为 **0**。

对 target、correct_cue、distractor_1–4、probe_distractor_cue、shuffled_cue 共8类角色逐一核查：

- 全部说话人、录音路径和配对身份都属于 validation anchors。
- 上述三类集合与 train anchors 的交集均为0。
- 相同录音出现多个 anchor 行允许；同一录音对应冲突说话人会拒绝。

## 解释边界

这是已绑定 manifest 的集合隔离证据，不是完整训练执行历史证明，也没有验证作者模型的训练数据。旧 bank 仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。不得把“与训练声源无交集”写成“没有被模型选择或开发过程使用”。

本地项目下 train/validation anchors 的压缩文件 SHA 分别为 `497b9dc6b79ca75829e352f3435962a04a8bb62f9a71c628625b1a109d64825f`、`b552e9acf83f83e4c3a73b17eb118f9636dd4d01a4d9693442d96994ab340a93`，与远端已绑定版本不一致，因此没有用它们替代远端统计。字节不同本身不证明解压内容不同。

## 后续顺序

1. 只读核查远端 `selftrain/artifacts/splits/split_audit.json`、候选表元数据及冻结构造源码，确定原始 Common Voice 元数据的精确位置；再限定读取范围，判断是否存在训练和验证均未使用且未被先前开发暴露的说话人。当前 `independent_holdout_availability=NOT_DETERMINED`，不能立即降级或宣称独立 holdout 可用。
2. 对先前列出的8个训练阶段建立独立的文件哈希/训练状态核验方案。目录存在和保存回调语义不替代文件内容核验；不直接无约束反序列化 checkpoint。
3. 汇总 R1 出口，再进入 E0 α=1 同布局历史桥接及 α=0 端点/负对照合同。GPU 批次仍逐项预算批准，不自动提交。

本次检查无需重跑；保留旧失败与正式比较证据，不重开旧诊断作业。
