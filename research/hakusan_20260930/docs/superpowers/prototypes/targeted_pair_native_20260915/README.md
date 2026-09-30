# v19 运行包：有界原生 CPU 兼容性检查

只验证已完成运行包在 HAKUSAN Python 3.11.5 / torch 2.1.1+cu118 下的部分合成 CPU 路径。
不是 GPU 提交入口，不执行真实 formal40 或作者 checkpoint，不写远端冻结清单。

运行入口：[2026-09-15-v19-pair-native-cpu.sh](../../evidence/2026-09-15-v19-pair-native-cpu.sh)。
需要用户先在终端建立共享 SSH 认证；入口不收集密码、不重连、不自动重试。

固定源码清单 `PROBE_RELEASE.json` 绑定四个源文件和原 v19 运行包的 162 文件清单。
远端仅在新建私有 `/tmp/v19-native-cpu-*` 内解包、执行、清理；每组新 Python 进程。
90 秒总执行预算、单 CPU affinity、每组最多 50 秒，日志每组最多 1 MiB；
连接传输外层最多 110 秒。失败立即停止后续组，保存已有证据。

| 合成测试组 | 数量 |
| --- | ---: |
| 新旧输入绑定 | 25 |
| 启动与临时目录 | 12 |
| 结果身份拒绝路径 | 11 |
| 观测适配器 CPU 行为 | 30 |
| 两轮 scratch 生命周期 | 2 |

`CUDA_VISIBLE_DEVICES` 为空，并检查 CUDA 未初始化；数值测试使用合成模型。
Linux mount 工厂条件有明确测试替身，不宣称验证真实挂载、Inductor、A100 推理或修复生产超时。

本地入口：`driver.py check-only` 只核对来源；`driver.py self-test` 运行相同载荷的本地模式。
`remote-cpu --local-receipt PATH` 强制要求同版通过的本地回执和已认证 master。
本地模式不可冒充远端通过。回执包含请求、源码、输出及五组子进程日志绑定。

本次本地自测已完成，原生远端阶段待认证，见[阶段记录](../../evidence/2026-09-15-v19-native-cpu-preparation.md)。
