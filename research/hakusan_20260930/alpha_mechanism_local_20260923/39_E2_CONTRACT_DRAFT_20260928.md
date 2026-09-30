# E2 轨迹合同草案与实施记录

最新整批见[43号原生小批合同](43_E2_NATIVE_PILOT_PLAN_20260928.md)：覆盖8阶段、五点α预选阶段及冷重复的2709条原生小批入口、完整验收负对照和held单次提交脚本已实现，89项本地测试通过。小批1 GPU小时为待批准预算，未上传、未提交；正式矩阵91134条另行批准。

当前增量见[42号文](42_E2_LOCAL_PIPELINE_CANDIDATE_20260928.md)：本地协调器与便携候选包已实现，68项测试及隔离包检查通过。含冷重复和九次端点共91,134条预测；生产小批、完整验收器负对照、调度脚本与科学分析仍待完成。4 GPU小时是未批准的预算候选，没有E2作业号。下述计数及待办保留为历史记录。

后续接入状态见[41号文](41_E2_SESSION_MATRIX_ARCHIVE_PROGRESS_20260928.md)：候选session/worker、矩阵、端点、归档和历史桥接已实现，59项本地测试通过。分析86400加端点1008共87408条预测，冷重复另计；生产协调器、发布包、原生GPU门及科学分析尚未完成。没有E2作业号。

最新增量：checkpoint元数据兼容问题已解决，8阶段原生内容核验 `E2_STAGE_INSPECTION_PASS`，39项本地回归通过，见[40号核验记录](40_E2_CHECKPOINT_COMPATIBILITY_RESOLVED_20260928.md)。下方“不支持元数据/内容尚未通过”为保留的历史状态；生产session、GPU推理及E2科学验收仍待完成。

状态：E2_PREPARATION_IN_PROGRESS，非冻结合同、非GPU批准。2026-09-28用户确认尚未取得人类数据，当前范围收敛为先完成E2；E4保持DATA_WAITING。

## 设计决定

- 科学问题：在固定开发场景上，训练量改变的识别/选择行为，与最终权重降低α得到的行为是否相同。只描述单条训练轨迹，不推断儿童年龄或训练日程因果性。
- 阶段候选为完成0、1、2、4、8、16、24、40轮，文件名见38号台账及 e2_checkpoint_inventory.py。先全部α=1，再选完成0、4、16、40轮做五点α=[0,.5,.75,.875,1]，以覆盖初始化、pilot端点、中期、末期；这是当前预选方案，不根据E2成绩挑阶段。阶段身份有缺口则修订并留痕，不暗中替换。
- 延用E1冻结2000条开发样本及实际批布局、400控制、200新clean；按correct/shuffled/silent/distractor及新clean正确/零cue输出。阶段、α、trial必须完整标识。
- 每阶段α=1基础预测量：2000+3×400+2×200=3600；8阶段28800。4个预选阶段补4个α：57600；基础总量86400，不含冷重复、端点桥接、失败诊断与加载开销。不能拿基础计数直接当最终预算。
- 对齐E1完整布局的formal40/α=1必须桥接历史E1数组；不把不同布局结果要求逐位相等，也不事后放宽验收阈值。新阶段先检查原始forward与α=1插入的一致性。
- 主要描述为各阶段α=1的准确率/NLL、cue差、clean正确cue−零cue差和错误结构；预定阶段配对差及阶段×α为开发探索。共享target-speaker簇重采样，trial加权，10000次固定seed20260928，95%区间；不将多个条件的探索性区间当多重校正后的确认结论。
- 保留所有低准确率与崩溃读数。E1低α崩溃不直接解释为选择减弱。新阶段的崩溃判据与初始化接近机会水平时的适用性须在冻结前明确，不能机械用阶段自身极低基线替代科学解释。

## 实施与验收门

