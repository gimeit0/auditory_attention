# 2026-09-15：v19 扫描优化独立加载/观测链本地验收

结论：**本地集成候选通过，不是 GPU 运行包已可提交。** 新版实际文件加载器、
reference bridge、观测/编译准备、归档适配器及新旧冻结关系检查已形成独立
版本并完成测试。GPU coordinator/child、启动/scratch、计时、结果 verifier
和提交控制器尚未绑定 v19 及其新 freeze；本轮没有网络操作、部署、冻结或
GPU 提交。Job715276 的旧授权已消费，不能复用。

## 改了什么

- [诊断 v19](../../../same_bank_eval_2026_09_03_v4_numeric_diag_v19/README.md)：
  新协议/新远端目录，单函数 `_live_protected_module_bindings` 优化。除版本
  字符串及该函数外，所有顶层语句、函数/类 AST 一致。
- 七组 `*_20260915_scan` 独立副本，依赖 SHA 按序更新；共 44 份生成源码。
  新 loader 读取实际 v19 文件，签发自己的模块/函数身份，不改旧模块或旧
  `_LOADED` 注册表。两版源码与已加载模块不能互相冒用。
- [冻结关系检查](../prototypes/guard_scan_integration_20260915/freeze_relation.py)：
  pin 新源码清单，确认新清单绑定四份新程序；科学输入必须与旧 v18 对照
  相同。只允许原 NFS 策略的 dev/inode/mtime 诊断字段变化，不能改输入内容、
  模式、顺序或使用关系。测试清单仅在内存中合成，**没有生成真实 freeze**。
- [本地说明和复核命令](../prototypes/guard_scan_integration_20260915/README.md)。

旧 v18 freeze `bd16929c21fcf740e12b5605e09c75be7138cba218b77977d1281c560ef43178`
只作 Job685198 的数据/数组对照身份；v19 validator 明确拒绝直接使用它。
新 v19 freeze SHA 尚未取得，未填写假值或把旧 SHA 标成新 SHA。

## 完成的测试

本机 Python 3.11.15、PyTorch 2.12.1，CPU 合成模型/隔离夹具；没有真实
formal40 checkpoint、A100、Inductor 或 HAKUSAN v19 生产执行验收。
编译便携测试使用的合成对象不代表真实编译后端已验收。

| 检查组 | 项数 |
|---|---:|
| 原 23 个诊断测试入口（每文件独立进程） | 751 |
| 新版本/加载身份/原源码范围 | 15 |
| 新旧冻结清单关系及拒绝反例 | 15 |
| reference bridge | 17 |
| 观测生命周期 | 25 |
| 加载后准备接口 | 18 |
| 合成编译接口 | 16 |
| CUDA 适配器的 CPU/静态检查 | 30 |
| 归档及 reference 合成集成 | 38 |
| 合计 | **925** |

31 个不同 PID、零跳过/失败/错误、全部正常退出。完整 16→1 生命周期仍有
34 次模型调用及一次严格加载；继承的准备/观测/归档反例全部通过。
每个测试入口最多 240 秒，最多两个入口并行，无自动重试。
另执行 `bash -n` 检查继承 runner 语法、诊断 CLI `--help`，均退出 0；未运行
runner 本身、freeze、sbatch 或真实推理。

## 原始证据与独立重验

最终证据目录使用 UTC 命名，执行/记录日期为 JST 2026-09-15：

[最终回执](scan-integration-local-20260914T174911Z-l79415yn/receipt.json)

- 回执 SHA：`5442bb34968994cec549a690529d1c5ec57e6eecdcccbc0e05fae8d7d21d50b4`
- 44 文件清单 SHA：`93508d886b6608dcdb31a4d84e7a033716cfb53fa80e62cb019743f18aeb28bd`
- v19 诊断程序 SHA：`c1ba3af9da8fb2be6e197fddbee38a03c0ef3a8f67da75e7abc0b1a9f568b50d`
- 扫描模板 SHA：`afb98f56aa2e17716ddc6ab52a2a684a7b345c78d63d9268cc0ce149577202d1`

[独立只读复核程序](2026-09-15-scan-integration-review.py)逐 SHA 重读了新包与
测试入口等 50 份来源、89 份父来源、62 份日志/结果工件，核对回执/PID/计数
及全部顶层 AST 差异，返回 `OFFLINE_INTEGRATION_REVIEW_PASS`。父来源包含
原冻结 GPU v4 控制/运行包、原诊断/回归及共同依赖；不是 89 份新的程序。
构建配方只读重算也返回 `INTEGRATION_SOURCES_EXACT`。

```bash
cd "$HOME/发表/超算"
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/evidence/2026-09-15-scan-integration-review.py \
  docs/superpowers/evidence/scan-integration-local-20260914T174911Z-l79415yn
```

## 两轮失败测试入口保留，不计作通过

1. [首轮回执](scan-integration-local-20260914T174146Z-3bsjr_ap/receipt.json)：
   错将 23 个测试模块合并 discovery 到同一进程，私有加载名称冲突；core
   共执行 751 项但 3 failure/284 error。改为历史 runner 使用的逐文件冷
   进程方式，未改保护规则。其余七组当轮通过也不冒充整轮通过。
2. [第二轮回执](scan-integration-local-20260914T174547Z-lpwkchvb/receipt.json)：
   编译生命周期的 24 项已打印 OK，但汇总入口随后额外 `import torch`
   阶段进程以 -11 结束，未产生该组回执；整轮仍判失败。直接执行原 v18
   和新 v19 同一测试均 24 项、退出 0。修正汇总为只读已加载模块，通过
   包元数据读取安装版本，不额外导入数值库；随后完整 925 项重跑通过。

第二轮后额外固定了冻结关系模块的清单 SHA，并加入清单被改的拒绝测试。
这些都是本轮测试/关系工具修订，**v19 诊断库及七组生成适配器字节不变**。
未删除任何失败日志，未给失败回执改状态。

## 下一步（未执行）

将已验收的 v19 加载链和冻结关系检查接入独立 B2 双进程运行/验收入口：
启动 scratch、child 的 live 输入前后检查、新旧 freeze 的不同字段、数组
归档及终态 verifier 必须全链绑定；加入旧授权/旧 freeze/混版工件拒绝测试。
然后做冷进程集成审核，再受控部署/审计冻结，取得并审阅真正的 v19 freeze
SHA；新 GPU 资源授权确认后才可单次提交。

计划 B2 作业仍为 1 A100 / 8 CPU / 64 GiB / 2 h，child 3000 s、pair 6600 s。
v19 保留的历史全矩阵 runner 4 h / child 5400 s 只是库回归依赖，不是本轮
可提交入口或新的资源授权。不得直接运行它，也不能复用旧 GPU v4 提交脚本。

本次通过不证明实际 A100 的 3000 秒超时已解决，也不消除原 batch-size NLL
差异。最终 formal40 vs 作者 checkpoint 比较仍未完成，数据角色仍是
`REUSED_VALIDATION_BANK_AUDIT_NOT_INDEPENDENT_TEST`，不能当作独立测试结果。
