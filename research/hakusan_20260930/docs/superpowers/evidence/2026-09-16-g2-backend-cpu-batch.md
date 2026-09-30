# G2 原生 Inductor 小型 CPU 单次批处理

2026-09-16。用户针对上一步明确提出的 1 CPU、6000 MiB、10 分钟、0 GPU、仅提交一次预算回复“好的”，本次据此执行。
此前 Job718727 的预算不复用；旧登录节点 50 秒检查不重跑，不改旧发布包、freeze、checkpoint 或失败证据。

新根目录：`/home/s2510040/audattn_external_eval_diag/g2_backend_cpu_2026-09-16_v1`。
候选目录：`docs/superpowers/prototypes/g2_backend_batch_20260916`。

## 范围和停止条件

- 同一小型 Linear/ReLU 合成 CPU 模型，固定 seed20260829；batch16、batch1 两次前向。
- 一个无追踪冷进程，再一个带 backend_evidence 取证的冷进程；独立编译缓存，前项失败则不启动后项。
- 每个子进程最多240秒、协调器540秒、Slurm600秒；每进程日志2MiB，进程组超时杀停。
- 默认原生 Inductor；AMP关闭、TF32关闭、highest，确定性设置固定；原有输出容差1e-6不放宽。
- 比较完整输入、权重、RNG、运行参数、eager端点、compiled端点；追踪侧必须具有目标编译器生成代码及实际执行证据。
- 先本地保护性测试，再只读预检、上传新包、scheduler test-only、持久化意图、单次 held 提交、精确资源校验、释放同一作业。
- 只复用现有 SSH master；不收集密码、不自动重连/重提，不附加 GPU 工作。

通过仅代表小型 CPU 合成模型的原生编译取证/端点干扰检查；不是生产模型、真实32条、GPU兼容性或checkpoint比较通过。
GPU G2-M3h / G2-R1h仍需另行授权。

## 执行记录

本地25项批处理/资源/提交/端点保护测试、原编译事件匹配器10项测试通过；7个新Python文件编译语法检查及sbatch shell语法检查通过。
这些是控制和验证逻辑测试，不是原生Inductor或计算节点测试通过。

- [本地测试与源码快照](g2-backend-batch-20260916/local-3hvzcg15/LOCAL_REVIEW.json)
  SHA `6186ae06e3eb15bde10014c0784c2a1dbc6c19368c90b924101c7a0f7a7572f0`。
- [10文件发布清单](g2-backend-batch-20260916/local-3hvzcg15/RELEASE.json)
  SHA `9c20cfa1fdc96744fda9fb30bc83f1fe3eb4c95edf95e0c418290c3f4bbe6f88`。
- 执行`driver.py preflight`时，本地认证检查发现
  `/Users/gigi/发表/超算/.hakusan-control/master.sock`不存在（FileNotFoundError）。
  失败发生在创建远端请求和本地提交意图之前：未查询实时分区/队列、未上传、未创建远端目录、未调用sbatch。
- 未重新认证、未自动重连，也没有消耗本次单次作业授权。

以上为认证缺失时的停点，下面记录本次恢复后的实际执行；旧失败记录保留。

只读预检恢复命令见[候选README](../prototypes/g2_backend_batch_20260916/README.md)。

## 认证恢复后：Job720730 已单次提交

用户回复“go on”后复用已有共享连接，未重新输入/收集密码、未自动重连。
源清单和本地测试回执再次复核通过，内容仍为上列固定SHA。

- [实时预检](g2-backend-batch-20260916/preflight-20260916T025347Z-lj8cuvj4/RECEIPT.json)：TINY UP、MaxMemPerCPU6000、账户队列为空、新根不存在。
- [新包上传](g2-backend-batch-20260916/deploy-20260916T025425Z-di0sojbb/RECEIPT.json)：10份文件和远端发布清单均核验通过，未触碰旧实验。
- [调度器试算](g2-backend-batch-20260916/test-only-20260916T025531Z-5xf2yzt9/RECEIPT.json)：test-only成功，无实际提交。试算信息中的720644不是本次运行作业号。
- [单次提交回执](g2-backend-batch-20260916/submit-20260916T032853Z-un005ydp/RECEIPT.json)：Job **720730**，持久化意图后调用sbatch一次，held资源/nonce/路径核验通过后释放。
  回执SHA `fdd9e6274bdbaf342cad3932d860a82c1551fa4785f18148ea8243a4c2dd79e2`；nonce `dfbbe425b5c04cfd905192d846cf76d7`。
