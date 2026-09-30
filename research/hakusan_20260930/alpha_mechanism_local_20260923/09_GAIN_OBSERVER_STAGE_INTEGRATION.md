# 八处gain观察器与模型阶段流程接入（2026-09-23）

状态：LOCAL_SMALL_MODEL_STAGE_REHEARSAL_PASS。不是生产E0验收通过。

## 实现内容

- `gain_observer.py`只允许在八个已安装的alpha=.5主干gain上注册局部forward hook，要求顺序attn0…attn6、attnfc。每个条件批必须恰好8事件。
- 只存cue/mixture/output的shape、dtype、device、min/max/mean，以及batch/condition/trial身份；不保存或返回激活tensor，不改变hook输出。
- 上限144事件、摘要预算256KiB、单事件保守预留4096字节、单tensor最多6400万元素。拒绝未知gain、已有hook、非有限tensor、错序/缺事件/错误批身份与超预算；异常退出移除自己注册的hook。
- `model_stage_driver.py`接入已加载外层模型的原predict函数，保持原6个scene批各自correct→controls的顺序；每完整pass前后检查模型/RNG/runtime，观测上下文在这些检查之前移除hook，不放宽旧check_model的拒绝规则。
- A阶段11轮（含观察），B阶段10轮。每个pass完成端点/计数/NLL检查后才交给sink。检查同一批条件在各pass间scene/cue不变；变标签、变输入、sink错误及截止时间超限立即退出，不自动重试。

## 本轮真实执行范围

新增11项测试，共67项本地测试通过。首次阶段测试夹具把30元素输入写成60元素，导致reshape失败；改正夹具后重跑全套通过，未改变科学公式或放宽验收。

随后运行[本地阶段演练脚本](run_local_stage_rehearsal.py)，保存了完整模型forward产物，不再只是算术logits夹具：

- 原架构类的缩小配置、随机权重、800类输出，CPU torch2.12.1；预处理/cochleagram仍是合成接口，不是音频管线。
- 独立创建两个同seed模型对象，**同一个Python进程**；因此不构成两个生产进程的冷重复证据。
- A：11轮/3168条；B：10轮/2880条，合计6048条；原路径/α1、独立旁路/α0、α0换cue及A/B对应输出逐位检查通过。
- alpha_05_observed实际挂载观察器，144个事件；与未观测alpha_05的logits/NLL逐位一致。观察记录164,059字节（约160.2KiB），没有整层激活归档。
- 完整npz归档经原合成归档验收器独立重读通过；NLL离线复算最大绝对误差约7.59e-7。

[演练报告](e0-model-stage-rehearsal-_jkdvznn/REPORT.json)包含源码SHA、阶段计数、环境与观察摘要身份；[观察记录](e0-model-stage-rehearsal-_jkdvznn/OBSERVER.json) SHA `9d17022e9b0288c2189493990b2d91e8b4d1567e5c9fbd550d42eddfdcfa95e3`；完整输出位于同目录attempt，不可当作formal40研究结果。

## 尚未通过的生产门槛

1. 无真实checkpoint strict-load、原生音频预处理、728520逐位桥接或A100执行。
2. 观察器目前提供定点摘要与无干扰验证，**尚未实现生产G5的独立gain公式误差统计**；不能把摘要当作完整负对照语义验收。CPU单元已有公式测试不替代此项。
3. 无独立两模型进程/进程组硬超时/Slurm接线。阶段driver只有callback边界的协作式截止检查，不能打断挂住的CUDA调用；现有合成worker watchdog不能冒充完整生产父进程。
4. 有限值检查和统计归约会引入GPU计算/同步开销，A100成本未知，不据缩小CPU模型耗时调整已提预算。
5. 单批测试便利入口predict_loaded_pass仍拒绝alpha_05_observed；观察轮必须走阶段driver，不能绕过批事件身份与预算检查。

## 下一步

在本地补独立gain公式统计和实际worker/历史参考接线，完成生产来源、两进程与失败归档的整包验收；此前不得标E0_PACKAGE_LOCAL_PASS或生成可提交成功状态。只有整包准备完成后再请求用户单独批准远端恢复/部署及GPU批次。

本轮没有连接、上传、checkpoint读取、训练或作业提交。
