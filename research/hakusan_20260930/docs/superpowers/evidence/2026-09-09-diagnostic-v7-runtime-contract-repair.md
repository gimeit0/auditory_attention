# 诊断 v7：冻结运行设置读回校验修复

日期：2026-09-09。用户授权：“执行下一步”。当前阶段：本地实现与验证完成，
尚未部署、冻结或提交 v7；原 NLL canary 与三模型 10k 比较仍未完成。

## 已知证据与有界计划

Job 671724 在模型严格加载前报 frozen runtime settings are not exact。
用户的集群 PyTorch 2.1.1+cu118 探针读回 medium → high、退出 0。
原冻结 evaluator 依次设置 medium、cuda.matmul.allow_tf32=True 和
cudnn.allow_tf32=True；不改变这些真实操作来迁就诊断器。

1. 保留已发布 v6 和旧候选清单，创建独立 v7 根及协议。
2. 新测试在未修复逻辑上复现 high 被拒绝；覆盖读取异常不得代填配置。
3. worker、冷参考等价、cell、持久结果解码共用严格的六项预期，精度为 high。
4. 错误包含实际值、期望值、torch 版本/读取错误；其他五项仍精确检查。
5. 本地 2.12.1 与生产 2.1.1 不同：明确区分测试替身和真实 getter，不能把
   模拟通过称为生产 GPU 验收，也不能在生产逻辑中伪造 getter 值。
6. 完成专项 RED→GREEN、既有各测试模块、静态/格式/runner 检查、旧版本
   SHA 及新候选清单。不得改变 checkpoint、bank、SNR、角色、AMP/TF32
   设置、batch 矩阵、数值比较函数或容差。

## 验证结果

先记录探针与授权，再经 apply_patch 创建独立 v7 的 11 个候选文件；没有覆盖
v6。原 v6 十文件候选清单在复制前、最终复核时均通过。未进行远端操作。

### RED → GREEN

将 CPU 夹具的最终读回改为明确的 high，保留旧生产逻辑时，worker 准备、
冷参考等价和持久结果复验三项回归全部失败（1 failure、2 errors，1.177 秒）。
报错分别为 frozen runtime settings are not exact、reference equivalence
runtime is not exact、persisted worker PID/runtime/scratch differs from launch。
修复后同三项全部通过，3.566 秒。日志保留在 v7-runtime-contract-red.log、
v7-focused-green.log；并非通过忽略错误、放宽阈值获得 GREEN。

v7 的 `_FROZEN_NUMERIC_RUNTIME` 使用不可变 MappingProxyType，四处校验共用
同一个六字段合同，精度 high；要求字段集合、值及类型均完全一致，不接受
整数 0/1 冒充布尔值。`_read_frozen_numeric_runtime` 逐项读取，不设置任何标志；
任何读取异常都作为实际错误记录拒绝，不再执行伪造 medium 的兼容回退。
live worker 错误带 expected/actual/torch_version；后续元数据错误带 expected/actual，
其 worker 软件版本仍由既有环境证据保存。

### 本地完整测试（各模块独立进程）

| 测试入口 | 结果 |
| --- | --- |
| test_numeric_diag.py | 344/344，96.302 秒 |
| test_submit_numeric_diag.py | 66/66，11.347 秒 |
| test_loader_record.py | 6/6，0.288 秒 |
| test_real_evaluator_scope.py | 28/28，1.329 秒 |
| test_v4_manifest_json.py | 21/21，6.747 秒 |
| test_runtime_contract.py（新增） | 14/14，1.361 秒 |
| 合计 | 479 项通过；focused/mutation 重跑不重复计入 |

测试环境为本地 Python 3.11.15 / torch 2.12.1（无 CUDA 构建），不是生产
2.1.1+cu118 / A100。既有玩具 CPU evaluator 直接设置 high 来建立预期最终
状态；这项夹具改动明确注释为模拟，不修改原冻结 `_configure_runtime`。

新增专项从 SHA 验证过的真实冻结源码提取并执行 `_configure_runtime`，配合
独立的 2.1.1 Context.cpp API 语义模型覆盖 medium→TF32→high；同时在真实
本地 torch 上执行该源码，确认 getter 发生 API 混用异常时诊断器明确拒绝。
测试不替换真实 getter 的结果，也不把这类拒绝称为生产兼容成功。
新测试初次将原 seed 误写为 0，真实源码执行返回 20260829；已修正测试预期，
没有改动生产随机种子。新增测试覆盖所有六项异常、字段缺失/多余/错误类型、
异常不代填、模型加载前停止、四个 cell、两侧冷参考和持久 worker 校验。

### 主代理有界复核与静态检查

- AST 比对确认：除两项诊断版本标识、运行预期常量、四个校验函数及新增
  两个辅助函数外，整个诊断 AST 与 v6 相同；数值运算和阈值未改。
- numeric_trace.py 字节完全相同；提交器及 runner 只替换诊断 v6→v7 根/协议。
- 原评估 v4 evaluator/runner 固定 SHA 不变；v6 十文件清单不变。
- 分别在内存恢复四处旧校验（持久校验恢复旧 medium 常量），测试全部识别
  退化；未改任何候选文件。这是主代理自查，不是独立子代理审查。
- Ruff check、format check、bash -n 和三个只读 CLI help 入口通过。
- README 内十文件 SHA 与外部十一文件候选清单均校验通过；格式工具生成
  的本次缓存已清理，候选目录只有十一份交付文件。

所有日志和清单位于
`.superpowers/sdd/2026-09-03-v4-numerical-diagnostic-implementation/v7-*`。

### 固定候选身份

| 文件 | SHA-256 |
| --- | --- |
| diagnose_batch_invariance.py | `7e18242bf96be03e8e50e713be877b4a52c321c6874cb81bca2b9955db924167` |
| numeric_trace.py | `fa950c751f5accb9176733c05faefe0a9b907a68135efe29cbae2b01e61ae38b` |
| submit_numeric_diag.py | `d74c4878ccd5e9c79cd3854139009c1d2c5449df846082667ac7407ade474e86` |
| run_numeric_diag.sbatch | `19c0d314f5ec1c8c3d93eae8a04c7c33d38b98079f1ee447cfabe95dacad0b62` |
| README.md | `21bc6061d0f4cfd1315ff19e0211757c0cc4bfa484f9a4251a5ce2f9b4078be4` |

完整清单为 `v7-candidate-manifest.sha256`。新协议为
`formal40_batch_invariance_diag_20260903_v7`；预定远端根为
`/home/s2510040/audattn_external_eval_diag/same_bank_v4_job646900_2026-09-03_v7`。
本轮没有创建该远端根，没有 v7 freeze SHA 或 Job ID，不得复用 v6 的
`c04bccfdb2b5bf88b8acb65c70265fd014f88c1b247d2aaa625c9b995c984cfc`。

## 下一阶段

先核对远端旧证据、原 v4 manifest/lock、队列和新 v7 根未占用，再按受控
流程上传、校验、发布、audit/freeze/check-only，核对新 freeze 后单次提交。
部署前可在同一 attn Python 新进程复验全部六个运行标志；已回传短探针只
确认版本与 precision 联动，不能代替这六项或实际 GPU 执行验收。
现有 CPU 合成矩阵、传输/持久化通过不代表真实 checkpoint/音频诊断通过。
原 Job 646900 的 NLL 差异 0.0077362060546875 仍待数值诊断解释；本修复没有
发布 SMOKE_PASS，也没有完成三模型 10k 对比。
