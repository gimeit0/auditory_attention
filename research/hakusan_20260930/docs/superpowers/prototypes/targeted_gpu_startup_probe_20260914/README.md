# HAKUSAN同版本启动复验入口（无模型、无GPU、无提交）

2026-09-14。验证新的49文件GPU候选所使用的真实库导入链与原scratch工厂。
旧/新reference和新observed各为全新CPU进程；不会调用gpu_child.run、
模型准备、forward或任何Slurm命令。不是分配到计算节点的GPU作业。

远端模式固定Python3.11.5、torch2.1.1+cu118、s2510040/Linux，保留原
Linux本地挂载检查，不使用本地测试stub。bootstrap在新建的/tmp私有目录
展开51份来源（49份包文件＋新manifest＋probe_child），用后清理；不发布
到生产或诊断root，不修改HOME或旧v18输入。

三个子进程合计最多85秒，每个最多45秒、日志256KiB；传输预算115秒，
失败不自动重试。设置合成目录标签只为调用原目录工厂，记录明确
`allocation_claimed=false`、`jobs_submitted=0`，不伪装为真实Slurm作业。

## 本地结果

- [完整打包/回传格式自测](../../evidence/startup-probe-local-20260913T173206Z-w59m2qld/receipt.json)
  通过：三个不同PID，真实本机库导入链；未加载模型、无forward、无CUDA。
- [12项反例测试](../../evidence/startup-probe-unit-5ivqin9l/receipt.json)通过：包/日志/PID、
  角色与环境错配、入口时序和清理、冒充远端/生产执行、路径逃逸等拒绝。
- 本机是Python3.11.15/torch2.12.1；`--self-test`仅对原Linux挂载决策使用
  显式测试stub，不能作为Linux/HAKUSAN证据。
- [远端入口尝试](../../evidence/startup-probe-remote-20260913T173304Z-lojw8poh/receipt.json)
  在本地发现master.sock缺失即停止，process=null。没有远端probe运行。

## 执行

仅本地打包自测（不会连接超算）：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_startup_probe_20260914/run_probe.py --self-test
```

已有共享认证连接时，只运行一次远端CPU复验：

```bash
cd "$HOME/发表/超算" &&
/opt/anaconda3/envs/audattn/bin/python -I -B \
  docs/superpowers/prototypes/targeted_gpu_startup_probe_20260914/run_probe.py
```

如果连接失效，需在用户终端运行已有连接脚本并在SSH提示输入密码，
密码不写入文件、脚本或聊天。远端入口自身不收集密码或自动重连。

```bash
bash "$HOME/发表/超算/docs/superpowers/evidence/2026-09-10-hakusan-connect.sh"
```

只有`self_test=false`、HAKUSAN_STARTUP_CPU_PASS、两新入口native mount验证、
三个不同PID、原始日志及SHA回传重验完整通过，才算同版本启动复验通过。
旧导入是否在该版本触发同一种mkdir另行记录，不能用本机原因代替远端观测。
即便CPU复验通过，也不等于A100/Inductor前向或最终模型比较成功。
