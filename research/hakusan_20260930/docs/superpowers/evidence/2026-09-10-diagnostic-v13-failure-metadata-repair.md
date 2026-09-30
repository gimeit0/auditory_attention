# v13：只补充失败元数据

2026-09-10。本轮延续用户已批准的有界异常日志修复范围。前因及同版本合成
CPU观察见[Job683076分析](2026-09-10-job683076-compiler-binding-failure.md)。
独立候选没有修改原v4/已发布v12及其证据；不改变预测、精度、矩阵或阈值。

## 改动与保护

生产代码只增加_frozen_module_binding_error、修改原拒绝分支抛出的错误构造
以及_bounded_exception_diagnostic。拒绝分支条件、同类同消息、sticky撤销、
顶层JSON和退出码不变。loader之外所有科学/运行函数逐节点AST保持一致。

内部异常直接读取BaseException原生字典描述符，不调用任意属性/str/repr。
仅识别torch._dynamo.exc.BackendCompilerFailed的inner_exception字段；标准
cause/context分支仍保留。至多6异常、6帧/异常、128 traceback步/异常、
64字段扫描；完整紧凑JSON限制12288字节，为16384展示预算留余量。
模块delta只有增删/替换计数和每类最多3个、每名最多64字符的名称；不含模块
内容、源码、张量、locals、全量环境或原始后台消息。固定编译关键词是
MENTIONED提示，不是自动根因判定。日志失败不替换已有拒绝。

## 实际本地验收

原v12十八SHA全部通过；旧612项测试只改版本路径，新17项，共629项。
14个独立Python入口完整重跑exit0；主数值344项101.245s、提交66项13.482s。
首次新增测试在本机torch2.12.1的异常构造器缺first_useful_frame参数失败，
只调整新测试按真实签名兼容2.1.1/2.12.1后，以上完整重跑全部通过。
未声称首次运行成功、未弱化任何旧测试。

Ruff全包检查/格式、runner bash-n、两个CLI help通过。逐函数AST检查确认
loader仅原raise对象构造变化，判定条件/其余代码不动。四项退化（撤销新
内部异常读取、去掉模块delta、替换错误类型、绕过loader拒绝）均被测试捕获。
这些是主代理检查，不是独立代理审查，也不是GPU数值验收。

候选十九文件manifest SHA：
9cee85c7940c0ee3e5f75aeff28f7beea2124ef3b25dd30e55a2250f6e935839。

```text
4fd9204bddf6291b2e5a0b2d0c797d4a883db5fb6c6fb57ddb0a7a5338b62d52 diagnose_batch_invariance.py
fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b numeric_trace.py
aa6c6f5e1977bcdf2aff69fabf4579d21f4a8fc6e25f7d44b7fe90202937504e submit_numeric_diag.py
5a5330c744d8b6b38a8ecf84bbf59e9e4cc93547e3b6cfb39d073e332cdb1e09 run_numeric_diag.sbatch
```

## 真实同版本检查

临时CPU探针本地预检通过，已启动真实torch2.1.1/formal40检查。使用私有
临时源码/缓存、不改HOME，不部署正式v13、不freeze、不sbatch、不forward。
先检查真实BackendCompilerFailed补充元数据，再重复原完整模型CPU准备检查。
实际结果待后续追加；完整三模型10k对比仍未完成。

续记：实际探针exit0，torch2.1.1+cu118。真实内部异常边/固定关键词/无原消息
泄露/替换模块delta均PASS。24pinned、96snapshot；strict formal40 61键、
参数覆盖1.0、70模块/210 OrderedDict；完整60状态张量、scene3/model9图、
71条指纹、重复状态/RNG/图及输入前后全部PASS，预算381329/600000不变。
FORMAL40_CPU_STATE_SEAL_PROBE_PASS不代表CUDA worker或数值通过。
下一项按原范围独立部署、freeze/check-only后单次32条GPU诊断补证据。
