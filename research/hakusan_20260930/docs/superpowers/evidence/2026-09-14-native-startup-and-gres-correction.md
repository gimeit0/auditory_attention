# 2026-09-14：原生启动复验与 A100 调度参数修正

12:00 JST 最新：[实际Job713897已修正为A100并放行](2026-09-14-job713897-corrected-released.md)。
连接恢复后sbatch一次；GPU错配暂扣后，仅原地修正同一JobID并经scontrol/sacct复核，
单次解除暂扣。现在PENDING/Resources，未分配节点、运行0秒。15项恢复测试、
55文件及6组实际回执独立校验通过。单次授权已使用，不能重跑submit/update/release。
下一项只查询/等待713897及严格工件验收，最终科学比较未完成。以下是历史状态。

11:28 JST 最新：[资源已确认，但提交前共享SSH连接消失](2026-09-14-gpu-v3-authentication-pending.json)。
提交命令在本地master_check停止，实际sbatch调用0次，本地提交意图不存在。
尚无新GPU作业，也不是新GPU运行失败；用户恢复连接后继续同一未消耗授权。
无需重新授权、重新部署或重新运行旧705468。下方授权缺失状态已成为历史。

11:12 JST 续作：用户在具体资源确认问题后回复“开始”，
[新的v3单次资源确认已收到](2026-09-14-gpu-v3-single-job-confirmation.md)。
此前授权阻塞解除；核对现有提交记录和预检时效后执行单次受控提交。
这不是最终科学结果，也不授权失败后的自动重提。下方10:31状态为历史记录。

10:31 JST 状态：新的一次性GPU资源授权仍缺失，同一阻塞已连续三个goal回合
复核，任务标记受阻而非完成。v3修正、130项检查、发布及test-only结果保留；
没有新GPU提交。[当前只读状态](gpu-control-20260914-v3/status-20260914T013110Z-x65l0v__/receipt.json)
确认仍只有DEPLOYMENT日志，本地无提交意图。收到新授权后检查现有记录及
预检时效，再继续同一v3候选；不重建目录、不复用705468授权、不自动重提。

本轮恢复了共享 SSH 连接，实际原生 CPU 启动检查已经完成。后续 v2
部署成功，但调度器 test-only 拒绝其 GPU 参数；尚未提交任何新 GPU 作业。
Job705468、v1/v2 包及远端失败证据保留。新的候选使用独立 v3 路径。

## 本轮最新结果（10:04 JST 后）

独立 v3 已实现、发布，**完整脚本的 scheduler test-only 通过**。
最新预检输出713541仍只是估计编号；本轮0个实际GPU提交。

- [v3运行包](../prototypes/targeted_gpu_job_20260914_v3/README.md)：49文件
  manifest SHA256 `2adce67a2b4a0b0d38ff3bf6fbb682863b6e58fccf65743dd213b927d185c687`。
- [v3控制器](../prototypes/targeted_gpu_control_20260914_v3/README.md)：55文件
  release SHA256 `355f29740dfdc159402c49a80b01e79acc1b69b9000e1361edf1e680d50aec52`。
- runner SHA256 `35c2001fb6c51e5791245a928918a11344f85d3b3066a5347bd3f1a4352db1bc`。
- 本地[45项运行包＋38项归档回归](gpu-job-v3-local-20260914T005558Z-jfz34p6x/receipt.json)
  和[47项控制器测试](gpu-control-v3-local-20260914T005558Z-v8_dzbzo/receipt.json)
  全部通过，无跳过；runner另经 `bash -n` 语法检查。
- [独立来源/测试复核](2026-09-14-gpu-v3-review.json)：v1的51文件、v2/v3各55文件
  逐SHA确认；v3的8个本包文件与v2字节相同（含gpu_child及verify_results），
  35个共享源不变；coordinator/contract只改路径。旧实际A100暂扣/记账
  记录离线回放仍可通过，不冒称新作业资源已经验收。
- [v3只读预检](gpu-control-20260914-v3/preflight-20260914T005834Z-x6zyvfne/receipt.json)
  确认原6个输入SHA、相关队列为空、新root尚未存在、GPU-1A可用。
  未检查个人配额，未以该预检宣称计算节点scratch已验证。
- [v3发布](gpu-control-20260914-v3/deploy-20260914T010331Z-41evwwrc/receipt.json)：
  独立root逐SHA发布55文件，1,916,885字节。
- [v3完整脚本预检](gpu-control-20260914-v3/test-only-20260914T010429Z-pri4e2f6/receipt.json)：
  `SCHEDULER_TEST_ONLY_PASS`，scheduler返回0；test ID
  `72c948edfc6f44338f1e866e63fb997c`，远端记录SHA256
  `2e0b16b5ab8e9ed052b2d018e11178cf680406d2fd8873ea66eff9bebd869530`。
  控制器要求这个收据与包一致且不超过24小时；过期不允许直接提交。
