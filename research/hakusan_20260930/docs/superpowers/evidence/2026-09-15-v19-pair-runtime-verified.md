# v19 B2 双进程入口：本地集成与验收完成

日期：2026-09-15 JST。对应用户“开始吧”。本轮范围为本地实现、验证和记录，未连接 HAKUSAN，未上传、冻结远端输入或提交 GPU 作业。

## 结论

v19 的已验证扫描优化已接入独立新版 `coordinator / gpu_child / startup / scratch / verify_results`。
本地 10 个冷测试进程、162 项测试全部通过，错误/失败/跳过均为 0，所有进程 RC=0。
随后独立复核 162 份源文件、20 份测试日志/JSON 工件及回执，通过。

入口目录：[targeted_gpu_job_20260915_v5](../prototypes/targeted_gpu_job_20260915_v5/README.md)。

这只完成“诊断工具运行与验收入口”的本地阶段，不是训练模型或作者 checkpoint 的总体比较结果，也没有证明 A100 上的 3000 秒超时已经消除。

## 实现的关键边界

1. 两个子进程实际使用 v19 loader、新核心 SHA；新 freeze SHA 为显式参数，不能拿 v18 SHA 代替。
2. 旧 v18 清单保留为相同科学输入/历史计划的依据，Job685198 的固定父结果仍是数组内容比较 oracle；没有伪造旧执行身份。
3. `INPUT_BINDING.json` 记录新代码、新清单与旧科学数据关系；子进程和父验收分别复查。原 `_load_worker_inputs`、`_revalidate_worker_inputs` 和完整数组/捕获门限保留。
4. PRECHECK 与 POSTCHECK 不仅要彼此相等，还必须转换后精确匹配新 freeze。每个原始 pass attestation 必须标记 v19 production 协议。
5. 新授权必须同时绑定 package、new freeze、v19 source、nonce 和固定资源；旧授权、错版本/清单、提高资源、缺失证据、子进程非零退出及清理失败均拒绝。
6. 17 份派生文件有逐项精确转换配方；执行 lifetime、原扫描调用次数和数值容差不变。旧包、完成的 v19 loader 集成及历史失败证据未覆盖。

限制仍为 1 A100 / 8 CPU / 64 GiB / GPU-1A / 2 小时，child 3000 秒、pair 6600 秒，reference 失败后不启动 observed，不自动重试或重连。

## 测试范围

| 组 | 数量 |
| --- | ---: |
| 进程、超时、资源与失败控制 | 27 |
| 新旧清单、源码和授权绑定 | 25 |
| scratch 生命周期 | 12 |
| 结果身份与原 pass 拒绝路径 | 11 |
| 168 项捕获文件验收 | 13 |
| 完整 204,800,000 字节合成数组流式校验 | 3 |
| 启动设置与外围计时 | 16 |
| 原两轮合成 CPU lifetime、真实 spill/mmap | 2 |
| 完整归档与 reference 回归 | 38 |
| 科学输入关系回归 | 15 |

本地 Python 3.11.15 / torch 2.12.1。CUDA 均未初始化；未加载真实 formal40。结果身份单测使用明确标注的 doubles；scratch 工厂的 Linux mount 判断使用测试替身。因此不宣称 HAKUSAN Python 3.11.5 / torch 2.1.1、Inductor 或 A100 已验证。

完整整包验证一次即通过。独立复核脚本初稿把过程日志记录（含 `name`）与文件哈希记录（不含 `name`）直接比较而拒绝；已改成同时检查准确文件名、size、SHA，未改测试回执或运行器，复核通过。

## 可追溯证据

- [本地回执](gpu-pair-v19-local-20260915T035834Z-sf4x1k2y/receipt.json)：`d85d45f80af2cac44a486d28416b9590f5ad7c70e1c78d9e74022f3fb0e9c437`
- [源码清单](../prototypes/targeted_gpu_job_20260915_v5/SOURCE_MANIFEST.json)：`c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20`
- [精确转换配方](../prototypes/targeted_gpu_job_20260915_v5/TRANSFORM_RECIPE.json)：`a1eb16b8a36313bfc3b8559339e55b2b824e32b831075db6f9e82328ac223750`
- v19 核心：`c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d`
- [独立只读复核脚本](2026-09-15-v19-pair-runtime-review.py)。前阶段的 925 项集成回执也已只读复核通过；不要把重叠测试简单相加为独立覆盖率。

从项目根目录重新只读检查：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/evidence/2026-09-15-v19-pair-runtime-review.py docs/superpowers/evidence/gpu-pair-v19-local-20260915T035834Z-sf4x1k2y
```

## 下一阶段与尚未完成

下一阶段是 HAKUSAN 同环境的有界兼容性检查及独立部署控制入口审核。之后才是发布新包、实际审计冻结新清单、审阅 SHA 和新资源授权、单次提交。

当前 `candidate_input_freeze_sha256=null`、`submission_authorized=false`、`ready_for_gpu=false`。没有新 JobID。不能重跑旧 Job715276 提交脚本，也不能直接执行 v19 目录继承的全矩阵 sbatch。

最终科研角色仍是 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`；正式模型比较尚未验收。
