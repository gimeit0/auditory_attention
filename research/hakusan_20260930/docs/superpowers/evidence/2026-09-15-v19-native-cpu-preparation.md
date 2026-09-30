# v19 原生 CPU 兼容性入口准备完成；远端待认证

日期：2026-09-15 JST。对应用户“下一步”。

## 本轮实际完成

已准备独立、固定范围的 HAKUSAN CPU 兼容性入口，不修改上一阶段冻结的 v19 运行包或历史证据。
新入口 12 项离线拒绝测试通过。相同载荷在本地 5 个全新 Python 进程中完成 80 项测试，
失败/错误/跳过均为 0，载荷耗时 22.338 秒；临时目录清理成功。
本地 Python 3.11.15 / torch 2.12.1，不能代替 HAKUSAN 原生版本验证。

完成后的只读复核也已通过：163 份载荷文件、完整请求、原始输出和 5 份子进程日志均匹配；
shell 入口语法及 `--check-only` 通过。上一阶段 162 份源码、17 份精确派生关系和 20 份测试工件
重新复核通过，未被本轮修改。

回执 `LOCAL_CPU_HARNESS_VERIFIED` 中字段名 `remote` 是载荷执行端的通用名称；
其实际 `mode=LOCAL_HARNESS`，本次没有通过 SSH 执行。检查时共享 master socket 不存在，
已请用户在自己的终端认证。没有尝试索取密码、自动重连、永久部署、冻结输入或提交作业。

## 已检查的边界

- 输入包固定为上一阶段 162 份源文件及其清单；逐字节绑定，并在每组后复查。
- 原生执行限制为 HAKUSAN 登录节点、指定账号及 Python/torch 版本、单 CPU、总计最多 90 秒。
- 仅创建私有临时源/缓存文件，保留账号 HOME，不改现有远端目录；成功必须确认清理。
- 五组测试覆盖输入绑定 25、启动 12、结果身份 11、适配器 CPU 30、scratch 生命周期 2。
- 请求/结果/日志身份、缺失或重复组、异常退出、清理失败、GPU 标记、超时和版本不符均拒绝。
- 仅合成 CPU 测试；真实模型、CUDA、Inductor、实际 mount 工厂和 A100 超时均未验收。

80 项是已有测试的兼容性子集，不应与上一阶段 162 项相加作为新的独立覆盖率。

## 证据及入口

- [本地回执](v19-local_harness-20260915T042507Z-joll00yp/receipt.json)：`97eda2c2b8c24580dac42de05e7352d84705949ed49967af52c546efc1639742`
- [原始载荷输出](v19-local_harness-20260915T042507Z-joll00yp/output.log)：`4f86cc1efd737b2094b1ba8a135387b3c97cc85d066f00f2b65a81c9ea22e3eb`
- [新检查器源码清单](../prototypes/targeted_pair_native_20260915/PROBE_RELEASE.json)：`4d2f742eea588eaaea8015538f48c8122d1258ed795c276eb86272d4840128da`
- 已冻结运行包 SHA：`c0b421d01d394f1fd3354eb74eb730e2d348cf4a37d0fb96f76a019c71c5aa20`，未改动。
- [只读本地证据复核](2026-09-15-v19-native-local-review.py)：核对回执固定 SHA、完整请求源码和五组日志，不执行请求，不连接网络。
- [用户运行入口](2026-09-15-v19-pair-native-cpu.sh)：先核对 driver/release/本地回执，再运行固定远端检查。

## 接下来执行

在 Mac 终端（不是 HAKUSAN shell）运行，密码仅输入 SSH 提示：

```sh
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-10-hakusan-connect.sh &&
bash 2026-09-15-v19-pair-native-cpu.sh
```

最终需要 `NATIVE_V19_COMPATIBILITY_VERIFIED` 与 `V19_NATIVE_CPU_RC=0`，并审阅新回执。
失败则保存回执路径和末尾错误，不自动重试，更不要运行旧 submit 脚本。
通过仍不代表允许 GPU 提交：下一阶段还需独立部署控制审核、新清单和新资源授权。
本轮 `ready_for_gpu=false`、新 freeze 未取得、实际新作业数为 0；最终三模型比较仍未完成。
