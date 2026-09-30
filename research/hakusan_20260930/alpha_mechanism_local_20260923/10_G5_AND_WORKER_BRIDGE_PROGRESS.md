# G5独立公式与worker桥接接口（2026-09-23）

状态：LOCAL_G5_AND_BRIDGE_SEAM_TESTED。不等于E0_PACKAGE_LOCAL_PASS或真实模型验收。

## 本轮完成

- `gain_formula_check.py`：独立NumPy FP64参考，不调用被测forward生成期望值；固定双样本、非均匀通道/频率/时间特征，ones和signed两种mixture，各含mask/无mask。八处gain每轮32项，覆盖原路径、旁路、五点α、uniform、conv-only、末层均值保持。
- 检查完整输出与逐样本均值；ones输入显露effective gain，mask行要求identity。固定提案容差atol=rtol=2e-6，分母非有限或绝对值≤1e-8拒绝，不加epsilon、不放宽阈值。仅支持受审架构的标量FP32 gain参数。
- 每轮模块安装后、批forward之前执行G5，纳入原状态/RNG/runtime上下文和协作式时限；报告随阶段结果返回。这不是全部真实激活的数值范围证明。
- `loaded_worker_bridge.py`：**已加载模型的worker-body接口**；正常入口强制读取校验后的728520历史参考，复用受审core、load-report检查与阶段driver。原路径及α=1的四条件logits、NLL逐位桥接，失败不交给下游sink、不继续后续阶段。NLL参考CSV恢复为FP32后比较。
- 接口没有strict-load CLI、不会加载checkpoint，不把调用者提供的load-report视为独立来源证明。成功仍返回NOT_QUALIFIED、production_verified=false。

## 实际证据

本地全套78项测试通过（Python `/opt/anaconda3/envs/audattn/bin/python`，torch2.12.1 CPU）。新增11项包含公式错误注入、控制模式替换、未定义分母、状态/RNG保持、桥接单bit/NLL/ID错配，以及显式合成参考的worker-body接线演练。合成参考只在测试内patch，不作为历史桥接证据。

[新演练REPORT](e0-model-stage-rehearsal-nogvb0d2/REPORT.json)：

- 21轮、6048条小型随机模型输出，672项固定特征公式检查。
- 公式max_abs=2.2145081546298684e-7；逐样本均值最大误差=8.034498044651173e-8。
- 144观察事件；观察记录SHA与上一轮相同，观察前后logits/NLL及归档独立重读检查通过。
- 两个模型对象仍在同一进程，音频预处理为合成接口；不是formal40结果、A100成本测量或冷重复。

复查命令（Mac本地，无远端操作）：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py'
```

## 下一步与保留门槛

1. 接入受审strict-load、冻结import与原生scene/cue provider；加载前核验checkpoint与全部输入来源，不能只信报告字段。
2. 接入两个独立进程、进程组硬超时、失败保留归档及独立验收；G5和桥接记录纳入正式manifest，不能仅留内存回传。
3. 本地完整负测试通过后再审定E0包及G5容差/预算；远端恢复、部署及GPU批次须单独批准。

本轮没有真实checkpoint加载、SSH、上传、GPU作业或训练。09文档G5“尚未实现”是历史状态；目前已实现固定特征检查，真实权重上的G5与历史桥接尚未执行。
