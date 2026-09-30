# 2026-09-08 诊断 v5 检查与修复记录

范围：修复独立审查在诊断 v4 中发现的合法 src 导入误报，并检查相邻加载、
授权和撤销路径。新目录 same_bank_eval_2026_09_03_v4_numeric_diag_v5。
已上传但未发布的诊断 v4、此前诊断 v1–v3、冻结评估 v4 均不原地修改。
本次没有连接超算、上传、冻结或提交作业。

## 原因与 RED → GREEN

冻结评估器 strict_load_model 在嵌套 _frozen_import_context 内导入
src.spatial_attn_lightning。诊断 v4 将这个模块的进程对象身份写入固定函数图，
未加载时为 id(None)，合法导入后发生变化，导致生产 capability 检查误拒绝。
旧专项夹具只含 selftrain，没有覆盖 src。

在新候选尚未修改生产逻辑时，补入哈希正确的 src 源码与
test_authorized_src_import_keeps_nonmaterializing_evaluator_graph，测试退出1，
比较固定函数图失败，复现独立审查 P1。

修复不是全局忽略 src：只有固定 SHA 的真实冻结评估器加载器签发的确切
strict_load_model 对象、唯一 src.spatial_attn_lightning 导入边，改用快照
授权身份，而不是会随正常作用域切换变化的进程模块身份。签发函数图时不再
从进程搜索路径提前导入该模块。活跃作用域仍验证声明、finder、模块来源、
绑定及函数身份；没有签发后无条件重设基线。
普通函数的 src 导入和其他依赖仍固定身份，数值容差未变。

## 扩大后的回归覆盖

- 合法 src 导入前、活跃作用域内及退出后，默认非 materialize 图一致。
- 未授权 src 模块替换被拒绝；普通 src 导入不获得特殊待遇。
- evaluator 签发阶段不从进程搜索路径导入 src。
- 缺失快照 src 声明被拒绝，封闭后新增 src 模块被拒绝。
- 实际 production capability 注册测试补齐 src/selftrain 源记录，随后合法
  导入 src，再调用真实 capability 活性校验。
- 真实冻结 strict loader 读取临时 YAML 和真实 torch.save CPU checkpoint，
  构建小型夹具模型，严格加载权重并验证 eval/frozen 状态、推理值。
- 同一夹具封闭模块绑定后再次推理，结果正确且 evaluator 图不变。
- 保留先前源码、函数、默认参数、第三方依赖、注册表、finder、退出撤销等反例。

## 主代理检查结果

各测试独立 Python 进程，使用 /opt/anaconda3/envs/audattn/bin/python -I -B。

| 项目 | 结果 |
| --- | --- |
| 主诊断 test_numeric_diag | 344/344；首次94.426秒，最终格式化后93.748秒 |
| test_submit_numeric_diag | 66/66，10.472秒 |
| test_loader_record | 6/6，0.291秒 |
| test_real_evaluator_scope | 最终28/28，1.235秒 |
| 合计 | 444项通过，不将重跑计为新增覆盖 |
| Ruff check / format check | 通过 |
| Bash runner语法 | 通过 |
| audit-inputs与submitter帮助入口 | 通过；没有运行真实audit |
| README八文件SHA / 外部九文件manifest | 主代理校验全部通过 |
| 旧诊断v4九文件manifest | 全部通过，原候选未改 |

诊断根和协议升级为 v5；runner/submitter只改版本身份。numeric_trace.py、
test_submit_numeric_diag.py、test_loader_record.py 与旧候选内容一致。
冻结评估 v4 的身份、bank、checkpoint、SNR、模型角色和科学协议未改。

## 独立复查

延续用户已授权的只读 diag_v4_release_review，由该审查者复核 v5。
代码结论：有界 Ready，可在发布清单闭环后受控部署并执行 audit-inputs。
独立专项28/28通过，1.231秒；额外临时反例在授权 src 模块封闭后给模型类
添加方法，检查拒绝 frozen module callable changed。
审查者没有修改候选、连接超算或提交。最终独立清单闭环：外部九文件manifest
及README八文件SHA均全部OK、退出0。最终限定结论Ready：可受控部署至新根，
远端身份复核后运行audit-inputs；不跳过冻结、check-only及单次提交门槛。

## 未获证明的内容

本地环境为 torch 2.12.1；用户确认集群为2.1.1+cu118。
CPU夹具不是实际formal40，未覆盖真实完整production attestation、冻结音频、
全部真实模型惰性导入或A100内核行为。本次不能证明原始NLL差异原因，不能
发布SMOKE_PASS或宣称三模型10k比较完成。
下一步是经复查的诊断v5新根预检/受控部署，然后先运行真实audit-inputs。
任何失败保留现场，不修改旧freeze，不放宽数值门槛，不自动重提作业。

## 用户回传的部署进度

用户在 HAKUSAN 完成 v5 新根及六个700权限子目录创建，输出
REMOTE_DIAG_V5_ROOT_CREATED=PASS / CREATE_RC=0。随后在 Mac 核对九文件
候选清单全部OK，上传四个生产文件至 v5/.upload-staging，传输均100%，
DIAG_V5_UPLOAD=PASS / UPLOAD_RC=0。
这仅证明该次创建与上传成功；远端哈希复核、tools发布及audit尚待执行。

用户随后回传四文件staging与tools双重SHA校验全部OK，tools中文件权限600，
根下五个子目录权限700，.upload-staging已移除；输出
REMOTE_DIAG_V5_TOOLS_PUBLISHED=PASS / PUBLISH_RC=0。
此为新诊断v5工具发布成功证据，不是模型结果发布。下一步仅audit-inputs，
尚无新freeze或GPU作业证据。

### 后续用户回传：v5 输入通过、Job 670830 失败

用户随后完成真实 audit、freeze、check-only，诊断 freeze SHA 为
`739f1b899e3aff02305c9038c98d5946bb45fa66979dd5ac3887b504e4babff8`。
单次提交 Job 670830 成功；作业在 spcc-a100g10 上 13 秒后 FAILED / 2:0。
失败结果复验返回 DIAGNOSTIC_FAILURE_RECORDED，错误是外部原评估 v4 清单
被紧凑 JSON 读取器误拒绝，尚未执行模型数值比较。
用户同意后在新本地诊断 v6 修复；本 v5 发布包保持不变。
完整原因、证据 SHA 和本地验收见
[v6 修复记录](2026-09-08-diagnostic-v6-json-boundary-repair.md)。
