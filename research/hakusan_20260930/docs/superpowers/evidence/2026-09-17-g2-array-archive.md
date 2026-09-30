# G2数组归档与独立内容校验：实现及本地验证

前置：[Job721086已独立验收](2026-09-17-job721086-native-pair-verified.md)、
[生产流程接线候选](2026-09-17-g2-production-lifetime.md)。本轮无SSH、上传、freeze或新调度提交。

## 本轮实际完成

新增独立[归档候选目录](../prototypes/g2_archive_20260917/README.md)。
真实推理仍由原bridge完成；新Consumer只保存已采集的CPU数组，返回ProductionCell所需回执。
旧writer/reader按固定源SHA复用，仅在私有副本调整绑定schema及真实feature所需文件容量。
40份数组逐块保存，独立重读全部字节/逐trial哈希并核对原pass承诺。
从已验official输出重算16/1的差异及1e-6判定，不把旧B2数值当新设置的输出oracle。
旧模型、旧freeze、原诊断代码、既有lifetime、数值标准均未修改。

## 最终结果

证据目录：[g2-archive-local-20260917T034258Z-47rh9pu7](g2-archive-local-20260917T034258Z-47rh9pu7/)。

- 27项内容/拒绝测试，0失败、0错误、0跳过。
- D与E两独立冷进程，各合成32条、34次forward、4份特征mmap、40份保存数组。
- 写入后原gate检查有效、RNG未变化、原清理通过；没有重复forward。
- 另两个冷进程，各复核40份文件、1280个逐trial哈希，原无损official编码和重新计算的数值摘要一致。
- 五阶段总26.835秒；45秒/child、120秒五阶段上限；最终复查另有每profile30秒上限。
- 27份来源快照；`REVIEW.json`记录最终复查通过；之后再次只读复查通过。
- 每组实际数组425,280字节。本轮没有真实大数组吞吐或峰值内存测量。

固定SHA：

- `pass_store.py`：`1b21505669bbc29b9072548f0134f582b3a3534cb7109e5a7b41e04e4dbc6a10`。
- `VALIDATION.json`：`6b1b4c4bc4c448ccf116a74a072c916c283f21636836fe9759fca2615c8ec332`。
- `REVIEW.json`：`67d5dd8ec1599d3459add28b2a46264f490e4ddd1fd17efcd64ab518c8833ebf`。

## 保留的初次失败

[初次证据](g2-archive-local-20260917T034149Z-eguw0sh_/)中五个child和27项测试均通过，
但最终主进程顺序复查D、E时触发原loader的 `module name already loaded: _numeric_trace_verified`。
该目录的`VALIDATION.json`只记录五阶段结果，**不代表最终复查通过**；没有`REVIEW.json`成功记录。
没有修改旧记录。修正为每profile新的只读解释器，不卸载/修改原加载器保护；最终运行另建目录。
新增复查失败持久记录，避免以后把子阶段通过误认为整轮完成。

## 不能扩大的结论及下一项

这是本机合成CPU和实际文件读写验证；Linux-mount使用已披露stub。
不是完整ProductionCell真实路径、真实checkpoint、原生R/C编译或A100验证。
内容校验器不认证调度/进程来源、不验证全部生产模型保护链或跟踪干扰，仍明确保留
`execution_authority_verified=false`、`independent_results_verified=false`、`ready_for_gpu=false`。

下一项为有界新生产运行器/coordinator及发布清单、新freeze绑定，再按G2规格完成资源审批和真实32条验证。
不重复Job721086，不重启旧失败诊断，不扩大容差，不更改冻结10k或checkpoint。
正式三模型10k/controls和最终统计报告仍未完成。
