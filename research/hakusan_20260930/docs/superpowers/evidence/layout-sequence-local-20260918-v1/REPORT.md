# P05b四进程运行/验收/本地收集包装

2026-09-18。LOCAL_SEQUENCE_TESTED；NOT_DEPLOYED；GPU_JOBS_SUBMITTED=0。

## 本轮完成

- `sequence.py`：四个独立模型进程，顺序bridge16→cold1→peers16→tail17；每个模型后另启独立验收进程，合计四模型＋四验收。模型与验收共用1680秒总deadline，30分钟仍是待批准Slurm额度。异常、超时或SIGTERM/SIGINT只清理本包装拥有的进程组，不触及其他作业。
- 每步独占写INTENT/PROCESS/EXIT及stdout/stderr日志。输出目录已存在即拒绝，不覆盖、不恢复、不重试。成功标记是`EXECUTION_COMPLETE_NOT_QUALIFIED`，失败保留部分产物；清单无法建立时记录inventory_error，不伪造可收集的完整产物。
- `sequence_worker.py`：用外部固定的725677 repeat16/batch1回执作为桥接与冷重复基线；实际模型PID/job/node与运行记录一致才继续。重用原独立reader及布局reader，不修改科学函数或阈值。
- bridge16/cold1要求固定配置logits逐位一致、旧结果表1e-6检查PASS；否则先保存报告，再停止后续阶段。这是保守停止条件，不是新的放宽政策。peers/tail的数值DIFF如实输出，不自动批准资格或全量。
- 逐样本CSV已接入。合成集四阶段分别输出159、318、318、192行配对记录；重复使用同一预测的不同对照不作为额外独立样本。
- `collect`：只读源目录、核对外部terminal SHA、逐文件SHA/大小和完整清单，复制到新的本地目录；失败产物仍标失败，拷贝不等于科研验收。中途失败不写COLLECTION完成标记。无SSH下载或自动重连。
- 运行契约绑定代码/四布局/旧reader/v4/两份基线回执、nonce、实际jobid及限额；只有明确审批状态和外部SHA匹配、原生Python/Slurm实际1 A100/8CPU/64GiB/30分钟/不重排队匹配时CLI才进入运行。本轮没有生成正式授权文件。
- `run_layouts.sbatch`为已分配作业内入口，不负责提交。使用明确部署路径，不从Slurm spool里的`$0`猜工具目录。

## 验证

[完整最终测试日志](tests.log)：69项，8.366秒，exit0。其中43项是上一轮候选/验收回归，26项是新增包装、契约、失败路径及集成测试。不是69次GPU测试。ruff通过，bash -n通过，两个CLI --help正常。

覆盖四模型/四验收真实OS子进程顺序、模型失败/验收失败、repeat DIFF、错误PID、缺少报告、重复运行拒绝、模型/验收超时、总预算不重置、信号处理与子进程清理、spawn失败、失败产物收集、hash篡改/额外文件/符号链接拒绝、不改源文件、现有目标拒绝、错误A100/预算/授权/源码拒绝。

另以真实合成disk-checkpoint→forward→archive→worker独立重算走完四阶段，核对所有CSV行的差值方向。此集成测试的节点/作业声明为测试数据；测试临时替换基线位置/回执，只在临时目录内，不是生产证据。scratch参数测试打印同一个测试PID是因为mock了模型入口；四个真实独立模型子进程的证据由另一项OS进程测试提供，两者不混淆。

本地环境沿用Python3.11.15/Torch2.12.1 CPU；尚未在HAKUSAN 3.11.5/2.1.1+cu118运行本套新包装，尚未进行真实A100布局检查。

## 指纹

| 文件 | SHA256 |
| --- | --- |
| sequence.py | 7645d8623aa9902fa05f635186de96fa036844b3df7211e2e544fb4868e488e4 |
| sequence_worker.py | 7138669a356ac8a45c80835851ba34cea1df3e116be835d59de45935679662de |
| run_layouts.sbatch | 7afe137daf47b8847bd6cabe78cc0bd6fefc55cf8d07602cdbff61753be59a28 |
| tests/test_sequence.py | b8f3fbd4cdeea4e8a20288f36fba8895b5c319006625b6fe94bb23095a0c46ff |

原新候选`eager_compare.py`仍为`8a191e7afc5a7e382b26039fb409041910bc250e7b9b84b8a483244d7c3042ed`，`review_layouts.py`仍为`a2648549402e3e56b2b670078557ded09b1dbc1015fa00320073088cc65eed23`；旧科学版本和Job725677结果未改。

## 剩余边界

本轮完成的是计算节点内运行包装＋本地收集，不是整套远程投递系统。仍需：原生CPU回归；新包/授权/唯一提交控制器；held/test-only与实际资源核验；经过审批的同一作业GPU修正范围；SSH传输和独立收集验收。旧725677投递脚本不得复用，当前不能直接运行sbatch。不得因为这些本地测试通过就认为P05b真实验证、P06接受政策或10k全量已完成。
