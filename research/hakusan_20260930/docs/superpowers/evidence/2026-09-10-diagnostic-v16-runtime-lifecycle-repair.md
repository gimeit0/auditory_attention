# v16：获批编译初始化校验修复

2026-09-10用户批准[修复边界](2026-09-10-job683523-runtime-lifecycle-diagnosis.md)。
原v15 21文件、Job683523失败证据和全部科学输入保持；不重提旧作业。

执行顺序：补有界组件差异→检查真实2.1.1框架来源/读写用途→精确生命周期
实现与反例→全部旧回归→同版本真实CPU准备与合成冷/热forward→审核发布。
现阶段尚无新的GPU结果或完整三模型比较，未改变科学配置/容差/预算。

## 实施及本地验证（2026-09-10）

在独立v16实现；v15原21文件及665测试按版本归一化保持。新24项编译生命周期
反例、9项有界差异日志测试，加旧665项，完整18个独立测试入口共698项通过。
Ruff、两个CLI帮助、runner语法检查通过。AST范围检查证实原完整模型执行
指纹函数体及状态/导入/scene检查未更改；只新增作用域装饰器与明确生命周期
发行步骤，组合拒绝条件拆分后仍按相同顺序短路。五项故意退化均被测试捕获。

允许的不是任意内部状态变化：固定torch2.1.1+cu118三份已核验源码，固定
OptimizeContext/on_enter/实际编译回调、写计数函数代码/闭包/模块/对象身份，
只在相应完整模型指纹检查作用域下归一化两个指定全局绑定。最近后端只能
从None转为发行时的同一编译器对象；进入后复位None、替换后端/上下文/代码/
闭包/计数字典/工厂均拒绝。计数结构类型、大小、键/非负整数值有界；不是
全局忽略counters。发行凭据防字段重绑定、失败后撤销，不通过首次forward
后的重新封存接受未知变动。异常只附组件、数字索引路径、差异种类（最多6项），
不输出模型/环境值或对象repr。

## 同版本真实环境复验

最终评估器SHA `e776d9917ecad3da529d311d536de89d90121d23bceb2cefe9fdadc7450609ec`：

- HAKUSAN torch2.1.1+cu118、单CPU线程、8元素合成模型，eager及Inductor分别
  完成两次forward；输出精确相等，完整执行指纹保持，强制替换后端被拒绝。
  都不是科研模型/GPU推理，不证明原NLL问题已解决。
- 真实formal40 CPU准备复验：24pinned、96snapshot来源复查通过；严格61键加载、
  70模块、60唯一状态条目；发行且复查1个编译上下文，未调用其forward；
  3个scene/9个model callable、71执行记录、19导入绑定检查通过。
  work=494024，仍低于原600000；重复执行图/权重/RNG/scene及源文件保持。
  最终 `FORMAL40_CPU_STATE_SEAL_PROBE_PASS`、`REMOTE_CPU_PROBE_RC=0`。

PyTorch源码SHA（来自实际安装包）：eval_frame
`a98df135208704b66f681646a3d9649b75cbe5a3093fc59e4650b44460c1921b`；
convert_frame `ec2e8c5cab884d7125192b706361e8c0e957f7f8b1298ab065824e875ecb0b`；
utils `0ef5253850c17c71ee002dc2aae12f7285da5e327a433d52232ad8f386c1787f`。

## 固定候选与下一门禁

23文件候选清单：`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v16-candidate-manifest.sha256`，
清单SHA `b8dd965e688ea8d2452a14cf831985e342969927e66363377eaaff1c6582bf15`。
辅助复验入口在同目录 `2026-09-10-diagnostic-v16-{local-review,test-runner,remote-cpu-probe,cpu-lifecycle-probe}.py`。
下一步按固定清单在独立v16发布、audit/freeze，核对新freeze再check-only，
全部通过后单次提交诊断。原v15 Job683523及原v4不改、不重提。
当前仅工程检查通过，不是科研提交完成；矩阵、smoke、10k对比和CI仍待验收。

## 实际GPU终态

单次Job683649在冷参考两pass后的工件发布路径失败，FAILED2:0（47分26秒）。
本次失败链不再是原组合执行图拒绝，而是普通0600单链接文件校验；没有完整
参考完成标记或诊断矩阵，验收仍为不可解释数值。原始六文件已逐SHA保留。
独立小文件在home上复现原writer错误，并验证了固定final FD的控制顺序。
这不等于完整生产发布修复完成，未改本候选/原证据，也未重提。
详见[发布问题与下一步范围](2026-09-10-job683649-publication-diagnosis.md)。
