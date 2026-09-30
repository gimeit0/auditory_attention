# Job685198：离线核对完成，下一阶段定点追踪方案

初始状态：离线分析已执行；本文件中的真实模型逐层追踪尚未运行。
后续进展：通用观测原型已实现，同一套28项合成CPU测试在本地与超算
torch2.1.1均通过，远端回执已核验。真实对象绑定及有界采集的静态前置核对
见[原型进展](2026-09-11-targeted-trace-prototype-progress.md)。
下述生产加载、资源和A100有效性门禁仍未完成，没有提交真实模型逐层追踪。
本轮未修改已冻结工具、权重、bank、阈值或远端文件，未申请GPU。

## 已完成的实际工作

从超算原attempt只读下载完整114项工件，211343132字节、10个子目录。
本地按已绑定完成标记核对文件名、目录、类型、权限、长度与SHA256；
分析结束后再次全量核对，全部一致。没有混入失败作业的文件。

- [完整attempt副本](job-685198-v18/slurm-685198/)
- [机器可读分析](job-685198-v18/OFFLINE_ANALYSIS.json)
- [只读分析脚本](2026-09-11-job685198-offline-analysis.py)
- [14项回归测试](2026-09-11-test-job685198-offline-analysis.py)、[原始测试输出](job-685198-v18/OFFLINE_TESTS.log)
- 本地Ruff检查通过；测试覆盖字节/大小变更、缺失/额外文件、链接、权限、
  重复/越界路径、清单摘要、NLL平移不变性、极值稳定性和非法输入。
- inventory SHA：57e589dd8f679715f49ba65cf841ef26b9e099ccf437024f8d13741afebf228b。
- terminal SHA：4db7f8ba6c63bb58b354cc30486a0e839bb186e31c4845676baa26cd741b72c1。

本地脚本不取代此前已通过的远端verify-results，也没有重跑GPU模型。
归档不包含完整音频、checkpoint和软件环境，不是无需其他输入即可重跑
推理的完整复现包。14项离线工具测试与v18的751项生产候选测试分开记账。

## 新发现：logits与NLL的最坏样本不同

| 指标 | A2：AMP开，16对1 | B2：AMP关，16对1 |
|---|---:|---:|
| logits有变化的样本 | 32/32 | 32/32 |
| logits最大绝对差 | 0.03125 | 0.0070323944091796875 |
| logits最大差异trial | 9000（ordinal 0） | 1428（ordinal 11） |
| 原记录NLL最大绝对差 | 0.003428220748901367 | 0.0024318695068359375 |
| NLL最大差异trial | 4126（ordinal 28） | 2698（ordinal 19） |
| NLL差异超过原1e-6阈值 | 30/32 | 29/32 |
| 预测类别相同 | 32/32 | 32/32 |

A1/B1的logits与NLL均保持一致。结果由完整原生logits和CSV按冻结ordinal、
trial_id、bank_row_index配对；预测类别/正确性也重新核对。阈值没有修改。

保存的logits在CPU以float64重算稳定logsumexp与NLL，两组最大差异仍为
0.003428132414639684和0.002432252769354548。重算NLL与原记录逐条差距均
小于6.8e-7。因此这些工件中的分歧不能仅归因于最后一步float32的
log-softmax/NLL计算；模型已输出足以产生该差异的不同logits。这不确定
具体层或底层算子，也不把float64重算值替换进正式结果。

B2的logits最坏trial1428，原记录NLL差恰好为0。只追踪它不足以解释NLL
canary失败。新方案保留原marker的选择，另外增加原CSV的NLL最坏样本，
不修改TARGETED_TRACE_REQUIRED.json。这是事后故障诊断，不是性能抽样评估。

## 追踪输入与目标

固定formal40、原32条完整顺序和16→1两次pass。不复制单条16次代替原batch，
不抽新样本。保持权重、前处理、AMP分组、TF32、compile、状态/RNG检查与阈值。

| Cell | 选择依据 | trial_id | ordinal | target label |
|---|---|---:|---:|---:|
| A2 | 原marker的native-logits最大差 | 9000 | 0 | 560 |
| A2 | 原CSV的NLL最大差 | 4126 | 28 | 54 |
| B2 | 原marker的native-logits最大差 | 1428 | 11 | 657 |
| B2 | 原CSV的NLL最大差 | 2698 | 19 | 292 |

