# GPU冷对照验证包：归档与比对组件候选

2026-09-13：本地38项检查通过，0 skips；没有远端执行或GPU提交。
**这里只完成运行包的归档/比对接入部分，不是可提交的Slurm发布包。**
旧v18、CUDA准备候选、输入freeze和成功/失败作业证据均不改写。

## 本轮完成

- `pass_archive.py`：新私有目录、单次写入；两轮各16个边界、4项正式输出，
  每个进程40份原生数组。按C序分块，不转dtype、不重算、不放宽容差。
  单数组上限128MiB、数组总量2GiB、JSON上限8MiB、传输块1MiB。
  路径逐级不跟随软链接；检查权限、归属、硬链接、文件身份、完整SHA和精确目录清单。
  部分写入失败保留文件，并禁止写完成manifest。
- 两个独立进程的数组文件重新完整读取，核对外部提供的进程/配对/源码/输入绑定、
  对应pass内容及父合同中每条样本的字节摘要。不能只检查两份自报PASS。
- `verify_pinned_parent_pair`固定Job685198的已审核父合同SHA，不能选择新oracle。
  `verify_content_pair`是可合成测试的底层内容核验器，不是生产授权接口。
- `archive_adapter.py`：原参考和CUDA候选循环分别只增加3条归档调用及一个关键字参数；
  删除新增部分后AST精确还原。原run_trace_pass、父结果gate、34批16→1顺序不变。
  观测路径归档前调用原scratch.spill；参考路径沿用已有spill，不重复调用。
  保存原encode_pass_evidence，归档前后要求完全一致；不替换旧函数或重签结果。

## 实际测试边界

[完整本地记录](../../evidence/2026-09-13-gpu-pair-archive-local.md)和
[回执](../../evidence/gpu-pair-archive-local-20260913T061730Z-r_rdxexp/receipt.json)。
38 tests，Python3.11.15/torch2.12.1，17.817秒。
30份固定源/输入前后SHA一致；源码清单SHA：
`b0225a084b3c1e074d4650546cfb04a34cd5f84f9c05cdb62a11e6dea78b6634`。

合成数组的两个新进程完成80文件重读比较；没有加载真实checkpoint。
另一个测试通过原v18合成CPU夹具执行完整34批，核验原严格加载一次、
两份原pass文档仍可由原decoder解码，40份数组与其合成父结果完全一致。
该测试的scratch是明确的测试替身，不是实际mmap、生产CUDA或Inductor测试。
CUDA观测分支目前只有AST/插入约束检查，**没有成功执行的GPU证据**。

本地复测入口（不要把它当成超算提交命令；本轮已运行，无需重复）：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_pair_20260913/validate_local.py
```

## 仍需补齐的计算节点执行包

1. 独立新参考进程和新观测进程的受控入口：原生产加载/scene scope/只读锁，
   新的私有node-local缓存与scratch，同一个实际A100/torch2.1.1/Inductor环境。
   当前`run_archived`只是进程内候选；调用者必须在所有准备/准入失败路径关闭
   自己的request、lease、writer、scratch并保存失败证据。
2. 保存并验证原完整worker来源、输入前后校验、状态/RNG、两份原pass文档、
   观测账本与168份中间采集；本组件只核验端点数组，不核验这些执行来源或中间值。
   因此内容PASS仍返回`execution_authority_verified=false`、
   `original_pass_commitments_verified=false`、`intermediate_captures_verified=false`。
3. 进程超时、资源限制、Slurm单次提交/回执绑定、失败不重试、完整下载清单与本地重验。
   新GPU算力和时限需单独审核，旧Job685198许可不能自动复用；没有新sbatch脚本。
4. 全部通过后才能解释42位置差异。端点一致也不证明未插桩编译的中间运算一致，
   因为hook可能引起图分割和内核选择变化。

目前`production_preparation_validated=false`、`ready_for_gpu=false`。
三模型smoke、10k对比和科研提交结论仍未完成，研究角色仍是
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
