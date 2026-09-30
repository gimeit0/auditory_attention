# G0–G1启动执行台账

2026-09-15 JST。用户已同意完整交付路线并要求开始。
当前工作单元：G0基线盘点、G1必要同环境工程入口、G2具体实验规格。

2026-09-16：[独立CPU批处理记录](2026-09-16-staged-cpu-batch.md)。用户已批准1CPU/8GiB/10分钟/0GPU上限，
按TINY每CPU限制下调内存为6000MiB；新封装18项保护测试和本地三冷阶段通过，进入单次CPU调度流程。
已完成：Job718727，COMPLETED/0:0/00:01:36，lcpcc-054，ReqTRES与AllocTRES均1CPU/6000MiB/0GPU。
A2/B2/mmap原生三冷阶段通过，下载及独立验收通过；固定只读复查和10项非法结果拒绝检查通过。
当前下一项为G2生产适配器准备/新GPU方案审定，不再以“原生三阶段尚未完成”描述现状。
以下保留此前登录节点50秒超时记录；未冒用旧80项全通过，也没有新的GPU授权。

**此前登录节点检查（历史）：认证已恢复、当时队列查空；A2分阶段检查仍在50秒超时，B2/mmap未执行。**
见[原生失败验收与新CPU预算待决项](2026-09-15-staged-native-timeout.md)。
下方“连接缺失”是前一轮启动时的历史状态，不再是当前阻塞。

## 已实际完成

| 项目 | 结果 | 证据/范围 |
| --- | --- | --- |
| 原本地stage基线复查 | PASS | 固定receipt、162旧来源、16工件，不运行模型 |
| 新远端封装离线测试 | 24项PASS，1.118秒 | 错来源、错session、错SHA、越界父路径、超时/失败、错误环境、CUDA/越权标志等拒绝 |
| 相同载荷本地A2预期 | PASS，7.462秒 | 独立进程，32条、16→1、原guard/模型生命周期 |
| 相同载荷本地B2预期 | PASS，6.880秒 | 同上，AMP配置按原B2合成fixture |
| 相同载荷本地B2 scratch/mmap | 原2项断言PASS，7.356秒 | 内容绑定预期结果，原断言不变 |
| 新载荷结果只读复查 | PASS | 请求包/来源、transport/子进程日志、输出、跨stage引用、旧monolithic对照 |
| G2规格 | 草案完成 | 精度/编译2×2、接受条件、停止规则、拟议预算，尚非批准或提交 |

本地环境：Python3.11.15 / torch2.12.1；不是HAKUSAN原生测试。
原子stage仍使用原fixture的 `LOCAL_STAGE_PASS` 测试身份，外层 `LOCAL_HARNESS` 才表明此次执行主机。
每次调用保留child50秒、supervisor90秒、transport110秒；远端模式另限单CPU。
三次调用是独立顺序期限，不声称三个总和≤90秒。

来源不变：旧v19/162源manifest、旧stage helper两份、旧freeze、所有失败作业记录。
未接入namespace候选、未放宽数值阈值、未改checkpoint/数据。
新封装只在独立目录，未向远端写文件或执行连接/调度命令。

## 固定本地证据

- [回执](staged-scratch-local_harness-20260915T124305Z-jdqphuin/receipt.json)：
  `29b587c8a8dc5bf222b730646de57234965df69e622eb4c0b03e297e8ab6c7cf`
- 完整输出contract：`cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000`，
  与原未拆分本地oracle一致，包含完整官方输出字节、边界记录和trial身份。
- [新入口源码/范围说明](../prototypes/staged_scratch_native_20260915/README.md)。
- [固定源码/receipt只读检查器及CPU入口](2026-09-15-staged-scratch-native-cpu.py)。
- [短shell入口](2026-09-15-staged-scratch-native-cpu.sh)。

## 首轮启动时的阻塞（历史；以上方后续更新为准）

本轮两次本地检查 `.hakusan-control/master.sock` 均不存在；没有假装成功认证，没有实时查询队列。
因此G0的远端当前队列/attempt盘点、G1的原生三阶段都尚未完成。
最近已知真实GPU仍为Job715276失败，这是已存证据，不是本轮实时状态。
旧原生78项通过+最后两项超时的记录保留；新分阶段结果不计作旧80项全过。

恢复本人SSH认证后：

1. 只读查既有作业/回执，防止重复提交。
2. 运行新CPU入口一次，三个阶段逐一验证；失败即停，不自动重连或重试。
3. 复核原生环境/期限/输出/临时清理。通过也不颁发GPU或正式比较通过标志。
4. 审定[G2数值对照规格](2026-09-15-g2-numeric-profile-spec.md)及具体资源，再实施新GPU入口。

本轮新GPU作业数 **0**；新远端freeze数 **0**；真实checkpoint对比结果 **尚未生成**。
