# 真实编译回调登记：本地候选检查完成

后续更新：另获明确资源许可后的CPU Job703751已通过，见
[真实超算执行与原始证据验收](2026-09-13-real-registration-cpu-job.md)。下文保留本地阶段当时的状态。

2026-09-13。用户请求“下一步”；本轮仅本地实现与验证，无远端调用、上传或新作业。
上一阶段CPU Job703415的原始证据重新核验仍为CPU_JOB_EVIDENCE_RECHECK_PASS。

新独立目录：[真实登记候选与操作边界](../prototypes/targeted_real_registration_20260913/README.md)。
使用原严格加载器和snapshot类身份检查，将真实formal40拟接入既有CompiledLease，
而不是改写其CPU限制、绕过原生产CUDA门禁、替换观测器或放宽数值阈值。
42个位置/27模块的结构与父计划相同，登记器包含外层入口/出口共29个回调。

本次已执行：[24项本地测试原始回执](real-registration-local-20260913T051944Z-n3u5umyq/receipt.json)。

- 状态LOCAL_REGISTRATION_CANDIDATE_VERIFIED；24 tests、0 skips、returncode0。
- 新进程PID11652，Python3.11.15、torch2.12.1，耗时2.297秒。
- 17份源/输入文件前后SHA一致；SOURCE_MANIFEST SHA
  `4c72fc9779fe48373908eca2638b69bcf5ed173a9cd9db52062b119128a876d5`。
- output.log：2851字节，SHA
  `273b55864e75a417bca94a9c9e5d6f1f39c1c719cc3642ec8827a26113cf4943`。
- child-result.json：442字节，SHA
  `c6a6c8ca04ee51acd3f35d5342996f0646f55de2d43825b080cc425f44d06f47`。
- Ruff通过。原v18、Job703415所有固定源码/回执不变并经原复核入口再次通过。

测试仅使用合成42位置拓扑，不是真实架构的执行；原2.1.1冷编译器签发在本机
不可验证，未伪造版本。真实checkpoint未加载、原生产worker未签发、CUDA未初始化。
新probe_cpu.py只是待打包计算节点入口，尚无本轮Slurm runner或部署回执。

下一次需要新的明确资源许可：1CPU、4GiB、最多30分钟、无GPU，仅B2真实严格加载/
回调登记/状态与清理检查，不做模型forward。获批后先打包并核对调度请求，再
提交一次；不复用703415的旧意图，不重跑旧提交脚本。

最终三模型smoke、10000条bank/controls、配对统计与论文结果仍未完成。
