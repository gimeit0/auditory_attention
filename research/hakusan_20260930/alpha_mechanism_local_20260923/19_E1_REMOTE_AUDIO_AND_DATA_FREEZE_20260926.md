# E1远端音频核验与数据身份冻结

状态：`E1_DATA_IDENTITIES_FROZEN_PRODUCTION_NOT_READY`。

- 复用用户已恢复的SSH master pid36193，单次只读请求，没有自动重连/重试、远端写文件或GPU提交。
- 核验全部2000条候选在bank中记录的角色引用（保守包含非control mixed的probe cue）：**10700条anchor引用**全部与历史冻结anchor按索引及关键字段一致。
- **1939份独立音频，96393726字节**，本地哈希盘点后远端逐一读取；所有size/SHA匹配。309份clean录音还与上一轮解码记录SHA再次核对。
- 远端根：`/home/s2510040/selective_listening_repro/code/auditory_attention/cv_train/clips`。全部请求/原始响应/本地及远端清单见 [e1-audio-remote-20260926-v1](e1-audio-remote-20260926-v1/)。
- clean输入和音频测试复跑14项通过；新增冻结比对测试5项通过（错哈希、缺文件、错误match标记、候选绑定错误均拒绝）。
- [数据身份冻结清单](E1_DATA_FREEZE_20260926_v1.json) SHA256：`6c4df571e897a2c13aa6c693a86783c83ac8620b1f24b7f932ddbe6d93ab62fe`。保存候选、bank、anchor、来源代码/报告的身份，完整音频哈希及父批/control/clean布局。独占创建，不覆盖原候选。

## 范围与未完成项

冻结的是**数据身份、选择顺序及布局**，不是“完整可提交输入合同”。`production_ready=false`，不能用此文件直接放行GPU。1939份全音频做了字节检查；本地解码通过只覆盖此前309份clean音频，不能将二者混称全音频解码通过。

仍需：新clean正确cue路径的原生真实音频验收、完整E1 worker/独立验收器、额外clean端点检查的预测数、统计口径和具体GPU预算审批。后续可执行包必须引用并复核本清单，运行前再次检查数据未变。此集合仍为复用验证bank的开发集，不是独立确认集。

下一步建议：先做不加载checkpoint的原生CPU真实音频输入检查，确认新旧clean目标波形逐位一致、正确cue不被清零、200条尾批布局合法；具体远端CPU预算与操作范围需先列明。之后才准备E1可执行包与单次GPU预算申请。
