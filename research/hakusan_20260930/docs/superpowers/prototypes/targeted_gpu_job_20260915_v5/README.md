# B2 v19 双进程候选入口（本地集成阶段）

目标：将 v19 模块扫描优化接入独立 reference / observed 两个冷进程，保留 Job685198 的 B2 数组作为历史数据 oracle。不是 formal40 与作者 checkpoint 的总体比较。

## 身份边界

- 新代码：v19 核心及 `*_20260915_scan` loader / observer 链。
- 新输入：固定 v19 根目录的 `input_freeze.json`，SHA 必须由未来实际冻结产生并显式传入；当前没有新远程冻结 SHA。
- 旧输入：v18 清单只绑定相同科学输入与历史计划，不授权新代码。
- 授权：必须另外审阅新 package SHA、new freeze SHA、v19 code SHA、pair nonce 和资源限制。旧 Job715276 授权不可复用。本目录不写授权、不调用 SSH / sbatch。
- 每个子进程记录 `INPUT_BINDING.json`。父进程独立复查新旧清单关系、v19 pass attestation、运行前后审计与新 freeze 的一致性，再进行原有完整数组和逐层捕获验收。缺失、非零退出、超时、清理失败均不接受为数值结果。

## 未变化的限制

1 A100 / 8 CPU / 64 GiB / GPU-1A / 2 小时；每个 child 3000 秒、整个 pair 6600 秒；reference 失败不启动 observed；没有重试、自动重连、容差放宽或减样本。

v19 目录内继承的 `run_numeric_diag.sbatch` 是全矩阵历史回归依赖，**不是本次提交入口**；不要运行。新 B2 入口是本目录 `run_gpu.sbatch`，但当前没有部署/冻结/提交授权，不要直接 sbatch。

## 本地验证

从项目根目录运行（只产生本地证据）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/prototypes/targeted_gpu_job_20260915_v5/validate_local.py
```

每组测试运行于独立进程。覆盖 synthetic CPU、真实 spill/mmap 文件、195.3125 MiB 合成零数组流式校验、失败控制与新身份拒绝测试。`test_result_identity.py` 使用明确标注的 provenance doubles，仅验证拒绝逻辑，不能当作真实 production/A100 证明。

`TRANSFORM_RECIPE.json` + `verify_recipe.py` 精确恢复旧入口到新入口的每项变更，未修改旧文件。`release_manifest.py --check` 只读复查整个源码集合。SOURCE_MANIFEST 中 `ready_for_gpu`、`submission_authorized` 均为 false，真实 candidate freeze SHA 为 null。

下一阶段：在 HAKUSAN 同一 Python / torch 环境进行有界兼容性测试、审查独立部署控制程序；实际冻结并审阅新 SHA 后另行确认一次 GPU 提交。当前尚未证明 v19 在 A100 上能够在原超时内完成。

科研解释仍为 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
