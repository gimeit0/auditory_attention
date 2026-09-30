# E0 v1候选发布包（2026-09-24）

本目录package由build_e0_package.py生成，生成后不再原地编辑；修改源码须新版本重建。RELEASE.json的SHA需从本地生成回执独立带到远端，不能在远端重新计算后当作期望值。

固定远端部署路径：`/home/s2510040/audattn_e0/e0_20260924_v1/package`。
状态目录：同级`state`，由单次提交器独占创建。已有state即停止，不删除、不覆盖、不自动重试。

资源：GPU-1A/student，1张nvidia_a100、8CPU、64GiB、30分钟、no-requeue。提交器先检查相关队列，再做sbatch test-only，最后一次held提交；它**没有release功能**。站点改写typed GRES时不自动修正，需单独审查授权。

生产入口先核对release全部文件与资源合同；子进程分别strict-load formal40，运行96固定样本/6048条预测及G5/历史桥接；1500秒子进程总截止，Slurm1800秒最终限制。父进程离线验收是协作式时限，不能声称其自身具备独立硬中断。

本地已完成合成测试、参考包复核；**未在真实checkpoint/A100上运行，未上传、未提交**。候选实现完成不等于E0通过。

## 上传后在HAKUSAN执行（本轮未执行）

先核对连接、账号、远端目录非链接、目录未占用、无相关作业，上传到上述独立路径。随后使用本地BUILD_RECEIPT.json中的release_sha256作独立期望值。

```bash
P=/home/s2510040/miniconda3/envs/attn/bin/python
PKG=/home/s2510040/audattn_e0/e0_20260924_v1/package
# SHA必须填本地BUILD_RECEIPT.json中的release_sha256，不是任意现场哈希。
SHA=请填本地已审核的64位release_sha256
"$P" -I -B "$PKG/e0_entry.py" check "$SHA"
```

只有PACKAGE_BYTES_PASS且发布/预算复核无误后，单独执行一次：

```bash
"$P" -I -B "$PKG/submit_e0_once.py" --release-sha256 "$SHA" --confirm-action SUBMIT_E0_HELD_ONCE
```

返回`SUBMITTED_HELD_NOT_RELEASED`不代表GPU已开始。保存receipt和job_id，检查scontrol中的JobState、Reason、UserId、Partition、Account、TimeLimit、CPU/内存/GRES、Command和WorkDir，以及Slurm实际保存的runner字节。字段不符停在held；本说明不提供自动release/自动GRES修正。

若SSH或sbatch响应不明，先检查state/INTENT、SUBMISSION_RESPONSE、SUBMISSION_UNKNOWN和队列，不得重新提交。运行失败保留state/attempt各worker日志、局部npz及失败记录。

完工要看独立验收后的E0_COMPLETE.json及其release/job绑定，不能只看Slurm COMPLETED。结果仍属复用验证集工程验收，不是独立测试或α科学结论。
