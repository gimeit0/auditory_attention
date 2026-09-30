# Job 680519：执行集合类型校验失败取证

日期：2026-09-09。范围为诊断与本地有界复现，不修改发布的 v7、不提交新作业。

## 用户回传的远端事实

- 作业 680519，诊断协议 formal40_batch_invariance_diag_20260903_v7。
- Slurm FAILED，退出 2:0，00:02:05，spcc-a100g04。
- 公开 verify-results 返回 DIAGNOSTIC_FAILURE_RECORDED，VERIFY_RC=2。
- primary_error：execution / EXECUTION_FAILED / child exit is nonzero: 2。
- 子进程 stderr：`diagnostic error: unsupported execution collection type`。
- post_errors=[]，lock_acquired=true，matrix=null。
- 工件只有 ENVIRONMENT.json、PRECHECK.json、POSTCHECK.json、RUNNING.json；
  没有参考推理或 cell 的完成工件。
- numeric_results_interpretable=false、results_verified=false；READ_RC=0 是
  取证读取成功，EVIDENCE_RC=2 保留了诊断失败返回值，不是新一次提交失败。

证据哈希：

| 对象 | SHA-256 |
| --- | --- |
| v7 freeze | `6b1f2dde8c1c173f58f7757fb6ca89055faca367d5e4f45301fc97e2d3f75920` |
| DIAGNOSTIC_FAILED.json（141759 bytes） | `2ecd6af2807d9315b4c5d1938188f0d0bf59e40fa544cee9132e7cfbffa57628` |
| artifact inventory | `36ed986fb5353d29f2796cf9a72ec13cd09105bc741e08f0e700763b0ab86ec8` |
| Job 680519 日志 | `92ad39871c7d20b36405bc78464a351c6842bbb5b220df99213337cd51f1dd92` |
| PRECHECK.json 与 POSTCHECK.json（各 69770 bytes） | `2187e9dafc18b33430c2af50640fb9e9a08d2478bc9161fbf6bfc024ea3e496c` |

PRE/POST 哈希相同且无 post_errors，说明记录范围内的输入/树后检未报告改变，
不能外推为整个共享文件系统完全未变。此次报错不同于 v6 的运行设置错误；
日志缺少 traceback/属性路径，不能只凭耗时和打印行定位确切实例属性。

## 本地代码证据

v7 `_container_execution_identity` 对 tuple/list/set/frozenset 使用精确类型
分支，剩余 Collection 在第 910–911 行抛出上述错误。该分支可能拒绝多种
类型，不只一种。`_module_config_fingerprint` 会递归记录未豁免的实例属性，
其中 `_amp_overflow_window` 不在观察属性排除集合内。

本地 `projects/auditory_attention/src/spatial_attn_lightning.py` 的 SHA 为
`6531a6548cc24dcdcffdb14c8b6b1d7040bc6f1f7ea53dd870d4d021327467c9`，与之前
远端冻结快照清单中同一路径的 SHA 相同。其第 37 行明确构造
`self._amp_overflow_window = deque(maxlen=overflow_window_steps)`。严格加载器
实例化该模型并恢复 checkpoint；诊断器随后为模型执行配置建立身份指纹。

现有真实 evaluator 生命周期测试使用合成的小型模型类；已有一项安全回归
甚至将新插入的 deque 用作应被拒绝的集合。这些测试不能证明真实冻结模型
已有的 deque 配置可通过，因此此前 479 项通过不覆盖这一兼容性问题。

## 本地复现计划与边界

探针 `2026-09-09-job680519-collection-probe.py` 核验 v7 诊断器及上述模型源码
SHA，通过 AST 仅提取并执行被审阅的 deque 构造表达式，再比较普通容器、
该 deque，以及附带同名属性的最小 torch.nn.Module 的配置指纹结果。
不执行完整模型构造、不读取 checkpoint/音频、不进行 GPU 运算或修改生产代码。
maxlen=1000 为源代码默认值对应的本地夹具，不是读取的远端队列状态。

即使该复现失败，也只能证明一个真实源码必然涉及的兼容性缺陷；远端报错
没有属性路径，尚不能证明这是 Job 680519 第一个或唯一被拒绝的集合。
下一步如授权修复，应在独立候选中先写此源属性回归和拒绝恶意子类/可调用
元素/内容变化的测试，再设计有界显式类型处理。不得直接放行所有 Collection、
删除该字段、转换原模型状态或降低科学数值容差来绕过错误。

## 本地实际复现结果

在 `/opt/anaconda3/envs/audattn/bin/python -I -B` 独立进程运行上述探针，
torch 2.12.1，进程退出 0（表示预期失败复现成功，不是 v7 已修好）：

```text
status=LOCAL_COMPATIBILITY_FAILURE_REPRODUCED
source_line=37
plain_list=accepted
plain_tuple=accepted
source_amp_overflow_window=unsupported execution collection type
plain_torch_module=accepted
module_with_source_window=unsupported execution collection type
torch.Size([1, 2])=unsupported execution collection type
```

这证明：不必推理或改变 checkpoint，仅给最小模块添加冻结源码本来就有的
deque 属性，v7 配置指纹就会触发与远端相同错误。torch.Size 也能触发同一
通用消息，进一步说明远端没有属性路径时不能确定首个实际触发对象。
此前源码哈希核验保证 deque 来源不是本地另一个修改版本；复现后候选
十一文件 SHA 再验全 OK。未修改原 v4、诊断 v7、训练模型源码或集群文件。

修复建议（尚未实施/发布）：保留 v7 和 Job 680519，在独立本地候选中先
补真实源属性的正向回归，改进拒绝消息以包含静态类型和属性路径；对必要的
精确类型设计有界身份/内容封装，并持续检测内容、maxlen、替换及可调用
子项改变，维持未知/恶意子类拒绝。再检查实际模型配置涉及的其他集合类型，
补端到端本地覆盖；不能以合成小模型全绿声称真实 A100 链路已验证。
本次只完成诊断和复现，尚未创建 v8 或改变验收规则。
