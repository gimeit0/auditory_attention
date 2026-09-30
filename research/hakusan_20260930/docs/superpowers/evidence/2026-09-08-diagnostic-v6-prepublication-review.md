# 诊断 v6 发布前有界复核

日期：2026-09-08。对象：`same_bank_eval_2026_09_03_v4_numeric_diag_v6`。
本次由主代理进行本地复核，不是独立代理审查；没有修改候选十文件、上传、
远端目录创建、freeze 或 Slurm 提交。只新增复核证据并更新进度文档。

## 结论与范围

在 Job 670830 所暴露的外部 v4 JSON 读取边界修复范围内，未发现新的阻塞项。
可以继续远端只读预检；本结论不等于实际 A100 执行成功，也不解释 Job 646900
的 NLL 差异。v6 尚无远端验收、GPU 结果或三模型完整 10k 比较结论。

检查三个专用清单读取入口：owner.inputs（PRE/POST）、owner.matrix、
成功结果复验 `_verify_complete_attempt`。扫描其余 `input_freeze.json` 和
`_owner_read_json` 使用点，未发现另一处把外部 v4 清单送入紧凑 owner reader
的路径。audit/check-only 原通用 SHA 读取路径保留；诊断自己的 freeze、journal
和工件仍由紧凑格式读取器校验。

新入口限定为合同根下 `input_freeze.json`，校验原始字节 SHA 后检查真实 v4
保存格式，不重写文件或重新设定可信 SHA。原 v4 序列化器与固定 evaluator SHA
已在回归夹具中绑定。既有有界 AST 差异记录表明数值函数、容差和 owner 其余
方法未改，submitter/runner 只作诊断版本迁移；本次复核前后候选 SHA 一致。

## 本次实际运行

| 检查 | 结果 |
| --- | --- |
| test_v4_manifest_json.py | 21/21，6.278 秒，退出 0 |
| test_real_evaluator_scope.py | 28/28，1.312 秒，退出 0 |
| 三入口分别恢复旧 v5 函数的内存回归探针 | 3/3 重现同一 noncanonical owner JSON 错误 |
| Ruff check / format | 通过，8 个 Python 文件已格式化 |
| runner bash -n | 通过 |
| v6 十文件候选 SHA | 复核前后均通过 |
| v5 九文件候选 SHA | 全部通过，未修改 |
| 原评估 v4 evaluator / runner SHA | 与固定值一致 |

三入口探针从保留的 v5 源码 AST 提取旧函数，在独立临时测试夹具中分别替换
inputs、matrix、成功结果复验函数。第三个探针先以当前 v6 完成真实持久化 CPU
合成矩阵和结果复验，再仅替换旧结果复验函数，因此不会由 PRE 失败掩盖遗漏。
替换只发生在内存，未编辑候选源码，也未运行真实 checkpoint 或 GPU。

Ruff 最初使用了不存在的 audattn 环境内路径，退出 127；随后通过 command -v
确认 `/opt/anaconda3/bin/ruff`，两个实际检查均退出 0。未安装或更改环境。

前一修复轮已完整运行 465 项回归；本次是其中 49 项针对性重跑和三入口探针，
不是新增 49 项覆盖，也没有再次声称重跑全部 465 项。原完整记录参见
[v6 修复记录](2026-09-08-diagnostic-v6-json-boundary-repair.md)。
本次原始输出及探针命令保存在
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v6-prepublication-checks.log`。

## 固定候选与后续

候选清单仍为 `v6-candidate-manifest.sha256`，没有重生成：

- diagnostic：`459613c3e9ca701bde52f5f4aea6d6190a032f6d869431a2860f3c86467a6dd9`
- trace：`fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b`
- submitter：`890f2c05f3982d3a53a526b3f07634ea2f811101865d83652431bd3cb94cd6b3`
- runner：`33232a2d085bb7dcdd1d11dc9cf34646bbc9042b9f868dcbabfe122bd5c05d29`

下一项由用户在 HAKUSAN 登录终端进行只读预检：旧 v5 根保留、新 v6 根未占用、
原评估 v4 manifest/lock 的固定 SHA 仍匹配、相关作业队列为空。任何检查失败
都停止，不删除旧目录，不重提旧 Job 670830。预检通过后才进入新根部署流程。
v5 诊断 freeze SHA `739f1b…` 不可作为未来 v6 的 freeze SHA。

本地 Python 3.11.15 / torch 2.12.1 与集群 torch 2.1.1+cu118 不同；真实音频、
checkpoint、GPU 数值和跨节点执行仍需后续验收。旧候选的独立审查结论不自动
继承给本次 v6。