- [v2只读状态](gpu-control-20260914-v2/status-20260914T005837Z-s7_0majm/receipt.json)
  只有部署日志，没有AUTHORIZATION、SUBMIT_INTENT或SUBMISSION_RECEIPT。
- [v3最终只读状态](gpu-control-20260914-v3/status-20260914T010548Z-84zr39pr/receipt.json)
  同样只有部署日志，没有任何授权/提交/放行日志；本地也无提交意图。
- [部署证据独立复核](2026-09-14-gpu-v3-deployment-review.json)重新校验55份源、
  四次操作的请求载荷、上传内容、原始日志及结构化回执绑定。
  新GPU提交0，旧作业未更新/取消/重提。

下一步是**取得新的单次1A100/8CPU/64GiB/最长2小时授权**后，才进入
v3实际提交、暂扣资源核验、放行、终态工件校验。失败不自动重提。
只有冷对照及完整结果验收通过，才能据证据决定数值设置，继而恢复smoke与
formal40/作者/valbest33的完整同bank比较。目前未得到新的模型比较结果。

### 10:13 JST 只读续查

[最新状态收据](gpu-control-20260914-v3/status-20260914T011312Z-p2d6xfhu/receipt.json)
确认远端仍只有DEPLOYMENT日志，未出现授权或提交意图；本地也没有提交意图。
该次没有提交、更新或重试任何作业。现有协调器保留双冷进程和完整数组/
168采集的严格验收，不能把status/进程退出0替代实际结果验证。
缺少新的一次性GPU资源授权，暂不能取得新的生产结果。
[授权边界审计](2026-09-14-gpu-v3-resource-authorization-audit.json)仅记录等待条件，
不是授权文件；原SSH连接问题已解决，与当前资源授权阻塞不同。

## 已取得证据

- [原生 CPU 收据](startup-probe-remote-20260914T002026Z-9etqy2ka/receipt.json)：
  HAKUSAN Python3.11.5 / torch2.1.1+cu118，两个新入口均通过原始 scratch
  类型绑定、空缓存/目录和关闭检查；未初始化 CUDA、加载生产模型或执行 forward。
  三个子进程合计84.093秒，传输全过程94.197秒。
- 原生 CPU 上的旧入口这次**没有复现**历史 GPU 目录冲突，不能据此宣称
  已动态证明705468的 GPU 根因或完成 GPU 验收。新入口把 scratch 创建
  移到数值库导入之前；需要后续实际 GPU 验证。
- [独立 CPU 证据复核](2026-09-14-gpu-v2-native-cpu-review.json)重新校验了
  51个载荷源文件及日志、PID、版本、清理状态等，旧包与新包哈希保持一致。
- [v2部署](gpu-control-20260914-v2/deploy-20260914T002911Z-3csrpo3s/receipt.json)
  已发布55个文件；[v2 test-only](gpu-control-20260914-v2/test-only-20260914T003105Z-z8030g1b/receipt.json)
  失败，错误为 typed/untyped GRES 混合。原始远端记录另存于
  [test-only原始JSON](2026-09-14-v2-test-only-error-raw.json)，SHA256
  `914e234feac282015ed2540370d47046392c3581505acd2f4f110e52d1a647f7`。
- [三个不同的最小 test-only 参数对照](slurm-gres-test-only-_p2vhb3q/receipt.json)：
  `--gpus` 单独或配合 `--gpus-per-node` 都被拒绝；仅
  `--gres=gpu:nvidia_a100:1` 通过。全部使用 `--test-only`，0个实际提交。
  输出713298只是调度估计编号，不是新作业。

## 这次修改范围

在独立 v3 包中改为单节点 `--gres=gpu:nvidia_a100:1`。
资源仍是1A100、8CPU、64GiB、2小时；不改模型、数据、阈值、32试验范围、
16→1 batch对照或168个采集验收。正式放行前仍要求暂扣作业的
ReqTRES、TresPerNode及独立记账明确匹配一张A100；不接受泛型GPU代替。
TresPerJob允许未列出，但如列出只能是同一张 typed A100。

集群启用了 JobSubmitPlugins=lua，但登录节点未提供其源码，因此
不能断言混合类型来自哪个集群插件。Slurm官方说明 typed/untyped
请求需要一致，`--gres` 是每节点请求；固定单节点不会扩大GPU数量。
参见[官方GRES说明](https://slurm.schedmd.com/gres.html)。

## 授权与科学边界

本轮只做本地修正、独立发布和调度 test-only，不实际提交新GPU作业。
705468已经用完旧的一次性授权，不能把旧授权搬到v3。最终目标仍是
formal40与作者checkpoint的完整同数据比较，valbest33为次要模型；
本阶段的工程/CPU检查不是最终比较结果，也不是独立测试集结果。
