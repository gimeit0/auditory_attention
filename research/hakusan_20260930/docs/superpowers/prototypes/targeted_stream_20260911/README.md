# 有界分块追踪原型：本地66项、超算可移植62项通过，尚未生产接入

2026-09-11，独立于已通过同版本CPU验证的targeted_trace_20260911。
不修改旧原型SHA清单、v18发布文件、冻结输入、compile/TF32/AMP或数值容差。
本模块不是v19发布，没有作业提交功能。

后续更新：独立[真实模型CPU绑定检查](../targeted_binding_20260911/README.md)
已通过。使用原严格加载器读取formal40，42个计划位置绑定27个真实模块，
60条注册状态与Job685198字节SHA一致，空hook安装/移除通过；不是实际forward
或生产执行能力认证。下面保留本分块原型自身的合成测试范围与限制。

最新：用户恢复SSH后，已实际完成一次HAKUSAN同版本CPU验证。
Python3.11.5/torch2.1.1+cu118的62项可移植测试全通过（6.320秒测试时间），
STREAM_CPU_PROBE_VERIFIED、returncode=0。另外4项固定本机证据路径的静态
检查不在远端集合中，不能把此次写成超算66项通过。62=原28＋分块/集成34，
是同一组用例的版本兼容复验，不与本地66相加为不同测试数。

## 这轮完成

- 保留原28项测试，新增34项分块/对象绑定/集成测试、4项静态计划测试。
  本地Python3.11.15/torch2.12.1共66项通过，4.180秒；无跳过、CUDA未初始化。
- 完整张量按逻辑C顺序切分成不超过1MiB的编码块；非连续/广播视图不先
  整体flatten拷贝。原生float16/32/64不转精度、不截断、不抽样。
- 每个选定张量保存到新建私有目录的独立文件。默认每store完整捕获总量
  2GiB，单张量128MiB，最多8192条；超过任一上限失败，不悄悄少采。
- 内存记录只存形状、stride、字节长度、SHA和事件身份，不保留每层完整数据。
  比较时即使已发现不同，也继续完整读验双方SHA，防止后续损坏被掩盖。
- 原端点、输入、参数、RNG、运行标志和事件顺序检查继续使用未改的原型。
  超预算、非有限值、文件篡改/截断/链接、写入失败、错配/多余记录均测试拒绝。
- 合成外层模型中的真实Dynamo OptimizedModule结构已测试；阶段路径绑定
  model._orig_mod前缀。替换wrapper或选定模块对象会被拒绝。
- 合成32条、16→1的34批次顺序完整保留；非目标trial不被从推理中删除。
- 首层尺寸[32,39,19967]的人工广播零张量完成两份全量写入和逐字节比较：
  共199,350,528字节；编码块不超过1MiB。它不是这些trial的真实特征，
  没有运行模型forward，测试临时数据由TemporaryDirectory清理。
- Ruff通过。旧原型7项SHA与v18原28项发布SHA再次核对通过。

## 原始证据

- [测试日志](../../evidence/stream-local-20260911T122354Z-nxc1z53j/tests.log)
  SHA：df6b0253bca2bd84c1baccf6880de56262eb4a0085e61f6d6cc367dfb1942b72。
- [验证回执](../../evidence/stream-local-20260911T122354Z-nxc1z53j/receipt.json)：
  绑定7份源码与输出，运行前后源码一致，LOCAL_STREAM_VALIDATION_PASS。
- [42边界静态预算](../../evidence/stream-local-20260911T122354Z-nxc1z53j/static-plan.json)
  SHA：9e693b59c4a50bb04f1edb0843b08f46425f24f6c8e92350245a97e1f0170c90。
- [源码SHA清单](SHA256SUMS)。

## 超算同版本实际证据（2026-09-11）

- [远端原始输出](../../evidence/stream-remote-cpu-20260911T131106Z-u432sjvm/output.log)
  SHA：878e8e873605a9fcde93ef3a684e5a12dc0fc1a25423b6476ab81c7a28faac65。
- [远端回执](../../evidence/stream-remote-cpu-20260911T131106Z-u432sjvm/receipt.json)：
  STREAM_CPU_PROBE_VERIFIED，remote_probe=true，returncode=0。
- bootstrap SHA：2ff7a73c3192e661778fa6e59ef9c98867bedab937ebfdbb1985a67a66ef0c59。
- driver SHA：5321551b0c369a7e72ceb0b399a829b6f6ec2665f1720731e10db2bab254671c。
- 已独立重算六份传输源码、driver、引导载荷和完整输出SHA，核对回执成功字段。
- [同一临时目录引导流程的本地自测](../../evidence/stream-bootstrap-selftest-20260911T131038Z-weq02lzs/receipt.json)
  先行通过；它是本机自测，不能代替上述远端回执。

执行方式与旧28项纯内存入口不同：本次将六份固定SHA测试源码放入新建私有
/tmp测试目录，人工张量文件也限于该目录；子测试限时60秒，无自动重试。
正常结束已确认temporary_directory_removed=true：临时测试源码和人工数据
已清理，本地日志/回执保留。没有发布生产文件，没有读取checkpoint/音频，
CUDA未初始化，jobs_submitted=0。没有修改HOME或读取/保存密码。

hook部分支持的warning再次出现，但无失败或跳过。编译仍仅Dynamo eager，
不是Inductor或A100观测有效性验证。原分块模块和测试源码无需版本修补便
通过了2.1.1检查；本轮只新增执行入口/远端驱动并记录证据。

## 静态预算

静态公式使用已核验的配置、架构和padding规则；完整42边界、每cell两个目标
及两个pass若全按float32保留，数据量为1,495,537,152字节（1426.255MiB），
最大单条99,675,264字节，落在默认单store预算内。A2各层真实autocast dtype
尚未观测，float32只用作存储估计；每cell需独立store，不能将两cell混装在
一个默认2GiB store。这不是GPU资源实测或新增资源授权。

## 不能混淆的限制

1MiB是编码块上限，**不是整个进程只占1MiB**。host张量与编码bytes可同时
存在；比较同时读两块；框架工作区、源张量、原型的输入/模型状态检查等不
包含在该上限。尚未测真实推理的RSS、显存、I/O耗时或完整磁盘峰值。

记录身份只由本进程的发行列表绑定，尚无跨进程导出/重载的封闭工件协议。
对象类型由调用者传入，结构绑定不等同于冻结来源/严格加载/生产能力认证。
相同源码的哈希检查也不构成对任意运行中代码的认证。不要把该原型直接接到
生产worker或将它替换v18既有校验器。

编译合成用例只用Dynamo eager，并在参考与观测间显式重置合成编译缓存；
不是Inductor。hooks仍有图分段干扰，端点相等也不能证明未观测编译程序的
内部算子等价。真实参考/观测需要独立冷进程，不能把此reset加入生产路径。

真实加载器的CPU加载/对象绑定已由上述独立检查完成；生产worker执行能力
接入、A100干扰验收、flatten/prehook及块内算子定位仍未实现。
ready_for_gpu仍为false；尚无新真实逐层数值结果，更无最终三模型10k比较。

## 本地复核命令

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_stream_20260911/validate_local.py
```

只在本机运行，生成新的私有证据目录；不会连接超算、加载checkpoint或提交
作业。静态报告还依赖本机项目中的三份精确SHA源码，移动环境前需显式核对。

此前SSH不可用的阻塞现已解除，本次同版本检查已经完成，无需重复运行旧
28项或任何submit脚本。下一阶段仍是生产执行能力接入及独立冷进程
观测有效性验证；合成测试通过不代表这两项已经完成。
