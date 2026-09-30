# 独立 GPU 运行包 v3：单节点 typed A100 请求候选

2026-09-14。与 v1/v2 并存，目标为
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v3`。
不能复用 Job705468 的一次性授权、目录或提交意图。

## 相对 v2 的范围

runner 只声明 `--gres=gpu:nvidia_a100:1`，固定1节点、8CPU、64GiB、2小时。
HAKUSAN 的三个最小 test-only 对照中，这种形式通过，含 `--gpus`
的两种形式被拒绝。完整本包仍须独立 test-only，实际资源暂扣回读核验
及新的明确授权；局部对照不是正式提交或 GPU 验收。

gpu_child、启动适配器、数值/归档验收逻辑保持 v2 相同字节；迁移 coordinator、
contract、runner 的包/root路径及相应测试。B2 formal40 双冷进程、32试验、
16→1 batch、168采集、模型/数据/阈值保持。

v2启动实现已通过 HAKUSAN Python3.11.5 / torch2.1.1+cu118 的原生 CPU
scratch-before-import 检查。旧入口在该原生 CPU 对照中没有复现历史 GPU
目录冲突；不能把这一结果写成 GPU 根因已完全验证。本 v3 仍是待 GPU
验证的工程候选，不是 formal40 与作者 checkpoint 的最终比较结果。

## 本地验证

从工作区运行本目录 `validate_local.py`，使用本地 audattn Python，
`-I -B` 模式。预计45项运行包测试＋38项原归档回归；无 SSH、生产模型、
GPU、真实提交或 Linux挂载验收。所有当前事实及收据集中记录在
[运行记录](../../evidence/2026-09-14-native-startup-and-gres-correction.md)。
