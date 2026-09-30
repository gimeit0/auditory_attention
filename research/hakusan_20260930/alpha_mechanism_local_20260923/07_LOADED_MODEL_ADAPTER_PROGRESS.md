# 已加载模型适配接口与独立旁路（2026-09-23）

状态：E0_LOADED_MODEL_SEAM_LOCAL_PASS。不是E0_PACKAGE_LOCAL_PASS或E0_ENDPOINT_PASS。

## 实际完成

- `loaded_model_adapter.py`按SHA `09cb0c4816d001d172215ead49a1a0c9efde07b794125da4980dd822883a4d5b`读取历史eager_compare模块，复用predict、unwrap_eager、check_model、state_digest、rng_digest、runtime_values；不修改旧三模型协议或冻结源码。
- 新接口只接收已加载模型。检查formal40标识、预期checkpoint SHA、加载覆盖计数和预处理角色，再检查模型解包与8处gain布局。**检查调用者提供的报告不是文件来源证明**，返回的production_provenance_verified固定False。
- `BypassGain`直接返回mixture，不读取cue、不计算sigmoid/α公式；与α适配器仅共享布局安全检查。参数身份和state_dict键保留，异常恢复原模块。
- 10个未观测条件已可通过统一上下文使用原预测函数；按阶段检查输入/模型状态/RNG/runtime。未知条件及尚未实现的alpha_05_observed明确拒绝，不能静默当作普通alpha_05运行。
- 12项新增测试，总48项本地测试通过。包括α=1原输出及NLL逐位一致、旁路独立性/α=0 cue无影响、所有预定未观测模式有限、异常恢复、状态/RNG/runtime改变拒绝、外层预处理training拒绝。

## 必须保留的边界

测试外层为合成wrapper，预处理为identity spy，cochleagram为合成features，主干来自受审类但使用缩小尺寸及随机权重。测试未调用strict_load_model，没有读取checkpoint/音频。它验证调用顺序与接口兼容，不证明真实音频路径或strict-load生产整合正确。

生产worker尚未实现：需在冻结manifest/导入上下文、已批准的作业环境下调用原strict_load_model(manifest, 'formal40', device=cpu)，核验来源，再解包/迁移/重置推理RNG后进入本接口。不得将手填SHA和合成report当作此过程。

异常路径恢复的是模块安装，不回滚调用方已经修改的参数、RNG或runtime；任一检测失败必须终止并记录，不继续使用污染模型。上下文正文报错时保留原异常；完整失败归档和后检查由待实现协调器负责。

目前predict_loaded_pass每次调用会做完整状态摘要，主要供本地测试。生产应每完整pass使用一次pass_context，在批循环内调用同一predict，避免把大型参数哈希同步成本乘以批数；必须用实际计时校验预算。

## 下一步

实现阶段协调器及本地合成完整归档：21轮、6048条输出、G1/G2/G3比较表、失败和超时记录；然后接入有界观察器G6与完整生产加载前置门。未完成之前不提供提交入口，不恢复超算。
