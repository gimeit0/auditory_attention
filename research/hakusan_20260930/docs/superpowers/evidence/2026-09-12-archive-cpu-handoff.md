# 归档CPU复验：认证后立即执行，避免人工交接间隔

## 最新结果：单次入口已经执行成功

2026-09-12用户完成该入口，REMOTE_ARCHIVE_LOCAL_RECHECK=PASS、
ARCHIVE_CPU_PIPELINE_RC=0。代理已独立核对31项远端测试及21份回传工件，
见[验收记录](2026-09-12-archive-remote-verified.md)。本次无需重跑。

## 历史：创建入口时的连接阻塞

2026-09-12 JST。用户在Mac运行原连接入口，00:16:08启动master pid78129，
00:16:28远端身份确认通过。随后同一master日志末尾出现
`client_loop: send disconnect: Broken pipe`。代理00:18检查时进程已退出、
master.sock不存在。不能把两分钟前的连接PASS当作当前仍连接。
这不是12小时空闲到期，日志不足以区分网络变化、休眠或服务端中断的原因。

连接私有记录位于`.hakusan-control/logs/connect-20260911T151558Z.iDmyPh/`，
保留原件，不公开整份日志。00:18之后读取的SHA：

- events.log：d636562b7f5c7633f0375690ec4708ee35eb12c61ae928a697e00e6147eb779b
- master-ssh.log：6c7f627c03c0ea3e0f65306771ac88e5932bb50e069762e9195507db7ebdf3ff

归档驱动的`--run`本次在本机socket检查处停止，没有发起驱动的远端命令，
没有新增远端CPU证据、上传生产工具、freeze或提交GPU作业。此前31项本地
检查与三组合成独立进程测试仍有效；**新增归档的超算同版本复验仍未执行**。

## 新单次入口

[2026-09-12-archive-cpu-connect-run.sh](2026-09-12-archive-cpu-connect-run.sh)
先校验原连接脚本、归档驱动及载荷；用户输入SSH密码并认证后，立即检查
master是否存活并调用原CPU驱动一次。避免先认证、回聊天等待代理接手的间隔。
它不能修复网络本身；保留终端运行、网络稳定，仍可能发生提前断线。

在Mac终端运行，只复制代码，不复制提示符或历史输出：

```bash
cd "$HOME/发表/超算/docs/superpowers/evidence" &&
bash 2026-09-12-archive-cpu-connect-run.sh --run
```

密码只输入SSH提示，不写入脚本或聊天。无需先单独运行connect脚本。
`--check-only`（或不传参数）仅本地校验，不连接、不加载模型、不提交作业。

原CPU驱动仅在私有/tmp中测试固定源码：31项CPU单元检查、一组dependent
独立进程对照及21份小型合成工件的回传/本地完整复核。原60秒单元进程、
每冷子进程60秒、pair监督150秒、SSH调用270秒限制保持；不使用Slurm。
正常完成清理专属远端临时目录；失败不会自动重连或重试。不要因网络中断
就自动重复执行，先看保存的日志及回执。

成功必须出现`REMOTE_ARCHIVE_LOCAL_RECHECK=PASS`及
`ARCHIVE_CPU_PIPELINE_RC=0`；仅连接PASS或默认本地校验PASS不等于复验通过。
完整记录路径由`ARCHIVE_REMOTE_EVIDENCE=`给出。此时仍只是CPU原型测试，
不是Inductor/A100、生产worker能力或最终模型比较验收。

## 本地验证

新入口Bash语法检查通过；真实`--check-only`固定源码/载荷校验通过、RC=0。
[离线入口测试](../../../local_tests/test_archive_cpu_entry.py)9项全部通过，
耗时2.237秒，Ruff通过。测试仅在临时目录替换连接/Python/SSH入口，覆盖：
默认不连接、单次顺序、连接失败、socket失败、复验失败保留退出码且不重试、
载荷错误、源码SHA错误、符号链接、错误参数。没有真实SSH或模型调用。
这9项是入口行为测试，不与归档31项混称为40项科学/超算测试。

新入口SHA：e23b20a61d03afd97b6d2c572232fe054ba224dfb603cae42653a72019dab617

新测试SHA：ab59c6969b65e0e027fe5f70f6d7a43489f9dc1114633c87aa25dfa72b50300e

原连接脚本SHA601ca2e…与原CPU驱动SHA93eb072…保持不变；没有改动任何
实验设置、数值容差、已冻结工具或既有证据。
