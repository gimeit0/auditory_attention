# G2 两轮推理连接候选

2026-09-16。把已固定的四组准备候选接到原有受保护的 AMP-off 推理上。
这是**进程内组件，不是可提交的生产包**。没有 SSH、上传、freeze、SBATCH 或 scheduler CLI。
不修改旧 v4/v19、checkpoint、冻结数据、准备候选及已验收编译取证源码。

## 当前实现

- 固定 R/C/D/E 派生源 SHA，执行前后检查源文件及函数绑定；原候选 CLI 仍拒绝运行。
- 同一 strict-load 后模型运行 32 条、batch16→1，共34次；不热身、不重载、不重置 RNG。
- 完整 trial 记录和 bank 身份核对，AMP 关闭；复用原推理、证据哈希、边界/状态检查函数。
- D/E 拒绝遗留编译包装。R/C 只接受已审阅的2.1.1默认Inductor，取证对象与原 compiler lifecycle 的目标必须是同一对象。
- 编译模块须在模型准备/执行图封存前预载；取证覆盖两轮同一生命周期，不替换编译器、不挂模型 hook。
- 原始 scene/cue 不同或非有限值、身份/状态异常会抛错、撤销当前证明，禁止重用该连接对象；不返回部分成功结果。
- 有效的 NLL/p_target/p_probe 差异超过原1e-6或类别翻转，报告 `NUMERIC_DIFF`，不伪装成执行异常。
- 原旧cell的 RNG变化仅作上下文，本新候选明确拒绝两轮RNG变化；不修改旧规则或旧结论。

返回 `passes` 仍是原始内存证据，**不是已验证的跨进程工件**。
`production_ready / ready_for_gpu / independent_results_verified / production_interference_validated`均保持false。
`NUMERIC_ACCEPT`只是此组件内的有限数值判定，不代表科学验收、泛化或模型胜负。

## 本地测试

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/g2_worker_20260916/validate_local.py
```

总上限150秒，各合成子进程60秒；本机CPU单线程，CUDA不可见，不需要SSH。
保留新证据目录、stdout/stderr和源码前后哈希回执。失败保留，不自动重试。
只读复查用同一命令加 `verify 证据目录`；最终固定目录见[执行记录](../../evidence/2026-09-16-g2-cell-bridge.md)。

D/E测试是32条合成完整身份、小型模型，原 fixture 以 `backend='eager'` 建立包装后按D/E解绑。
本机torch2.12.1已没有2.1.1的 `most_recent_backend` 字段：此分支只能检查本地无包装路径，
明确记录 `native_cold_state_verified=false`，不能替代超算原生冷状态证明。
R/C本地只测试版本拒绝和源绑定，**没有跑通原生compiled连接**，也不把Job720730的小模型结果当作真实模型集成结果。

## 必须继续完成的生产工作

1. 同版本R/C的原保护链与取证连接验证；真实formal40来源/加载和AMP-off端点干扰对照。
2. G2冷进程worker/coordinator、独立空缓存与预算、全部输入重验、完整工件编码和独立验收。
   原v19 scratch API只认旧cell名字，不能直接拿本组件去调用旧coordinator或旧submit。
3. 原真实32条冻结身份与旧B2结果的对应；本组件只预留固定旧freeze身份校验，未执行真实重放。
4. 新G2协议/生产包审查、freeze、GPU额度批准后才提交一次新矩阵。

G2-M 3小时、G2-R 1小时GPU预算仍未批准。本组件不发放任何作业授权。
后续三模型smoke、10k及controls、配对统计和报告仍是最终交付目标。
