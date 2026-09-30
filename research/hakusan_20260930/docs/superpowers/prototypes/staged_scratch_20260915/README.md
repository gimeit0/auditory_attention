# v19 合成 scratch 测试的内容绑定分阶段方案

本目录只实现**本地验证**。不含 SSH、远端部署、freeze 或作业提交入口。
保持冻结 v19 与 162 份原包源码不变，也不把 namespace 候选登记为正式加载器对象。

阶段顺序：

1. A2 预期结果：只选取原 expected_contract 的 A2 外层循环；32条样本、同一模型内 batch16/1 两轮、34次 forward 不变。
2. B2 预期结果：同上，选择 B2。原函数本来就给每个 cell 分配独立模型，因此不拆开模型的两轮生命周期。
3. B2 scratch/mmap：仅将原两项 scratch 测试中的一次 expected_contract 调用换为经 SHA 校验的预期数据读取；所有断言、完整两轮、4个 spill/mmap 和错误缓存目录拒绝检查不变。
4. 本地对照：另起进程运行原版完整 expected_contract；要求分阶段合并结果的所有输出字节、边界记录及元数据与其完全一致。

两种 AST 改写均反向恢复并比较原 AST，不改 evaluator、模型、guard 或正式 loader。
分阶段回执绑定 session、原 manifest、新测试源码、环境和前置产物 SHA；完整 contract 还经原 replay 解码器验证。
每个子进程最多50秒，本地四阶段合计90秒。失败保留证据且不自动重试。
这些限制不等于远端方案已通过；远端入口尚未实现，不能把阶段 PASS 写成旧原生单进程超时测试 PASS。

本地运行：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/prototypes/staged_scratch_20260915/test_lifecycle.py
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/prototypes/staged_scratch_20260915/lifecycle.py local
```

本方案只是工程合成 CPU 测试，不是 formal40 与作者 checkpoint 的结果，也不证明 A100、Inductor 或正式 guard 已通过。
