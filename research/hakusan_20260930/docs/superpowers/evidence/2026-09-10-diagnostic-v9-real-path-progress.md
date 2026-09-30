# v9 真实实例检查与集群连接：继续实验

## 目标与本轮判定

目标仍是解释/解决原数值阻塞后，完成 formal40、valbest33、作者 checkpoint
同 frozen bank 的完整比较；不是把 535 项本地测试或工具部署算作完成。
上一目标轮为 progress：独立候选修复、535 回归与候选固定已完成。
本轮也是 progress：更强的真实实例检查发现新限制，改变下一项部署决策。

## 本轮实际证据（2026-09-10）

1. v9 外部十三文件候选清单重验全 OK，没有改变已固定候选。
2. 沙箱内 SSH 首次名称解析失败；经用户工具批准在沙箱外重新只读连接，
   网络可达但认证失败：`Permission denied (publickey,password,hostbased)`，
   exit 255。没有登录成功、读到当前远端队列或修改任何远端状态。
3. 搜索工作区及本地项目，未找到 ckpt 文件；不能在本机复验真实 formal40
   权重。实际 full.yaml SHA 与冻结值一致。
4. 新增独立 probe 导入 SHA 绑定的真实模型源码，用原 full.yaml 在 CPU
   构造完整随机初始化实例，不缩小网络、不关闭 compile、不改配置。
   构造 PASS：62,622,520 参数、61 state keys、compiled wrapper 存在；
   9 个模型可调用项的物化依赖图 PASS。
5. 实际 `_model_execution_fingerprint` FAIL：`model module training state is
   unavailable`。定位 `model` 子模块为 `torch._dynamo.eval_frame.OptimizedModule`，
   本机 2.12.1 下实例字典没有 training，公开属性为 False。诊断器要求直接
   字典 bool。最终 probe exit 2，并非完整实例验证通过。

这是随机 CPU 模型、2.12.1 环境，不是冻结 checkpoint/2.1.1/A100 结果。
不据此断言超算也有同一问题，不向包装器补属性或放宽生产校验来强行通过。
v9 发布暂缓，下一项是实际集群同版本加载/指纹路径验证。

证据：[实例探针](2026-09-10-diagnostic-v9-real-instance-probe.py)、
[输出](2026-09-10-diagnostic-v9-real-instance-probe.log)。探针 Ruff/格式通过。
未做 GPU 推理、下载依赖、checkpoint 比较或新作业提交。

## 需要用户完成的认证

准备 Mac 入口 `2026-09-10-hakusan-connect.sh`，bash -n 通过，尚未实际执行。
它只建立本地私有 700 目录中的 SSH ControlMaster 连接，密码由用户在 SSH
提示符输入，不传给聊天、不写入脚本/日志、不安装密钥。验证远端账号及主机，
不上传/冻结/提交。现有非活动 socket 拒绝覆盖；保留 SSH 默认主机密钥检查。
连接空闲一小时后退出，也可显式 `ssh -S ... -O exit` 关闭。

用户建立共享连接后，主代理才可经同一 socket 只读核对远端冻结输入、旧失败
证据与当前作业，然后准备受控的实际环境检查。没有把授权连接等同于忽略
冻结协议或允许不经检查重提作业。完整实验目标仍 active；认证阻塞首次确认，
尚不满足连续三轮 genuinely blocked 的标记条件。

## 后续源码核对（认证阻塞第二次确认）

下一持续目标轮只读检查 `.hakusan-control/master.sock`，结果 ABSENT；没有
可等待的已存活 SSH 句柄，也没有远端新作业可验证等待。上一轮仍归类 progress。

本轮通过经批准的只读 HTTPS 请求取得 PyTorch 官方 v2.1.1 源码：
https://raw.githubusercontent.com/pytorch/pytorch/v2.1.1/torch/_dynamo/eval_frame.py
（web 页面抓取失败后使用 curl；不安装依赖、不运行下载源码）。
OptimizedModule 类没有 training property，也没有 __setattr__ 覆盖，并调用
基类初始化；本地 2.12.1 实现则有 training property，读取 _orig_mod.training，
初始化时忽略自身 training 设置。这解释了为何不能把 2.12 本机的直接字典
训练状态失败直接外推到超算 2.1.1；不因此为生产 v9 添加绕过分支。
这只是源码对比，不证明实际生产 worker/冻结权重加载或数值推理通过。

