# G2双轮编译配对：CPU Job721086已完成并独立验收

2026-09-17 11:14 JST后更新：[完整结果与独立验收](2026-09-17-job721086-native-pair-verified.md)。
SSH已恢复，COMPLETED/0:0、10分26秒、lcpcc-051；R/C原生合成CPU参考/观测配对均通过。
完整工件下载后验收为NATIVE_CPU_PAIR_VERIFIED；未重提作业，下一项为生产worker整合。
不是A100/真实checkpoint比较。下面认证失效和RUNNING均为保留的历史记录。

2026-09-17较早记录：共享SSH socket已失效，免密只读查询在认证阶段返回255。
下文RUNNING为9月16日历史回执，不是当前状态；尚不能判断作业最终成功或失败。
新本地scratch接口工作不修改本作业发布包，详见[当前状态与接口记录](2026-09-17-g2-scratch-and-status.md)。

2026-09-16。用户在明确的1CPU/6000MiB/22分钟/0GPU/仅一次申请后回复“开始”，
本轮据此记录新的CPU额度批准。不是旧Job720730授权续用，也不授权GPU或全量评估。

## 2026-09-16最后已取回状态

- 用户认证已恢复，共享master检查通过（pid69100）；未接收密码或自动重连。
- 只读预检通过：账户队列为空，TINY为UP、MaxMemPerCPU6000，目标新root不存在。
- 30文件包上传完成、源SHA复核通过；Slurm test-only成功。
- **正式作业721086仅提交一次，held实际资源核验后已release。新的单次额度已使用。**
- 2026-09-16 15:13 JST再次查询：RUNNING，lcpcc-051，Elapsed00:03:39；
  ReqTRES/AllocTRES均为billing1/cpu1/mem6000M/node1，无GPU；尚无成功或失败终态。
- 尚未收集/独立验收最终结果，不是R/C已通过，更不是checkpoint总体比较完成。

此前连接缺失的阻塞已解除。首次受限环境下预检未能访问master，
在明确网络权限获批后完成同一个只读预检；没有因此重复提交调度作业。

## 本次远端执行凭据

- 预检：`preflight-20260916T054535Z-asinlybm/RECEIPT.json`。
- 上传：`deploy-20260916T060323Z-y5qqdczy/RECEIPT.json`，jobs_submitted0。
- 调度检查：`test-only-20260916T060851Z-_o3dcjq2/RECEIPT.json`，jobs_submitted0。
  test-only打印的721085是预估编号，不是本次正式提交回执。
- [单次提交回执](g2-bridge-batch-20260916/submit-20260916T060935Z-9t4cp6ka/RECEIPT.json)：
  SHA `f1545947d00fb536a4da44dfaaa191e2fdc49239b5b8d9f2bfbddb6c2b97e21b`。
- [本地提交意图](g2-bridge-batch-20260916/LOCAL_SUBMIT_INTENT.json)：
  SHA `c1a0652129079a4a8bc6601c638fcac28887b77eb9e6cb8543415f10c3241516`。
- 状态查询：`status-20260916T061135Z-7emrtiub/RECEIPT.json`。
- 后续状态查询：`status-20260916T061338Z-83amhhmm/RECEIPT.json`，仍RUNNING。

实际nonce为`b472c5ed3130470ebc656aa87863ab0e`；release SHA仍为
`50820c6fa76f60064cdcc0dd0ae3d9f4a5de2dd64ed41d2256e5e2c1945fa227`。
历史SUBMISSION_RECEIPT中的SUBMITTED_HELD记录初始提交状态，不覆盖后来release响应和实时RUNNING。

## 本轮实现与验证

新目录：[g2_bridge_batch_20260916](../prototypes/g2_bridge_batch_20260916/README.md)。
在新目录复用旧CPU控制器的写入一次、先持久记录提交意图、held检查后释放、收集与复核模式；
修改仅限新包的root、作业名、22分钟额度和四阶段编排，旧发布包不变。

30文件包 = 7份新控制/测试/SBATCH文件 + 21份已固定core来源 + 原core发布清单 + 固定进程监督器。
原core仍用自己的固定SHA；新BATCH_RELEASE另外绑定控制器和资源，避免混用两个协议。

27项测试全部通过，包括：

- 资源、账户、root、nonce、held状态、array/GPU/重排队和重复字段异常拒绝；
- 提交前持久意图、第二次调用不提交、回应不明确时不重试、资源不符时不release；
- core和batch清单分离、额外文件/源码变化、路径逃逸/symlink、只写一次；
- 固定R参考/R观测/C参考/C观测顺序、300秒子进程额度、失败首格中止并保留原日志；
- native结果job绑定、跨profile复用PID/缓存、缺少编译执行、伪造scope等拒绝；
- 真实监督器超时终止子进程并保存日志、SBATCH语法检查。

native记录的部分测试采用显式fabricated test doubles，只验证控制器判定逻辑，
不把模拟的版本/调用标签作为真实原生运行证据。

另从新30文件包实际启动本地D-observed冷子进程，完整两轮、32条、34次调用，
9.977秒、rc0；原core内容/身份/状态校验通过。此项是torch2.12.1合成eager，不是R/C原生结果。
新6份Python文件AST检查通过。

## 固定证据

目录：[local-tjfvm5j0](g2-bridge-batch-20260916/local-tjfvm5j0/)。

- BATCH_RELEASE SHA：`50820c6fa76f60064cdcc0dd0ae3d9f4a5de2dd64ed41d2256e5e2c1945fa227`
- LOCAL_REVIEW SHA：`88a72b2f8982afde2c329468d4c70d13302a362869035c5e3cd76189a203a957`
- `test_batch.log`：27项完整测试日志。
- `packaged-local/`：实际本地child日志、结果和监督器回执。
- `package/`：完整30份来源快照；复核要求实时来源与快照完全匹配。

本轮只清理自身创建的临时本地测试/编译缓存目录；旧证据、旧超算目录和模型均保留。

## 后续操作边界

认证命令（Mac本地）：

```sh
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

新的[单次CPU入口脚本](2026-09-16-g2-bridge-cpu.sh)默认只做preflight。
本次预检、部署、test-only、submit已经完成；**不要再次执行submit、deploy或test-only。**
已有本地/远端intent，只查询721086；终态后collect并review，不重复提交。

```sh
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-16-g2-bridge-cpu.sh" status
```

实际作业名`audattn_g2_bridge_cpu`，本次独立root
`/home/s2510040/audattn_external_eval_diag/g2_bridge_cpu_2026-09-16_v1`。
上限为每child300秒、coordinator1260秒、Slurm1320秒；失败停止余格，不保证成功。
完成后下载完整工件、复核调度状态和两组配对；无论成功失败，都不直接跳到全量10k或自动追加GPU作业。
