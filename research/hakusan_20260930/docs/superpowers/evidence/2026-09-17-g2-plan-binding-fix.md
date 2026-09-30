# G2提交前计划绑定与A100资源检查修正

2026-09-17；上一轮确有进展，但31文件入口候选仍有提交时序缺口。本轮修正开发候选，保留旧候选目录和证据，不改写旧部署或真实作业结果。

## 发现和修正

原入口将包含job_id的请求SHA作为sbatch参数。job_id只有sbatch返回后才知道，因此无法按既定held工作流提前生成该参数。
新方式为：

1. 提交前固定不含job_id的 `EXECUTION_PLAN.json`：release、四freeze、nonce、资源、partition。
2. sbatch接收已固定的release SHA、plan SHA和nonce；作业保持held，不先执行。
3. 提交器取得job_id后生成 `RUN_REQUEST.json = plan + job_id`，核对实际held请求，之后才允许释放。
4. 启动器从固定plan和实际SLURM_JOB_ID重新推导请求，逐字节核对；验证实际spool脚本与发布runner SHA，再启动原matrix入口。

本轮仅实现并测试启动器和计划推导；并未实际调用sbatch，也尚未完成新单次提交控制器。

同时修正资源验证：必须有 `gres/gpu:nvidia_a100=1` 及 `TresPerNode=gres/gpu:nvidia_a100:1`。
仅 `gres/gpu=1` 不能证明A100；H100或其他typed资源被拒绝。兼容旧集群输出中省略aggregate gres/gpu的情况，但不能省略typed A100。
held检查要求PENDING/JobHeldUser/Priority0、空NodeList、AllocTRES=(null)、RunTime0。
此检查依据项目已保存的Slurm资源字段；最新实际分区可用性仍未查询到。

## 本地证据与范围

最终目录：`g2-entry-local-20260917T063951Z-zcygp8in`。

- 27项入口/计划/资源/打包/小进程检查通过，0.456秒。
- 30项原运行控制回归通过，1.660秒。
- 新32文件实际包四profile冷导入通过，0.268秒；未导入torch/numpy或权重。
- 新runner bash语法检查通过，0.003秒。
- 40份来源与快照固定，运行前后相同；独立只读复查通过。
- `VALIDATION.json` SHA：`c5f73f892c1ed60301f85241fe365a340571754eba71ca7c1f8ec1dbc6d05b2e`。
- 最新候选release SHA：`6becba7b27f8ba37657e66f0173bf991aec0136e8285afbd211eeeb65318d300`。

中间32文件计划绑定检查目录 `g2-entry-local-20260917T063626Z-59ttxy7t` 也保留，后由严格typed A100修正的最终候选替代。
此前31文件包 `g2-entry-local-20260917T063102Z-rvjjh422/candidate` 保留为历史，**不部署或提交**。
旧检查当时通过不表示覆盖了后来发现的时序缺口；开发源码已前进，旧候选不再与当前源码相同。

最终候选只读复查：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_runtime_20260917/validate_entry.py verify \
  docs/superpowers/evidence/g2-entry-local-20260917T063951Z-zcygp8in
```

未执行真实生产入口、GPU推理、新freeze或调度提交。没有新checkpoint比较数值。

## 当前外部边界

本轮有界只读SSH再次返回255：`Permission denied (publickey,password,hostbased)`。
未取得当前queue/partition/root信息。单次G2-M的1 A100/8CPU/64GiB/3小时预算请求尚无确认，不能把自动持续目标当作该具体额度的批准。
需要用户本人恢复共享认证并确认额度后，才进入现场预检、部署/真实freeze及单次提交准备。
没有重复提交或清理旧作业、旧结果、旧socket。当前目标仍未完成。
