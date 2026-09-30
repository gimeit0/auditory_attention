# 正式推理准备接口：本地候选完成

2026-09-13，用户请求“下一步”。本轮仅本地实现与测试，没有SSH、上传、新freeze或Slurm提交。
前置真实CPU Job703751已完成，本轮重新独立复核其26份源/10份原始工件仍PASS。
合成CPU Job703415的25份源/11份工件也重新复核PASS，旧代码和证据未变。

## 本次改动

新增独立[候选目录与边界说明](../prototypes/targeted_production_preparation_20260913/README.md)。
完成正式生产准备函数的两调用接入和CUDA观测生命周期候选，不再使用只支持CPU的lease。
原生产CUDA门禁、严格加载、冻结来源/状态/运行设置检查、原两轮16→1诊断和父结果gate全部保留。

检查发现：原prepare_formal40_worker已经调用_issue_compiler_lifecycle，且该签发器禁止重发。
因此新接口只在加载后登记hook，等待原函数签发后采用既有身份；没有再次签发或改写原函数。
安装或准备中途失败会清理自己的新增回调/worker/编译器身份，保留此前已有身份。

GPU端点摘要复用旧分块传输；FP16/32/64保持原dtype/形状/C序字节SHA，不改变容差或精度。
观测入口使用原run_trace_pass和BaselineBridge，不自行替代推理、重置RNG或重新加载模型。
注意：这是未执行的CUDA候选，不能借用Job703751的CPU PASS宣布GPU接入通过。

## 实际测试结果

[新进程完整回执](production-preparation-local-20260913T055522Z-k2b34qi7/receipt.json)：

- LOCAL_PRODUCTION_PREPARATION_CANDIDATE_VERIFIED，30 tests、0 skips、rc0。
- PID12170，Python3.11.15、torch2.12.1，2.139秒。
- 21份源/输入前后SHA一致；manifest SHA
  `667dca263b9422c67a6308330a9610d6ac5247e4ef76c681a83dc955d590d6a9`。
- output.log：4161字节，SHA `38865d2d49dafd6bd1fa7d64abd70f5c3b78f58e2fd970b21dc630eaa37e91a9`。
- child-result.json：479字节，SHA `8f45b132aa62ea8b4250704168500b7c24af5ddc61ce84b83a3d3806526f2536`。
- 旧准备接口18项回归通过（45.148秒），旧编译接口16项回归通过（1.020秒）；Ruff通过。
- 所有本轮测试均无CUDA初始化、无真实checkpoint加载、无新作业。

保留了一次[本地失败回执](production-preparation-local-20260913T055406Z-g01xegey/receipt.json)：
新增静态测试只匹配方法名reset，将life._ACTIVE.reset（恢复上下文）误判成编译器重置。
已改为完整调用目标匹配，只允许该上下文恢复；禁止编译器/RNG重置仍保留。
这是测试修正，CUDA候选逻辑未因该失败放宽。失败原始日志未覆盖。

## 下一阶段

准备独立GPU小样本运行包和原始证据验收：新参考进程/新观测进程，实际A100/Inductor，
先通过父结果回放与端点无干扰检查，再解释42位置的差异。具体算力与时限、
包SHA、输入绑定、输出/失败归档和单次提交控制仍需审核；本轮不提交。

当前 production_preparation_validated=false、ready_for_gpu=false。
三模型最终对比及科研提交结果尚未完成；这份材料只记录工程接入候选与本地证据。
