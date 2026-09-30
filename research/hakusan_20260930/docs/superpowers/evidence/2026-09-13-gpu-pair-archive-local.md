# GPU冷对照归档组件：本地验证记录

2026-09-13，继续用户“下一步”。本轮只做本地实现、测试与文档；无SSH、上传、
freeze或Slurm提交。不是最终模型比较结果，也不是完整GPU部署包已完成。

新增[候选目录](../prototypes/targeted_gpu_pair_20260913/README.md)，
补齐原两轮输出导出和独立按字节核验。此前CUDA准备候选只返回摘要，
不能直接用两个PASS证明观测无干扰；新组件保存两进程共80份原生端点数组，
并保留原pass校验文档。原v18和此前21项源/输入清单都仍保持原SHA。

## 成功回执

[receipt.json](gpu-pair-archive-local-20260913T061730Z-r_rdxexp/receipt.json)
及[完整日志](gpu-pair-archive-local-20260913T061730Z-r_rdxexp/output.log)：

- `LOCAL_GPU_PAIR_ARCHIVE_CANDIDATE_VERIFIED`，rc0，38 tests、0 skips。
- 独立测试进程PID12417；Python3.11.15、torch2.12.1；17.817秒。
- 30份源/输入，前后SHA一致；manifest SHA
  `b0225a084b3c1e074d4650546cfb04a34cd5f84f9c05cdb62a11e6dea78b6634`。
- output.log：4225B，SHA `3a320ceb2367d929c032ef04d03581aee17553c2647a6fc287ea5a5a320588d0`。
- child-result.json：459B，SHA `df8cef327e46f2c4ff79758ec691183e3991f4825bb50639b73015b5619dc286`。
- Ruff检查通过。CUDA未初始化、真实checkpoint未加载、jobs_submitted=0。

覆盖内容：完整数组/每条样本摘要、两新进程绑定、父合同固定SHA、非连续多分块、
FP16/32/64/int64/bool原生格式、预算先于复制、NaN拒绝、错序/改名/改SHA/
改形状/改dtype/缺失/额外文件/软链接/硬链接/FIFO/权限改变拒绝，失败保留部分文件。

通过原v18合成CPU工作流程实际执行一模型34批16→1；原父结果gate通过，
40份归档数组重新读取一致，两轮原文档经原decode_pass_evidence解码成功。
**其scratch是测试替身；没有真实mmap、CUDA、Inductor或生产执行验证。**
新CUDA归档包装仅做AST精确还原检查，没有借用CPU结果宣称GPU成功。

## 开发时发现并修正

初始本地终端测试发现：FP16测试数据超过其有限范围、预算反例先触发了维度限制、
`-I`子进程缺少显式本地模块路径。这些均修正测试夹具，未放松数值或安全检查。
额外原v18集成测试还发现新包装器把只允许关键字的`scratch`当位置参数传入；
已修正为`scratch=scratch`，随后集成测试及完整38项打包测试通过。
上述开发失败见本轮执行记录；此文件没有把终端输出伪装成此前已落盘的失败日志。

## 明确的下一项

完成计算节点双进程coordinator、原执行来源/状态/RNG检查、168份中间采集归档、
超时与资源审核、单次提交和本地完整回传验收。当前没有可执行的新GPU提交入口。
原来的成功/失败作业都不重复提交。本轮不声称修复了批大小数值差异，
不声称拿到了formal40/valbest33/作者checkpoint的最终比较。
