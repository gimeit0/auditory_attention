# 原 v18 检查下的受控观测生命周期（合成 CPU）

本组件接续[无新增 hook 的基线桥接](../targeted_worker_20260912/README.md)，
在**原 v18 函数不修改、不复制、不替换、不重新签发已有身份**的条件下，
验证预先登记 hook 与原执行检查能否共同运行。不是生产 worker 或 GPU 入口。

## 接入方式

测试夹具预先构造一个模型，安装固定回调，再把该对象交给原严格加载接口的
`model_to_load` 测试槽。随后实际调用原 `prepare_formal40_worker`，只签发
一次 `hermetic-test` 身份；原 `run_trace_pass` 完整运行 16→1 两个 pass，
32 条、34 次 forward。没有改写生产加载器，也没有安装后重新计算身份来
掩盖变动。真实严格加载器没有这个测试槽，生产接入尚未实现。

固定 hook 通过 `ContextVar` 路由到唯一活动记录器。需要明确：**v18 只绑定
固定回调与 ContextVar 对象，并不递归认证其当前内容**。新组件因此单独
核对源文件、函数/方法绑定、模块与 hook/flags、计划和批次、追加记录、
采集账本、字节预算、原 prediction 作用域及输入/输出，不能把这称作已
获得生产执行能力认证，更不是可抵抗任意 Python 内存篡改的安全沙箱。

每个批次验证原输入特征未改变、RNG 和 runtime 未改变、共享模块调用
顺序与阶段覆盖完整。pass 返回后，记录器的输入/输出摘要要与原 pass 的
逐批 guard 匹配；所有原边界、原 commitment 和正式指标继续交给未改写的
父数组 gate 核对。采集沿用固定 SHA 的 `CaptureStore`，结束时逐文件完整
重读。运行成功或失败都移除本组件 hook；对应旧身份撤销，不可再使用。

这里直接拒绝 `OptimizedModule`、非 CPU 或非 hermetic 路径。严格的逐调用
RNG 不变检查尚未处理真实编译首次初始化的合法变化；不能直接拿去跑
Inductor，或者通过重设种子解决。后续必须与独立冷参考的实际行为核对。

## 本地运行

在项目根目录执行：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_lifecycle_20260912/validate_local.py
```

一次监督运行最多 180 秒，没有自动重试。新私有证据目录保存日志、子进程
结果与监督回执；测试采集文件仅存在于 `TemporaryDirectory` 中，测试退出
后清理，不能把摘要回执称作已归档完整真实模型特征。

## 验收范围与限制

新增 25 项测试包括 A2/B2 各 34 次实际合成推理、4 个阶段（共享 stem 两次）
的 136 次调用、2 个目标的 16 份完整采集，以及晚登记/错序/缺失/多调用/
hook 替换、函数与实例方法替换、账本/计划/预算变动、RNG/runtime/输入/
注册状态/端点变动、父数组不匹配、失败重试和非测试域拒绝。

参考和观测使用同一测试进程内分别创建的合成模型。CPU 上的 A2/B2 标签不
代表执行了 GPU AMP；没有使用 Job685198 的真实 32 条数据，也未装载
formal40。原型只证明此生命周期在本机测试环境中可行，不证明 42 个真实
位置、独立冷进程、torch2.1.1、Inductor 或 A100 的观测有效性。

源代码见[实现](observer_lifecycle.py)、[测试](test_observer_lifecycle.py)、
[监督入口](validate_local.py)、[固定 SHA](SHA256SUMS)。
最终证据见[本地验收记录](../../evidence/2026-09-12-observer-lifecycle-verified.md)。

下一阶段是生产准备流程中的显式观测登记与来源绑定，并连接真实模型、
同版本检查和冷进程归档。新 GPU 作业要另外确认范围与预算。本轮不上传、
不 freeze、不提交作业；三模型 smoke 和完整 same-bank 对比仍未完成。
