# E1 v2 整包本地交付与后续操作

日期：2026-09-27。状态：**E1_LOCAL_RELEASE_CANDIDATE_PASS（v2）**。本包按用户 2026-09-27 定下的决定 A 至 E 重新冻结，替代 [v1 package_ready](../release_e1_20260926_v1/package_ready/)（release SHA `ebe4dfb9…`，不再是待提交候选，保留不覆盖）。**不表示原生 E1 运行、GPU 授权或科学实验完成。**

## 唯一应继续使用的候选

- 本地包：[package_ready](package_ready/)（26 个文件加 RELEASE.json）
- 计划远端位置：`/home/s2510040/audattn_e1/e1_20260927_v2/package`（本轮未创建/上传）
- Release SHA：`964a00837fb0df1e0bd13e0da09dbe3c6c584289b70f229f506685b084318e99`
- Entry SHA：`28cae480576a3beccf17d0c26b969beac4c70a41a7f4280bf81b654f2879f2f2`
- Runner SHA：`9466b2a7bffc6bdbfbd2dadf6f746e8453bf5519ce2e312b4bf5bba7c1ab8e72`
- 输入合同 SHA：`396e233463f07b3bce3ba744cea5505bc6be55c560e25de527033a470a6877a7`（合同版本 E1_EXECUTION_V2_20260927；数据冻结、2000 条布局与 v1 相同）
- scope：`E1_FORMAL40_NATIVE_20260927_V2`；scientific_status：`DECISIONS_A_E_RECORDED_STATISTICS_CONTRACT_V2_BOUND_SIGNOFF_EXTERNAL`

## 相对 v1 的变化（决定 A 至 E）

- 决定 A：干预公式 `gα = 1 − α(1 − g)` 不变，E0 作业 746603 的验收继续有效。
- 决定 B：α 网格由 {0, .25, .5, .75, 1} 改为 {0, .5, .75, .875, 1}（alpha_875 替换 alpha_025）；三负对照仍在 α=.5；预测数仍为 38400（A 34800 + B 3600，60 个数组记录）。RELEASE.json `execution.alpha_grid_revision` 记录前后网格与依据。
- 决定 C：`execution.pilot_exposure` 记录 E0 96 条与 E1 2000 条的 19 条重叠 trial（5 条 clean）及处理方式（保留、披露、标记、附敏感性版本）。
- 决定 D：不做探针。决定 E：预算候选上限不变（1 A100 / 8 CPU / 64 GiB / 180 分钟；9900 秒总时限、9000 秒 worker 上限），仍需单独批准。
- 来源字段（27 号文 §7 的 P1 至 P5、P7、P8）：worker 在 WORKER.json 写 `environment`（Python/torch/CUDA/cuDNN 版本、GPU 型号、hostname、Slurm 作业号与 CPU 数），在 STAGES.json 写 `process_started_utc`/`process_finished_utc`、`runtime_values` 与每 pass 的 `pass_resources`（起止 UTC、耗时、CUDA 峰值显存 allocated/reserved、进程 ru_maxrss 与单位）；`verify_archive` 对这些字段做存在性与类型验收（PROVENANCE_ENVIRONMENT / PROVENANCE_FIELDS / PASS_RESOURCES 等拒绝码）。P6（sacct/scontrol 只读回读）属收集阶段动作，P9（统计合同签署记录）为外部文件，P10 未采纳。
- `decision_record` 绑定三份文档的 SHA：26 号读数备忘、27 号决策稿、28 号统计合同 v2（`d9dd0eca574ba529…`）。这三份文档此后不得改动，否则须重新冻结。

## 已实际完成的验收

全目录回归：

```sh
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py' -q
```

220 项通过（此前 214；新增决定 B 网格、试点暴露常量与 E0_LAYOUT_96.json 一致、来源字段缺失/类型错误拒绝、合成 body 的资源记录等 6 项）。

冻结包检查（cwd=/，隔离解释器）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/release_e1_20260927_v2/package_ready/e1_entry.py check 964a00837fb0df1e0bd13e0da09dbe3c6c584289b70f229f506685b084318e99
```

返回 `E1_PACKAGE_BYTES_AND_INPUTS_PASS`，jobs_submitted=0。

三进程合成演练（SYNTHETIC ONLY，不加载 checkpoint、不初始化 CUDA）：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/rehearse_e1_release.py "$PWD/alpha_mechanism_local_20260923/release_e1_20260927_v2/package_ready" 964a00837fb0df1e0bd13e0da09dbe3c6c584289b70f229f506685b084318e99
```

结果 `E1_PACKAGED_SYNTHETIC_PIPELINE_PASS`，38400 条，A/B/VERIFY 三个不同 PID，证据目录 [e1-release-rehearsal-8lrxuv6g/](../e1-release-rehearsal-8lrxuv6g/)；A 进程 WORKER.json 已含 `environment`，STAGES.json 含 17 个 pass 的 `pass_resources`（本机无 CUDA，显存字段为 null，ru_maxrss 单位 bytes）。

## 后续（每步单独授权，见主计划 §13）

1. 统计合同签署记录：新建 `docs/superpowers/evidence/e1-contract-signoff-2026MMDD/SIGNOFF.json` 绑定 28 号文 SHA `d9dd0eca574ba529c0b0596ba3ed26f557917222b1fa965112e21105d91a7c5f`；签署人须先阅读 28 号文 §4.4 关于 δ=2 个百分点可达性的保留意见并决定 δ。
2. 用户终端认证 SSH 后：独立新目录上传、外部核验 entry 与 release SHA、整包核验、原生只读 source-check。
3. 预算申请（1 A100 × 180 分钟候选上限）与单次 held 提交；held 回读；若 typed GRES 被改写按单独授权唯一一次修正；用户授权 release。
4. 收集时保存 sacct/scontrol 只读回读（P6）；离线 `offline-check`；来源字段完整性检查。

`package`、`package_final`、v1 `package_ready` 均为历史候选，保留不覆盖，不部署。
