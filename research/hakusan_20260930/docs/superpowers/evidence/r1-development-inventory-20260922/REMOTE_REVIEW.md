# R1-C 远端元数据回执审阅

日期：2026-09-22。状态：`R1_REMOTE_METADATA_REVIEWED`，不是完整 `R1_INVENTORY_VERIFIED`。本轮仅审阅用户运行后留下的本地工件，没有再次连接超算。

## 1. 证据与完整性

- [回执](remote-readonly-50rg5hgi/RECEIPT.json)：returncode=0，`METADATA_INVENTORY_COLLECTED`。
- [原始结果](remote-readonly-50rg5hgi/stdout.json)：本地重新计算SHA，等于回执的 `323417ff6536c56adfad50cb6eafb9f659de267eccba0a614549c0e65e78429e`。
- 执行载荷SHA `3d9d62d210f1c7100474f6c6f098cd5c15fd11417a5cb1e2b2d26dcd99c05976` 与本地受审脚本一致；stderr为空。
- 全部指定目录/文件返回OBSERVED；11个指定小文件有SHA。checkpoint内容未读取，未反序列化，未提交作业、未写远端文件。

## 2. checkpoint 实际目录观察

`full/checkpoints`返回46个常规文件：

- `stage-0.ckpt`一个初始化阶段候选。
- `stage-epoch=00...39-step=...ckpt`共40个，epoch编号无缺口，文件名中的step均满足`1736×(epoch+1)`。
- `pilot4-final.ckpt`、`epoch=33-step=59024.ckpt`、`formal-final.ckpt`、`last.ckpt`、`rolling.ckpt`五个其他文件。
- 作者目录返回`epoch=1-step=24679-v1.ckpt`一个文件。

这纠正了仅凭早期本地记录推断“可能只有三个阶段”的不完整认识。**文件存在/命名一致不等于内容和loop state已验收。** 不把stage-epoch33与valbest33当成字节相同文件，不把last当历史epoch16文件。

E2可先按原设计核验以下8个候选，不必立刻评估40个阶段：

| 计划完成轮数 | 文件候选 | 当前证据等级 |
| --- | --- | --- |
| 0 | stage-0.ckpt | 目录已观察，内容/初始化状态待核验 |
| 1 | stage-epoch=00-step=1736.ckpt | 同上，阶段含义待核验 |
| 2 | stage-epoch=01-step=3472.ckpt | 同上 |
| 4 | stage-epoch=03-step=6944.ckpt | 同上；与pilot4-final关系待核验 |
| 8 | stage-epoch=07-step=13888.ckpt | 同上 |
| 16 | stage-epoch=15-step=27776.ckpt | 同上；不要错用epoch16表示完成16轮 |
| 24 | stage-epoch=23-step=41664.ckpt | 同上 |
| 40 | formal-final.ckpt | 历史正式主模型；当前文件仅元数据核验 |

以上是待核验选择方案，不是新的GPU作业批准；暂不需为“缺中间阶段”重训。

## 3. 冻结源码与数据

远端snapshot下`src/spatialtrain.py`、`selftrain/configs/full.yaml`、`selftrain/scripts/eval_full_pilot.py`及`build_full_pilot_eval_bank.py`的SHA，均与本地`patch_stage_next`对应文件重新计算的SHA一致。后续可用这四份本地副本审查实际冻结代码，不能用未绑定的最新项目源码替代。

远端validation anchor SHA为`b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65`，与已核验bank元数据绑定一致；train anchor观察SHA为`9294a24ea824296322eb99ace07e557a712d4460a3b49b4b0c6f91a130395a82`。bank TSV SHA仍为`d03404f2bca5aeb8a5d096b84f6ef758b6b07d0ee5efbd44ded59135bced0091`，与本地冻结bank一致。

本次 metadata 入口没有读取两份anchor的行内容；随后已完成独立的三表只读核查，见 [ANCHOR_SCOPE_REVIEW.md](ANCHOR_SCOPE_REVIEW.md)：train/validation 说话人及录音交集均为0，bank各角色完全属于validation且不属于train。`cv_train`顶层按本次扩展名过滤返回0条，不能据此断言没有clips、没有其他目录元数据或没有独立说话人。

## 4. 下一步（仍不做GPU推理）

1. 从已绑定的本地冻结脚本确认anchor列结构与原始语料元数据路径，先形成精确读取清单。
2. 准备有界的anchor声源/录音集合统计，核查所有角色；若需额外数据目录，先说明范围，不递归扫描整个home。
3. 对上述8个E2候选建立哈希/阶段核验方案；本次元数据入口不扩成无约束torch.load。区分身份核对和实际模型加载。
4. 完成R1数据角色与缺口报告，再准备E0历史完整批桥接、α端点和负对照的合同/预算。

无须重跑本次metadata入口。E0_ENDPOINT_PASS、独立holdout可用和E2轨迹实验完成均仍未达成。
