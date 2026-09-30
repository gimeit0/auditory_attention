# P05b 投递/收集控制器核心：本地验证

2026-09-18。本轮没有 SSH、远程写入、Slurm test-only、提交或放行。

## 实现

- `control.py`：严格发布清单、独占发布、预算/明确授权要求、调度 test-only、单次 held 提交、独立资源/脚本/未运行 accounting 核验、实际 job ID 契约生成、条件放行、结果有界导出/导入。
- 所有调度写操作前独占写 intent，文件与父目录 fsync。提交/放行结果不明时不重试、不追加作业。实际 GPU 若被站点改写，保持 held；无自动资源修正。
- `launch_approved.py`：从已绑定发布、提交回执、release intent 解析真实 job ID 契约，再进入原运行包装。
- `run_layouts.sbatch` 新增 `--release` 路径；原 contract 参数入口保留。解决了提交前没有 job ID、无法预先生成契约 SHA 的循环依赖。
- 收集验证外部终态 SHA、源码/发布/作业身份、完整目录/文件集合、大小上限、逐文件 SHA；失败产物不会改名为成功。目录穿越、篡改和覆盖拒绝。

## 验证

- 新控制器合成调度测试：15/15，0.256 秒，`controller-tests.log`。
- 原核心回归：69/69，8.474 秒，`core-tests.log`。
- ruff 与 bash 语法检查通过。
- 测试中的批准记录、job 12345、scheduler 响应都是临时合成数据，不是实际用户授权或超算作业。

源码 SHA256：

| 文件 | SHA256 |
| --- | --- |
| control.py | 8877c3bbf42d1178bea0e79a0af4e77985b4fa4442955d21ffd6093a66138796 |
| launch_approved.py | 034cf46b3db77848c08d0335b5e7e009812db0e35666a0765180f82226176737 |
| run_layouts.sbatch | 960cc40f6b8a5c22782ee6ce2eb57dc080f898aa26272bb77bdb98631dac4838 |
| controller_tests/test_control.py | c51619d757cd8d12f89590b6399d034b2e1d44ce20ddbc85535cdbf34f100916 |

## 未完成边界

本次只是可测试的控制器库，尚无 SSH 操作 CLI、发布包生成/冻结入口、原生账户前检、异常提交身份恢复查询入口和下载后的科学独立复算入口；不可直接用于正式投递。后续需将这些接上并补充集成测试。

此前原生 69 项通过仅覆盖当时源码；新增 controller/launcher 和此次改变的 sbatch 尚未在原生环境验证。不能把旧原生证据当作新包的原生证据。

1 A100 / 8CPU / 64GiB / 30分钟预算仍未批准；未生成任何正式 RELEASE/AUTHORIZATION/CONTRACT。四布局真实模型尚未执行，全量 checkpoint 对比尚未完成。
