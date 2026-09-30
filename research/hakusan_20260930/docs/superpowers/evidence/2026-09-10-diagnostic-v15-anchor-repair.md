# v15 不可变 anchor 复用与科研验收记录

用户2026-09-10要求修正到科研提交状态，授权继续原预算下的工程优化。
原v4科学合同、v13失败作业683154、未通过CPU门禁的v14全部保留。
本记录不是最终数值诊断或三模型10k实验结果。

## 实现与本地回归

- v14原20文件逐SHA保持；旧645项只递增版本路径，新20项，合计665项通过。
- `_SealBudget`仅增加同次强引用anchor字典；所有预算上限未改。
- `_callable_anchor`每次读self/function/code/defaults/kwdefaults绑定，只有
  无kwdict且默认值为None或已证明精确不可变标量/tuple树才可复用记录。
- `_default_anchor_identity`扩大不可变证明到嵌套精确tuple；实际记录仍由
  原container函数构造，保留别名/循环、深度和子类拒绝行为。可变内容不缓存。
- loader/live绑定、闭包、globals、hook、模型/张量状态检查及所有科学代码
  AST保持不变；trace、submitter、runner仅版本字符串变更。
- 七项内存退化被测试捕获：删除复用、忽略code/defaults/kwdict/可变值/
  callable默认值变化，以及错误跨检查缓存。Ruff、bash -n、两CLI help通过。

本地环境Python3.11.15、torch2.12.1 CPU。不是独立代理评审。

## 实际 torch2.1.1+cu118 / formal40 CPU

通过既有认证master49656运行受SHA绑定的临时CPU探针；原输入只读、共享
evaluation lock、/tmp私有源码与缓存，未改HOME或生产工具，无forward/sbatch。
未提高原240秒CPU探针时限或600000执行校验预算。

- 固定环境三个值及/usr/sbin/ldconfig解析PASS，后者不等同GPU驱动验收。
- 24 pinned records、96 snapshot files读入并验源。
- 严格加载61 state keys，训练参数覆盖1.0，70执行模块。
- 原10个唯一已签发缺失模块恢复；现有绑定不替换，不重新执行源码。
- 60个唯一参数/buffer内容快照、scene3/model9 callable图PASS。
- 完整执行指纹71 records PASS；work=494021，unique callable nodes=230，
  code cache=110，immutable default cache=36，低于600000原上限。
- 19个导入绑定封存后重复执行指纹、scene/model图、60项状态、RNG均PASS。
- 原snapshot/pinned输入前后复验PASS；`FORMAL40_CPU_STATE_SEAL_PROBE_PASS`，
  `REMOTE_CPU_PROBE_RC=0`。没有GPU数值结果，不能将其记为production worker通过。

## 固定本地候选与检查入口

包：`same_bank_eval_2026_09_03_v4_numeric_diag_v15`（21文件）。
candidate manifest SHA：`d2f61015d5275f6ee50be70c40a90d54d198a10194d91150ca42b1cc063c6337`。

| 文件 | SHA256 |
|---|---|
| diagnose_batch_invariance.py | 993d89b6c97f706cb7bc1e1f6dc8b27d2c608e7866fb5b4cbef316ddcb389cca |
| numeric_trace.py | fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b |
| submit_numeric_diag.py | 9c21049a380756ee93c6dad226890988338d05560f5a747a21f3ff28ba966870 |
| run_numeric_diag.sbatch | d54e69d262099147ca222ef556a484eb414e5224901fadc8d5ba13b71ad1a0f9 |

外部检查入口同目录：
`2026-09-10-diagnostic-v15-test-runner.py`、`...-local-review.py`、
`...-remote-cpu-probe.py`。后者SHA
`a96ab47141b4134497a3f5564e9b5d8bc940a8b14980be5e0eefb059ee6ecdee`。
独立`--synthetic-only`进程测试跨模块CPU Dynamo；不在实际模型探针之前
预热编译缓存，也不使用该合成结果替代GPU科学推理。
实测该独立进程亦PASS：恢复4个原模块对象，CPU Dynamo graph.forward的8元素
合成输出正确，封存后模块变化0；`SYNTHETIC_IMPORT_CPU_PROBE_PASS`、RC0。

实际受控创建/上传、四文件SHA发布已通过（UPLOAD_RC=0、PUBLISH_RC=0）。
仅移除已核验的staging硬链接及空staging目录，四份同一数据保留在新tools中。
未删除旧版或旧证据。新audit/freeze/check-only均通过，唯一Job683523已提交。
新freeze及原始回执见[v15部署记录](2026-09-10-diagnostic-v15-remote-deployment.md)。

上述发布与唯一GPU诊断已实际执行；Job683523终态FAILED2:0，完整既定矩阵
未取得。只读验收与五份原始工件已归档，不能再运行本版提交入口。
最新阻塞是参考预测正常返回后的组合执行校验拒绝。合成同版本CPU对照
复现了正常Dynamo首次初始化导致完整模型指纹变化，但不等同实际GPU的
全部根因；见[实测与待审批边界](2026-09-10-job683523-runtime-lifecycle-diagnosis.md)。
仍须验收完整既定矩阵后再判断原批大小NLL问题。若需精度/TF32/compile/数值阈值改变，
先另行报告证据和方案，不自动放宽或重基线化。最终结果标签仍为复用验证bank。
