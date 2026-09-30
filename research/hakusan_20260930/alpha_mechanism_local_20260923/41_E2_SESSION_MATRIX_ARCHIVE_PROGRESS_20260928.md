# E2 session、矩阵、端点与归档接入

日期：2026-09-28。状态 `E2_LOCAL_STAGE_PIPELINE_CANDIDATE`。本批无SSH、上传或GPU作业；真实checkpoint原生内容检查的通过证据见[40号文](40_E2_CHECKPOINT_COMPATIBILITY_RESOLVED_20260928.md)，不将其扩大成模型推理通过。

## 完成内容

1. `e2_catalog.py`固定8阶段的路径、大小、SHA及阶段编号，来自已核验远端库存。`load_stage`要求记录逐字段相等，不能将早期权重替换成formal40或反过来。
2. `e2_audited_session.py`以E1 session为受审基线另建候选，不改E1文件/冻结包。保留快照源码、原生前处理/音频、运行设置和锁检查；新加载入口在原生构造器生成模型后、eager unwrap之前严格装载阶段权重。这里的顺序必须保持，因为checkpoint含原有compile-wrapper键名，不允许随意改键。
3. `e2_matrix.py`、`e2_execution.py`接入8阶段。0/4/16/40轮五点α，1/2/8/24轮仅α=1，共144条条件记录、86400条预测。复用E1原生音频provider和gain干预/公式检查，不添加新声源或新科学样本。
4. `e2_endpoint.py`固定取首个含control的原main批及首个clean批，六条件原始forward对α=1逐位比较；每阶段126预测，总1008。检查失败停止，不按结果放宽阈值。检查后重设原运行随机状态，再进入科学条件。
5. `e2_stage_archive.py`保存阶段绑定和NPZ，独立复核文件SHA、布局SHA、条件库存、trial顺序与NLL。验证拒绝跨阶段错绑、额外文件和修改后的加载身份。此门明确不等于完整生产来源与实验验收。
6. `e2_history_bridge.py`绑定E1作业750474的A/WORKER.json SHA `073755f2d0aba58502c76614971d6e613440f6e13ba5d6b2ea4e418e74557da5`，读取六个同布局α=1条件共3600预测，逐文件核对SHA和NLL。检查新stage40输出的logits/NLL必须逐位相等，不修改原参考。当前只完成历史参考自检和篡改拒绝测试，尚无新GPU输出供真实桥接。
7. `e2_stage_worker.py`连接session→端点→执行→输入后检→归档→离线数组验证→stage40历史桥接；保存失败类型与已完成记录数，无自动重试。父进程完整时间记录模块已存在，但多阶段生产协调器仍须接入。

## 本地验证

以下11个测试模块共59项通过：test_e2_endpoint、test_e2_history_bridge、test_e2_stage_archive、test_e2_execution、test_e2_stage_loading、test_e2_archive_loader、test_e2_restricted_load、test_e2_stage_inspection、test_e2_static_stage_fields、test_e2_process、test_e2_checkpoint_inventory。

合成执行覆盖8阶段、144条件记录、86400预测；这些零logits合成数组没有科学含义。真实E1参考只读自检通过；候选stage worker导入通过，未构造真实模型或初始化CUDA。PyTorch2.12本地/2.1.1远端差异仍需原生生产验收，不能仅以本地测试取代。

当前预算计数：分析86400 + 八阶段端点1008 = **87408**；未包括独立冷重复。此数替代“86400为全部成本”的潜在误读。GPU时限还必须计8次模型加载、输入/来源前后核验、落盘和独立验证，尚无GPU预算批准。

## 剩余出口（不可跳过）

- 多阶段协调器及独立验证进程：绑定完整生命周期、job/release/argv、环境/运行设置、阶段报告与来源，不能只信数组通过。
- 冷重复范围与预算、失败/超时归档语义；科学矩阵与工程预测分别计数。
- 便携候选包：源码/输入/历史参考完整闭包、默认不执行的入口、冻结合同和一次held提交工具。现有模块不是可直接提交包。
- 原生小批端点与stage40历史桥接，经有限预算批准后执行；通过后才申请/运行完整E2矩阵。
- 阶段×α统计、错误结构、独立复算和报告，才达到E2_TRAJECTORY_DESCRIBED。只有α=1的阶段不具备自身α=0批形状残差对照，相关cue差须如实说明，不能假定残差为零或冒充E1的完整D。

E4仍因未取得人类数据保持DATA_WAITING；本批未启动E3或E4。
