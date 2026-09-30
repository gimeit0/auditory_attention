# E0远端部署进度（2026-09-24）

用户要求继续预检、部署及单次held流程。本记录不代表release授权。

- 已复用用户建立的SSH master（pid28212），没有自动重连。
- 只读预检：hakusan1、s2510040；squeue为空；GPU-1A分区UP，nvidia_a100可用；目标目录此前不存在。
- 新建独立目录 `/home/s2510040/audattn_e0/e0_20260924_v1`，暂存上传后移动至其`package`。
- 上传前本地、暂存目录和最终远端目录均通过PACKAGE_BYTES_PASS。
- Release SHA：`05a1271fa398bf2c0006a9486ca09ffae6d9bd8759f7ecb54522460c3c57a9f8`。
- Bootstrap SHA：`1f5e5078689480817f34dfd04c6111b35d2feed7b3a7ce3664ad37dc7e5187be`，远端独立核验通过。
- `E0_PACKAGE_PUBLISHED=PASS`；没有修改原v4输入或旧诊断版本。

## 原生预检结果：停止在提交之前

只读命令导入生产模块后执行verify_snapshot，返回`ValueError: SNAPSHOT_BYTECODE`（退出码1）。依照函数顺序，此前snapshot manifest/provenance_files逐项哈希与size检查未报错；检查在发现`*.pyc`时停止，后续Python文件集合检查尚未执行。不据此声称所有原生预检通过。

没有运行submit_e0_once.py，没有INTENT/作业号，没有模型加载或GPU推理。没有删除缓存或修改原快照，已发布v1保持原样。

下一步：本地设计并测试源码导入的独立缓存隔离，确保不会读旧bytecode，而不是直接允许未知缓存；成功后生成新冻结版本，重新原生预检。不得提交当前v1，不得直接删原快照pyc来制造PASS。
