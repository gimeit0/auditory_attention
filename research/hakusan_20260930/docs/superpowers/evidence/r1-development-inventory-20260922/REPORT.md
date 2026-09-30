# R1-A/B 本地资产索引与远端只读入口

日期：2026-09-22。状态：`R1_LOCAL_INDEX_READY`；只读入口本地8项测试通过。**远端未查询，E0未开始，作业提交数0。** 本目录取代计划中尚未创建的20260920拟定目录作为实际R1证据目录。

**同日后续更新（取代上方远端未查询状态）：** 用户已完成只读查询，回执/输出SHA与载荷核对通过，见[REMOTE_REVIEW.md](REMOTE_REVIEW.md)。观察到46个自训文件（含stage-0和40个连续阶段文件）及1个作者文件。当前为`R1_REMOTE_METADATA_REVIEWED`；仍未核验checkpoint内容、loop state或声源交集，下文“下一次远端盘点”保留为本次已执行入口说明，不需要重跑。

## 1. 已实际执行

- `local_audit.py`重新核验P10原SHA清单23文件，包括结果、logits、统计、旧政策与相关源码，全部通过。
- 图件MANIFEST列出的3张图、6个PNG/PDF文件的大小/SHA与统计来源全部通过。这是文件/来源核验，不是重新做视觉和图注科学审查。
- SHA验证后的原bank有10,000个唯一trial；target说话人795，所有角色并集817。具体各角色计数见[LOCAL_AUDIT.json](LOCAL_AUDIT.json)。不能把795当成bank全部使用过的说话人。
- 排除原O集合32条后，检查2k提案的82个细分配额，全部有足够候选：clean男女各100；20个mixed格中每种gender分别10 control+35 noncontrol。**只检查容量，未抽样、未生成layout或冻结新输入**。
- 远端入口默认dry-run通过；小文件哈希、checkpoint不反序列化、文件/父目录软链拒绝、缺失报告、非递归目录、禁用新SSH传输回退共8项本地测试通过。

结果可重算：

```bash
cd "$HOME/发表/超算"
R="docs/superpowers/evidence/r1-development-inventory-20260922"
P="/opt/anaconda3/envs/audattn/bin/python"
"$P" -I -B "$R/local_audit.py"
"$P" -I -B "$R/test_inventory.py"
```

LOCAL_AUDIT.json为本轮输出归档；脚本重跑只打印JSON，不覆盖归档。

## 2. checkpoint 索引：历史证据不等于当前远端库存

| 对象 | 本地证据 | 已知历史身份/阶段 | 仍待核实 |
| --- | --- | --- | --- |
| formal40 | 总计划§16、P08归档与加载报告 | SHA `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff`；固定40轮主模型 | 当前远端文件可用性 |
| author_external | 总计划§16、P08归档 | SHA `6fb23dde8455ef353a00d9bf676bf00f337961ac7c6d45f35f2c45a15cd88ed0`；外部参考 | 当前远端文件可用性 |
| valbest33 | 总计划§16、P08归档 | SHA `853069b8a9c037bc11d373b1d76e63f3e5c9f7601fad724a6ce7e7d7840d5e14`；验证选择补充 | 当前远端文件可用性/训练量 |
| pilot4-final | [40轮完成记录](../../../../2026-08-30_full训练40轮完成、恢复发布与same-bank评估准备记录.md)、[pilot记录](../../../../2026-08-16_Job575142_full-distribution四轮pilot训练记录.md) | SHA `c61af82c1ce32071616a81f992bcf25edfb06476e6c3a87542103cf3eb2a28ba`；历史step6944；路径在`full/checkpoints/pilot4-final.ckpt` | 文件是否保留；不能猜成`pilot4/checkpoints` |
| epoch16后last.ckpt | 40轮完成记录的历史续训证据 | 历史SHA `11f79ce63d01a0c5f47c3d17d12442e64548503b181047573b314c228e8a9c44`；不代表当前last仍是此内容 | 是否保留独立副本，可能已滚动覆盖 |
| 其他stage/rolling/best文件 | 保存配置与当前训练源码提供候选线索 | 不是已确认存在的实体 | 冻结训练源码的保存合同、实际目录、必要的后续哈希/loop state |

