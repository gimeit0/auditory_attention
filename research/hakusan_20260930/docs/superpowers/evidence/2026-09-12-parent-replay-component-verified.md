# 2026-09-12：Job685198父数组重放核对组件，本地验收

状态：`LOCAL_PARENT_REPLAY_COMPONENT_PASS`。接续超算归档CPU验收；本次
新增的是独立本地数组匹配组件，不是新的生产worker、A100追踪或最终模型
比较。没有连接超算、上传源码、冻结输入或提交作业。

## 已执行

- 新增[组件、测试、驱动与限制](../prototypes/targeted_replay_20260912/README.md)。
- Python3.11.15/NumPy2.4.6执行36项单元测试，无失败、无跳过；未导入torch。
- 156项原始数组核对通过：4完整logits、128逐行logits、8单trial特征、
  16正式输出。这里不是156个独立样本；原实验仍为32条。
- 10个真实归档反例被拒绝：A2/B2两pass的尾部一个ULP改变、错pass绑定，
  以及两cell试图用局部证据提前完成完整重放。
- 父terminal/freeze/计划SHA固定；未修改的旧核验器在前后检查完整114份
  工件。CELL_INPUTS与BOUNDARY_DIGESTS重复内容一致。生成合同前后字节一致。
- 用另一个只读Python进程，不调用新匹配函数，逐一从原NPY/hex重算156项
  字节SHA，与回传检查记录一致；同时核对114份父文件、3份组件源码、3份
  新证据工件、最终回执。结果`INDEPENDENT_LOCAL_RECHECK_PASS`。
- Ruff通过；v18原28项release SHA、既有archive和stream源码SHA均通过。
  本轮未重跑v18的751项回归，不把SHA核对称为执行回归测试。

## 最终证据

以下为去除驱动未使用import后的最终源码运行，所有记录只写新目录。

- [36项单元测试原始日志](parent-replay-local-20260911T155226Z-rcw6ytm5/unit-tests.log)
- [父数组合同](parent-replay-local-20260911T155226Z-rcw6ytm5/PARENT_REPLAY_CONTRACT.json)
- [真实数组检查与反例](parent-replay-local-20260911T155226Z-rcw6ytm5/SAVED_ARRAY_CHECKS.json)
- [最终回执](parent-replay-local-20260911T155226Z-rcw6ytm5/receipt.json)

```text
contract 95e25bde17fa8358cd20f90c2edf27a94a4ffd6f49aab8bd9fa3395b6c7c7b34
checks   7f3ca24c1fe0ea4fe8c2e8cf50ca93c98117e26209943ab88ee03a1f8a5b410a
tests    1516c1cc09106b2933a9c00da78b2ec0f792923f957b7561c171f5002f137683
receipt  f53d9a165c8722de4dd6131f9dde6a6526cee8f565c2a0dca58538d5c2917384
```

较早的`parent-replay-local-20260911T155150Z-or6wek3w`是保留的开发运行，
虽同样通过，其驱动SHA不同；不作为最终源码验收，也不与最终运行累加用例。
UTC目录时间2026-09-11T15:52:26对应JST2026-09-12T00:52:26。

## 科学与工程边界

完整gate要求A2/B2各自原32条16→1全34批、16个边界及4个实际正式输出；
任何缺失/错序/重复/字节差异均拒绝。保留原AMP/TF32/编译设置和1e-6
canary容差。新组件的逐字节核对只是确认重放输入与父证据的身份条件，
不是把原科学canary改为另一个数值阈值；不匹配时必须另行诊断，不能忽略。

本轮**完整34批只做合成验证**；真实验证使用已有归档，既没有重建全部真实
输入，也没有生产forward。8份最差中间特征均为trial9000，不能冒充
4126/1428/2698的完整追踪。原记录没有stride，组件不声称原布局已证明；
调用者runtime标签比较也不等于独立运行时认证。成功回执明确：
`real_full_replay_verified=false`、`production_authority=false`、`ready_for_gpu=false`。

## 下一段工作

接入真实worker，使原32条输入、正式输出与这个合同核对，同时维持原来源、
参数/输入/RNG/实际运行标志检查。原v18的执行指纹覆盖hook及其闭包；不能
直接给已冻结实例加可变hook，也不能把原检查关闭或替换成“已验证”标记。
需要单独验证观测器的有界生命周期，再执行受控冷参考/观测对照。

接入及同版本检查通过后，才确认新A100作业的范围和预算。原685198授权
不能被当作无限新提交授权；本轮没有新增作业。批大小数值根因、三模型
smoke、10000条最终same-bank对比与统计报告均尚未完成。

结果角色仍为`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