须保留两批16条的原始上下文和完整singleton顺序，避免改变编译生命周期。
A2/B2的WORST_CASES/scene_features与cue_features全对应trial9000（特征相等
时按ordinal打破并列）；不能当作1428、4126或2698的输入。后续应从冻结bank
重建特征，逐trial核对原边界摘要，并记录dtype、shape、stride和batch布局。

## 已核对的模型路径

从冻结snapshot下载架构、自定义模块及full.yaml并逐SHA核对，见
[源码来源](job-685198-v18/frozen-model-source/README.md)。未执行下载文件，
未用本地开发仓库代替固定源码。配置有7个注意力卷积块，norm_first=true、
v08=true；源码默认fc_attn=true。实际运行前仍须核对checkpoint构建的模块清单。

| 顺序 | 候选观测边界 | 必须区分 |
|---|---|---|
| 1 | norm_coch_rep | cue与mixture两次调用 |
| 2 | 每个idx=0…6的attn、conv_block、hann_pool | cue/attended-mixture分支、调用序号 |
| 3 | attnfc（实际存在时） | cue驱动的增益、mixture输出 |
| 4 | flatten、fullyconnected、relu、dropout、classification | 布局、eval状态、native logits |

卷积块顺序为LayerNorm→Conv→ReLU；注意力使用cue时间平均、阈值/斜率、
sigmoid增益和逐元素乘法。HannPooling2d合并batch与channel后执行conv2d。
这些是源码事实，不是某个算子已被判定为根因。同一模块服务两条分支，
只按模块名保存一次会覆盖信息。

## 观测有效性门禁与实施次序

不能给已编译生产对象随意加hook就称为原执行的逐层证据。PyTorch v2.1.1
官方文档说明，部分模块的hook会触发graph break，默认也不一定检测编译后
hook字典的变化。[同版本官方说明](https://raw.githubusercontent.com/pytorch/pytorch/v2.1.1/docs/source/torch.compiler_nn_module.rst)。
因此观测可能改变计算图，是必须验证的风险，不是本模型已发生的事实。

1. 在独立、未部署候选中实现分支/调用序号记录和严格配对。不得给v18加hook
   或放宽旧guard；新候选明确绑定观测代码和范围。先测试共享模块、错trial、
   缺失/重复边界、状态变化、非有限值、记录器篡改及输出改变的拒绝路径。
2. 在torch2.1.1验证观测器；CPU只验证工程。未观测冷参考仍用原路径；
   观测在独立对象/冷进程进行，不在已编译对象上开关hook，也不关闭compile
   冒充原基线。必须声明观测代码造成的编译图变化及其解释限制。
3. 先逐位核对未观测参考与已绑定v18输入/输出。若不同，记录环境、布局、
   状态和编译差异，停止将其等同v18，不临时放宽匹配标准。
4. 再逐位核对观测/未观测native logits、派生指标、状态/RNG。失败标记为
   观测干扰，不报告原模型首个分歧层。输出相同也只是必要条件，不能单凭
   终点相同证明全部中间算子保持；不同执行条件最多作为单独标注的旁证。
5. 门禁有效后按分支、调用与ordinal定位首个不同块，再细分该块内部算子。
   保存有限值、dtype/shape/stride、摘要及受限最坏张量；区分继承的输入
   差异与当前算子新产生的差异，不能把首个观测边界等同底层根因。

实施前测量显存、存储与耗时。沿用不超过1GPU/总4小时、子进程90分钟作为
设计上限；容纳不了应先缩减无关保存或报告阻塞，不自动扩时、循环重提或
跳过检查。本文件尚不是已实现、已验收的GPU逐层追踪，也没有新增提交脚本。

## 回到最终比较

本轮没有批准关闭TF32、改变compile、放宽阈值或只用16对16冒充canary通过。
如需新数值执行方案，须单独记录控制变量和理由，验证三模型共同可用性，
再完成三模型smoke及10k/controls、配对统计与CI。
目标仍为formal40主结果、valbest33补充、作者外部参考；保留
REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST。没有最终模型排名或后台新作业。

## 本地复查

Mac本地执行，不需要SSH、不上传、不提交，只打印结果：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-11-job685198-offline-analysis.py
```

保存的JSON、脚本和测试摘要见[离线SHA清单](job-685198-v18/OFFLINE_SHA256SUMS)。