因此现阶段不能说“最多/最少可用三个阶段”。E2阶段数以盘点后证据为准，checkpoint文件名本身不是完成训练量证明。

## 3. 数据索引和缺口

| 对象 | 目前证据 | 下一动作 |
| --- | --- | --- |
| 原bank及metadata | 原TSV SHA `d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091`已本地核验；由validation anchors生成 | 盘点远端同名文件并对照身份 |
| validation_anchors.tsv.gz | bank元数据绑定SHA `b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65` | 远端小文件哈希；后续解析全部声源 |
| train_anchors.tsv.gz | 明确源路径；尚未在本轮读取实体 | 远端哈希；后续对照训练冻结身份并解析 |
| Common Voice候选资源 | 仅计划已知`cv_train`位置，未核实额外数据是否存在 | 先列该目录即时TSV/JSON元数据；不扫音频树、不推断独立说话人数 |
| 人类数据 | 无本轮访问/可用性证据 | 用户/导师确认任务、权限、数据层级，不虚构年龄映射输入 |

本轮未计算train/validation/external pool说话人交集；817只描述bank并集，不能代替完整anchor覆盖或独立测试筛选。

## 4. 下一次远端盘点的精确范围

入口：[run_readonly.py](run_readonly.py)；载荷：[remote_inventory.py](remote_inventory.py)。

- 只列`full/checkpoints`和作者checkpoint目录的即时条目，不递归、不读取checkpoint字节、不调用torch/pickle。
- `cv_train`只列即时`.tsv/.tsv.gz/.json`的元数据，不遍历clips；每目录上限1000个条目。
- 只对载荷中明确列出的11个输入/快照/完成记录进行≤16MiB小文件读取与SHA：两份anchor、snapshot manifest、冻结训练/配置/评估/构造脚本、bank/metadata、两个完成记录。
- 软链不跟随，缺失显式报告，不删除/创建远端文件。可能存在NFS访问时间等系统元数据效应；这里“只读”指无内容写入、无作业/应用状态变更。
- 远端90秒信号时限、本地110秒超时；不自动重试。系统级阻塞可能延迟远端信号处理，不宣称硬实时终止保证。
- 必须复用现存SSH master，`ProxyCommand=/usr/bin/false`防止master失效时回退到新连接；密码只能由用户使用原连接脚本在终端输入。
- 保存新的私有**本地**回执目录、stdout/stderr和载荷SHA。即使命令成功，仍只是`METADATA_INVENTORY_COLLECTED`或`WITH_GAPS`，不是checkpoint哈希/阶段/独立数据资格验收。

### 用户在Mac终端执行

先使用现有连接脚本认证（如果连接已经可用，它会复用）：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

再执行只读盘点：

```bash
cd "$HOME/发表/超算"
R="docs/superpowers/evidence/r1-development-inventory-20260922"
P="/opt/anaconda3/envs/audattn/bin/python"
"$P" -I -B "$R/run_readonly.py" --run
```

去掉`--run`只打印计划，不访问SSH。失败或WITH_GAPS时返回本地回执目录，不重复提交或自动扩大范围。若本机Python路径不同，先确认环境，勿猜改远端命令。

## 5. 后续出口

1. 审阅远端回执，核对候选保存位置、冻结源码/anchor身份及缺失项。
2. 对确实存在且需要用于E2的文件另做有界哈希核对；本入口不反序列化loop state。
3. 依据实际anchor schema准备下一份说话人隔离统计；现有盘点未自动下载大数据或创建新bank。
4. 完成R1数据角色报告和E0合同草案，再申请明确GPU预算。禁止把本轮本地8项测试写成E0端点通过。
