# 21轮完整合成归档与失败处理（2026-09-23）

状态：SYNTHETIC_ARCHIVE_VERIFIED。不是E0_PACKAGE_LOCAL_PASS或E0_ENDPOINT_PASS。

## 实际执行

`e0_archive_harness.py`按已锁定96条布局依次产生21轮、84组条件数组，共6048条800维float32合成logits，保存NLL与trial IDs；每轮独立npz，清单记录SHA/大小/条件身份。父进程独立重读后才写SYNTHETIC_COMPLETE.json，不生成生产COMPLETE。

保留的完整演练产物：[attempt](e0-synthetic-archive-ggutebpt/attempt/)，[完成记录](e0-synthetic-archive-ggutebpt/attempt/SYNTHETIC_COMPLETE.json)。总字节19,496,530，manifest SHA `3c8bffa49c79f3d9c5375078cc9bf6f6f65c79f81f0d649045845ce1b646e40e`，CPU NLL复算最大绝对误差2.30e-7。文件是合成测试结果，不可并入研究数据。

新增8项归档测试，与已有测试合计56项全部通过。测试涵盖：完整写入/重读、已有目录拒绝覆盖、worker报错保留前两轮、父进程超时终止worker、端点错配不准完成、字节损坏、缺文件、伪造生产通过标记。测试中的临时损坏文件随临时目录清理；上述独立演练完整产物保留。

## 现有机制

- 每个attempt只运行一次，目录已存在即拒绝，无自动重试。
- 父进程限制合成worker≤60秒；超时终止并等待退出，保存FAILED与已有产物。正文失败不生成完成标记，失败attempt不能通过重读。
- 验收固定21轮顺序、mode/条件/trial身份、6048计数、有限FP32 logits、NLL复算、端点/重复/观测标签之间的logits与NLL逐位关系、α0条件间不变性。
- 归档≤128MiB；只接受普通文件；npz不允许pickle。文件SHA和完成标记均复核，不把文件存在当成功。

## 不可省略的边界

这是一个**单worker合成演练**：A/B是逻辑标签，不是两个重新strict-load的生产进程。logits由固定算术夹具生成，观察器标签也由夹具模拟，未调用真实gain观察器。因此不能据此宣布冷重复、观测无干扰或真实模型G0–G7通过。

当前端点参考来自合成夹具内部，不是728520历史桥接；历史参考读取器已另测，但与worker的实际接线仍待完成。合成演练不用GPU，也没有读取checkpoint。父进程超时只管理该直接worker；未来若worker启动子孙进程，需要另实现进程组清理。验收阶段逐段检查/预算仍需生产协调器整合，不能声称本工具等同Slurm硬时限。

## 下一步

1. 实现有界8处gain观察器，测试记录不改变输出、异常清理与完整事件计数。
2. 将阶段驱动与已加载模型接口相接，补独立两进程、严格加载前置、输入来源与历史桥接，而不是把合成worker改名为生产worker。
3. 整包本地回归通过后才可称E0_PACKAGE_LOCAL_PASS；之后仍须独立批准远端恢复/部署/原生CPU验收及GPU批次。

无SSH、上传、GPU或训练。远端暂停不变。
