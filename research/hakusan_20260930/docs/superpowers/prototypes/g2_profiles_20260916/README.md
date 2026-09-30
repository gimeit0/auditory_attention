# G2 精度与编译设置：加载准备候选

2026-09-16。本目录服务 G2 的 R/C/D/E 数值对照，**不是生产运行包或提交入口**。
本地准备验证完成；真实 formal40/HAKUSAN Inductor/A100 和完整数值矩阵均未运行。

| 文件 | 用途 |
| --- | --- |
| profiles.py | 固定四组设置、32条真实试验 ID、16→1顺序和原1e-6标准 |
| adapter.py | strict-load 后、首次 forward/新证明签发前，核对状态并调整目标包装绑定 |
| build_candidate.py | 由固定 v19 源码派生新身份；7处可逆替换，其余275个顶层函数/类 AST 保持一致 |
| test_profiles.py | 22项本地 CPU 准备测试；D/E使用各自独立冷进程和原有保护逻辑 |
| validate_local.py | 单次有界本地测试、派生代码/日志/来源回执保存及离线复查 |

R/C 保留 `BinauralAttentionModule.model` 上的实际 `OptimizedModule`；
D/E 在原 strict-load 完成后，将同一底层 `model._orig_mod` 绑定到 `model`。
不复制权重、不重建模型、不全局替换 `torch.compile`，不改旧 checkpoint、配置或发布源码。
适配前后校验模块/参数/缓冲区对象身份、全部张量内容、RNG和运行设置。
适配记录加入新的 load report 后才签发原有 attestation，不能冒用旧证明。

## 本地执行

在 Mac 的项目目录运行；不需要 SSH，不上传、不冻结输入、不提交作业。

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_profiles_20260916/validate_local.py
```

测试总上限120秒；D/E子检查各60秒，单CPU线程，CUDA不可见。
每次保存新的 `g2-profiles-local-*` 证据目录，失败保留，不自动重试。
候选的继承命令行入口刻意拒绝运行；不要直接调用旧 `submit-once` 或候选 `freeze-inputs`。

已完成这次验证的只读复查：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_profiles_20260916/validate_local.py \
  verify \
  docs/superpowers/evidence/g2-profiles-local-20260915T153933Z-07dtorzu
```

## 验证边界与下一项

本地 Python3.11.15/torch2.12.1，不是 HAKUSAN 的3.11.5/2.1.1+cu118。
合成模型使用 `torch.compile(backend='eager')` 检查包装路径；不能据此声称 Inductor 已验证。
D/E各用32条**合成身份**运行16→1共34次，四项官方输出逐位一致，随后模型状态修改被原保护拒绝。
没有加载真实 checkpoint；`profiles.py` 中真实32条ID也不能替代生产完整身份/输入核验。

`_g2_backend_gate` 只是条件判断函数，返回值不是执行证明，也尚未接入生产验收。
旧 compiler lifecycle 的 `entered` 仅记录上下文进入，不能单独证明目标 Inductor 图实际执行。
下一项是与目标模型绑定的编译执行证据、同版本集成及受控 AMP-off 推理/采集端点验证，随后完成有界 worker/结果验收。
原 v4 `predict_batch` 在 CUDA 上会开启 AMP，不能未经适配直接拿它代表本矩阵 AMP-off。

只有上述工程验证完成、G2规格/资源/新freeze获审定后，才能准备一次真实 GPU 提交。
G2-M拟议1A100/8CPU/64GiB/3小时与后续G2-R1小时**均尚未批准**。
正式 checkpoint 比较仍在后续G4三模型smoke、G5全量、G6统计和G7报告。

详见[本次实现与证据](../../evidence/2026-09-16-g2-profile-preparation.md)及[G2规格](../../evidence/2026-09-15-g2-numeric-profile-spec.md)。
