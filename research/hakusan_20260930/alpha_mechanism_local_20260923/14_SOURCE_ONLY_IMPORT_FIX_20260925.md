# SNAPSHOT_BYTECODE修正（2026-09-25）

状态：SOURCE_ONLY_IMPORT_LOCAL_TESTED_NOT_DEPLOYED。114项本地测试通过；未连接超算、未上传/提交或读取真实checkpoint。

## 原因与修正

v1验证把快照下任何pyc的存在都视为失败。远端已有缓存，因此在模型加载前停止。单纯`-B`只禁止写缓存，不能作为“不读取缓存”的依据。本轮测试用unchecked-hash缓存构造了可重复对照：普通导入返回缓存中的旧值，新导入器返回已固定源码中的新值。

新增`snapshot_source_import.py`：仅在快照受审导入作用域安装finder，取得模块spec后要求它是清单内的Python源码，读取/核验源字节SHA，再编译这些字节；不走缓存get_code实现、不调用缓存写入。支持命名空间包、嵌套上下文与异常清理。无源码pyc、未知源码、SHA变化、受保护模块或命名空间逃逸仍停止。不修改第三方全局加载器，不改变模型/α公式和任何数值容差。

verify_snapshot继续逐项核验原manifest与文件SHA/大小、Python源码集合、拒绝链接；已存在pyc改为诊断计数。**它本身只是文件检查，防止缓存执行由配套source_only_imports保证**，不是删除一条检查后就宣称安全。加载上下文与新source-check都接入该作用域。

本边界适用于标准Python快照导入；不是防御受信源码主动反序列化任意代码的沙箱。没有新建通用运行时追踪系统。

## 验证结果

- 全套114 tests，10.362秒，OK。
- 新缓存测试：有效但错误的缓存不执行且不改写；损坏缓存不读取；即使允许Python写缓存也不产生新pyc；源码突变/未列入清单/遗留无源码pyc拒绝；命名空间包正常；异常及嵌套时恢复finder。
- Mac调用native source-check在任何远端文件读取或模型加载前拒绝。
- 原v1冻结包按原SHA再次check通过，证明本地冻结v1未改；远端v1和原快照未接触。
- v2冻结包已通过完整文件hash检查；历史参考manifest SHA与v1相同。

## 新发布身份

- [v2构建回执](release_20260925_v2/BUILD_RECEIPT.json)
- [v2操作说明](release_20260925_v2/README.md)
- Release：`abcaa1af63d019e5e4d8701a8522e47f1e280cc8d477f21b2e64225485fd2f17`
- 目标独立目录：`/home/s2510040/audattn_e0/e0_20260925_v2/package`

下一步是远端独立目录部署、全包核验及`source-check`（登录节点只读原生导入，不加载模型/不做GPU推理）。通过后才考虑单次held提交。当前没有新作业号，不能称真实E0已通过。