已保存官方源码副本 `2026-09-10-pytorch-2.1.1-eval_frame.source.txt`，SHA：
`a98df135208704b66f681646a3d9649b75cbe5a3093fc59e4650b44460c1921b`。
本轮新增证据改变决策，归类 progress；认证未完成仍是运行完整实验的实际阻塞。
仍需用户执行已准备的 Mac 连接入口，不能由聊天输入密码或自动猜测密码。

## 第三轮阻塞复核

同一认证阻塞连续第三个目标轮出现。当前共享 socket 仍 ABSENT；再次使用
经批准的只读 BatchMode SSH 连接，返回 Permission denied，exit 255。
没有已认证的活连接、可验证等待的进程或已取得的新远端状态。

上一轮官方源码核对属于 progress；本轮只有阻塞复核，没有实验进展。
本地兼容修复、真实实例探针、源实现对比等现有安全替代检查已经完成，
进一步同版本/冻结权重/GPU 验收须用户本机完成 SSH 认证。不能把继续撰写
操作计划视为完整比较的推进，也不能凭 535 项本地回归宣布完成。
按连续三轮阻塞规则，将完整目标标记 blocked（非 complete），保留原目标。
恢复条件：用户执行连接入口并得到 HAKUSAN_SHARED_CONNECTION=PASS 后恢复目标，
届时先检查实际连接/远端状态，不假设旧作业仍运行，不自动重提任何旧版本。

## 用户回传连接成功后的现场复核

用户回传 master pid 29994、hakusan1、HAKUSAN_AUTHENTICATED=PASS 与
HAKUSAN_SHARED_CONNECTION=PASS；这证明其命令执行时认证成功。
随后主代理重验 v9 十三 SHA 全通过，并经批准尝试共享连接的只读远端
队列/旧证据检查。沙箱内先被 socket 访问权限拒绝，按规则在沙箱外重试。
该原请求始终无远端输出，复验本地 control check 报 socket 不存在。
继续轮询原会话直到其确实以 exit 255 终止，没有因等待超时启动重复请求。

本地进程检查确认 master pid 29994 和原 SSH 客户端均已不存在；700 权限
控制目录仍在但为空。普通 BatchMode SSH 复查也被认证拒绝，exit 255。
核对本机时间 2026-09-10 03:17:22 JST。连接为何退出尚不明确，不能认定是
空闲计时、网络变化或用户主动关闭。没有取得新的远端状态，没有上传、
freeze、修改或提交；只读查询失败不能算 GPU 作业失败。

需要用户重新运行现有连接脚本。当前无旧 socket，不需要删除或修复目录。
成功回传后再次以实时 socket/远端响应为准，不能仅凭过去的 PASS 推定活跃。
这是用户恢复交互后首次重新确认的连接阻塞；没有另行标记完成。

## 新连接现场通过（master 30687）

本轮使用用户新建立的共享连接，原只读请求正常退出 0：主机 hakusan1、账号
s2510040，当前队列为空，诊断 v9 根目录不存在。v4 manifest、lock、evaluator、
runner 与 v8 freeze/log 的 SHA 均与固定值一致。首次取得 v8 失败标记 SHA：
`5551361860244c94e40982781d1d8aed06e73ec5127b8c851321a298bc804dee`。
sacct 确认旧 Job 680910 FAILED、2:0、48 秒、spcc-a100g04；没有重提。

随后在同一连接的实际 Python 中构造 torch.compile(nn.Linear(2,2))，不做
forward：torch 2.1.1+cu118，OptimizedModule 实例字典含 training，直接值和
公开值均为 False。退出 0。等待期间确认 master 30687 存活，没有重复启动；
后续只读 ps 结果没有遗留 Python 探针。此结果只验证包装器版本差异，不是
正式权重、完整模型签发或 GPU 验收。

下一项为独立临时 CPU 探针：用未改字节的 v9 diag/trace 和原 SHA 绑定 v4
loader，读取冻结 formal40 权重与 snapshot，在真实 2.1.1 中检查模型依赖图
和执行指纹。仅临时目录容纳候选源文件/依赖缓存；不发布 v9、不 freeze、不
提交作业，不修改原科学文件，不把局部 CPU 探针称为生产 CUDA worker 通过。

