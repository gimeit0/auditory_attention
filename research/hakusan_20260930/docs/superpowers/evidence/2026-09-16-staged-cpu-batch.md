# 独立CPU批处理验证：授权、范围与执行记录

2026-09-16 JST。用户已同意将原合成分阶段检查移至独立计算节点CPU作业。
批准上限：1 CPU、8 GiB、10分钟、0 GPU；不是新的GPU矩阵/总体模型比较授权。

只读TINY分区检查返回State=UP、AllowAccounts=ALL、MaxMemPerCPU=6000。
因此实际申请降低为 **1 CPU、6000 MiB、10分钟、0 GPU**，account=student。
在同一作业先held提交，只有调度器的CPU/内存/时间/GPU/nonce/脚本/输出路径完全匹配才release。
若调度器改配2 CPU等资源，保持held并停止；不自动改配、取消重提或扩大额度。

## 同一被测逻辑

保留旧162源manifest及两个原始分阶段helper的SHA；171文件包=162源+原manifest+2 helper+6新封装。
A2、B2各32条，batch16→1，同一cell内模型生命周期、所有原断言不变；mmap消费两者完整结果的SHA。
三阶段各冷进程≤180秒，总coordinator≤570秒，Slurm≤600秒；CPU affinity必须只有1。
私有缓存/临时目录与HOME保持分离，禁止CUDA初始化，不加载真实checkpoint、不写生产freeze。
允许的成功标签仅是新的合成CPU批处理验收，**不是旧50秒门槛通过，也不是G2/G5通过**。

## 本地验证与冻结身份

新封装18项保护测试通过：来源/路径/预算、scheduler身份、held资源、单次intent、模糊响应、拒绝重提等。
最终同包本地三冷阶段A2/B2/mmap通过；mmap原2项完整断言通过。
完整合并contract SHA仍是`cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000`，与旧未拆分本地oracle一致。
本地Python3.11.15/torch2.12.1，不冒充HAKUSAN3.11.5/2.1.1。

- [固定本地结果](staged-cpu-batch-20260915/local-dx511ko2/LOCAL_REVIEW.json)
  SHA `5cb8b36be32926f9a943cfe5cb9b86ae441eb738ed5ca851187ac7ff9666ae1a`。
- [171文件清单](staged-cpu-batch-20260915/local-dx511ko2/RELEASE.json)
  SHA `9fedb04058706453561c874eb9fba90ac37283c46e81e65f54a8148ff35b78db`。
- [CPU短入口](2026-09-16-staged-cpu-batch.sh)：校验6新源、清单、本地回执，再执行明确的单个action。
- [被测封装](../prototypes/staged_scratch_batch_20260915/runtime.py)、[单次CPU调度器](../prototypes/staged_scratch_batch_20260915/remote.py)。

尚未提交时的边界：先preflight→deploy→test-only→审阅→一次held submit/资源核对/release；
随后status→collect→独立验收。所有远端动作仅复用现有SSH master；连接失效则停止，不收密码、不自动重连。
真正运行结果追加于下方；不能凭本地PASS宣称原生通过。

## 当前执行结果

**Job718727已完成并独立验收：SYNTHETIC_CPU_BATCH_VERIFIED。**

| 项目 | 已核验证据 |
| --- | --- |
| Slurm | COMPLETED，0:0，00:01:36，lcpcc-054 |
| 请求及实际分配 | cpu=1、mem=6000M、node=1、billing=1；没有GPU TRES |
| 暂停保护 | held资源/身份核对通过后单次release；只有一次sbatch调用 |
| 原生环境 | Python3.11.5、torch2.1.1+cu118；三进程CPU affinity都只有[96] |
| A2 | PASS，47.822秒，pid2587456 |
| B2 | PASS，20.565秒，pid2587521 |
| mmap | 原2项测试PASS，20.499秒，pid2587592 |
| 完整性 | 171源前后校验、阶段请求/父结果/输出SHA、相同原生环境与原断言恢复均通过 |
| 清理/范围 | 私有临时目录清理，HOME未变；CUDA未初始化，生产模型未加载 |

本地同包最终三段为7.443、6.826、7.658秒；与原生执行环境不同，不据此宣称性能改善比例。
原生合并contract SHA：`11c18e4f7ca758a72680836314d56d97289f03bcc195b172b0aaa8530bef47a5`。
它由本次同环境A2/B2生成并被mmap精确消费；**不要求、也未声称与Mac跨版本结果逐字节一致**。
本次A2小于50秒不使旧登录节点失败失效，更不能把旧单进程80项检查改称全通过。

### 固定验收工件

- [实际提交回执](staged-cpu-batch-20260915/submit-20260915T151259Z-43ajqkl6/RECEIPT.json)：
  SHA `3daefc9425410dd72be23808583e0dd5c1277c288b8f5f3328ea4b8a6a622eee`。
- [完整下载回执](staged-cpu-batch-20260915/collect-20260915T151610Z-8o907xvv/RECEIPT.json)：
  SHA `caa58df840637d092de626243d7c55f2ac51ffbc1cea781a0bfae97d25db27a6`。
- [独立验收结果](staged-cpu-batch-20260915/collect-20260915T151610Z-8o907xvv/VERIFIED.json)：
  SHA `847bfdf736156f9d529ef987379a07bdd3adecb11e52316c30c0d420bd2ab0c6`。
- [原生终态](staged-cpu-batch-20260915/collect-20260915T151610Z-8o907xvv/recovered/attempts/slurm-718727/TERMINAL.json)：
  SHA `f71d2aa4b2a573178691ac0b38ce91c4b0365b6159718c4a7148165d431d1427`。
- [固定只读复查器](2026-09-16-staged-cpu-batch-review.py)：再次验收通过；另有10项内存中篡改拒绝检查通过，
  覆盖假成功、错误Job、超时、未后检、未清理、HOME改变、越权GPU/生产声明等；不改原工件，无网络。

远端新发布包与全部运行记录保留在
`/home/s2510040/audattn_external_eval_diag/staged_cpu_2026-09-15_v1`。
旧失败、旧freeze、旧模型/音频/源码未覆盖或删除。SUBMISSION_RECEIPT中的SUBMITTED_HELD是历史提交时状态，
当前状态必须看Slurm完成记录及TERMINAL，而非误判“仍在held”。

## 下一项与边界

G1所缺的这一组三阶段合成生命周期验证已有同环境有效证据，**可以转向G2生产适配器的准备**。
G2新compile/TF32配置的实际加载、端点/状态检查、freeze和GPU额度仍须实现、回归和审定。
当前CPU通过不直接证明真实A100路径可用，不自动提交G2-M，更不跳到完整10k。
G2-M草案上限单A100/8CPU/64GiB/3小时；G2-R是结果审阅后另外批准的单A100/1小时。
本次未申请这些GPU额度，完整checkpoint比较仍未完成。

重复只读复查（在Mac终端；不会再次提交）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-16-staged-cpu-batch-review.py
```

不要重跑submit；如需实时状态，只调用短入口的`status`动作。