- [首次状态](g2-backend-batch-20260916/status-20260916T032917Z-mzqoqptl/RECEIPT.json)：RUNNING，lcpcc-065；ReqTRES与AllocTRES均为1CPU/6000M/1node，无GPU。

本次单次作业授权已经使用，不能再运行submit。以上为运行中记录，最终结果如下。

## 最终结果：计算节点执行及独立验收通过

Job720730：**COMPLETED / 0:0**，Slurm耗时 **00:02:26**，节点lcpcc-065。
请求和实际分配均为cpu=1、mem=6000M、node=1、billing=1，无GPU。
两个冷子进程使用Python3.11.5、torch2.1.1+cu118，亲和性[220]，intra/inter-op线程均为1；独立编译缓存。

| 检查项 | reference | observed |
| --- | --- | --- |
| 子进程PID | 1229525 | 1229625 |
| 监督器记录耗时 | 72.957秒 | 34.000秒 |
| compiled与自身eager差，batch16/1 | 0 / 0 | 0 / 0 |
| 模型、输入、RNG、运行设置前后 | 相同 | 相同 |
| CUDA初始化 / 真实模型加载 | 否 / 否 | 否 / 否 |

reference与observed的完整输出字节相同，两个batch的最大绝对差均为0。
observed绑定的默认Inductor目标编译器调用/返回均为2；两份生成代码各记录1次实际调用和成功返回。
生成代码源及SHA保存于observed/result.json，未把`context entered`或`compiled=true`作为单独证明。
协调器107.155秒；完整源清单后检通过，临时目录清理完成，HOME不变。

### 日志里的Timeout不是本次作业超时

reference在60秒输出了一次`faulthandler`预定栈采样（`Timeout (0:01:00)!`）；这是诊断日志，未杀停进程。
当时栈位于Inductor编译工具链的CPU向量能力检测/编译子进程等待；首个forward在70.220秒返回，子进程最终0退出。
真实子进程限时仍为240秒，本次未触发。原登录节点50秒失败仍保留；不能仅凭新节点结果确定旧空日志失败的具体位置。
reference导入约34.58秒、observed导入约5.77秒：冷进程/独立编译缓存不等于系统文件缓存也清空，且仅一次顺序样本，不能称追踪提高了性能。

### 固定工件与可重复只读核验

- [收集回执](g2-backend-batch-20260916/collect-20260916T033234Z-ipdssq7n/RECEIPT.json)：
  SHA `750ec59843332a63f69927ac005575518c39a54e2e35d50fc9db360ce3792d2d`。
- [独立验收结果](g2-backend-batch-20260916/collect-20260916T033234Z-ipdssq7n/VERIFIED.json)：
  SHA `05b6776ebe551647acbad86cf9030ae0c5423a23e4e9caefb604f585a99edade`，`NATIVE_CPU_PAIR_VERIFIED`。
- [只读复查脚本](2026-09-16-g2-backend-cpu-review.py)：固定上述回执、源包、提交nonce、held/实际资源、Slurm终态、全部工件及完整数值结果。
  已以新进程运行，通过`FIXED_CPU_RESULT_RECHECK_PASS`；不联网、不改证据、不执行下载的生成代码、不提交。

### 结论与下一项

本次解决的是**原生2.1.1小型CPU模型上的编译执行取证与两次端点无差异检查**。
不是formal40或作者模型、不是A100、不是真实32条矩阵、不是正式总体比较；`ready_for_gpu=false`及`production_interference_validated=false`保持。
下一项在新G2生产worker中整合已验证的准备适配器和目标编译取证，验证真实strict-load来源、输入/采集端点及原保护链，准备完整生产包。
随后审定G2-M GPU矩阵预算，再执行真实32条R/C/D/E对照；不得把本次CPU单次额度延伸为GPU提交。
