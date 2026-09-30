# 精简 checkpoint 对比候选：eager FP32 小样本入口

日期：2026-09-17。新协议：`same_bank_eager_fp32_small_20260917_v1`。

这是落实[失败总审计与收敛方案](../2026-09-17_checkpoint对比_失败总审计与收敛方案.md)的 **S0 与 S1 本地实现**，不是新的诊断 v20，也不是已经通过科学验收的正式评估。

## 当前状态与权限边界

| 阶段 | 状态 |
| --- | --- |
| 新执行路径、严格加载接入、原生预处理、三模型/controls、保存与独立重算 | 已实现 |
| 本地真实 PyTorch 小模型 + 磁盘 checkpoint 全链路测试 | 已通过；合成模型/数据，不是正式 checkpoint |
| 原 v4 科学辅助代码回归 | 已通过；原文件不修改 |
| HAKUSAN 原生 2.1.1 / A100 / 真实三个 checkpoint 完整流程 | **未运行、未验证** |
| 冷启动重复、16/1 数值资格、覆盖确认集、同伴重排 | 尚未完成；不可声称数值问题解决 |
| 上传、GPU 提交、全量 10k 比较、最终统计报告 | **本轮均未执行** |

只提供小样本 `run-small` 和只读 `verify-small`。不包含 `sbatch`、SSH、自动重试、断点拼接或全量入口。下一步先审查该候选与单次计算节点预算，再安排真实小样本运行；不能复用以前诊断作业的额度默默再提交。

## 保留什么，改变什么

直接以固定 SHA 导入原 [v4 evaluator](../same_bank_eval_2026_08_29_v4/locked_same_bank_eval.py)，不拷贝修改其冻结版本、不改其全局变量。保留：

- 原 v4 输入 manifest、完成证据、checkpoint 与 frozen snapshot 验证；运行前后重查文件。
- 原严格加载：selftrain 精确键、作者仅既定 compile-wrapper 键映射，100% 参数覆盖，selftrain checkpoint 恢复回调。
- 同一冻结音频场景同时供三个模型使用；scene SHA 必须等于历史 Job584990。
- 每个模型自己的单样本原生预处理；正确 cue 与 shuffled/silent/distractor 控制。
- 原逐 trial 身份与指标完整性校验。统计代码仍留在原 v4，尚不对 32 条工程样本做总体推断。

新的执行设置：

| 项目 | 固定设置 |
| --- | --- |
| 数值模式 | FP32；autocast 关闭；matmul 与 cuDNN TF32 关闭 |
| cuDNN | deterministic=true；benchmark=false |
| matmul precision | `highest`，设置后读回 |
| 编译 | 严格加载之后，仅移除已知 `model.model` 的 `OptimizedModule` 包装，保留同一 `_orig_mod` 对象；核对全部参数/buffer 对象绑定；实际 forward 不编译 |
| 模型状态 | eval、无梯度、有限状态；pass 前后比对参数/buffer 内容、对象与版本 |
| 随机性 | 显式设置 Python/NumPy/Torch seed=20260829；模型构造后重置；推理前后检查 RNG 不变 |
| batch | 每次明确选择 16 或 1；control 子集与尾批使用实际长度，不补样本、不凑满 batch |
| 类别判定 | 沿用原 FP32 概率 argmax，并要求与 logits argmax 一致；若浮点舍入造成二者不一致则停止；保存 logits 并从文件独立重算 NLL/概率/类别 |
| 追踪 | 不挂逐层 hook；不扫描任意 Python 对象图、每算子 sys.modules 或编译器内部状态 |

`python -I` 忽略 `PYTHONHASHSEED` 等 Python 环境设置，本候选不把“环境里写了 seed”当作生效证明；科学执行顺序使用固定列表，数值 RNG 显式设置与检查。`CUBLAS_WORKSPACE_CONFIG=:4096:8` 必须在 Python 启动前设置，只在最初配置入口检查 CUDA 尚未初始化，不再在 forward 前重复要求“CUDA 从未初始化”。缓存置于唯一 scratch 下，**不修改 HOME**。

