# E1 加载接口、进程与归档接入（2026-09-26）

状态：`E1_SESSION_ARCHIVE_LOCAL_TESTS_PASS`。仅本地实现及合成验收；不代表生产包就绪、真实模型推理通过或科学结果成立。

## 本轮完成

- `e1_provider.py`：主布局沿用原生 provider；新 clean 使用 v2 正确 cue/零 cue 配对路径，约束配对顺序与 trial 身份。
- `e1_audited_session.py`：保留 E0 文件，另建 E1 受审加载接口；绑定冻结数据、检查音频 SHA、沿用严格 checkpoint 加载、源码检查与输入后验检查。
- `e1_supervisor.py`：A、B 两个独立 worker 后启动独立 VERIFY 进程，三者共享最多 9,900 秒硬时限。首个失败即停止，无重试；保留各进程日志、启动记录和失败记录。
- `e1_worker_archive.py`：仅在受审 session 后验检查完成后发布 WORKER/STAGES；对输出逐文件 SHA、trial 顺序、进程/作业/合同绑定、加载覆盖率、阶段数及数组端点进行离线验收。
- 不改既有 E0 冻结包或 E1 数据冻结文件；新 clean 生产路径使用 v2 适配器。

## 实际测试

命令：

```sh
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_e1_*.py' -q
```

结果：52 项通过，5.540 秒。包括 provider 路由、入口拒绝、独立进程、worker/验收超时、失败归档、38,400 条合成预测归档往返及数组/阶段/进程身份篡改、额外文件拒绝。

合成归档中的加载和 G5 报告为测试夹具，**不能证明真实加载或真实 G5 通过**；归档散列只提供一致性检查，不独立证明报告真实性。生产入口必须绑定实际执行源码及启动记录。旧 clean 兼容测试触发一次只读 NumPy 数组转换 warning；本轮不改冻结历史函数。

本轮未连接超算、未加载真实 checkpoint、未上传或提交 GPU 作业。

## 剩余出口与顺序

1. 完成便携生产入口：移除 contract 对本地仓库路径的依赖，明确数据、布局、音频、源码身份及唯一启动参数；连接 worker/supervisor/verifier CLI。当前组件不能直接视作可提交包。
2. 补生产启动链、G5 明细完整性和失败注入测试；本地冻结发布包，再单独申请原生 CPU 导入/接口验收。
3. 审定完整 E1 合同及预算：当前矩阵 A 34,800 + B 3,600 = 38,400 条，60 个数组记录。候选 1 A100、8 CPU、64 GiB、3 小时仍待批准，不保证吞吐线性。
4. 批准后才上传/核验、test-only、单次 held 提交；放行和站点 GRES 修正另按权限执行。失败不自动重试。
5. GPU 完成后独立验收和统计分析；E1 为复用验证 bank 的开发扫描，不改称独立测试。
