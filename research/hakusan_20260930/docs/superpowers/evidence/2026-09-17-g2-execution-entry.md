# G2真实进程入口候选与本地发布包

**历史候选，已被[计划绑定与typed A100修正](2026-09-17-g2-plan-binding-fix.md)替代。下面31文件包与当时证据保留，不部署/提交。旧验证命令与当前开发源码不再同版本；当前复查请使用修正记录中的32文件候选。**

2026-09-17。服务G2固定32条数值设置对照。**未上传、未生成生产freeze、未提交、未得到新真实模型结果。**

## 已完成

- 新matrix/worker/verify入口连接既有生产cell、40数组保存、独立原语义验收与R/C/D/E控制。
- 不接受来自结果JSON的任意命令；使用固定解释器、固定源码入口及固定profile。
- 请求必须绑定新发布、四freeze、job和nonce；实际scontrol资源、命令、输出路径、账户和无重启状态独立检查。
- 父进程先写启动意图，保存实际进程PID/环境/命令、日志和返回码，再固定子产物哈希；验收在另一个无可见GPU的冷进程中进行。
- 复用已有进程组超时/日志限制工具。保留失败attempt及scratch，不自动重提、不覆写旧版本。
- 31文件候选包包含原生backend依赖、四组工具及旧输入/几何只读参考；profile-local旧提交名改为明确拒绝独立执行的notice。

## 固定证据

目录：`g2-entry-local-20260917T063102Z-rvjjh422`。

| 项目 | 结果 |
| --- | --- |
| 入口/打包/资源拒绝/实际小进程检查 | 22项通过，pid74993，0.448秒 |
| 原运行控制及保存合成数组语义 | 30项通过，pid75004，1.592秒 |
| 实际候选包四profile冷导入 | pid75006，0.270秒，通过，无torch/numpy/模型导入 |
| 已打包runner bash语法 | pid75007，0.003秒，通过 |
| 来源记录/快照 | 38份，运行前后相同 |
| 独立只读复查 | `LOCAL_G2_ENTRY_CANDIDATE_RECHECK=PASS` |

`VALIDATION.json` SHA：`94142ebab9da6135e634380d689f4b2e70006d536bddf70ec34ba8e918a2ff04`。

候选包 `candidate/RELEASE.json` SHA：
`85525eaaab43c08f8d6cc3d3c310c3555657471ed08c249897f14e6958145650`。

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_runtime_20260917/validate_entry.py verify \
  docs/superpowers/evidence/g2-entry-local-20260917T063102Z-rvjjh422
```

## 必须保留的限制

调度行测试是合成fixture，生产根目录/解释器限制没有在本地绕过。没有实际正向运行完整生产入口。
本地通过不证明Slurm字段在当前分区完全吻合，也不证明真实加载、A100内存、编译耗时或数值阈值通过。
R/C生成代码的在线源/调用证据继承原backend检查；当前完整生成代码字节尚未打包为可下载的独立编译工件。
coordinator终态是已记录结果，不是下载后独立验收，也不能跳过旧B2解释、冷重复、三模型smoke。
scratch保留供失败分析/编译工件收集；没有删除远端数据。

最新有界只读SSH查询仍返回255和 `Permission denied (publickey,password,hostbased)`。
没有新的队列、分区或生产目录状态。Job721086的已下载已验收历史结果不受影响，未重提。

## 进入真实执行仍需

1. 用户本人恢复共享SSH认证；密码仅在SSH提示符输入。
2. 审定G2-M单次资源：1 A100、8CPU、64GiB、3小时；本次已请求确认，尚未视作批准。
3. 新目录现场预检、候选包上传/校验、四组真实audit/freeze与科学输入不变检查。
4. 完成单次held提交/请求绑定/实际资源核对后释放；未知提交结果先查账，不重试。
5. 收集真实32条输出，独立验收及旧B2对应解释。只有满足规则才选候选，再另审冷重复与后续全量额度。

无新GPU作业、无总体checkpoint对比结论。新候选仅是向上述执行迈进，不能将测试数量当作科学结果。
