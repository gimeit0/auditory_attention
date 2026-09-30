# Job715276后续：原v18检查开销的有界CPU定位

2026-09-15 JST。完成本地测量和离线复核；没有连接超算、修改冻结运行包、
修改模型/阈值、扩大运行时限或提交作业。本次是性能诊断，不是新的科研数值验收。

## 结论与证据边界

**重复的运行时身份/模块绑定检查确实随小batch显著放大。**
原样执行v18的合成B2 fixture，32条固定合成样本先batch=16、再batch=1：
完整身份检查从45次增至675次，15倍；启用一个最小合成模块的原始
`_SnapshotLoader`后，前后模块扫描从3060次增至45900次。

这与Job715276在batch=1中超时、40分钟的一次栈样本位于模块绑定检查相吻合，
支持优先优化这条检查调用链。**尚不能证明真实作业全部时间都耗在这里，
也不能把本地时间外推为A100完成时间。** 没有获得真实作业逐函数完整profile，
不能据此认定模型数值有错或GPU硬件故障。

## 测量设计

- Python3.11.15 / torch2.12.1，Mac本地CPU单线程；不同于HAKUSAN的3.11.5 / 2.1.1。
- 三个新进程PID47371、47375、47381，每个上限120秒，整体上限300秒。
  全部完成，监督器记录总耗时71.30秒，无超时/重试。
- 原v18和原CPU fixture均按已发布SHA读取；58份v4发布来源在前后均校验一致。
- 三种场景：原fixture不剖析、原fixture启用cProfile、启用cProfile并添加最小合成导入绑定。
  原fixture没有生产导入权限，不能悄悄把它称作生产模块检查；第三种场景专门覆盖原方法。
- 第三种仅安装一个独立的合成模块和原`_SnapshotLoader`实例，调用原方法；
  没有替换guard函数、编译器、模型调用或已有模块，没有加载真实snapshot或权重。
- 每个进程严格加载一次合成模型并调用34次，原批次顺序为2个16和32个1。
- 三个进程对应两轮的官方输出、记录的粗粒度/派生边界摘要、批次守卫内容摘要完全一致。
  这是合成场景下的非干扰证据，不是实际模型hook非干扰验收。

## 调用计数

以下是第三种场景；第二种的身份/图遍历次数相同，但没有活动loader，绑定扫描为0。

| 原函数 | batch=16：2批 | batch=1：32批 |
| --- | ---: | ---: |
| `trace_predict_batch` | 2 | 32 |
| `_live_inference_attestation` | 45 | 675 |
| `_model_execution_fingerprint` | 45 | 675 |
| `_callable_graph_fingerprint` | 1530 | 22950 |
| `verify_runtime_bindings` | 1530 | 22950 |
| `_live_protected_module_bindings` | 3060 | 45900 |

本次fixture计数满足：完整身份检查`3 + 21 × 批数`；每次对应34次可调用图检查；
每次图检查调用一次导入绑定校验，而绑定校验分别扫描前后两次。
这是本次冻结fixture的实测关系，不能将34当作真实formal40模型的固定常数。

原代码对应位置：

- v18 `run_trace_pass`（5740行起）：按batch执行raw/preprocess/model及前后guard。
- `_callable_graph_fingerprint`（1761行起）：每次进入先调用`_verify_active_import_authority`。
- `_SnapshotLoader.verify_runtime_bindings`（3531行起）：两次实时模块扫描及可调用对象核验。
- `_live_protected_module_bindings`（3401行起）：每次重新枚举模块名、校验名称类型、建立集合并筛选。

## 时间——仅作本地诊断

| 场景 | batch=16墙钟 | batch=1墙钟 |
| --- | ---: | ---: |
| 原fixture，不开cProfile | 0.389秒 | 4.647秒 |
| 原fixture，开cProfile | 1.304秒 | 18.692秒 |
| 最小合成loader，开cProfile | 2.562秒 | 38.110秒 |

cProfile本身引入明显开销；不能把剖析时间当作未剖析性能。
第三种batch=1的`verify_runtime_bindings`累积时间19.013秒，
其中模块扫描累积18.444秒；这些时间是嵌套关系，**不可相加**。
完整身份检查累计37.912秒，包含这些子调用。
这里的绑定集合只有一个合成模块，结束时模块注册表2248项；不是生产模块集合。

## 检查与修正的边界

原有绑定扫描5项、模块名称分类13项反例/正例测试通过，覆盖扫描期间新增、替换、删除模块、
函数默认值修改、名称类型异常、允许的非保护模块变化等。
这18项是原实现的回归基线，不是尚未编写的优化候选已经通过。

执行测试调度时，第一次第二组命令的参数下标写错，未开始分类测试；
失败回执保留。修正测试调用参数后单独执行13项，全部通过。
没有把首次聚合失败回执计作全部通过；5项取首次实际成功的第一组，13项取修正后的独立进程。

下一项为**独立候选中的检查链性能修正及对照测试**：

1. 优先处理重复模块遍历/内部数据构造，明确哪些工作可在同一次检查内复用。
2. 保留每个推理算子的前后检查、实时对象读取和异常拒绝；不缓存跨算子的“检查通过”结论。
3. 任何合并/复用必须证明不会漏掉检查期间的绑定、函数、状态或输入变化；
   重放上述反例并增加新缓存失效反例，再用同一测量驱动比较性能和结果。
4. 本地通过后进行HAKUSAN同版本的有界CPU复验；真实GPU验收需另行确认资源范围。

本轮**未实施该性能修正**，不更新原发布清单、不重提715276，也不发布最终模型比较指标。

## 可复核工件

- [测量脚本](2026-09-15-guard-cpu-profile.py)
- [测量原始回执、三组结果和日志](guard-cpu-profile-20260914T162903Z-id_7igm_/receipt.json)
- [离线一致性核验脚本](2026-09-15-guard-profile-review.py)
- [原绑定测试及保留的调度失败回执](guard-binding-regression-rv_5s2q4/receipt.json)
- [修正调度后13项分类测试](guard-classification-regression-ixtkjifv/receipt.json)
- [真实作业失败/阶段证据](2026-09-15-job715276-result-check.md)

测量回执SHA256：`6783152fd9c65c6ebdebd9305a61278181b5c1daac6f67dabb547a4aff83f110`。
离线核验输出`PROFILE_EVIDENCE_RECHECK_PASS`；新GPU作业提交数0，`ready_for_gpu=false`。

仅重验已有本地证据的命令：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-15-guard-profile-review.py
```
