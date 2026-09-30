# 合成编译模型完整 CPU 生命周期候选

用途：在两个全新 CPU 进程中，分别无 hook/有 hook 地通过原 v18 执行接口
运行 32 条合成 trial、16→1 两 pass，每进程 34 次前向，再逐字节比较输出。
仅 B2 配置及 eager 编译后端；不加载 checkpoint、不接入生产、不申请 GPU。

旧 v18、单次编译候选和既有所有冻结材料保持不变。

- worker.py：参考登记只签发原编译器身份；观测复用已验收的原候选。
  两者都从严格加载中新建模型，保持原准备函数两条插入点和原推理检查。
- verify_pair.py：纯标准库重新核对 16 端点、4 正式输出、逐 trial/batch、
  34 条事件、16 份完整采集字节、已知合成 Identity 阶段的输出和冷进程端点。
- test_verify_pair.py：16 项正反例，本地及临时打包独立子进程均通过。
- run_probe.py：源文件清单 SHA、独立临时树、CPU 单线程、CUDA 不可见；
  子进程最多 60 秒，整个远端 80 秒、本地 90 秒，无认证或自动重试。

2026-09-13首次远端完整调用的参考子进程触及60秒上限，退出124。没有
参考成功记录，观测未启动；临时目录正常清理。**完整生命周期未验收。**
这不撤销上一阶段单次前向通过，也不构成新数值发现。不要重复远端命令
或延长登录节点上的上限；下一步需要计算节点 CPU 验证的资源授权与规则核对。

可重复的本地只读包核验：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_compiled_lifetime_20260913/run_probe.py --check-only
```

[验收记录、原始回执与下一步边界](../../evidence/2026-09-13-compiled-cpu-verified-and-lifetime.md)

研究结论、真实42位置、Inductor/A100和三模型完整比较仍未完成。
