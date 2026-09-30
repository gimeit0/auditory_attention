# GPU v4启动环境修正与Job715276单次提交

2026-09-14。用户要求“下一步 直到完成作业提交”。本阶段已完成实施、验证、
独立发布、单次真实提交、同一作业的GPU型号修正和放行。
最后只读查询（22:44 JST）为 **715276 / PENDING / Resources**，无分配节点、运行0秒。
这是等待资源，不是计算失败。计算和数值验收尚未完成。

## 作业范围

- 名称：`audattn_b2_coldpair`；范围：`B2_formal40_cold_reference_observed_pair`。
- 单作业、GPU-1A分区、1张NVIDIA A100、8 CPU、64 GiB、运行时限2小时。
  reference/observed各3000秒上限，pair监督上限6600秒；排队时间不算运行时限。
- formal40在两个独立冷启动进程中分别做参考/观测，保留32条冻结样本、batch16→1、
  权重、数值六标志、父结果约束及原比较阈值；不预热、不换eager、不扩大时限。
- 用来检查追踪加入后的端点一致性并定位批大小差异；**不是formal40与作者checkpoint
  的全量比较作业，也不是论文结果已完成**。
- 科学角色仍为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。

## 本次修正

依据[Job713897的时间线和环境构造证据](2026-09-14-job713897-timing-localization-plan.md)，
独立v4恢复原v18固定的`OMP_NUM_THREADS=8`、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、
`TOKENIZERS_PARALLELISM=false`。启动器和子进程环境工厂均显式固定；导入数值库前检查，
导入后读回实际torch线程数、interop和CPU affinity。环境缺失、冲突或太晚设置均拒绝。
该缺陷已经复现和修正，**但尚未证明它就是旧作业50分钟超时的根因**。

增加外围阶段起止/进程CPU时间日志及一次40分钟Python栈转储。没有新增模型hook、
张量改写、CUDA同步、随机种子重置或精度调整。计时插入剥离后要求AST恢复原调用；
原v18对象身份和数值/状态检查保持不变。计时不是CUDA kernel性能测量，也不声称零扰动。

旧v3、Job713897失败证据和原始冻结输入保留。新远端根：
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v4`。

## 已完成的验证与发布

- 新运行包61项、归档回归38项、控制器47项：共146项本地测试通过。
  包含真实新CPU进程8线程读回和带外围计时的合成CPU/mmap参考循环。
- [HAKUSAN原生CPU复验](gpu-control-20260914-v4/runtime-cpu-20260914T133134Z-1a2kihp6/receipt.json)：
  两角色均为Python3.11.5 / torch2.1.1+cu118，三项环境值正确、torch线程8、interop4，
  CPU affinity为0—7；CUDA未初始化，未加载生产模型，临时目录已清理。
- 52文件运行包、58文件控制发布独立上传并核验；调度器test-only通过。
  test-only打印的715275只是估计编号，真实提交编号是715276。
- [提交前独立复核](2026-09-14-gpu-v4-pre-submit-review.json)记录源文件SHA、
  本地测试及远端部署/CPU/test-only回执。该历史记录中的jobs=0是提交前的事实。
- 同一作业恢复脚本另有[15项本地反例及日志测试](2026-09-14-job715276-recovery-local-tests.json)，
  使用本次真实暂扣记录重放。恢复脚本位于58文件发布清单之外，未修改已发布包。

包SHA：`91b263ac3a22171e97314e6574a4422515b80a2b74f8e1e96e87b0fa6debb7e8`。

控制发布SHA：`abc075315541791c201ea637825a5f653253d4a0325126a63c73e560a64c6864`。

## 单次提交及同作业恢复

22:33:39 JST，唯一一次真实sbatch创建715276。初次控制命令退出2，因为暂扣记录仍显示
`ReqTRES=...gres/gpu:h100-20c=1`、`TresPerNode=gres/gpu:1`，不符合获准的A100。
原始SUBMIT_ERROR及SUBMITTED_HELD回执保留；这不是计算过程失败，也没有再执行submit。

核对原授权、nonce、包SHA、提交凭据、Slurm版本、GPU-1A十节点型号、相关队列及
原资源限制后，仅更新同一715276的两个GPU请求字段：

```text
TresPerJob=gres/gpu:nvidia_a100:1
TresPerNode=gres/gpu:nvidia_a100:1
```

更新后scontrol与sacct均为`gres/gpu:nvidia_a100=1`。CPU8、64GiB、单节点、2小时、
作业路径和nonce保持不变。随后仅放行该JobID一次，优先级从0升至16437，暂扣解除。
22:44只读复查为`PENDING / Resources`，无节点、运行0秒。

- [真实提交回执（暂扣核对退出2）](gpu-control-20260914-v4/submit-20260914T133330Z-gzq2zpl_/receipt.json)
- [同一作业A100修正回执](gpu-control-20260914-v4/update-20260914T134221Z-8ret1mo2/receipt.json)
- [同一作业放行回执](gpu-control-20260914-v4/release-20260914T134409Z-au_dt6fl/receipt.json)
- [放行后状态回执](gpu-control-20260914-v4/status-20260914T134438Z-4bwjiqmr/receipt.json)
- [最终本地独立复核](2026-09-14-job715276-submission-review.json)：10组请求/输出/回执的
  SHA与响应绑定通过，新58份及旧55份文件SHA保持一致。

计数：本发布真实提交1次，同一作业GPU更新1次，放行1次；不自动重试、取消或重提。
恢复阶段回执的`jobs_submitted=0`表示这些操作没有新增作业，不表示原作业不存在。

## 下一项：只查询和验收

Mac工作区中可执行以下只读命令；不要再次执行submit、update、release、deploy或freeze：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_control_20260914_v4/control.py status
```

作业已交给Slurm，关闭本地终端不等于取消作业。再次查询需有效SSH认证。
结束后先核验进程/阶段日志、终态和完整归档，再运行数值/父结果/观测端点验收；
不能仅凭Slurm COMPLETED就写“比较通过”。失败保留原目录，不能自动新增作业。
