# v19 扫描优化：独立加载与观测链候选

本轮范围是**本地集成**，不是已部署的 GPU 作业，也不是最终模型比较。
v18、Job685198 对照工件、Job715276 失败证据及已发布 GPU v4 包保持原样。

实测：31 个独立进程、925 项通过（原诊断 751 项），独立离线复核通过。
完整证据、两轮测试入口失败记录及剩余事项见
[本轮验收记录](../../evidence/2026-09-15-scan-integration-verified.md)。

## 代码身份

新诊断库位于 [v19](../../../../same_bank_eval_2026_09_03_v4_numeric_diag_v19/README.md)。
与 v18 相比，只变更诊断协议/远端目录版本和已通过 CPU 复验的
`_live_protected_module_bindings`。所有其他函数和类的 AST 保持一致；
参数、buffer、hook、运行时、导入绑定的检查次数和失败规则不删减。

七个 `*_20260915_scan` 目录是独立副本：baseline bridge、观测生命周期、
准备适配器、编译登记、实际模型登记、CUDA 准备以及归档适配器。
依赖 SHA 按顺序重新绑定；`load_v19` 读取真实 v19 文件，登记自己的模块和
函数身份。旧 loader 拒绝新源码，新 loader 拒绝旧源码和非自身签发模块。
不是给旧模块换一个函数，也不向旧 `_LOADED` 注册表塞入候选。

旧准备与 forward 循环语句不变；“original”出现在继承的字段名中时，指
相对于该适配器所绑定诊断库的原始语句/记录，**不表示执行源码仍是旧 v18**。
具体执行版本以 v19 协议、实际文件 SHA 和新清单为准。

## 两种冻结身份不能混用

- 旧 v18 freeze `bd16929c…ef43178`：仅作 Job685198 数据/数组对照来源。
- 新 v19 freeze：**尚未在 HAKUSAN 创建，SHA 未知**，不填写虚构值。
- [freeze_relation.py](freeze_relation.py) 检查未来新清单的四份程序 SHA，以及
  与旧清单相同的科学输入。仅原有 NFS 诊断字段 dev/inode/mtime 可不同；
  trial 顺序、音频、checkpoint、bank、快照、权限及使用关系不能改。
- 关系检查不是生产授权。将来的入口还必须绑定审阅过的新 freeze SHA、
  校验整个运行包，并调用 v19 原有 live 输入前后检查。

## 当前明确未完成

GPU 双进程 coordinator/child、启动 scratch、计时器、结果 verifier 和提交
控制器**尚未接入 v19 与两份 freeze 的关系检查**。已生成的适配器不可直接
塞进旧 GPU v4 作业。继承的远端 CPU 入口主动拒绝运行，避免偷用旧 v18 路径。

没有上传、远端冻结、正式模型 forward 或新 GPU 提交。下一阶段必须完成
上述入口绑定、冷进程/归档验证及审核，才可部署；新资源授权需单独确认。
计划中的 GPU 对照上限仍是 1 A100 / 8 CPU / 64 GiB / 2 h，单 child 3000 s、
pair 6600 s。本候选没有扩大它们。

v19 目录保留的历史全矩阵 runner（4 h / child 5400 s）只是原库的回归依赖，
**不是本轮可执行的提交入口，也不是新的 4 小时资源授权**。不要运行它。

## 本地复核入口

以下均不连接超算、不提交作业。正式测试结果以独立证据记录为准。

```bash
cd "$HOME/发表/超算"
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/guard_scan_integration_20260915/build_release.py
```

需要重新做完整本地回归时才运行（每文件独立进程，最多两个并行，单进程 240 秒）：

```bash
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/guard_scan_integration_20260915/validate_local.py
```

`build_release.py --create` 只用于首次生成缺失的新文件。默认只读复核，已有
不同内容会拒绝，不能覆盖冻结版本或已存在的候选。新源码共 44 份，另有本轮
关系检查、回归入口及文档；完整依赖与父来源记录见 `SOURCE_MANIFEST.json`。
