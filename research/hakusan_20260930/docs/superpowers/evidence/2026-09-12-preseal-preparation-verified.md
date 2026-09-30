# 2026-09-12：签发前登记接口候选，本地验收

[新准备接口候选](../prototypes/targeted_preparation_20260912/README.md)已完成
本地实现与18项测试，零跳过。上一阶段25项原样重跑通过。**这不是生产
编译模型接入完成，也没有完成超算同版本、真实checkpoint或GPU验收。**

## 本轮相对上一阶段的变化

上一阶段依赖预先构造并装好hook的测试模型。本轮测试的严格加载接口现场
创建模型，不使用`model_to_load`或`strict_load_hook`注入槽；模型返回后，
新的显式登记点安装hook，再继续原有来源、模型、runtime及身份签发逻辑。
测试中的加载器仍是明确的`LazyEvaluator`合成实现，不能据此宣称实际读取
了formal40 checkpoint或调用了生产严格加载实现。

新入口在内存中派生原v18准备函数，仅增加登记参数、严格加载报告核验后
的安装调用、身份构造前的登记复核调用。去掉两条新增调用并恢复参数/名称
后，语法树与父函数精确一致。原源码、函数对象和原模块字典不替换；运行
精度、加载次数和原有来源检查不删改。派生准备入口须标记为新候选，不能
把保留原源文件误解为本轮实际执行了未扩展的原准备入口。

候选语法树SHA：`8b091574d3cf5dc495316fc08e3e72e57105082ca99b156ba1b1fcf3807e7bf6`。
父准备函数语法树SHA：`26513a8902c112311116bd90b41345005eec2d6813b746b60f2b42d13ce5a477`。
回执单独绑定候选标识、来源SHA、计划SHA和原签发记录；没有建立新的生产
发布/冻结协议或授予生产执行能力。

## 实测结果

A2/B2两条合成成功路径各一次加载、一次runtime配置，登记一次、签发前
复核一次。各运行完整32条16→1的34次forward、136次阶段调用、16份目标
采集（13184字节），原数组gate及观测输入/输出核对通过，结束后hook移除。
这里A2/B2为CPU测试标签，不是CUDA AMP；4阶段不是正式计划中的42位置。

18项覆盖语法树精确还原，以及原校验删改/runtime调用变更/登记位置移动/
重复插入拒绝；加载报告、原能力、加载后来源失败；错误请求、实例方法、
计划变动和重复运行拒绝；登记后失败清理、已有合法身份保护。加载后来源
反例确实先安装hook，随后被原来源校验拒绝并清理；没有通过跳过校验接受。

清理只撤销本次新增身份；尝试复用已签发模型被拒绝时，不撤销此前合法
身份，也不移除它原有的hook。生产模式在配置runtime和加载前直接拒绝，
不借用hermetic测试例外绕过CUDA/编译要求。

最终测试进程PID79846；Python3.11.15、torch2.12.1、NumPy2.4.6，CUDA未
初始化。18项耗时46.969秒；监督总48.762秒，上限180秒，无自动重试。

## 证据

- [18项原始日志](preseal-preparation-local-20260911T174203Z-_qvylnil/output.log)
- [子进程结果和两条完整运行记录](preseal-preparation-local-20260911T174203Z-_qvylnil/child-result.json)
- [监督回执](preseal-preparation-local-20260911T174203Z-_qvylnil/receipt.json)
- [三个源码SHA](../prototypes/targeted_preparation_20260912/SHA256SUMS)

```text
output  cb852d07f506ed84a6a1b07a2fc50ed80f147db470de8c049078f7f188fa1539
child   f41438bebc3c7b8df82f733d8956d0bb29b84fb16c63494152001f1978fb9f6b
receipt 6ec6e7deaa23bfe81e469349ebd414d9e528ce988d346e190d398803d820ebfd
```

另一个只读Python进程核对源码/工件SHA与长度、PID、18项/零跳过、A2/B2
各1次加载/34次forward/16份采集、候选来源标记与父函数AST摘要，得到
`INDEPENDENT_PREPARATION_RECEIPT_RECHECK=PASS`。这只是回执/来源完整性复核，
不是另一次科学推理或独立冷对照。

上一阶段25项测试原样重跑通过（50.235秒）；Ruff通过。原v18的28项发布
文件SHA、上一阶段三个源码SHA仍通过。本轮没有重跑v18的751项完整回归。
较早`preseal-preparation-local-20260911T174034Z-qpdzf_t2`的17项开发验收
保留不覆盖；后来补上已有身份保护后，以上18项才是最终版本对应证据。
UTC17:42:03对应JST2026-09-12T02:42:03。

## 当前界限与下一项

新接口候选仅开放合成CPU域。上一阶段观测器不支持`OptimizedModule`，
因此本轮没有伪装已接通生产严格加载器，也没有开放生产模式。下一项应
实现绑定真实42位置的编译观测登记和已审查的调用生命周期，再连接独立
冷参考/观测与完整父32条核对，随后做超算同版本和有预算的新A100验收。

参考与观测仍在同一测试进程，未执行真实forward、Inductor或GPU AMP；
临时合成采集文件随测试清理，只保留日志和摘要证据。本轮只读发现本机
SSH共享socket已不存在，没有尝试自动重连，亦未执行远端操作。

`production_preparation_validated=false`、`ready_for_gpu=false`、作业数0。
旧v18与失败材料不变；原1e-6容差和`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`
角色不变。最终三模型smoke及10000条same-bank比较仍未完成。
