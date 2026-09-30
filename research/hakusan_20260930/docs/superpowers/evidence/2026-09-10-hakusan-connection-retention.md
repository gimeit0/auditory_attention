# SSH 连接工具：12 小时空闲保留与私有日志

2026-09-10。用户明确同意修改连接脚本。仅改 Mac 连接工具及新增离线测试，
不改实验代码、冻结输入、科学设置或作业；不关闭或重启当前 master。

入口仍为：

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

## 行为

- 新建 master 使用 `ControlPersist=43200`，即没有客户端会话时空闲保留 12 小时。
  保活仍为 30 秒 / 3 次，连接超时仍为 12 秒。
- 已存在的正常 master 原样复用；不能追溯改变其超时或日志参数，输出明确说明。
- 失效 socket、非 socket 文件或符号链接均停止，不自动删除、覆盖或重连。
- 每次运行创建 `.hakusan-control/logs/connect-<UTC时间>.<随机后缀>/`。
  控制、日志目录为 700，日志文件为 600；之前的日志不覆盖、不自动清理。
- `events.log` 保存本次脚本的 UTC 生命周期与退出码。
  `check-ssh.log` 保存本次检查诊断。
  仅新建 master 时生成 `master-ssh.log`，记录 DEBUG1 及直接 stderr；
  后台进程可在连接脚本退出后继续记录断开事件。
- 日志含主机名、用户名、路径、密钥指纹等连接元数据，不应公开整份日志。
  不录制终端会话，不读取或存储 SSH 密码；密码仍只由 SSH 终端提示读取。
- 不承诺连接永不断开；休眠、网络故障和服务端关闭仍可能导致提前断线。

采用 DEBUG1 是为了覆盖正常的 `ControlPersist timeout expired` 记录；
只用 INFO/VERBOSE 不足以得到这一诊断信息。
依据：[OpenSSH 10.0 客户端源码](https://github.com/openssh/openssh-portable/blob/V_10_0_P1/clientloop.c#L1527)、
[SSH 日志参数](https://man.openbsd.org/ssh#E)和
[ControlPersist 语义](https://man.openbsd.org/ssh_config#ControlPersist)。

## 验证与限制

- Bash 语法检查通过；Ruff 检查及格式检查通过。
- `local_tests/test_hakusan_connect.py` 的 12 项离线测试通过。
  测试在临时目录内替换 SSH 可执行文件，覆盖新建、复用、重复日志保留、
  认证失败、远端探针失败、失效 socket、符号链接和目录权限拒绝路径。
  没有实际 SSH 登录、密码输入、作业提交或真实网络故障注入。
- 实际本机 `/usr/bin/ssh -G` 解析出 `controlpersist 43200`、
  `serveraliveinterval 30`、`serveralivecountmax 3`、`loglevel DEBUG`。
- 修改前后只读 `ssh -O check` 均看到现有 master pid=49656；未关闭它。
  该旧连接不因此变成 12 小时版本。尚未新建实际 12 小时连接，也未做 12 小时等待测试。

脚本 SHA256：`601ca2e23d7d4907b39a3b72d601decb012d5eacfa5fecdb6833d1bc291f347a`。
测试 SHA256：`bf5f2aa931610d2fae33ff4e762a952f5d3cf7d01949333f49e288f7eea1f06f`。
