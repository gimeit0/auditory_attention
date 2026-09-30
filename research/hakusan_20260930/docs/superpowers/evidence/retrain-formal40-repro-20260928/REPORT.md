# formal40 同配方同种子重训：执行台账

开始：2026-09-28。依据：[AUTHORIZATION.json](AUTHORIZATION.json)（用户批准同种子 20260721、总额 320 A100 小时、每段单独放行、不自动重提）。RUN_ID `formal40_repro_seed20260721_20260928`；参照 run `fullpilot4_accum9_20260815_181000`（formal40，不加载、不续训）。研究身份：同种子流程复现，不是独立种子重复。

## 代码与门控

- 远端 live 树与旧 run 冻结快照 46/46 个语义文件一致；新 run 快照语义摘要 `496cf41c8abedb4673a83a4ec148bc74ea92e6c059ea4bc998610a0db1ab9038`，与 formal40 相同。本地 `patch_stage_next` 的 submit_training.sh、run_training.sbatch、full.yaml、spatialtrain.py 与远端逐字节相同。
- 数值预检 PASS：`selftrain/numerics_preflight_runs/566556/PASS.json`，SHA `640fd59a…`，与旧 run 快照副本相同。
- cue-control 放行：`selftrain/experiments/cue_controls/job551219/jobs/565217`，提交时重算通过（RELEASED_FOR_FULL_DISTRIBUTION_PILOT）。
- 未修改任何项目文件。held 通过项目树外的包装脚本实现：`~/audattn_retrain_ops/formal40_repro_20260928/bin/sbatch`（SHA `8625a60c…`，内容为 `exec /usr/bin/sbatch --hold "$@"` 并记录调用）。

## 执行记录

| 时间（JST） | 动作 | 结果 |
| --- | --- | --- |
| 2026-09-28 12:4x | 第 1 次运行提交脚本 | 在首个本地自检停止：登录环境 `.bashrc` 把 `~/conda/bin`（Python 3.13）放在 PATH 最前，激活 `attn` 后 python 仍指向它，缺 numpy。sbatch 未被调用，未建 run 目录，未排队 |
| 2026-09-28 12:54 | 第 2 次：以干净环境（`env -i`，PATH 仅含包装脚本与系统目录）运行原提交脚本 | 本地自检与门控全部通过；`--test-only` 预估 spcc-a100g09；提交 **Job 753918**，MODE=new、RUN_PHASE=pilot4、时限 1-12:00:00 |
| 2026-09-28 | held 回读 | PENDING / JobHeldUser / Priority 0；ReqTRES `gres/gpu:h100-20c=1`（与原训练 4 个作业相同的站点改写；原作业均在 spcc-a100 节点运行）；spool 脚本 SHA 与 runner 相同 `feabe927…`；见 [held_readback_753918.log](held_readback_753918.log) |

| 2026-09-28 12:55 | 用户授权后执行一次 `scontrol release 753918` | 12:55:50 于 spcc-a100g09 开始运行；AllocTRES `gres/gpu:nvidia_a100=1`；见 [release_753918.log](release_753918.log) |
| 2026-09-28 12:57 | 启动检查 | 完整性、A100 环境指纹、PASS 绑定通过；stage-0 已保存；验证集健全性检查完成；见 [startup_753918.log](startup_753918.log) |
| 2026-09-28 | 初始权重对照 | 新旧 stage-0 的 61 个张量、63,271,260 个参数逐个完全相等（文件 SHA 不同，差在元数据）；同种子初始化复现成立；见 [stage0_compare.log](stage0_compare.log) |

| 2026-09-28 13:43 | 用户决定换种子重复优先，取消本 run 以腾出 GPU 名额；执行一次 `scancel 753918` | CANCELLED by 27831，Elapsed 00:47:48，第 0 轮 1680/15624 批；run 目录与 stage-0 保留；已批准的 320 小时额度不再使用；见 [cancel_753918.log](cancel_753918.log) |

**状态：同种子复现已取消。** 已得到的证据只有初始权重与 formal40 完全相同这一项。

## 已知事项

- 作业继承干净的提交环境，runner 自行激活 `attn`（Python 3.11.5、torch 2.1.1+cu118）；分配后 `validate-pass --check-environment` 校验 A100 与软件指纹，不符即失败退出。
- 第 40 轮结束时 finalizer 可能再次误报（PL epoch_progress.total.completed 计数），届时以本 run 专用恢复处理，不改训练代码。
- 后续：pilot 完成 → 10k pilot 评估（≤12 小时）与人工审查 → PILOT4_GO → 续训各段 4 天，每段 held 提交、单独放行。