1. 字节身份：8文件SHA、大小、读取前后稳定性；formal40必须匹配历史SHA。不反序列化，最多90秒/8GiB，无自动重试。
2. 阶段内容：受审读取epoch/global_step/loop state及参数键与shape；确认初始状态和训练保存语义。文件名不是内容证明。不得无审核pickle加载，不在登录节点无界构建模型。
3. 新E2阶段加载器：不能修改E1冻结包或把早期权重伪装成formal40；checkpoint清单进入合同、加载报告及输出身份。加载覆盖必须完整，参数不匹配拒绝。
4. 生产worker：复用受审音频provider/前处理/运行设置；父进程记录启动前与wait返回后的UTC、单调耗时、PID和退出码，完整涵盖加载及归档，子进程执行窗口另记。
5. 本地合成回归：阶段错绑、SHA错、重复/缺失trial、错误布局、错误α、状态/RNG改变、进程超时、未完整退出等均拒绝；统计独立复算。
6. 原生小批、正式运行分别写预算，卡型/时限/预测数/失败出口批准后单次held提交。此草案不授权提交。
7. 完成：阶段证据、原始结果、离线验收、独立统计复算、局限和可复现报告齐备，才记E2_TRAJECTORY_DESCRIBED。仅测试或哈希通过不算完成。

## 本轮记录

- 已检查E1加载路径：e1_audited_session.py调用formal40严格加载，loaded_model_adapter.py还检查FORMAL_SHA；E2须新建清单绑定接口，不能只改模型名。
- 本地冻结训练源码显示stage-zero于on_fit_start保存；逐epoch回调save_top_k=-1、save_on_train_epoch_end=False。实际checkpoint阶段仍须内容验证。
- 新增e2_checkpoint_inventory.py、run_e2_checkpoint_inventory.py及7项测试，全部通过。只读载荷SHA：7f0761900e9ba8edb168e6e5e2d4ff4dc07b3e0f82f673fb345161f58c312bd2。
- 第一次连接检查被本地sandbox拒绝，未执行远端载荷；经系统权限批准后复用现有master（pid51232），未自动重连。远端回执另行记录。
- 远端8份checkpoint全部完成字节核验，formal40与历史SHA相符，状态 `E2_BYTES_HASHED_STAGE_UNVERIFIED`。证据：[回执](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-fb3qsucc/RECEIPT.json)、[8文件结果](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-fb3qsucc/stdout.json)。本地重算stdout SHA与回执一致。未反序列化、未加载模型、未提交作业；下一门是阶段内容验证及新加载入口。

### 第二批推进

- 用户要求推进到E2完成。范围仍为E2，不启动E3/E4或自动批准GPU。
- 受限CPU内容检查在stage-0因PyTorch2.1.1拒绝pathlib.PosixPath而停止，没有回退到不受限pickle：[失败证据](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-lcg8f0o6/stdout.json)。完整tensor签名/有限值检查尚未通过。
- 改用独立静态opcode读取（不执行pickle），8文件重新核对SHA后取得epoch/global_step字面字段：[原始证据](../docs/superpowers/evidence/r1-development-inventory-20260922/remote-readonly-oyc0xh58/stdout.json)。回执SHA本地核对通过；这不是完整反序列化或模型兼容性证明。
- 前7阶段字面字段符合阶段候选；formal-final为epoch=40/global_step=69440，而非中间保存的epoch=39。冻结训练代码patch_stage_next/src/spatialtrain.py在trainer.fit返回后另存final_checkpoint；因此formal40专用规则绑定已知SHA和after-fit保存语义，不泛化放宽其他阶段。保留静态报告原始MISMATCH，不覆盖历史报告。
- 新增e2_process.py完整父进程生命周期记录，包含成功、非零退出、超时、启动失败；时间为父进程观测边界，不宣称精确内核时刻。尚未接入生产E2运行器。
- 此时E2仍未科学运行。下一工程门：支持checkpoint元数据的受审加载方案、八阶段严格权重兼容性、新worker/归档/桥接集成和预算。
- 本批最终四组本地回归24项通过；无GPU作业提交。静态提取只作补充证据，不以其绕过参数内容检查。
