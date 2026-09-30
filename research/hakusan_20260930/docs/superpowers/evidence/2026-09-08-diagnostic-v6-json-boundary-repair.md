# 诊断 v6：Job 670830 外部 JSON 读取边界修复

## 授权、范围与状态

用户回传诊断 v5 的失败验证结果后，明确同意开始本地修复。本记录先于修改
生产代码创建。新候选目录为 `same_bank_eval_2026_09_03_v4_numeric_diag_v6`。
保留已发布诊断 v5、原冻结评估 v4、Job 670830 及所有失败证据；本轮不连接
集群、不上传、不重新冻结、不提交 GPU 作业，不修改模型、bank、SNR 或容差。

当前状态：本地有界修复、RED→GREEN、465 项回归与候选清单验证完成。
同日主代理发布前有界复核完成，见
[发布前复核记录](2026-09-08-diagnostic-v6-prepublication-review.md)。
没有新的独立代理审查或集群验收；尚未上传或提交 v6。GPU 数值原因与最终
三模型 10k 对比仍未完成。

## 用户回传的远端事实（非本代理直接读取集群）

- v5 audit-inputs、freeze-inputs、check-only 依次通过。
- 诊断 freeze：`739f1b899e3aff02305c9038c98d5946bb45fa66979dd5ac3887b504e4babff8`。
- 诊断协议：`formal40_batch_invariance_diag_20260903_v5`；32 trials、24 pinned records。
- 单次提交 Job `670830` 成功，随后 Slurm `FAILED`、`2:0`、用时 13 秒，节点
  `spcc-a100g10`。
- verify-results 返回 `DIAGNOSTIC_FAILURE_RECORDED`、退出 2、
  `results_verified=false`、`numeric_results_interpretable=false`。
- primary_error/execution 与 post_errors/post_inputs 均报：
  `noncanonical owner JSON: /home/s2510040/audattn_external_eval/same_bank_2026-08-29_v4/input_freeze.json`。
- `INVALID_BOUND_INPUT_CHANGED` 是该异常处理阶段的通用代码，单凭此代码不能
  推断文件内容改变；格式检查在预期 SHA 比较之前已拒绝输入。
- 回传 attempt inventory 仅列 ENVIRONMENT.json、POSTCHECK.json，未进入模型比较。

| 证据 | SHA-256 |
| --- | --- |
| DIAGNOSTIC_FAILED.json | `3d62296b7bec692803e2966f3d14466061b5dfd113608eacd8c931a72417a2e7` |
| artifact inventory | `4a469781f268f4c4f48d8ce66de864665f6318b63ae5552c1b6f5fbbe783d1a4` |
| audattn_v4_numdiag_670830.log | `1a60affff3093ba730a376b9875f0433263c2dc269cc50035e6a9365b2468311` |
| SUBMISSION_RECEIPT.json | `5aa61d8399f347f8a7d0935beb7b9885e1b6a0d073f2edcc6d0feedf19e33216` |

## 已核对的原因

本地冻结评估器 SHA 与已发布 v4 一致：
`31399fdf63233023d0d4047a5a9ec4f9d4e77f821831e75a52ef8f5e1ec803c4`。
其 canonical_json_bytes 使用 `indent=2`、UTF-8、末尾换行。
诊断 v5 `_owner_read_json` 却要求紧凑 JSON 序列化后的字节完全相同。
它被错误地用于三个外部 v4 清单读取位置：owner.inputs、owner.matrix、
成功结果复验 `_verify_complete_attempt`。audit/check-only 的外部读取路径不作
同样的紧凑格式要求，故前置检查通过不能覆盖这个执行期缺陷。

最小复现提取了真实序列化与读取函数，使用内存 I/O 替身：相同 JSON 对象、
正确哈希、v4 原格式可被 audit reader 接受，但被 owner reader 拒绝；诊断紧凑
格式对照通过。该复现没有改写源文件或清单，不是 GPU 或完整模型测试。

测试遗漏：CoordinatorFileOwnerTests 将模拟 v4 清单写成了诊断紧凑格式，
而不是生产 v4 的格式。新回归必须在文件系统夹具和协调器/结果验证链路中覆盖
真实 v4 序列化规则，不能仅测试 json.loads 或模拟成功返回。

## 修复验收要求

1. 先以真实 v4 格式复现旧读取路径失败，保存 RED 结果。
2. 外部 v4 清单使用专用、固定路径与原始字节 SHA 绑定的格式校验入口；
   诊断自身 journal/terminal/freeze 继续严格紧凑格式，不增加全局放宽开关。
3. 覆盖 PRE、matrix 和成功结果复验三处调用，拒绝错误 SHA、路径/符号链接、
   非规范 v4 格式、重复键、非有限数等；原文件不得被重排或改写。
