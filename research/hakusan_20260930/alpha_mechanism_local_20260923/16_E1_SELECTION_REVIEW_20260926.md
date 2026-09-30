# E1 本地选择与clean来源检查

状态：`E1_METADATA_CANDIDATE_NOT_INPUTS_FROZEN`。完成本地选择器、候选生成与音频存在/字节哈希盘点；不声称完整输入冻结。没有网络、上传、GPU或模型推理。

## 实际结果

- [选择器](select_e1.py)固定seed20260920、PCG64、NumPy2.4.6；只读已SHA核验bank与先导manifest，不读取模型输出。独占创建候选文件，禁止覆盖重抽。
- 82个分层配额全部可行，最小候选数减配额余量38。排除O的32条；先导16人所有角色命中数为0。
- 候选2000条：200clean、1800mixed，其中400control；125个16条父批。clean独立布局为12×16+8。
- 目标说话人603位，control目标说话人246位，目标词标签657类。与E0重叠19条，与旧confirmation_256重叠50条，已显式记录。此集合仍是开发集。
- [候选JSON](E1_CANDIDATE_2000_20260926.json) SHA256=`be2011fdd6489777521a5f54af8d8f4fc39a73b14c6669b636e674f844bbb69b`，其中记录选择器SHA、源SHA、完整ID顺序、角色覆盖、配额容量、排除原因与clean来源。
- 200条clean均有bank绑定的target/correct_cue索引、路径、说话人、词标签及anchor中心；同说话人、不同录音。200对词标签都不同，正确cue指正确目标说话人，不是重复目标词。
- clean涉及309个独立录音，本地Common Voice clips中309/309存在且为非空常规文件，已计算各自SHA和size。见[来源报告](E1_CLEAN_SOURCE_AUDIT_20260926.json)。本轮没有解码、没有核对远端字节，也没有执行新增clean预处理。
- [11项测试](test_select_e1.py)通过（2.061秒）：确定性/输入顺序不敏感、配额布局、缺角色、重复ID、容量不足、先导角色排除、缺donor、cue说话人错误、录音重复、输入SHA错误、非有限anchor中心。

## 为什么没有完整冻结

历史冻结validation anchor期望SHA：`b5d5a2c826bffc51ee9cb830277afffe07d4695b9aac488cd3127e7804f17e65`。

本地当前artifacts版本SHA=`b552e9acf83f83e4c3a73b17eb118f9636dd4d01a4d9693442d96994ab340a93`；before_hakusan_491636版本SHA=`6899a54f590470ac77c6fda5f22625aa48e192be54b076d8a637085492de9faa`。两者都不是冻结字节身份，未拿它们替代历史anchor。压缩字节不同本身不证明解压内容不同，但没有已绑定的等价性证据就不能静默互换。

因此，bank层面的cue元数据检查通过，不等于已经重新核对正确版本anchor的每个索引/片段。当前只保留候选清单及其SHA，不生成 `E1_INPUTS_FROZEN` 或可提交包。

## 下一动作

1. 单独授权只读获取/核验远端已绑定validation anchor，并核对200对target/cue索引、路径、说话人、标签和中心；不得改远端旧文件。
2. 对309份本地音频有界解码并核对片段范围；若用于远端执行，再核验远端音频SHA。不能用“文件存在”代替音频可用。
3. 新clean正确cue路径实现并验收，特别是防止旧clean逻辑清零、确认target波形不变；补齐新增检查预测数和统计合同。
4. 这些门槛完成后才发布输入冻结版本。继续使用本次候选ID，不能根据后续模型结果重抽。若样本不可用，保留失败证据，先修订设计再生成新版本。

实现过程首次元数据检查曾因把probe_distractor_cue误认为仅control才有而停止，没有写候选文件。检查实际bank后修正：所有mixed都有probe cue，shuffled cue仅control有；随后一次生成候选，测试通过。这是schema修正，不是因模型结果筛样。
