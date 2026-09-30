# 严格加载后、身份签发前的登记接口候选

上一阶段的[观测生命周期](../targeted_lifecycle_20260912/README.md)使用提前
构造的测试模型。本阶段新增独立准备入口：模型由严格加载接口现场创建，
返回后才安装观测 hook，随后执行原有来源/模型/运行设置检查并签发身份。
**实际测试仍为合成 CPU；生产编译模型的登记和推理入口尚未发布。**

## 实现差异

从固定 SHA 的 v18 源码中，只取 `prepare_formal40_worker` 的语法树，在
内存中生成单独的新函数。原文件、原函数对象及原模块字典不被替换。
新函数增加一个内部登记参数及两条调用：

1. 原 `_require_load_report(report)` 后立即调用登记器安装 hook。
2. 原 attestation 构造前立即重新核对登记器、hook 和状态/RNG/runtime。

去掉这两条调用及新增参数、恢复函数名后，语法树必须与原函数完全相同，
否则拒绝执行。复制的名称空间保留原 helper、注册表与 ContextVar 对象；
调用前后核对原全局绑定，不能以此修改运行精度、加载次数或既有来源检查。
这个派生准备函数是**新候选**，不能称为原 v18 二进制/准备入口未变。
回执单独记录候选身份、父源码 SHA、两个语法树 SHA、计划 SHA 与原签发记录。

只接受固定类的登记请求，不接收任意用户回调；失败清理本次 hook 并撤销
本次新增身份。拒绝复用已签发模型时，保留原本合法的身份和 hook。
默认非测试模式在配置 runtime 和加载模型之前明确拒绝。

## 本地验证

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_preparation_20260912/validate_local.py
```

一次新 CPU 子进程、最多180秒、不自动重试。日志和回执写入新的私有
evidence目录；不连接SSH，不读取真实checkpoint，不冻结或提交作业。

测试中的 `LazyEvaluator` 实现与生产相同的严格加载接口形状，现场创建
合成模型，不使用 `model_to_load`、`strict_load_hook` 或预装 hook 模型。
这是接口控制流验证，**不代表实际执行了作者/正式模型的生产加载代码**。
成功路径 A2/B2 各一次加载和runtime配置，完整34次forward，原边界、正式
输出和新观测记录都与合成参考核对。原观测器代码保持其固定SHA不变。

18项测试含：精确语法树还原；原校验删改、runtime调用变更、安装位置移动、
重复安装调用拒绝；原加载报告/来源/能力失败；任意请求和实例方法替换拒绝；
计划变化、重复执行、复制回执拒绝；登记后失败清理及先前合法身份保护。

源码：[适配器](prepare_registration.py)、[测试](test_prepare_registration.py)、
[监督入口](validate_local.py)、[SHA清单](SHA256SUMS)。
最终证据见[本地验收记录](../../evidence/2026-09-12-preseal-preparation-verified.md)。

## 下一项仍需完成

真实模型含 `OptimizedModule`，旧观测生命周期明确只接受非编译CPU模型。
本阶段没有删除该限制，也没有让生产能力走CPU测试例外。还需完成已绑定
真实42位置的编译观测登记、编译首次初始化的RNG/状态核对、独立冷参考与
观测进程接入，才能开放生产准备入口。之后再做超算torch2.1.1验证和有
明确预算的新A100验收；不能借用原作业授权重复提交。

本机参考和观测在同一测试进程内，不是独立冷进程；没有真实父32条数据
重建、GPU AMP/Inductor验证或三模型比较结果。原容差和same-bank非独立
测试角色保持，`production_preparation_validated=false`、`ready_for_gpu=false`。
