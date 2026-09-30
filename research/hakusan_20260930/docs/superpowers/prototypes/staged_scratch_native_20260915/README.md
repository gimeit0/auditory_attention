# 有界同环境 scratch 分阶段检查

G1工程入口。不是GPU诊断或总体checkpoint比较。

新增 `run_native.py` 和 `child.py` 包装已固定的本地 staged fixture；
原运行包162份来源、原stage helper两份来源、旧freeze及guard/loader均不修改。
原supervisor以固定SHA和逐项精确匹配派生，不改CPU亲和性及期限。

执行顺序：A2预期生成 → B2预期生成 → B2 scratch/mmap原两项断言。
32条顺序、每cell同一模型16→1两轮、所有原断言保留。
阶段间以session、来源、Python/torch、输出字节、外部SHA绑定。
临时目录退出清理；HOME不重定向；CUDA不初始化；仅合成模型。

每次SSH调用：单CPU、child≤50秒、supervisor≤90秒、transport≤110秒。
共三次顺序独立调用，**不是声称三次总计≤90秒**；任一失败立即停，不自动重试。
只复用既有认证master；不提示/读取密码、不自动重连、不走备用连接。
远端临时写入包与测试数据，回传日志/工件存本地，不创建永久诊断根目录。

## 本地验证

24项离线拒绝/绑定检查通过。测试中构造的native JSON只检查解析规则，不是原生运行证据。
实际同载荷本地三段7.462、6.880、7.356秒，mmap两项断言通过。
输出contract与旧未拆分本地oracle完整相同：
`cdfe21ec7eb65f72a6fd11f76fc3c975a67c6a7d01f4c121de1f3c98dd271000`。

同载荷证据位于 `../../evidence/staged-scratch-local_harness-20260915T124305Z-jdqphuin`。
回执SHA `29b587c8a8dc5bf222b730646de57234965df69e622eb4c0b03e297e8ab6c7cf`。
新入口代码及全部请求、回复、结果文件已重新读取复核。

原helper字段 `LOCAL_STAGE_PASS` / `local_v19_staged_synthetic_scratch_only`
保留为测试variant身份；实际执行位置以外层 `mode` 判断，不能仅靠内层字段认定主机。
原生结果（若以后通过）名称为 `NATIVE_STAGED_COMPONENT_PASS`，
不是旧monolithic80项全过、真实checkpoint推理、A100或mount验证。

## 命令

在Mac工作区只读核验：

```sh
/opt/anaconda3/envs/audattn/bin/python -I -B docs/superpowers/evidence/2026-09-15-staged-scratch-native-cpu.py --review-only
```

已本人认证后执行：

```sh
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-15-staged-scratch-native-cpu.sh"
```

若连接不存在，先由本人运行连接脚本；CPU入口自身不会重连。
失败保留本地 `STAGED_CPU_EVIDENCE` 中所有已产生证据，不重提旧GPU作业。
