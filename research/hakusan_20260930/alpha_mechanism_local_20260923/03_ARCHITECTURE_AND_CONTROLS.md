# 本地架构与负对照验收（2026-09-23）

状态：LOCAL_ARCHITECTURE_CONTROLS_PASS；不是E0_ENDPOINT_PASS，也不是科学实验完成。

## 实际执行

- `pinned_architecture.py`：对原架构、padding、conv2d_same、custom_modules四份文件核验SHA，提取所需定义；不修改原工程，不导入训练入口。
- `architecture_adapter.py`：临时替换7处卷积前gain及attnfc，保留Parameter对象身份和state_dict键；退出上下文（含异常）恢复原模块。
- `test_architecture_adapter.py`：12项新增测试；与第一轮11项合并，23项全部通过。命令见README。最后一次执行耗时0.438秒（测试主体），退出码0；本地PyTorch环境，不等同超算2.1.1环境。
- 首轮两个测试因漏传原gain接口的必选`cue_mask_ixs`报错；补传None后全量重跑通过，没有改动原gain接口来绕过测试。

## 通过范围

| 检查 | 结果与边界 |
| --- | --- |
| 原架构接入 | 使用受审BinauralAuditoryAttentionCNN类，随机权重缩小配置：7层、2通道、3×5输入、1×1卷积、无池化、3分类；非生产模型 |
| α=1 | CPU float32/64及两类mask：原路径与适配路径逐位一致；参数身份、state_dict和RNG保持 |
| α=0 | 主干干预输出与原架构无cue路径逐位一致；更换cue不改变输出 |
| 三个负对照 | uniform逐样本平均且不跨batch；conv_only保留attnfc原对象；fc_mean_preserved仅在末端保持原gain均值 |
| 稳定性 | 四种模式固定输入重复输出一致；输入不变；异常退出恢复；嵌套接入拒绝 |
| 拒绝路径 | 训练模式、未冻结参数、残差/额外cue/双任务/per-kernel路径、additive、模块别名、已有hook、实例forward覆盖、未知模式、错误布局 |
| 数值保护 | 均值保持分母绝对值≤1e-8或非有限时拒绝；不加epsilon掩盖问题；mask行保持identity |

## 负对照端点不能混同主干

- uniform在α=1仍抹去空间/通道gain结构，故不要求等于原模型。
- conv_only在α=0仍保留attnfc的cue作用，不能声称完全cue-independent。
- fc_mean_preserved在α=0仍依赖原末端gain均值，也不是完全无cue基线。

这些是对照定义，不是发现模型存在/不存在某种机制。尚无真实α曲线或负对照统计结果。

## 使用与后续边界

适配器限冻结eval、单线程使用的eager推理；上下文内不得训练、compile、改变dtype/device/架构。它不是针对任意恶意代码的安全隔离器。α和mode不进入state_dict，后续必须绑定外部contract/RUN，当前尚未提供生产RUN生成器。

下一步依次：补池化与生产配置形状覆盖；实现contract/条件-输出身份及拒绝错配回归；准备生产E0小批端点验收清单。超算恢复授权后另行验证真实checkpoint、预处理、A100/编译路径与728520相同布局桥接。当前不具备生产提交资格，不开展独立测试集对齐或训练。
