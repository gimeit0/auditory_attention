# E0/E1 α实验合同草案（本地阶段）

状态：`E0_LOCAL_GAIN_UNIT_PASS`；不是E0_ENDPOINT_PASS，也未批准GPU。

## 机制定义与适用范围

受审`spatial_attn_architecture.py` SHA为`84e68e051f2a2a7a2373aab5c510b72e626aa3b11a9d54f5ec9e35ddbe570eed`。SimpleAttentionalGain按时间平均cue后计算

`g = b + (1-b) sigmoid((mean_time(cue)-t) s)`，再令`mixture_out = mixture * g`。

本候选为`gα = 1 − α(1 − g)`，α为固定有限Python标量，范围[0,1]。不把α训练为参数；不假设训练后的b使gain总在[0,1]，也不假设行为随α单调。

- α=1：直接调用原始forward，不用代数等价表达式替换其浮点路径。
- α=0：直接返回mixture，不计算cue/gain；显式旁路，不等于零cue。
- 0<α<1：先计算原gain，再插值；cue_mask对应有效gain严格设1。
- additive模式拒绝，不能套用乘性解释。生产接入前必须拒绝或另立协议处理residual_attn、其他cue出口、未知模块布局。
- 当前配置有7个conv gain和attnfc，共8处的设计预期；真实加载模型须列出模块全路径、类/源码、参数身份并验证恰好8处，不能仅凭配置或合成链认定生产模型已验证。

## 固定输入与分析

主模型formal40，θ固定、eval、无梯度推理。开发α={0,.25,.5,.75,1}，每个α严格同trial、scene、cue、顺序、批组成、batch尾部规则、预处理和执行精度。冻结bank为开发用途。2k草案按总计划200 clean+1800 mixed、400 control；本轮不声称已抽样/冻结。

主要效应草案：`Dα = mean[(correct − shuffled)α − (correct − shuffled)α=0]`，以逐trial正确与否计算Accuracy交互；预定α=1对0为主要对照，其他α作为预定剂量曲线，不事后挑峰值。silent/distractor分开报告；NLL方向明确为越低越好，另报误认目标/干扰/其他及标签碰撞规则。最终主要指标、最小有意义效应、确认集规模与多重比较政策须在确认实验前审定。

按target-speaker簇配对bootstrap，保持各条件/α共同重采样；报告实际簇数与条件覆盖。不得将场景数直接当独立人数。不以两个模型各自显著性代替配对差中之差。

## 最小E0生产验收（尚未执行）

1. 先在独立候选架构内接入模块，strict加载后比较原参数键/张量、模式与runtime；不得修改冻结评估器。α作为配置及RUN字段保存，现原型state_dict故意不含α，单独保存state_dict不构成可复现实验。
2. 原模型vsα=1：先同新布局参考逐位相等，再对728520的完整原批布局桥接。原历史输入/顺序/分支/精度相同才可称历史桥接。任何失败停止，不以包络替代逐位要求。
3. α=0对显式bypass逐位比较；在确认word输出无其他cue通路后，同scene更换cue应不变。共享conv/归一化若有可变状态必须额外检查，合成单模块不能替代。
4. α=.25/.5/.75有限输出、重复性、输入/参数/buffer/RNG不变；观察器有无输出一致。CPU单元通过不说明Inductor/A100通过。
5. negative controls独立实现并验收：均匀gain为每样本有效gain在非batch维均值广播；conv-only仅改7个conv gain、attnfc保持原值；末层均值保持以原attnfc gain均值匹配干预gain均值，分母近零/非有限即拒绝，不静默加eps改变定义。均值/缩放本身不是完整行为解释，需比较输出和错误结构。
6. target-only+正确cue须新构造；旧clean零cue与gain bypass分别保留，不把三者合并。

## 成本和停止规则

本地没有GPU预算消耗。生产E0必须另批一次小预算试验，测实际加载、forward、输出与验收成本；不自动投递。本轮不批准2k×5α扫描。

2k,c=400开发基础预测数为5×(2000+3×400)=16,000次/模型；端点桥接、重复、三个负对照及新增clean条件另计。旧成本公式只能粗估，不能保证新代码耗时。

endpoint/状态失败→修接口；α曲线平坦/非单调→记录，不为显著性加密搜索；均匀缩放可解释→收窄gain选择性主张；独立数据不足→仍标开发结果；远端连接暂停→只做本地实现，不重试连接。
