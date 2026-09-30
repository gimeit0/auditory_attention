# E2 checkpoint 兼容性修复与原生核验

2026-09-28。当前 `E2_STAGE_INSPECTION_PASS`，不是 E2 推理或科学报告完成。

## 原因与处理

PyTorch 2.1.1 的 weights_only 先拒绝 pathlib.PosixPath；仅加入路径类型后，又拒绝 NumPy RNG 的 `_reconstruct`。这属于完整Lightning训练归档中的元数据兼容性问题，不是权重损坏证据。

保留两次失败回执：`remote-readonly-lcg8f0o6`、`remote-readonly-ch9zxg5p`。随后静态列举8份文件的GLOBAL引用：路径、OrderedDict、NumPy dtype/ndarray/reconstruct、latin1编码及两种torch Storage和tensor重建函数，全部一致，无STACK_GLOBAL/EXT间接引用。证据：[完整类型清单](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-w_00b5qx/stdout.json)。

采用 `e2_archive_loader.py`：加载前核对完整字节SHA、静态opcode与显式类型白名单；自定义Unpickler.find_class拒绝其他全局对象，路径参数仅字符串、codec仅latin1。调用torch自定义pickle_module入口，因此参数是weights_only=False，但**并非使用默认不受限pickle**；不得再称weights_only=True。没有失败后回退分支，不修改原checkpoint。仅供已绑定的本项目归档，不宣称能安全加载任意来源文件。

初版PosixPath-only模块 `e2_restricted_load.py` 留作失败路径记录/测试，不再是阶段检查的生产候选入口。

## 原生结果

证据：[结果](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-9l0u8m2c/stdout.json)、[回执](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-9l0u8m2c/RECEIPT.json)。本地重算stdout SHA与回执相符。

| 完成轮数 | epoch | global_step |
| --- | --- | --- |
| 0 | 0 | 0 |
| 1 | 0 | 1736 |
| 2 | 1 | 3472 |
| 4 | 3 | 6944 |
| 8 | 7 | 13888 |
| 16 | 15 | 27776 |
| 24 | 23 | 41664 |
| 40 | 40 | 69440 |

八份state_dict均61项、63,271,260个元素；每个状态张量均有限。键名/shape/dtype签名一致：`289c4ac10e04b6b09533c0b8de2d38d04aa81ac8aa971750e4a92cb920ef6faa`。这个签名不是权重值摘要，不能说八模型参数相同；各文件SHA分别保留。

formal-final单独绑定after-fit保存语义和历史SHA；不将epoch=40套成中间阶段的epoch=39规则。此次只检查epoch/global_step与张量内容，未完整解释loop state，也未构建真实模型。CUDA未初始化，jobs_submitted=0。

## 后续接入进度

新增 `e2_stage_loading.py` 候选装载接口：阶段身份、native状态签名、strict=True、禁止key改写、形状/dtype/有限值、完整参数覆盖及eval/freeze；回调后检查状态一致。真实构造器及源码来源须由后续受审session绑定，接口报告明确production_provenance_verified=False，不把回调接入候选当生产验收。

39项本地回归通过，包括SHA不符、任意函数拒绝、路径/NumPy RNG/tensor往返、阶段错位、参数缺失/形状/dtype/有限值、进程完整时间/失败归档等。该测试数不等于39项真实模型测试。现代本地NumPy有core别名弃用警告，不影响通过结果；远端实际版本已成功。

下一整批：E2 session绑定真实构造器与原生输入、执行矩阵/归档/独立验收集成、formal40历史桥接和原生小批预算。当前没有E2 GPU作业号，不宣称E2_TRAJECTORY_DESCRIBED。
