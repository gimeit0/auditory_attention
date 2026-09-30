# 低α扫描v2：修正候选验收

日期：2026-09-28。最新续接19:07 JST：**v2上传、41文件哈希/包核验和原生只读源码导入预检均已通过，未获新GPU授权或提交**；未加载checkpoint、未初始化CUDA。见[上传回执](upload-v2-reviewed-job-once/RESULT.json)、[原生预检回执](source-check-v2-once/RESULT.json)及[当前台账](REMOTE_PROGRESS.md)。下面为本地候选验收及此前阶段的历史记录，不改写原LOCAL_ACCEPTANCE.json。

16:53 JST后续：用户已批准上传及哈希/包核验；单次调用被运行中作业754073触发的队列保护拦截，发生在远端文件写入之前。没有自动重试或提交，见[上传台账](REMOTE_PROGRESS.md)。本文件以下本地验收和原生CPU记录保留原时点口径。

## 身份

- release SHA：`a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0`。
- [package/RELEASE.json](package/RELEASE.json)：40个清单文件，另加RELEASE自身共41个文件。
- 新远端目标：`/home/s2510040/audattn_fine_alpha/fine_alpha_20260928_v2`；本地验收时尚未发布，后续18:33 JST已成功发布至其`package`子目录。
- α网格/公式、formal40 checkpoint、数据和批布局、194,400条科学预测/219,600条总预测、A100/8CPU/64GiB/6小时候选上限不变。新版本不继承753729的审批。

## 修正与证据

1. 已是字符串的TorchVersion在环境采集边界转为普通str；错误类型不泛化转换，严格验收不放宽。
2. 实际worker在加载session进入后、第一次forward前检查环境和运行设置，保存预检记录；推理结束重采环境检查漂移；最终独立重读按SHA和job/PID/release等绑定预检文件。
3. 新增19项回归；全目录 **453项通过，58.061秒**，没有跳过项。见[regression.log](regression.log)、[regression.json](regression.json)、[LOCAL_ACCEPTANCE.json](LOCAL_ACCEPTANCE.json)。测试含真实TorchVersion producer直连validator、坏值拒绝、worker接缝、失败/漂移、预检破坏与终态查询回退。
4. [隔离包检查](package-check.log)及runner语法检查通过。5个历史冻结包的174个文件前后哈希一致：[LEGACY_BEFORE.json](LEGACY_BEFORE.json)、[LEGACY_AFTER.json](LEGACY_AFTER.json)。
5. v1→v2仅5个包内文件不同：`e1_worker_archive.py`、`fine_alpha_archive.py`、`fine_alpha_contract.py`、`fine_alpha_entry.py`、生成的`run_fine_alpha.sbatch`。合同仅scope从V1变V2，科学内容和预算不变。

## 原生CPU复核（与本地阶段分开记账）

[native-cpu-hhstvw6w/RESULT.json](native-cpu-hhstvw6w/RESULT.json)返回`FINE_ALPHA_V2_NATIVE_CPU_TYPE_CHECK_PASS_NOT_GPU_VALIDATED`。

- 使用现有SSH连接，单次、最长90秒，无自动重连/重试。
- HAKUSAN Python 3.11.5、torch 2.1.1+cu118；原始版本类型确为TorchVersion，修正后记录类型为str。直接内存验收和JSON往返验收均通过；4类非法版本拒绝；CPU记录不能通过生产GPU验收。
- 函数和环境schema来自本候选3个文件的哈希绑定源码，在内存中只执行选定定义。没有上传生产包、写远端源码、加载checkpoint、进行forward、初始化CUDA或提交作业。
- **不是整个生产worker导入测试，也不是A100验证。** 本地LOCAL_ACCEPTANCE.json的network_access=false仅描述先前本地准备阶段；本次CPU检查确实使用了SSH，记录单独保存。

## 下一步及权限

绑定v2的原生只读导入预检已完成；GPU预算/提交/放行尚未获批。冻结提交器仍有按`audattn`名称阻止并发的旧规则，实际提交前需明确是等待队列条件满足，还是修正并生成新冻结身份，见[当前台账](REMOTE_PROGRESS.md)。以下为本地交付时列出的后续步骤，其中“准备驱动、上传与哈希核验、原生只读导入”现已完成：

本轮修正范围已完成。下一步是准备绑定本v2 SHA的发布驱动，并在批准后上传独立目录、逐文件核验及原生只读导入检查。之后需要新的GPU预算/单次held提交授权，资源核验后单独批准放行。旧v1上传/提交/修正/放行脚本不可用于v2。

失败作业753729和旧冻结包保持原样；不续写旧attempt，不将126份部分数组补标为通过。新作业尚未存在，不自动重投，也没有新科学曲线。

只读本地复查命令：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  "$HOME/发表/超算/alpha_mechanism_local_20260923/release_fine_alpha_20260928_candidate_v2/package/fine_alpha_entry.py" \
  check a7a2f6307159af72a1906a153d07d8797c770de71037e24b382a873a9ed657e0
```

详细根因和后续门槛：[47号修正记录](../47_FINE_ALPHA_PROVENANCE_FIX_20260928.md)。
