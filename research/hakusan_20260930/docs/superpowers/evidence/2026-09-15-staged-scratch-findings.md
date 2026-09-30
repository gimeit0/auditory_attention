# v19 合成 scratch 生命周期：本地内容绑定分阶段验证

2026-09-15 JST。本轮结论：**本地分阶段测试通过，尚未执行远端分阶段测试。**
没有 SSH、上传、freeze、真实 checkpoint 加载或 GPU 作业提交。
原生旧单进程 scratch 组仍未通过时限验收，不能把本轮结果算成原来的80项原生全过。

## 改了什么

新增独立目录 `docs/superpowers/prototypes/staged_scratch_20260915`。
采用原先已冻结、可由正式 loader 识别的 v19；没有把 namespace 扫描候选伪装成已发布来源。
原162份运行包源码、冻结输入、旧失败记录全部保持不变。

此前完整测试先调用 expected_contract 生成 A2/B2，再执行 B2 双轮 scratch/mmap。
现在把 A2、B2 预期生成分开，结果以 session、源码、Python/torch环境及外部 SHA 绑定到 mmap 阶段。
最后另起本地冷进程执行**未拆分的原版 expected_contract**，做完整内容对照。

| 冷进程 | 保留内容 | 包含启动的耗时 |
| --- | --- | ---: |
| A2 oracle | 32条、batch16/1、同一模型34次forward | 7.937秒 |
| B2 oracle | 32条、batch16/1、同一模型34次forward | 7.563秒 |
| B2 scratch/mmap | 原两项测试断言、单次加载、两轮34次forward、4个spill/mmap、缓存环境错误拒绝 | 8.137秒 |
| 原版完整 oracle 对照 | 未拆分 A2+B2 的原 expected_contract | 13.689秒 |

每子进程上限50秒，本地四段总上限90秒；未增大旧时限。
本地环境 Python3.11.15 / torch2.12.1；不能替代 HAKUSAN Python3.11.5 / torch2.1.1。

## 实际验收

- 17项离线结构/拒绝检查通过：错session、错源码、错环境、重复cell、缺trial、错batch/autocast、篡改输出、错SHA、非规范JSON、符号链接和越界父路径等均拒绝。
- 两种 AST 变换可逆恢复为原结构：只改 outer cell 选择，及 scratch 测试中一次预期数据生成调用；不改任何原断言或模型/guard/loader。
- 两项派生 scratch 测试通过（6.814秒测试体），保留全部原断言。
- 分阶段合并结果与原版完整生成结果：所有官方输出字节、粗粒度/派生边界记录、样本身份和元数据完全相同，无容差放宽。
- 完整 contract SHA：`cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000`。
- 四个冷进程PID不同；HOME保持不变，CUDA未初始化；162旧来源及16份工件重新复核通过。

首轮新单元测试有一项失败：macOS临时目录经 `/var` 符号链接访问，被新入口的无符号链接读文件检查拒绝。
仅在测试中先解析临时目录的真实路径修正；读文件保护未放宽。此后17项通过。
完整四阶段只执行一次，没有失败后自动重试。

## 固定证据及复核

- [本地回执](staged-scratch-local-20260915T091408Z-nobia7gy/receipt.json)
- 回执SHA：`eabe071aed44e8f7f1dba6443d48555494bdcdbad677626434caa2143e340e6c`
- lifecycle.py：`9b0f2c511ed1cda9ee4cb0743795ddf50d8518e31d05e1a23e5d2af3281ca20e`
- test_lifecycle.py：`5038f717ba5974336abf3ab3d5106b027a9798ac87e5f4ca2d5ad3c471de41e4`

只读复核，不运行模型、不提交：

```sh
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/evidence/2026-09-15-staged-scratch-review.py
```

## 下一项及科学边界

准备并审核 HAKUSAN 有界阶段入口：每次独立调用仍须遵守50秒子进程、90秒监督器、110秒传输和单CPU限制；不同调用的中间数据必须绑定并验收，失败即停、不重试。
本轮没有实现或执行该远端入口，也没有证明原生时限问题已解决。
namespace 候选的正式身份/加载器集成仍需独立审核，不能写入旧v19并复用旧冻结哈希。

这只是推理/归档测试准备，不是 formal40 与作者 checkpoint 的总体比较结果。
最终比较仍须在通过相关验收后执行；复用验证bank的结果仍标注 `REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`。
