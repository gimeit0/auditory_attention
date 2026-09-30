# E1 整包本地交付与后续操作

日期：2026-09-26。状态：**E1_LOCAL_RELEASE_CANDIDATE_PASS**。

本轮完整交付单元已完成：便携输入/执行合同、标准库bootstrap、A/B worker与独立验收、硬超时/失败归档、冻结包构建器、runner及单次held提交器，并完成本地回归和三进程合成演练。**不表示原生E1运行或科学实验完成。**

## 唯一应继续使用的候选

- 本地包：[package_ready](package_ready/)
- 计划远端位置：`/home/s2510040/audattn_e1/e1_20260926_v1/package`（本轮未创建/上传）
- Release SHA：`ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176`
- Entry SHA：`4bd2f1d8c34097fa42a4961bc38d931e4c272a0b39b4963104311b22618c8443`
- Runner SHA：`5fa0901bf329ec54ec5a3076ccfc995e2c54949f15ee2a16767eff728dd1b877`
- 输入合同 SHA：`f3fcacec3efb77962091ae58cbecde59de6b79ee503399c9ae8c0a120398b843`

`package`、`package_final` 是本轮本地中间候选，保留不覆盖，**不部署它们**。前者收尾时发现提交器缺少隔离启动支持；后者仍带未使用的旧合成归档工具。最终 `package_ready` 已修正并重新冻结/验收；所有候选均未上传或提交。

## 执行与权限合同

- 固定formal40，2000开发trial；A 34800、B 3600，共38400条条件预测、60个数组记录，不是38400条独立样本。
- α={0,.25,.5,.75,1}、原模型/旁路及三个既定负对照；新clean正确cue/零cue成对。完整列表在RELEASE.json的execution字段，输入布局在E1_CONTRACT.json。
- eager FP32，固定种子20260829，TF32关闭；原生Python3.11.5/PyTorch2.1.1+cu118/A100门禁不放宽。
- A/B/VERIFY三进程共享9900秒上限；worker另有9000秒合作式截止。进程超时终止进程组，首败停后续，归档但不重试。Slurm候选180分钟包含余量。
- 提交器只支持显式确认的单次held、3 GPU小时候选预算；state独占创建，意图/响应/receipt绑定，超时歧义也不得重提。无自动release、GRES修正或SSH重连。
- GPU预算与统计口径**仍待单独审定**。源码里的确认参数、manifest和本地PASS均不构成用户授权。

## 已实际完成的验收

### 全目录回归

```sh
/opt/anaconda3/envs/audattn/bin/python -B -m unittest discover -s alpha_mechanism_local_20260923 -p 'test_*.py' -q
```

最终205项通过，29.338秒。含E0既有回归、E1数据/输入/执行/归档、包篡改/额外文件/符号链接、receipt错配、假调度器test-only失败、歧义响应、重复提交拒绝、隔离提交器help、超时和完成记录负例。假调度器测试没有调用真实squeue/sbatch。

旧clean兼容测试仍有一次NumPy只读数组转tensor warning；历史函数未改，此warning未导致测试失败。它不替代原生完整包兼容性检查。

### 冻结包检查

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B alpha_mechanism_local_20260923/release_e1_20260926_v1/package_ready/e1_entry.py check ebe4dfb96974274be0433874c65be8b1614079efc73dd20aefa3427637ec6176
```

返回 `E1_PACKAGE_BYTES_AND_INPUTS_PASS`。隔离目录测试从 `/` 启动，无本地仓库回退；生产模块导入闭包通过。runner的 `bash -n` 通过。演练驱动、测试文件及旧合成归档工具不在最终包中。

### 冻结包三进程合成端到端

[SUMMARY.json](../e1-release-rehearsal-r4dfvj2a/SUMMARY.json)；[进程记录](../e1-release-rehearsal-r4dfvj2a/attempt/PROCESS_COMPLETE.json)。

- 状态 `E1_PACKAGED_SYNTHETIC_PIPELINE_PASS`，38400条，独立PID 37285/37289/37292。
- pipeline SHA：`b90b323b04459981c9f9230fe40d9b495bd2b9f4beae2dba6b6e0e061ce2e9db`。
- 调用最终包的worker调度、数组写盘与独立归档复算。严格加载、音频张量、模型预测、G5计算由明确标识的合成夹具替代；**不能据此声称真实模型或原生GPU通过**。
- 原生部署路径/receipt/完成报告绑定另用伪造测试元数据做正负例验证；不是原生调度实证。
- checkpoint_loaded=false，cuda_initialized=false，jobs_submitted=0。

## 下一整批（需新授权）

**远端发布与原生只读预检**作为一批执行：复用用户现有SSH连接、只读查队列/路径 → 独立目录暂存 → 外部核验entry和release SHA → 整包核验 → 发布 → 有界原生source-check → 保存回执。不自动重连，不提交GPU。若目录已存在或哈希不符，停止并保留证据。

通过后审定统计口径和1 A100/8 CPU/64 GiB/3小时预算，再执行单次held提交/资源审核。站点GRES异常修正和release仍遵循单独授权，不因本轮整批交付而合并越权。

GPU完成后的下一批是收集、`offline-check`、指标/CI复算与E1开发报告；不是再次拆成每个小模块询问。任何数值门槛失败停止科学解释，保留失败归档。
