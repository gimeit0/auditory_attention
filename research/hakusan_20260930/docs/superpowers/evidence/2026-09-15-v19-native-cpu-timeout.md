# HAKUSAN 原生 CPU 检查：78 项通过，最后一组两次触及时限

日期：2026-09-15 JST。对应用户“下一步”。最终模型比较仍未完成，没有新 GPU 作业。

## 已核实的实际状态

上轮交给用户的 CPU 入口已经运行，不能再把它记作“未连接、尚未执行”。
回执目录 `v19-native_cpu-20260915T044848Z-asqdz_1u` 中，前四组 78 项在
HAKUSAN Python 3.11.5 / torch 2.1.1+cu118 下通过，均为独立进程、单 CPU affinity、
CUDA 未初始化、无真实模型。最后 `scratch_lifetime` 组未完成。

| 原生检查组 | 完成回执中的测试数 | 子进程耗时（秒） | 结果 |
| --- | ---: | ---: | --- |
| 输入绑定 | 25 | 5.807 | PASS |
| 启动与目录 | 12 | 6.444 | PASS |
| 结果身份 | 11 | 1.374 | PASS |
| 适配器 CPU | 30 | 33.712 | PASS |
| scratch 生命周期 | 无完整回执 | 37.690 | 总预算剩余时限耗尽，-9 |

90 秒监督器为清理预留 5 秒，最后一组实际只获得约 38 秒；整个载荷 85.166 秒，
传输总计 93.138 秒。终态是 `CPU_PROBE_FAILED`，不能记为 80 项通过。

## 本轮执行的一次补测

保留原包、原清单、失败回执和日志；新增独立
[scratch-only 入口](2026-09-15-v19-scratch-only.py)。
它从固定旧监督器精确派生，仅选择 `scratch_lifetime`，并更名成功标记和范围说明；
原 90 秒总上限、50 秒单子进程上限、单 CPU、清理和结果检查不变。
没有改动实际测试源码、v19 模型/保护逻辑、样本数、数组验收或数值容差。

8 项离线拒绝测试通过。相同补测载荷先在本地完成两个测试，18.182 秒、RC=0。
随后经现有 SSH 连接在 HAKUSAN 执行 **一次**，子进程在 50 秒上限被停止：

- 子进程耗时 50.285 秒（包含停止/回收开销），`TimeoutError: child deadline reached`，RC=-9。
- 载荷耗时 50.335 秒；SSH 传输总计 58.517 秒，正常返回失败 RC=2。
- 监督器确认临时目录已删除；没有永久部署、input freeze 或 Slurm 提交。
- 本轮没有再重跑任何远端测试。前四组不重复执行；原失败没有被改成 PASS。

两次超时日志逐字节相同：第一项 `test_original_globals_preserved_and_exact_type_substitution` 显示 `ok`；
第二项 `test_real_mmap_two_pass_original_cpu_lifetime` 已开始但没有结束、断言失败或异常栈输出。
由于该组缺少最终完整回执，按完整组保守报告 **78 项已核验，最后 2 项待完整验收**。

## 能确定什么，不能确定什么

单独给予该组原有 50 秒上限仍然超时，所以不能把第一次失败完全解释成“前面的组占用了时间”。
当前只能定位到第二个测试，不能进一步确定是模型检查扫描、数组归档、mmap、导入或登录节点负载。
没有证据证明是数值不一致、死锁、GPU 故障或内存不足；也不能据此断言只需扩大超时。
CPU 合成测试与正式 GPU 推理不同，不能把本地/登录节点耗时解释成 A100 的预测耗时。

## 可追溯证据

- [原生五组失败回执](v19-native_cpu-20260915T044848Z-asqdz_1u/receipt.json)：`c40a8cbc84f88fbadffdf8df077e50f41b7058c7f950faf4185aab55b5f95081`
- [补测本地成功回执](v19-scratch-local_harness-20260915T045750Z-_z_arfpq/receipt.json)：`ba9a3fddf7fa879ecd47c8ea2ad87b8355b03287de83bb0eb0f60f85a9849b3f`
- [补测原生超时回执](v19-scratch-native_cpu-20260915T050719Z-4mvl4z7h/receipt.json)：`36316c36be181dce71ffd171047dbefd7795a5db5538db6684d2b2b9806db661`
- 两次超时子日志 SHA：`8ee0c56923a9e6d720db4e853671a3eb842a2481c20f5f57442fc592496c94d6`
- 精确派生 CPU 监督器 SHA：`af892c8baca803c0da36f3cf262dec952efcc61bb94e1acfe4439cda8fa9c776`
- [只读证据复核入口](2026-09-15-v19-native-continuation-review.py)：核对原失败、两次补测包、完整请求、日志及 163 份载荷文件，不执行请求、不连接网络。

上一阶段 162 份运行包来源、17 份派生关系、20 份测试工件也已重新只读复核通过。
本轮文件新增在 evidence 内，原 native 检查器和冻结运行包没有修改。
三个执行包及其请求/日志的只读复核已通过；这证明失败证据绑定一致，不代表原生测试整体通过。

## 下一步范围

需要先为这个合成 CPU 测试增加可审核的阶段计时或单次超时栈定位，保留原测试及拒绝条件，
再决定修正耗时路径还是将完整测试迁到获批计算节点。不能直接重复现有补测、减少样本、
放宽验收或放行 GPU。阶段计时/栈定位 **本轮尚未实施或执行**。

当前：`complete_native_compatibility_verified=false`、`ready_for_gpu=false`，新 freeze 未取得。
科研角色仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，尚非模型总体比较结果。