作者 checkpoint 使用作者原生预处理，是系统级外部参考，不是仅换权重的严格对照。所有结果保留 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`：复用验证/pilot bank，不能写成独立测试结果。

## 小样本范围与产物

固定原诊断 32 个 trial，顺序见 `eager_compare.TRIAL_IDS`；不根据新结果挑样本。执行顺序 formal40 → author_external → valbest33，三者都必须完整。最终科学角色仍为 formal40 主比较、valbest33 次要比较，不重新选模型。

每次独立、全新输出目录中保存：

- `RUN.json`：新协议、旧 manifest SHA、三模型记录、trial 顺序、历史 scene SHA、运行设置和环境。
- `LOAD_REPORTS.json`：原严格加载报告及显式 eager 解包报告。
- `bank.csv`、`results.csv`：选择的原始行与逐 trial 结果，controls 外不填控制预测。
- `logits.npz`：三个模型四种条件的 FP32 logits；禁止 pickle。
- `pass.json`：全部 cue 哈希、SNR 重建误差、运行设置和状态不变检查。
- `RECEIPT.json`：前述文件哈希清单；只有保存后独立重读/重算与输入 postcheck 完成才写入。
- 失败时 `FAILED.json` 和未截断的 `FAILURE.txt`。进程被强杀时可能没有失败标记，但没有完整 receipt 绝不算成功。

成功终态故意命名为 **`SMALL_RUN_COMPLETE_NOT_QUALIFIED`**，不写旧 `SMOKE_PASS`。它仅表示小样本执行与产物重算完成，不能解锁全量比较。

文件重算用 NumPy FP64 logsumexp 对照保存时的 FP32 指标，`rtol=1e-6, atol=2e-6` 仅用于这两种算术实现之间的序列化/指标语义核对，**不是放宽原 batch-size canary 的 1e-6 判据**。16/1 是否达标要另外做资格比较、报告差值与预测翻转；本候选不自动给该项 PASS。

## 本地复核命令

在 Mac 项目根目录执行；只运行合成 CPU 测试，不连接超算：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover \
  -s same_bank_compare_2026_09_17_eager_v1/tests -v
```

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover \
  -s same_bank_eval_2026_08_29_v4 \
  -p test_locked_same_bank_eval.py -q
```

本地环境与测试范围见 [LOCAL_VALIDATION.json](LOCAL_VALIDATION.json)。测试走磁盘 YAML/checkpoint → **原 strict_load_model** → 精确 eager 解包 → 新共享场景/三模型/全部控制 → 保存 → 独立重读，并覆盖缺权重、NaN、输入修改、训练态、BatchNorm、模型 buffer 修改、RNG/运行设置变化、损坏指标、非整数类别、错误 trial 和失败标记等反例。

但真实音频、真实 cochleagram/模型、HAKUSAN 动态导入、GPU 显存、NFS、原生 Torch 2.1.1 等仍须在计算节点验证，不能用本地小模型替代。当前没有“科研提交就绪”声明。

## 后续计算节点入口（说明，不是现在的提交命令）

入口接受以下参数；只有获批的 Slurm 计算节点才可运行：

```text
python -I -B eager_compare.py run-small
  --output <全新的、冻结输入根之外的目录>
  --scratch-parent <计算节点已分配的/tmp父目录>
  --expected-candidate-sha256 <审定的候选脚本SHA>
  --confirm same_bank_eager_fp32_small_20260917_v1
  --batch-size 16
```

核验已下载的结果时，在本地使用相同候选脚本、固定原 v4 源码和从运行日志独立保留的 receipt SHA：

```text
python -I -B eager_compare.py --v4-core <本地原v4/locked_same_bank_eval.py>
  verify-small --output <已收集的单次结果目录>
  --receipt-sha256 <运行日志中的receipt SHA>
```

当前尚缺计算节点投递/收集包装、独立冷重复与敏感性比较报告入口、额外覆盖确认集、实测预算、全量入口和统计交付整合。它们属于后续阶段，不通过改一个状态字段或重新跑旧提交脚本来省略。