## 实际 formal40 CPU 路径：加载通过，执行指纹仍失败

经单独工具批准运行两项临时检查，均使用未改字节的 v9 diag/trace，实际
HAKUSAN Python 3.11 / torch 2.1.1+cu118、一个 CPU 线程，不执行 forward。
读取原 evaluation.lock 后取得非阻塞共享锁；仅在 mktemp 等价的随机临时
目录放源文件及依赖缓存。没有调整 HOME、数值阈值、compile 或精度设置。

两次实际证据一致：

- 原固定上下文读取通过：24 pinned roles、96 snapshot files。
- formal40 严格加载通过：全部可训练参数覆盖比例 1.0、61 state keys。
- 67 个模块的直接训练状态/冻结参数检查通过。
- 9 个主要模型可调用项的依赖图物化通过。
- 完整 `_model_execution_fingerprint` 失败：`execution seal work budget exceeded`。
- 两次探针均退出 2；没有到达重复指纹/CPU 探针成功标记，不能声称完整
  CPU seal、生产 CUDA worker、32 条数值诊断或最终三模型比较通过。

第二项探针只从外部安装原 `_SealBudget` 实例以便观察失败计数，沿用原
装饰器/候选代码和所有限制，不提高上限、不跳过检查。失败时：

```
module_path = model._orig_mod.model_dict.conv_block_1.1
inspected_code = torch/nn/modules/module.py : _call_impl
work = 200001
unique_callable_nodes = 121
```

源码显示共享工作上限为 200,000，节点上限为 10,000；这次是前者触发，
不是节点上限、权重加载错误或原 NLL 数值差异。每个模块多次检查 resolved/
type call dispatch，且全模块共用一个预算；重复遍历开销是需要验证的
优化方向，而不是已经证实某个缓存修复正确。不能简单调大上限后发布。

下一项：先以最小重复模块夹具复现累计预算问题，审查可复用的静态字节码
分析与每次仍须重验的 live 绑定，保留默认值、闭包、bound self、hook、
全局/属性变更和共享预算的拒绝覆盖，再决定有界修复。不得跨验证轮缓存
live 指纹或省略每个模块的配置/状态检查。v9 继续 HOLD；没有新版本部署。

证据文件：

- [首次真实权重探针](2026-09-10-diagnostic-v9-remote-cpu-probe.py)，SHA
  `c99bca8df3528162d737781d821110a9919a9feee29495c818efea505eabc6ec`。
- [首次输出](2026-09-10-diagnostic-v9-remote-cpu-probe.log)，SHA
  `ef8ac3b019803d3ebced5f5d2769b1479857acb7103db92449e288b219a0ed92`。
- [原上限定位探针](2026-09-10-diagnostic-v9-seal-budget-probe.py)，SHA
  `482fd2b0607212a81e786e551796aa617e352eb8f9713bc09031cd2d89517404`。
- [预算定位输出](2026-09-10-diagnostic-v9-seal-budget-probe.log)。

两入口执行前本地候选十三 SHA 及远端代码哈希验证通过；本地 Ruff 检查、
格式化及仅验证模式通过。没有把新增外部探针加入固定生产候选或更改其清单。
由于在指纹步骤抛错，探针内的成功后 source postcheck 没有执行；单独只读
现场复核的结果应在下方另记，不能把其省略伪称为完整 postcheck 通过。

### 独立只读结束复核

SSH 请求退出 0；8 个明确指定的文件哈希保持固定值：v4 manifest、lock、
evaluator、runner，v8 freeze、失败标记、日志，以及 formal40 checkpoint。
formal40 SHA 仍为 `2c2a0f9b78248dd82726c63156360f7c125a927cc2e0aa7cc8a4ed58fca1c9ff`。
两个临时探针目录均不存在，v9 正式根不存在，当前用户 Slurm 队列为空。
仅清理了探针自己创建的临时源码/缓存，所有原版本和失败证据保留。
这项是指定关键文件/目录/队列复核，不冒充未执行的 96 文件完整 postcheck。
完整输出：[结束复核](2026-09-10-diagnostic-v9-post-probe-check.log)。
