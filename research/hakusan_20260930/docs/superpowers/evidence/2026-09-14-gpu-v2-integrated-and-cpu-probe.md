# 完整对比续作：GPU v2已接入修正，CPU复验入口准备完毕

后续更新：下文“新部署控制器待完成”已由
[GPU v2提交控制器修正和验收](2026-09-14-gpu-v2-control-local.md)完成本地实现，
45项新测试＋34项旧回归通过；同版本CPU、远端部署/A100及最终比较仍待完成。

2026-09-14 JST。继续最终formal40与作者checkpoint比较的长期目标。
上一轮分类为progress：启动缺陷本地复现、修正及测试改变了下一行动。
本轮也有实际进展：修正已进入独立GPU运行包的真正入口，而不只是一个
未接入的helper；并准备了真实Linux/同版本CPU验证入口。最终目标未完成。

## 新运行包

[GPU运行包v2](../prototypes/targeted_gpu_job_20260914/README.md)目标root为
`/home/s2510040/audattn_external_eval_diag/gpu_pair_2026-09-14_v2`。
这是待部署目标，不是本轮已创建的超算目录。旧Job705468和v1不变。

新的gpu_child.run与审核过的startup AST完全一致，原lifetime AST保持。
coordinator/contract/runner路径已迁移到新root。B2/32条16→1、严格加载、
父数组匹配、168采集及所有科学数值容差没有改变。

runner同时明确总量和每节点GPU类型为nvidia_a100:1；8CPU/64GiB/2h不变。
这些选项支持指定GPU类型，见[Slurm官方sbatch参数](https://slurm.schedmd.com/sbatch.html#OPT_gpus)。
真实HAKUSAN仍须调度器test-only和暂扣后的资源回读，不能用本地静态测试
声称资源已正确分配，也不依赖旧705468的单次资源修正/放行记录。

- [新49文件manifest](../prototypes/targeted_gpu_job_20260914/SOURCE_MANIFEST.json)
  SHA：`8ddf8cc8ece27a14c49336b60fd1a45ffa295f57fb45778a66c559514d6d04f5`。
- [运行包45项＋归档38项回归](gpu-job-v2-local-20260913T172450Z-jahyzkfz/receipt.json)
  全部通过、零跳过；Python3.11.15/torch2.12.1，CUDA未初始化、生产模型未加载。
- 三个新增测试确认实际新run的AST、typed-A100新root与资源、入口导入失败
  的先建目录/后导入/清理及CHILD记录；原导入前门控静态测试亦加强。
- 旧51文件控制包和旧45文件运行包来源保持固定；新包不借用旧SHA/授权。

## 同版本CPU入口与当前阻塞

[CPU复验脚本与命令](../prototypes/targeted_gpu_startup_probe_20260914/README.md)
在新/tmp目录展开完整来源。旧reference导入顺序、新reference、新observed
三个独立CPU进程，合计85秒、单个45秒、日志256KiB；无GPU、无模型准备、
无forward、无Slurm调用。保留真实HOME。远端模式保留原Linux挂载决策，
只在本地自测模式显式使用挂载stub。临时目录正常清理是成功条件之一。

- [最终载荷本地自测](startup-probe-local-20260913T173206Z-w59m2qld/receipt.json)：
  三个新进程通过，51份来源及原始子日志回传核验通过。仅本地版本，不能
  把它写成HAKUSAN通过。
- [12项验证器/载荷反例](startup-probe-unit-5ivqin9l/receipt.json)通过，拒绝
  错误角色/PID/包/日志、缺失清理、CPU/生产范围混淆及路径逃逸等。
- 本轮实测共享socket缺失；另一次非交互hostname检查退出255，
  `Permission denied (publickey,password,hostbased)`，不是正常的已连接等待。
- [实际远端入口尝试回执](startup-probe-remote-20260913T173304Z-lojw8poh/receipt.json)：
  process=null，连接检查因socket缺失停止，没有发送CPU载荷或提交作业。

不收集密码、不把密码写入脚本、不自动重连。本轮不是verified wait，
因为没有确认活跃的SSH或新作业句柄；也不是no-progress，因为已完成上述
新的可执行代码及验证。长期goal保持active，不以本地通过替代完整对比。

## 接下来（仍未完成）

1. 恢复认证后实际运行有界同版本CPU启动复验，完整核对native mount和日志。
2. 完成新GPU v2部署/提交控制器，要求typed-A100资源、独立新包/新root，
   test-only/暂扣复核和独占提交日志。旧705468授权不可复用。
3. 按新的有效资源授权运行真实冷参考/观测，回传原始数组并核对观测干扰，
   再定位原数值差异，不放宽容差换取PASS。
4. 科学设置明确并通过三模型smoke后，完成10000条bank/既定control对比、
   逐trial验收、配对统计/不确定性及报告。当前没有最终比较结果。

本轮新增作业0、上传/生产发布0、冻结修改0。
评估角色仍为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