4. 运行新回归、全部独立测试入口、静态检查和候选 SHA 校验；记录实际范围与限制。
5. 本地测试不能证明完整 A100 执行成功，也不能解释 Job 646900 的 NLL 差异。

## 实施与 RED → GREEN

- 先逐文件复制 v5 到新的 v6 本地目录；复制前后的九文件 v5 清单均校验通过。
  没有覆盖任何旧版本，也没有将缓存目录复制进候选。
- 修改测试夹具，提取 SHA 核验过的真实冻结 v4 `canonical_json_bytes` 函数，
  以其输出构建文件系统夹具。保持复制后的生产逻辑不变时，三个既有链路回归
  全部失败：PRE 输入与 matrix 入口各一个同源异常，CPU 完成/复验链路一个
  失败断言；0.175 秒，退出 1。日志为 `v6-json-boundary-red.log`。
- 增加 `_read_v4_manifest(contract)`，只从合同根的固定 `input_freeze.json`
  读取，保留目录/文件描述符及单链接身份检查；先核对原始字节 SHA，再检查
  JSON 对象与真实 v4 保存格式的一致性。没有 `allow_noncanonical` 全局开关，
  没有回写、重排文件或重新设定可信哈希。
- owner.inputs（PRE/POST）、owner.matrix 和成功结果复验改用此专用入口。
  `_owner_read_json`、audit 的通用读取器及所有数值计算函数未修改。
- 同样三个回归修复后通过，2.879 秒；新增边界测试最终 21/21 通过。
  一个新测试最初用不完整 matrix 替身尝试发布成功，被既有终态验证器正确拒绝；
  已改为真实持久化 CPU 矩阵夹具，未放松终态验证。
- 诊断根、协议、runner 和 submitter 的身份升级为 v6；原评估 v4 合同不变。

## 最终校验结果

本地 Python 3.11.15 / PyTorch 2.12.1。每个测试入口使用独立 Python 进程；
主测试与提交测试并行，但不合并 discover、不共享模拟模块注册表。

| 检查 | 结果 |
| --- | --- |
| test_numeric_diag.py | 344/344，95.842 秒 |
| test_submit_numeric_diag.py | 66/66，10.594 秒 |
| test_loader_record.py | 6/6，0.328 秒 |
| test_real_evaluator_scope.py | 28/28，1.213 秒 |
| test_v4_manifest_json.py | 21/21，5.905 秒 |
| 合计 | 465 项通过，不重复计算 focused 重跑 |
| Ruff check / format check | 通过 |
| runner bash -n | 通过 |
| freeze-inputs、check-only、submit 帮助入口 | 通过；没有执行这些真实动作 |
| README 九文件 SHA / 外部十文件候选清单 | 全部通过 |
| 已发布 v5 九文件清单 | 全部通过，未改 |
| 原冻结评估 v4 evaluator / runner SHA | 与已固定值一致 |

静态 AST 差异复核：除新增专用读取器、两项诊断版本常量、owner 的 inputs/matrix
和成功结果复验函数外，原诊断的所有顶层函数、类及赋值均一致；owner 其余
方法一致。submitter 和 runner 仅更新诊断版本字符串。numeric_trace、提交测试、
loader 测试、真实 evaluator 作用域测试字节不变。此项由主代理自查完成，
不是独立审查结论。

完整测试日志及候选清单位于：
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/`。

| v6 生产候选 | SHA-256 |
| --- | --- |
| diagnose_batch_invariance.py | `459613c3e9ca701bde52f5f4aea6d6190a032f6d869431a2860f3c86467a6dd9` |
| numeric_trace.py | `fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b` |
| submit_numeric_diag.py | `890f2c05f3982d3a53a526b3f07634ea2f811101865d83652431bd3cb94cd6b3` |
| run_numeric_diag.sbatch | `33232a2d085bb7dcdd1d11dc9cf34646bbc9042b9f868dcbabfe122bd5c05d29` |
| README.md | `e369d1b6edbecf0ca3fff27ac04fb43aa142e79cf47d589753c46806d0f61d5b` |

## 后续与限制

下一步先复核 v6 候选，再按批准流程检查远端新根、部署、audit、生成新的
诊断 freeze、人工核对其 SHA、check-only 和单次提交。不能复用 v5 诊断 freeze
的 SHA，不能覆盖 v5 或重提 Job 670830。本轮未执行任何远端动作。

回归覆盖的是实际 JSON 格式、真实文件系统 owner、持久化 CPU 合成矩阵及
只读结果复验，不是实际 checkpoint/音频和 A100 内核。原 0.0077362060546875
NLL 差异尚待诊断，不能宣称已修复数值问题或得到作者模型对比结论。
