# 独立进程追踪与可重读归档原型

2026-09-12：本地31项单元测试及三组独立进程测试已通过；随后超算torch2.1.1
的同一套31项及一组dependent冷进程对照也通过。21份回传工件已完整重验，
代理另行只读独立复核通过，见[超算验收记录](../../evidence/2026-09-12-archive-remote-verified.md)。
本轮未加载生产模型、执行GPU推理、发布生产版本、冻结输入或提交作业。
这是Job685198之后逐层观测的工程准备，不是模型数值根因或三模型比较结果。

连接阻塞历史（现已解除）：用户再次认证成功后，master又以Broken pipe退出，代理接手时
socket已不存在。新增[认证后立即CPU复验的单次入口](../../evidence/2026-09-12-archive-cpu-handoff.md)
已通过9项离线入口测试及本地载荷校验；不改原连接/归档驱动，无自动重试。
此入口已由用户在Mac终端认证并连续执行成功，无需再次运行。

## 本次补齐的能力

- 参考与观测分别在全新的Python子进程运行，缓存目录分开；监督进程核对
  实际Popen PID、子进程回执及归档writer PID，不使用Dynamo reset代替冷进程。
- 原分块观测器保持原SHA。新增封闭类型的规范JSON格式和原始二进制数据，
  不使用pickle、不根据归档任意导入类；参考输出、批次顺序、事件和数据引用
  均保存，读取器必须接收监督方给定的预期SHA、计划、角色及绑定记录。
- 新建私有归档、单次写入；检查目录/文件类型、owner、权限、链接数、精确
  文件清单、长度及SHA。逐块完整读取，即使已经发现差异也不跳过后续数据。
  文件截短、短读、额外/缺失文件、换名替换、非有限值及元数据错配均有反例。
- 每个数据块编码载荷不超过1MiB，单文件不超过128MiB，捕获数据总计不超过
  2GiB，最多8192个引用；JSON不超过8MiB。这不是整个进程RSS或显存上限。
- 先验证参考/观测端点、输入、状态、RNG及运行设置；若观测改变端点，拒绝
  输出逐层定位结论。端点一致也不证明内部编译图完全等价。

## 实际证据

最终[本地回执](../../evidence/archive-local-20260911T144552Z-yiyecqo7/receipt.json)
为LOCAL_ARCHIVE_VALIDATION_PASS；Python3.11.15、torch2.12.1、CPU，31项无跳过。
三组集成测试共启动六个参考/观测子进程；不是再增加三项单元测试，也没有
把旧原型测试重复计数。每个子进程保留32条合成输入的16→1顺序，共34批。

| 合成场景 | 参考/观测PID | 实际结论 |
|---|---|---|
| invariant | 77619 / 77620 | 两个目标均未发现观测边界差异 |
| dependent | 77629 / 77631 | 两个目标首个观测差异均为index 2，model._orig_mod.gain，mixture |
| interference | 77638 / 77640 | EXPECTED_OBSERVATION_INTERFERENCE_REJECTED；不报告逐层结果 |

原始[单元测试输出](../../evidence/archive-local-20260911T144552Z-yiyecqo7/units.log)、
[无差异回执](../../evidence/archive-local-20260911T144552Z-yiyecqo7/invariant/PAIR_RECEIPT.json)、
[已知差异回执](../../evidence/archive-local-20260911T144552Z-yiyecqo7/dependent/PAIR_RECEIPT.json)、
[干扰拒绝回执](../../evidence/archive-local-20260911T144552Z-yiyecqo7/interference/PAIR_RECEIPT.json)
及六份完整archive.json、各观测数据文件均保留在同一证据目录（约3.2MiB）。
合成trial编号0/28只是测试编号，不能当作生产trial9000/4126等的追踪结果。

最终回执SHA256：
`49cb855ebf02684834c8aab31d6b3ddb9ea25310a1aeaab89117bd7980173252`。
完成后另一个只读Python进程重新核对六个源码SHA、四份日志、三个pair回执、
子进程日志、六份归档预期SHA/身份及全部捕获字节，复算结果完全一致：
INDEPENDENT_ARCHIVE_RECHECK_PASS。此复核没有再次执行模型forward。
旧observer七项、stream九项、binding三项及v18 release二十八项SHA全部仍通过。
本次六个源码与远端驱动固定于[SHA清单](SHA256SUMS)。

较早的archive-local-20260911T144131Z-_na7cdmj保留的是27项中间版本测试，
不作为最终31项版本证据。没有覆盖这份历史输出。

## 超算CPU复验：已完成并独立重验

实际[回执](../../evidence/archive-remote-cpu-20260911T152452Z-bcyhkj5v/receipt.json)
为REMOTE_ARCHIVE_CPU_AND_LOCAL_RECHECK_PASS、returncode=0。远端31项无跳过，
耗时1.663秒；reference/observed PID分别553517/553661，各34批。两个合成目标
首个差异均为index2、gain、mixture。21份工件共1,025,811字节回传并完整重验，
十份源码、bootstrap、输出、回执与子进程身份再经代理独立只读复核通过。
专属远端临时目录正常清理。具体摘要与范围见顶部验收记录。

以下保留执行入口以便审查，本次已验收，不需要重复运行。

[远端驱动](../../evidence/2026-09-11-archive-cpu-check.py)默认只校验十份固定源码
及引导载荷语法。`--run`才使用现有SSH共享socket，临时写入私有/tmp目录，
执行31项同版本CPU单元检查及一组dependent独立进程对照，回传21份小型合成
工件供Mac再次完整读取核验；正常完成后清理该专属临时目录。不发布生产工具，
不接触checkpoint/audio，不调用Slurm。失败不自动重试。

上限：单元进程60秒、每个冷子进程60秒、pair监督进程150秒、Mac SSH调用
270秒。远端监督进程超时会终止所属进程组；没有不受限轮询或自动扩时。
远端版本要求Python3.11.5、torch2.1.1+cu118。驱动已通过本地载荷校验及Ruff，
远端执行和工件往返路径现已通过上述实际运行验证；不等于生产GPU验收。

早先受阻调用在读取`.hakusan-control/master.sock`时发现文件不存在，尚未发起
驱动的远端命令。一次只读BatchMode连接检查返回255、认证失败；没有重试
提交或变更远端数据。以下是代理使用现存连接时的底层命令，无需重复旧提交脚本：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-11-archive-cpu-check.py --run
```

上面命令从项目根目录运行。此次用户实际使用顶部新增的单次入口，将
[原连接脚本](../../evidence/2026-09-10-hakusan-connect.sh)与CPU复验连续执行，
不再等待聊天交接，完成了复验。密码仅输入SSH提示。

## 仍未完成，不能越过的边界

本次编译仅合成模型的Dynamo eager后端，不是Inductor/A100。归档scope固定为
UNATTESTED_PROTOTYPE_ARCHIVE，production_execution_authority_verified=false，
ready_for_gpu=false。SHA/清单及PID字段不能自行证明生产执行授权、抵御恶意
运行时或证明冷进程；进程独立性还依赖监督方实际启动记录。

同版本归档往返复验已完成；后续需生产worker执行能力接入、完整原32条特征重建
与v18边界摘要核对、A100上独立冷参考/观测及观测干扰验收。真实CPU加载/绑定
已通过的证据见[前一阶段](../targeted_binding_20260911/README.md)，但没有
真实forward。原精度/compile设置及1e-6容差不变，不能拿原型成功替代smoke。
最终三模型smoke、10000条bank与既定control比较、置信区间及结果报告仍待完成。
报告必须保留REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST标签。
