# 正式 CUDA 准备与观测接口候选

2026-09-13：**本地30项检查通过；没有远端执行、CUDA验证或新增作业。**
这是独立候选，不是已发布的GPU诊断包。不要直接在登录节点运行模型，
也不要重跑703751或旧提交脚本。

## 已实现的接入

`cuda_registration.py`提供三个仅进程内接口：

- `ProductionRequest` / `prepare_production`：严格要求原production冻结身份、
  实际torch2.1.1+cu118和CUDA。固定原32样本、42位置计划；不接受注入模型、
  自称可信的类对象或hermetic测试开关。真实类从原snapshot loader导出并核验。
- `CudaCompiledLease`：独立CUDA候选，不放松旧CPU CompiledLease。
  27个模块加外层pre/post共29个回调；保留原顺序、账本、状态/RNG/运行设置检查。
  使用原CaptureStore的有界分块传输。pre/post只将CPU专用端点摘要替换为
  同字节格式的分块摘要，原方法语法树可精确恢复。
- `run_observed_candidate`：只调用原run_trace_pass两次，16→1、同一模型，
  保留BaselineBridge父结果逐项校验、原执行身份检查和采集字节重读。
  正常/异常退出均恢复观测ContextVar并清理自己的回调/权限。

关键顺序：严格加载 → 登记回调 → **原准备函数签发编译器权限** →
适配器接收既有权限 → **原准备函数签发worker**。适配器不得再次签发/重置编译器。
此前CPU空登记是自行签发冷编译器；该顺序不能照搬到正式准备函数，因为
原 `_issue_compiler_lifecycle` 明确禁止重复签发。

原prepare函数仅通过既有审核的两处调用插入生成新函数，删除插入后AST与
SHA固定的v18原函数完全一致。旧模块字典、旧函数和所有旧文件不替换。
新函数是派生候选，不冒充原始v18的未修改执行来源。

## 本地验证证据

[记录](../../evidence/2026-09-13-production-preparation-local.md)及
[实际回执](../../evidence/production-preparation-local-20260913T055522Z-k2b34qi7/receipt.json)。
30 tests、0 skips、rc0；实际Python3.11.15/torch2.12.1。
仅可移植CPU编码、AST、CPU拒绝和清理所有权测试。没有伪造CUDA或原2.1.1版本，
没有声称新CUDA准备函数或两轮GPU观测已运行。

覆盖包括FP16/32/64端点字节一致、非连续/多分块张量、预算先于传输、NaN/Inf拒绝、
元信息/代码绑定更改拒绝、CPU模型拒绝、保留原CUDA门禁和单次编译器签发位置、
准备中途失败仅撤销本次新身份。清理单元测试使用显式简单对象夹具，
不是生产身份/真实编译器签发测试。

SOURCE_MANIFEST（21份源/输入）SHA：
`667dca263b9422c67a6308330a9610d6ac5247e4ef76c681a83dc955d590d6a9`。
候选代码SHA：
`b159c84e27d2fef996424d27b39d8fcb91abf2b2b4d2a829dd385ebe130bdf18`。

仅本地复测：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_production_preparation_20260913/validate_local.py
```

## 尚需完成才可验收GPU观测

1. 独立计算节点运行包：原冻结输入/真实scene scope/受控scratch、完整stdout与失败证据、
   资源和时限、防重复提交、归档及本地原始字节验证。
2. 分开的新进程分别执行无观测参考与观测版本；同实际A100/torch2.1.1/Inductor条件，
   保持原加载、精度、batch计划及阈值，不混用CPU结果。
3. 验证参考与原父诊断结果、观测与参考端点的一致性，再解释逐层差异。
   单独出现CUDA_OBSERVED_PARENT_REPLAY_CANDIDATE_PASS仍不等于无干扰冷对照通过。
   图分割可能改变内核选择；端点一致也不证明中间运算与未插桩编译完全相同。

本候选不含GPU提交入口，不自行获批算力。`production_preparation_validated=false`、
`ready_for_gpu=false`是本轮实际验收状态，不得改成科研完成标记。
未得到三模型smoke、10k对比或论文结果；研究角色仍为
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
