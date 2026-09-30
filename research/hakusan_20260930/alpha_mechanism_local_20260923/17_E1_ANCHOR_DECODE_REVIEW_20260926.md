# E1 冻结anchor及本地解码验收

状态：`E1_PINNED_ANCHOR_AND_LOCAL_DECODE_PASS`。本次完成上一轮来源缺口核验，无模型推理、远端写入或GPU作业。

1. 经工具权限批准，复用现有SSH连接，只读下载冻结快照的validation_anchors.tsv.gz（约284KB）至 `E1_REMOTE_VALIDATION_ANCHORS_20260926.tsv.gz`。哈希为 `b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65`，与历史冻结记录一致。没有以本地不同版本替代。
2. 本次候选SHA仍为 `be2011fdd6489777521a5f54af8d8f4fc39a73b14c6669b636e674f844bbb69b`，未重抽、未修改候选。
3. 核对200条clean的400个target/cue角色：索引、录音路径、说话人、norm、词标签、anchor中心全部与冻结anchor对应行一致。
4. 对309份本地录音重新核验字节SHA，有界分块解码（总体300秒上限，单录音最长300秒、最多8声道、采样率≤192kHz）。309份全部成功，波形有限，转单声道后非静音。
5. 对400个片段按受审代码的44.1kHz、110250样本、中心round规则检查2.5秒窗口落在解码时长内，全部通过。此检查不执行torchaudio原生重采样，不能代替原生输出长度/波形逐位验证。
6. 新增6项测试通过：正常音频、静音拒绝、损坏音频拒绝、片段越界/非有限中心、anchor字段错配和索引越界。

工具：[检查脚本](check_e1_clean_audio.py)、[测试](test_e1_clean_audio.py)。完整机器回执：[E1_CLEAN_DECODE_20260926.json](E1_CLEAN_DECODE_20260926.json)，包含音频字节SHA、解码元数据及每个片段边界。

## 剩余门槛

- 远端音频字节尚未与本地309份SHA核对；新增clean正确cue路径尚未接入和验收，不能误用旧clean清零逻辑。
- 当前 `inputs_frozen=false`：本轮报告补充候选的来源证据，不修改先前候选内的历史blocker记录；最终冻结时应引用本报告解除已完成项。
- 下一步本地实现新增clean输入路径与同布局负例测试，明确新增验收预测量；然后只读核验远端音频，审定完整合同并生成新输入冻结版本。仍不授权GPU提交。
